"""FDE v2 知识图谱模块（LightRAG 封装 · 可插拔）。

把一组应用的设计文档（brd/架构/应用详设/前端详设/README/契约）建成**语义知识图谱**，
供智能体跨文档问答（"毛需求怎么算""σ_L 哪来的"），替代逐文件读。

- **可插拔**：`is_available()` 返回 False（未装 lightrag）时，上层工具自动降级；
  本模块对 lightrag 为**延迟 import**，平台启动不加载。
- **复用 LLM**：抽取/查询用 `fde_platform.llm.get_provider("operator")`（DeepSeek 等）。
- **embedding 独立服务**：经 `FDE_EMBED_URL` 调独立 embed 进程
  （`fde_platform.embed_service`），本进程不 import torch。
- **存储**：本地模式（`config/kg_storage/<组>/`），生产可切 PG。

用法（先起 embedding 服务，再跑索引/问答/可视化/导出）：
    python -m fde_platform.embed_service                             # :9800，唯一 import torch
    python -m fde_platform.knowledge_graph index psc                 # 建/重建索引
    python -m fde_platform.knowledge_graph query psc "毛需求怎么算"    # 问答
    python -m fde_platform.knowledge_graph viz psc [-o out.html]      # 出知识图谱 HTML
    python -m fde_platform.knowledge_graph export psc [-o out.md]     # 导出本体对象候选清单

**书目组的目录分工**（正文与辅助产物分开，见 `scripts/book_to_brd.py` 与《从材料到BRD.md》）：
    app/<组>/book/       原始书籍，任意格式（pdf/epub/docx）——**不入索引**、不入 git
    app/<组>/brd/        分章 md —— **唯一的索引源**，同时是 design-plus 第①步的输入
    app/<组>/本体对象.md   对象候选清单 —— **组根，不进 brd/**（它是本模块的**导出物**，
                        混进 brd/ 会在下次索引时被吃回图谱，形成反馈环）
    app/<组>/术语表.md     原词 → 业务名，下游命名的唯一来源 —— 同样放组根
    app/<组>/kg_config.json  可选组级抽取配置（gleaning / entity_types / language / 并发）

环境变量（可选）：
    FDE_EMBED_URL          embedding 服务地址（默认 http://127.0.0.1:9800）
    FDE_KG_EMBED_MODEL     bge 模型名（默认 BAAI/bge-small-zh-v1.5，embed 服务侧加载）
    FDE_KG_EMBED_DIM       向量维度（默认 512，须与模型一致）
    HF_ENDPOINT            国内下载 bge 用 https://hf-mirror.com（embed 服务侧）
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import time

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CONFIG_DIR = PROJECT_ROOT / "config"
# ⚠ 只隔离**会被写**的平台状态（KG 存储），不隔离**只读内容库**（`rules/` 是人工维护的制度文件，
# 与 app 文档同级，测试不需要它的副本）。`KG_DIR` 走调用时解析，认 `FDE_CONFIG_ROOT`。
from fde_platform.config_paths import config_path  # noqa: E402


def kg_dir() -> pathlib.Path:
    """KG 存储目录（**调用时解析**，认 `FDE_CONFIG_ROOT`）。

    ⚠ 保留这个函数而不是只留常量：模块级常量在 import 期求值，"进程内测试先 import、
    后设环境变量"的顺序会把它冻在真 config/ 上。外部要用的（如 `rules_admin._index_status`）请调本函数。
    """
    return config_path("kg_storage")


# 兼容别名（import 期求值；**新的调用点请用 `kg_dir()`**）——`rules_admin` 曾直接读它，
# 2026-09-18 改成只留函数时忘了别名，`/api/knowledge` 当场 500（view e2e 抓到了）。
KG_DIR = kg_dir()

EMBED_MODEL = os.environ.get("FDE_KG_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
EMBED_DIM = int(os.environ.get("FDE_KG_EMBED_DIM", "512"))

# 国内默认走 HF 镜像，避免直连 huggingface.co 超时（用户已显式设置则尊重之）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# 组级文档文件名（按优先级：旧「架构设计.md」→ 新「architecture.md」）
_ARCH_FILENAMES = ("架构设计.md", "architecture.md")
_GROUP_DOCS = ("_contracts.md", "销售预测与库存策略说明.md")
# 只索引「应用详设」（含 BR 规则 / FUNC 功能 / 数据字典）。前端详设 / README 对业务问答价值低，
# 且量大拖慢索引，不纳入。
_APP_DOCS = ("应用详设.md",)

# 企业非结构化制度库目录：放 .md/.txt 制度/政策文件（规章制度、SOP、行业规范等自由文本）。
# 与「应用组结构化文档」分离——应用组的业务规则走 read_app_doc 精确读，制度库才走知识图谱语义检索。
RULES_DIR = CONFIG_DIR / "rules"


def is_available() -> bool:
    """lightrag 是否可用（未安装 → False，上层工具据此降级为「未启用」）。"""
    try:
        import lightrag  # noqa: F401
        return True
    except Exception:
        return False


# ────────────────────────────────────────────────────────────
# 文档收集
# ────────────────────────────────────────────────────────────

def _collect_rules_docs() -> list[tuple[str, str]]:
    """收集企业非结构化制度文件（config/rules/ 下的 .md/.txt）。"""
    if not RULES_DIR.is_dir():
        raise RuntimeError(f"{RULES_DIR} 不存在——这是企业制度库目录，放 .md/.txt 制度文件后再 index rules")
    docs: list[tuple[str, str]] = []
    for p in sorted(RULES_DIR.rglob("*")):
        if p.is_file() and p.suffix.lower() in (".md", ".txt"):
            rel = p.relative_to(RULES_DIR)
            docs.append((f"rules/{rel}", p.read_text(encoding="utf-8")))
    return docs


def _collect_docs(group: str) -> list[tuple[str, str]]:
    """收集知识库文档 → [(相对路径, 全文)]。

    group == "rules" 时收集企业制度库（config/rules/）；否则按应用组收集设计文档
    （架构/brd/应用详设，排除 tests/ 与前端测试用例）。
    """
    if group == "rules":
        return _collect_rules_docs()
    group_dir = APP_DIR / group
    if not group_dir.is_dir():
        raise RuntimeError(f"app/{group} 目录不存在")
    docs: list[tuple[str, str]] = []
    for name in _ARCH_FILENAMES:
        p = group_dir / name
        if p.is_file():
            docs.append((f"{group}/{name}", p.read_text(encoding="utf-8")))
            break
    for name in _GROUP_DOCS:
        p = group_dir / name
        if p.is_file():
            docs.append((f"{group}/{name}", p.read_text(encoding="utf-8")))
    brd = group_dir / "brd"
    if brd.is_dir():
        for p in sorted(brd.glob("*.md")):
            docs.append((f"{group}/brd/{p.name}", p.read_text(encoding="utf-8")))
    for app_dir in sorted(d for d in group_dir.iterdir() if d.is_dir()):
        if app_dir.name in ("tests", "brd"):
            continue
        if not (app_dir / f"{app_dir.name}.py").exists():
            continue
        for name in _APP_DOCS:
            p = app_dir / name
            if p.is_file():
                docs.append((f"{group}/{app_dir.name}/{name}", p.read_text(encoding="utf-8")))
    return docs


# ────────────────────────────────────────────────────────────
# LLM / Embedding 函数（LightRAG 约定的签名）
# ────────────────────────────────────────────────────────────

def _llm_func(prompt, system_prompt=None, history_messages=None,
              keyword_extraction=False, **kwargs):
    """同步 LLM 函数体：复用 fde_platform.llm 的 operator 配置。"""
    from fde_platform import llm

    provider = llm.get_provider("operator")
    if isinstance(provider, llm.NotConfiguredProvider):
        raise RuntimeError("LLM 未配置：请先在「大模型配置」页（/llm）设置 operator 模型")
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if history_messages:
        messages.extend(history_messages)
    messages.append({"role": "user", "content": prompt})
    result = provider.chat(messages)
    return (result or {}).get("content") or ""


async def _llm_model_func(prompt, system_prompt=None, history_messages=None,
                          keyword_extraction=False, **kwargs) -> str:
    """LightRAG 期望的异步 llm_model_func。"""
    return await asyncio.to_thread(
        _llm_func, prompt, system_prompt, history_messages, keyword_extraction
    )


async def _embed_func(texts: list[str]):
    """LightRAG 期望的异步 embedding_func：经 HTTP 调独立 embed 服务（FDE_EMBED_URL）。

    本进程不 import torch——embedding 由独立进程 embed_service 提供
    （见 fde_platform/embed_service.py）。返回 numpy 数组
    （NanoVectorDB flush 时对其调 .size，list 无此属性会报错）。
    """
    import httpx
    import numpy as np

    url = os.environ.get("FDE_EMBED_URL", "http://127.0.0.1:9800").rstrip("/")
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{url}/embed", json={"texts": texts})
        r.raise_for_status()
        return np.asarray(r.json()["vectors"], dtype="float32")


# ────────────────────────────────────────────────────────────
# 组级抽取配置（app/<组>/kg_config.json，可选）
# ────────────────────────────────────────────────────────────

KG_CONFIG_NAME = "kg_config.json"

# 与 LightRAG 内置 default_entity_types_guidance 同句式——只换类型表，别改句式。
_GUIDANCE_HEAD = ("Classify each entity using one of the following types. "
                  "If no type fits, use `Other`.")


def _load_kg_config(group: str) -> dict:
    """读组级抽取配置 `app/<组>/kg_config.json`；文件不存在 → 空 dict（全走内置默认）。

    支持的键（全部可选）：
      ``gleaning``     int   实体补抽轮数。0=关（默认，结构化文档够用）；书籍等密集散文建议 1。
      ``entity_types`` 数组或对象  业务实体类型。数组=只要类型名；对象={类型名: 说明}（推荐）。
      ``language``     str   抽取语言（默认 English）。中文材料建议 "Simplified Chinese"。
      ``llm_max_async`` int  抽取并发（默认 4）。⚠ **别指望它大幅提速**——
                              瓶颈在 LLM 服务端：实测单次抽取调用约 100 秒，
                              并发 4→8 实测只快约 **2 倍**（并发 8 次实测加速比 2.0x，理想 8x），
                              再往上基本无效且易触发重试。要实质提速只能**换吞吐更大的抽取模型**。
      ``max_parallel_insert`` int **文档**级并发（默认 3）。总并发 ≈ 本项 × llm_max_async。
                              官方建议 2~10、约取 llm_max_async/3：调太大反而会加重
                              实体/关系命名冲突、拖慢合并。同样受上面的服务端上限约束。

    ⚠ 配置**只在建索引时生效**：改完须 `index <组> --force` 重建，否则旧图不动。
    ⚠ 放在组根目录**不会被收进索引**（`_collect_docs` 只认固定文件名 + `brd/*.md` + 应用详设）。
    """
    p = APP_DIR / group / KG_CONFIG_NAME
    if not p.is_file():
        return {}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"{p} 解析失败（须是合法 JSON）：{e}")
    if not isinstance(cfg, dict):
        raise RuntimeError(f"{p} 顶层必须是 JSON 对象")
    return cfg


def _entity_type_items(entity_types) -> list[tuple[str, str]]:
    """归一化配置 → [(类型名, 说明)]。两种写法都收：

        ["业务单据", "主数据"]                    只给类型名
        {"业务单据": "需按单据号管理、有状态流转"}  类型 + 说明（抽取更准）
        ["业务单据：说明", ...]                    行内说明也认（：或 :）
    """
    if not entity_types:
        return []
    if isinstance(entity_types, dict):
        items = [(str(k).strip(), str(v).strip()) for k, v in entity_types.items()]
    elif isinstance(entity_types, (list, tuple)):
        items = []
        for it in entity_types:
            s = str(it).strip()
            for sep in ("：", ":"):
                if sep in s:
                    k, _, v = s.partition(sep)
                    items.append((k.strip(), v.strip()))
                    break
            else:
                items.append((s, ""))
    else:
        raise RuntimeError("kg_config.json 的 entity_types 须是数组或对象")
    return [(k, v) for k, v in items if k]


def _entity_types_guidance(entity_types) -> str | None:
    """渲染 LightRAG 的 entity_types_guidance 文本；未配置 → None（用内置指南）。"""
    items = _entity_type_items(entity_types)
    if not items:
        return None
    lines = [_GUIDANCE_HEAD, ""]
    lines += [f"- {n}: {d}" if d else f"- {n}" for n, d in items]
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────
# LightRAG 构建 / 索引 / 查询 / 可视化 / 导出
# ────────────────────────────────────────────────────────────

def _get_rag(group: str):
    from lightrag import LightRAG
    from lightrag.utils import EmbeddingFunc

    working_dir = kg_dir() / group
    working_dir.mkdir(parents=True, exist_ok=True)
    # 组级配置（app/<组>/kg_config.json，可选）。**无配置时逐项走内置默认**——
    # gleaning=0 / 内置实体类型 / English，与加此配置前行为一致（psc、rules 不受影响）。
    cfg = _load_kg_config(group)
    addon: dict = {}
    guidance = _entity_types_guidance(cfg.get("entity_types"))
    if guidance:
        addon["entity_types_guidance"] = guidance
    if cfg.get("language"):
        addon["language"] = str(cfg["language"])
    return LightRAG(
        working_dir=str(working_dir),
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBED_DIM, func=_embed_func, model_name=EMBED_MODEL
        ),
        llm_model_func=_llm_model_func,
        llm_model_name="fde-operator",
        # 本地 embedding 模型常驻内存，多 worker 会各加载一份 → 内存爆炸。
        # 置 1：单 worker 只加载一份 bge（CPU 推理对 PSC 规模完全够）。
        embedding_func_max_async=1,
        # 实体补抽轮数：默认 0（每 chunk 少一次 LLM 调用，索引耗时减半）。
        # PSC 结构化文档实体密度不高（实测每 chunk 10~29 实体，远低于 40 上限），关掉几乎无损；
        # 但**密集散文**（书籍）会撞 40/chunk 上限而静默漏抽 → 那类组在 kg_config.json 写 gleaning=1。
        entity_extract_max_gleaning=int(cfg.get("gleaning", 0)),
        # 抽取并发（默认 4）。⚠ **别指望它大提速**：瓶颈在 LLM 服务端 ——
        # 实测单次抽取约 100 秒，并发 4→8 只快约 2 倍（并发 8 次实测加速比 2.0x，理想 8x），
        # 再往上基本无效。要实质提速只能换吞吐更大的抽取模型。不传时行为与改前一致。
        llm_model_max_async=int(cfg.get("llm_max_async", 4)),
        # 文档级并发（默认 3，与 LightRAG 内置默认一致）。总并发 ≈ 本项 × llm_model_max_async。
        # 官方建议 2~10、约取 llm_max_async/3 —— 调太大反而加重实体命名冲突、拖慢合并。
        max_parallel_insert=int(cfg.get("max_parallel_insert", 3)),
        # addon_params 是 LightRAG 1.5.7 传 entity_types_guidance / language 的正规入口
        # （见 lightrag.py 的 InitVar 与 prompt.load_entity_extraction_prompt_profile）。
        addon_params=addon or None,
    )


async def build_index(group: str, force: bool = False) -> dict:
    """全量建索引：收集文档 → 一次性入队并处理。返回 {docs, storage}。

    ⚠ **按小时计的成本**：抽取耗时由 LLM 服务端吞吐决定（实测单次约 100 秒，
    并发只买到约 2 倍）。实测一本 300 页 / 870k 字符的书（切成 27 章、约 180 个 chunk）
    **约 2~3 小时**，其中合并类调用只占约 9%。

    ⚠ 估速率时**别拿小样本外推**：单 chunk 的小文档无法并行、慢得离谱（实测 0.83 次
    调用/分钟），而 21 个 chunk 的大章能跑满并发（1.4 次/分钟）——**大章反而更快**。
    要估就先拿**一个中大章**试跑，别拿前言/附录试。
    """
    from lightrag import LightRAG

    docs = _collect_docs(group)
    if not docs:
        raise RuntimeError(f"app/{group} 下没有可索引的设计文档")

    working_dir = kg_dir() / group
    if force and working_dir.is_dir():
        import shutil
        shutil.rmtree(working_dir)
        working_dir.mkdir(parents=True, exist_ok=True)

    rag = _get_rag(group)
    await rag.initialize_storages()
    try:
        # ⚠ **一次传全部**，不要逐份 ainsert：
        # `ainsert` 内部是「enqueue → process」，而 process 会**等这份文档跑完才返回**。
        # 逐份调用 ⇒ 文档之间严格串行，并发工作池只在**单份文档内部**起作用 ——
        # 一本书里有几十个小文件时，每个都独占一个满轮次（实测每个约 100 秒），
        # worker 全程闲着。传列表则先全部入队、再由一次 process 取走**所有 pending**
        # 文档统一处理，并发才能跨文档保持饱和（REST 路径就是这么做的）。
        #
        # file_paths 必须显式传：不传时实体的 file_path 落成 `unknown_source`，
        # 溯源就只剩 source_id 反推这一条路（export 里两条路都留了，但正路是这条）。
        relpaths = [relpath for relpath, _ in docs]
        await rag.ainsert([content for _, content in docs],
                          ids=relpaths, file_paths=relpaths)
    finally:
        await rag.finalize_storages()
    return {"docs": len(docs), "storage": str(working_dir)}


async def add_doc(group: str, doc_id: str, content: str) -> None:
    """增量插入单份文档（幂等：同 doc_id + 同 content hash 自动跳过，命中 LLM 抽取缓存）。"""
    rag = _get_rag(group)
    await rag.initialize_storages()
    try:
        await rag.ainsert(content, ids=doc_id, file_paths=doc_id)
    finally:
        await rag.finalize_storages()


async def remove_doc(group: str, doc_id: str) -> None:
    """增量删除单份文档的索引（其抽出的实体/关系一并移除）。"""
    rag = _get_rag(group)
    await rag.initialize_storages()
    try:
        await rag.adelete_by_doc_id(doc_id)
    finally:
        await rag.finalize_storages()


async def _embed_not_ready() -> str:
    """嵌入服务探活：**就绪返回空串**，否则返回一句人话原因。

    ⚠ 为什么必须显式探活（2026-09-25 补，实测踩到）：嵌入服务没起时，LightRAG 的检索会
    **静默返回 None**（日志里只有 `Query failed: All connection attempts failed`），
    而 `agentscope_bridge` 会把 None 当成"查到了"交给 Agent —— 于是它收到
    `{"found": true, "answer": null}`，要么答"知识库里没有相关内容"，**要么自己编**。
    这正是平台自己反复强调的最坏失败模式（两边一致地错、没人报红）。
    所以宁可在入口**明确报错**：让 Agent / 页面看到"知识库未就绪：嵌入服务没起"。
    """
    import httpx
    url = os.environ.get("FDE_EMBED_URL", "http://127.0.0.1:9800").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(url + "/")
        if r.status_code < 500:
            return ""
        return f"嵌入服务返回 HTTP {r.status_code}"
    except Exception as e:                                    # noqa: BLE001
        return (f"嵌入服务连不上（{url}）—— 先起 `python -m fde_platform.embed_service`"
                f"（{type(e).__name__}）")


async def query(group: str, q: str, mode: str = "hybrid") -> str:
    """语义问答：沿图谱检索 + LLM 生成回答。"""
    from lightrag import QueryParam

    reason = await _embed_not_ready()
    if reason:
        raise RuntimeError(f"知识库未就绪：{reason}")
    rag = _get_rag(group)
    await rag.initialize_storages()
    try:
        # ⚠ **显式关掉重排**（2026-09-27 定）：lightrag 的 `enable_rerank` 默认 True，而平台没配
        # `rerank_model_func` ⇒ 每次查询都打一行
        # 「Rerank is enabled but no rerank model is configured」的 warning，而它**什么都不做**
        # （日志里 `84 -> 84 (deduplicated 0)` 就是证据），容易让读日志的人以为检索坏了。
        # 要不要开：开了才需要（也才值得）配重排模型 ——
        #   · API 路线（推荐）：lightrag 自带 `ali_rerank` / `jina_rerank` / `cohere_rerank` /
        #     `generic_rerank_api`，给一家 key 即可（DeepSeek **没有**重排接口）；
        #   · 本地路线：`bge-reranker-base` ≈ **1.1 GB 下载 + 1.1 GB 常驻内存**（2核2G 的服务器跑不了）。
        #   开的时候要**两处一起**：这里 `enable_rerank=True` + `_get_rag` 传 `rerank_model_func=`。
        result = await rag.aquery(q, param=QueryParam(mode=mode, enable_rerank=False))
    finally:
        await rag.finalize_storages()
    if not result:
        # 嵌入服务在、也检索了，但没捞到东西 —— 与"服务没起"区分开，别让调用方以为是同一件事
        raise RuntimeError(f"知识库 {group} 未检索到内容（该库可能还没建索引，"
                           f"或问题与该库无关）")
    return result if isinstance(result, str) else str(result)


_LOOP = None
_LOOP_THREAD = None
_LOOP_LOCK = None


def _get_loop():
    """获取/创建一个持久后台事件循环。

    LightRAG 1.5.7 的 pipeline ingress 是「按 workspace 的全局单例」，绑定创建时的 event loop；
    若每次 asyncio.run 新建 loop，同一个 workspace 的 ingress 会被跨 loop 共享而报错。
    故所有 LightRAG 操作复用同一个持久 loop。
    """
    global _LOOP, _LOOP_THREAD, _LOOP_LOCK
    import threading

    if _LOOP_LOCK is None:
        _LOOP_LOCK = threading.Lock()
    with _LOOP_LOCK:
        if _LOOP is None or _LOOP.is_closed():
            _LOOP = asyncio.new_event_loop()
            _LOOP_THREAD = threading.Thread(target=_LOOP.run_forever, name="fde-kg-loop", daemon=True)
            _LOOP_THREAD.start()
        return _LOOP


def _run_sync(coro):
    """同步执行 async 协程：提交到持久后台 loop，阻塞等结果。"""
    future = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    return future.result()


def query_sync(group: str, q: str, mode: str = "hybrid") -> str:
    """同步查询封装（供平台工具 / HTTP 接口调用）。"""
    return _run_sync(query(group, q, mode))


def add_doc_sync(group: str, doc_id: str, content: str) -> None:
    """同步增量插入封装。"""
    return _run_sync(add_doc(group, doc_id, content))


def remove_doc_sync(group: str, doc_id: str) -> None:
    """同步增量删除封装。"""
    return _run_sync(remove_doc(group, doc_id))


def build_index_sync(group: str, force: bool = False) -> dict:
    """同步全量索引封装。"""
    return _run_sync(build_index(group, force))


def viz(group: str, out=None) -> pathlib.Path:
    """读 graphml → pyvis 生成交互式 HTML（力导向图，零 CDN 内嵌）。"""
    import networkx as nx
    from pyvis.network import Network

    graphml = kg_dir() / group / "graph_chunk_entity_relation.graphml"
    if not graphml.is_file():
        raise RuntimeError(f"未找到知识图谱（{graphml}），请先 index {group}")

    G = nx.read_graphml(str(graphml))
    net = Network(height="100vh", width="100%", directed=True,
                  bgcolor="#ffffff", font_color="#1f2937")
    palette = ["#2563eb", "#16a34a", "#ea580c", "#9333ea", "#dc2626",
               "#0891b2", "#ca8a04", "#db2777", "#4f46e5", "#0d9488"]
    type_color: dict[str, str] = {}
    for node_id, data in G.nodes(data=True):
        etype = str(data.get("entity_type") or data.get("d1") or "unknown")
        desc = str(data.get("description") or data.get("d2") or "")
        color = type_color.setdefault(etype, palette[len(type_color) % len(palette)])
        title = f"{node_id}  <b>[{etype}]</b><br>{desc[:240]}"
        net.add_node(node_id, label=str(node_id), title=title, color=color, size=18)
    for src, dst, data in G.edges(data=True):
        rel = str(data.get("description") or data.get("keywords")
                  or data.get("d6") or "")
        net.add_edge(src, dst, title=rel[:240], arrows="to")

    out_path = pathlib.Path(out) if out else (APP_DIR / group / "知识图谱.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(out_path), open_browser=False, local=True)
    # 后处理：把 vis-network 的 js/css 与 utils.js 内嵌进 HTML——消除 file:// 下
    # crossorigin 触发的 CORS 报错 + CDN 依赖 → 单文件、离线可用、0 console error。
    try:
        import re

        import pyvis

        pkg_lib = pathlib.Path(pyvis.__file__).parent / "lib"
        html = out_path.read_text(encoding="utf-8")
        # utils.js 内嵌
        utils_js = pkg_lib / "bindings" / "utils.js"
        if utils_js.is_file():
            html = html.replace('<script src="lib/bindings/utils.js"></script>',
                                "<script>" + utils_js.read_text(encoding="utf-8") + "</script>")
        # vis-network css 内嵌
        vn_css = pkg_lib / "vis-9.1.2" / "vis-network.css"
        if vn_css.is_file():
            html = re.sub(r'<link[^>]*vis-network\.min\.css[^>]*/>',
                          lambda m: "<style>" + vn_css.read_text(encoding="utf-8") + "</style>",
                          html, count=1)
        # vis-network js 内嵌（用 lambda 作 repl，避免 js 里的 \d 等被 re 当转义）
        vn_js = pkg_lib / "vis-9.1.2" / "vis-network.min.js"
        if vn_js.is_file():
            html = re.sub(r'<script[^>]*vis-network\.min\.js[^>]*>\s*</script>',
                          lambda m: "<script>" + vn_js.read_text(encoding="utf-8") + "</script>",
                          html, count=1)
        out_path.write_text(html, encoding="utf-8")
    except Exception:
        pass
    return out_path


# ────────────────────────────────────────────────────────────
# 导出本体对象候选清单（供 design-plus 第①步当输入之一）
# ────────────────────────────────────────────────────────────

def _oneline(x) -> str:
    """压成单行：graphml 里的描述带换行与多余空白，进表格会破版；
    另把 LightRAG 合并多条描述用的 ``<SEP>`` 换成中文分号（否则一行里堆一长串）。"""
    s = str(x or "").replace("<SEP>", "；")
    return re.sub(r"\s+", " ", s).strip()


def _md_esc(x) -> str:
    """Markdown 表格单元格转义（裸 `|` 会截断列）。"""
    return _oneline(x).replace("|", "\\|")


# source_id 是 LightRAG 拼的 chunk id 串：既见过 `<SEP>` 分隔，也可能出现逗号。
_SEP_RE = re.compile(r"<SEP>|[,，]")


def _chunk_ids(data) -> list[str]:
    """取该实体的全部源 chunk id（形如 `rules/xx.md-chunk-003`）。"""
    raw = str(data.get("source_id") or "")
    return [s.strip() for s in _SEP_RE.split(raw) if s.strip()]


def _doc_of(chunk_id: str) -> str:
    """chunk id → 文档路径（去掉 `-chunk-003` 尾巴）。"""
    return chunk_id.rsplit("-chunk-", 1)[0]


def _origin_cell(data) -> str:
    """「出处」列：优先用 file_path；它是 `unknown_source` 时退回从源 chunk id 反推。

    ⚠ 2026-09-24 前建的索引 file_path 全是 `unknown_source`——那时 `ainsert` 没传
    `file_paths`（已修）。反推路径对老图仍然有效，所以两条路都留着。
    """
    fp = _oneline(data.get("file_path") or "")
    if fp and fp != "unknown_source":
        return _md_esc(fp)
    docs = []
    for cid in _chunk_ids(data):
        d = _doc_of(cid)
        if d and d not in docs:
            docs.append(d)
    if not docs:
        return ""
    return _md_esc(docs[0]) + (f"（共{len(docs)}份）" if len(docs) > 1 else "")


def _src_cell(data) -> str:
    """「源块」列：首个 chunk id（去文档前缀）+ 总处数，供回查原文用。"""
    ids = _chunk_ids(data)
    if not ids:
        return ""
    short = ids[0].rsplit("-chunk-", 1)[-1]
    short = f"chunk-{short}" if not short.startswith("chunk-") else short
    return _md_esc(short) + (f" 等{len(ids)}处" if len(ids) > 1 else "")


def export_entities(group: str, out=None) -> pathlib.Path:
    """读 graphml → 生成《本体对象.md》候选清单。

    只做「把图里的实体摊平成可读清单」，**不做判断、不划边界、不生成代码**：
      · 配置过的业务类型各一节（按 kg_config.json 的顺序），组内按**关联数**降序
      · 每行带**出处**（file_path）与**源块**（source_id），便于回查原文核对
      · 附高频关系 Top 50；未归入配置类型的实体不丢，降级到末尾一节

    文件头显式声明「机器提取候选，未经业务确认，以 brd/ 原书为准」——下游须把它
    当**候选提示**而非事实，逐项处置后写进 `architecture_review.md`
    （独立聚合 / 并入 / 排除 + 理由）。
    """
    import networkx as nx

    graphml = kg_dir() / group / "graph_chunk_entity_relation.graphml"
    if not graphml.is_file():
        raise RuntimeError(f"未找到知识图谱（{graphml}），请先 index {group}")

    G = nx.read_graphml(str(graphml))
    deg = dict(G.degree())
    cfg = _load_kg_config(group)
    want = [n for n, _ in _entity_type_items(cfg.get("entity_types"))]

    by_type: dict[str, list] = {}
    for node_id, data in G.nodes(data=True):
        etype = str(data.get("entity_type") or data.get("d1") or "未分类")
        by_type.setdefault(etype, []).append((str(node_id), data))
    for rows in by_type.values():
        rows.sort(key=lambda nd: -deg.get(nd[0], 0))

    def _table(rows) -> list[str]:
        lines = ["| 对象 | 描述 | 关联数 | 出处 | 源块 |", "|---|---|---|---|---|"]
        for node_id, data in rows:
            lines.append("| %s | %s | %d | %s | %s |" % (
                _md_esc(node_id),
                _md_esc(data.get("description") or data.get("d2") or "")[:120],
                deg.get(node_id, 0),
                _origin_cell(data),
                _src_cell(data),
            ))
        return lines

    L: list[str] = []
    L.append(f"# {group} 本体对象候选清单")
    L.append("")
    L.append("> ⚠ **机器提取候选，未经业务确认，以 `brd/` 里的原书为准。**")
    L.append(f"> 生成：`python -m fde_platform.knowledge_graph export {group}`"
             f" · {time.strftime('%Y-%m-%d %H:%M')}"
             f" · 实体 {G.number_of_nodes()} / 关系 {G.number_of_edges()}")
    L.append(">")
    L.append("> ### 这份清单是什么、不是什么（**先读这段**）")
    L.append(">")
    L.append("> **它是**：从材料里抽出的「**实体提及清单 + 共现图**」——"
             "即「文本里提到过哪些概念性名词、谁和谁常一起出现」。")
    L.append("> **它不是**：**不是本体**（没有层级 / 属性 / 公理），**也不是领域模型**"
             "（没有标识 / 不变量 / 聚合边界）。名字里的「本体对象」只是沿用惯称，别当它有骨架。")
    L.append(">")
    L.append("> **清单里混着三类东西，要分开看**：")
    L.append("> - ✅ **能建档管理的领域对象**（如 `SEMP` / `需求` / `风险`）—— 真正的候选")
    L.append("> - ⚠️ **方法论概念**（如「产品验证过程」「决策分析过程」）—— 讲「怎么做」，"
             "通常**不独立成聚合**")
    L.append("> - ❌ **文本产物**（表格标题、机构名碎片）—— 噪声")
    L.append(">")
    L.append("> **量级提醒**：本清单动辄**上千条**，其中真正能被建档的是**几十个**量级。")
    L.append("> **不要逐条处置** —— 只处置筛出的「聚合根候选」，其余按类型概述落选理由。")
    L.append(">")
    L.append("> 用途：design-plus 第①步的输入之一（与 `brd/` 的分章 md 并排读）。")
    L.append("> **聚合边界判断归第①步**——本清单不划边界、不分层、不产代码；"
             "每个候选对象的处置（独立聚合 / 并入 / 排除 + 理由）记进 `architecture_review.md`。")
    L.append("> 「关联数」= 该对象在图中的连接边数，只说明它在文本里被一起提到得多，"
             "**不代表重要性、更不代表该独立成聚合**。")
    L.append("")

    known = want or sorted(by_type, key=lambda t: (-len(by_type[t]), t))
    L.append("## 一、业务对象")
    L.append("")
    if not want:
        L.append("> 未配置 `entity_types`（`app/<组>/kg_config.json`）——"
                 "下列类型是 LightRAG 用**内置通用类型表**抽出来的，不是业务类型。")
        L.append("")
    for t in known:
        rows = by_type.get(t, [])
        L.append(f"### {t}（{len(rows)}）")
        L.append("")
        L.extend(_table(rows) if rows else ["（无）"])
        L.append("")

    others = [t for t in by_type if t not in known]
    if others:
        others.sort(key=lambda t: (-len(by_type[t]), t))
        L.append("## 二、附：其他类型实体（未归入上述类型，全量保留）")
        L.append("")
        for t in others:
            L.append(f"### {t}（{len(by_type[t])}）")
            L.append("")
            L.extend(_table(by_type[t]))
            L.append("")

    edges = sorted(G.edges(data=True),
                   key=lambda e: -(deg.get(e[0], 0) + deg.get(e[1], 0)))[:50]
    L.append("## 三、高频关系 Top 50（按两端关联数之和降序）")
    L.append("")
    L.append("| 对象A | 关系 | 对象B | 出处 |")
    L.append("|---|---|---|---|")
    for s, d, data in edges:
        rel = data.get("description") or data.get("keywords") or data.get("d6") or ""
        L.append("| %s | %s | %s | %s |" % (
            _md_esc(s), _md_esc(rel)[:120], _md_esc(d), _origin_cell(data)))
    L.append("")

    out_path = pathlib.Path(out) if out else (APP_DIR / group / "本体对象.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(L), encoding="utf-8")
    return out_path


# ────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    # Windows 控制台默认 GBK，输出含 −/中文等字符会 UnicodeEncodeError；统一转 UTF-8。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="FDE 知识图谱（LightRAG）索引/问答/可视化")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_idx = sub.add_parser("index", help="全量建索引")
    p_idx.add_argument("group")
    p_idx.add_argument("--force", action="store_true", help="清空已有索引重建")

    p_q = sub.add_parser("query", help="语义问答")
    p_q.add_argument("group")
    p_q.add_argument("query")
    p_q.add_argument("--mode", default="hybrid", help="hybrid/local/global/mix/naive")

    p_v = sub.add_parser("viz", help="出知识图谱 HTML")
    p_v.add_argument("group")
    p_v.add_argument("-o", "--out", default=None)

    p_add = sub.add_parser("add", help="增量插入单份文档（幂等，同 id 跳过）")
    p_add.add_argument("group")
    p_add.add_argument("doc_id", help="文档 id（如 rules/制度.md）")
    p_add.add_argument("file", help="本地文件路径")

    p_rm = sub.add_parser("remove", help="增量删除单份文档的索引")
    p_rm.add_argument("group")
    p_rm.add_argument("doc_id", help="文档 id（如 rules/制度.md）")

    p_ex = sub.add_parser("export", help="导出本体对象候选清单（Markdown）")
    p_ex.add_argument("group")
    p_ex.add_argument("-o", "--out", default=None,
                      help="输出路径（默认 app/<组>/本体对象.md）")

    args = ap.parse_args()

    if args.cmd == "index":
        r = asyncio.run(build_index(args.group, force=args.force))
        print(f"已索引 {r['docs']} 份文档 → {r['storage']}")
    elif args.cmd == "query":
        print(asyncio.run(query(args.group, args.query, args.mode)))
    elif args.cmd == "viz":
        print(f"已生成 {viz(args.group, args.out)}")
    elif args.cmd == "export":
        print(f"已导出 {export_entities(args.group, args.out)}")
    elif args.cmd == "add":
        import pathlib as _pl
        content = _pl.Path(args.file).read_text(encoding="utf-8")
        asyncio.run(add_doc(args.group, args.doc_id, content))
        print(f"已增量插入 {args.doc_id}")
    elif args.cmd == "remove":
        asyncio.run(remove_doc(args.group, args.doc_id))
        print(f"已增量删除 {args.doc_id}")
