"""FDE v2 知识图谱模块（LightRAG 封装 · 可插拔）。

把一组应用的设计文档（brd/架构/应用详设/前端详设/README/契约）建成**语义知识图谱**，
供智能体跨文档问答（"毛需求怎么算""σ_L 哪来的"），替代逐文件读。

- **可插拔**：`is_available()` 返回 False（未装 lightrag）时，上层工具自动降级；
  本模块对 lightrag / sentence-transformers 均为**延迟 import**，平台启动不加载它们。
- **复用 LLM**：抽取/查询用 `fde_platform.llm.get_provider("operator")`（DeepSeek 等）。
- **本地 embedding**：默认 `BAAI/bge-small-zh-v1.5`（sentence-transformers 加载，CPU 推理；资源充足可换 bge-m3）。
- **存储**：本地模式（`config/kg_storage/<组>/`），生产可切 PG。

用法：
    python -m fde_platform.knowledge_graph index psc                # 建/重建索引
    python -m fde_platform.knowledge_graph query psc "毛需求怎么算"   # 问答
    python -m fde_platform.knowledge_graph viz psc [-o out.html]     # 出知识图谱 HTML

环境变量（可选）：
    FDE_KG_EMBED_MODEL   bge 模型名（默认 BAAI/bge-small-zh-v1.5；资源充足可换 bge-m3）
    FDE_KG_EMBED_DIM     向量维度（默认 512，须与模型一致；bge-m3 为 1024）
    HF_ENDPOINT          国内下载 bge 用 https://hf-mirror.com
    HF_HOME              HF 缓存目录（默认 ~/.cache/huggingface；C 盘紧张可指到数据盘）
"""
from __future__ import annotations

import asyncio
import os
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CONFIG_DIR = PROJECT_ROOT / "config"
KG_DIR = CONFIG_DIR / "kg_storage"

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


_embed_model = None
_embed_lock = None


def _get_embed_model():
    """惰性加载 bge 模型（线程安全：并发 worker 只加载一份）。"""
    global _embed_model, _embed_lock
    if _embed_model is not None:
        return _embed_model
    import threading

    if _embed_lock is None:
        _embed_lock = threading.Lock()
    with _embed_lock:
        if _embed_model is None:
            from sentence_transformers import SentenceTransformer

            _embed_model = SentenceTransformer(EMBED_MODEL)
    return _embed_model


async def _embed_remote(texts: list[str]) -> list[list[float]]:
    """经 HTTP 调独立 embed 服务（FDE_EMBED_URL），本进程不 import torch。"""
    import httpx

    url = os.environ.get("FDE_EMBED_URL", "http://127.0.0.1:9800").rstrip("/")
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{url}/embed", json={"texts": texts})
        r.raise_for_status()
        return r.json()["vectors"]


async def _embed_func(texts: list[str]):
    """LightRAG 期望的异步 embedding_func。

    FDE_EMBED_MODE=remote 时经 HTTP 调独立 embed 服务（本进程不 import torch）；
    否则（local）进程内 bge encode（CPU，归一化）。返回 numpy 数组
    （NanoVectorDB flush 时对其调 .size，list 无此属性会报错）。
    """
    if os.environ.get("FDE_EMBED_MODE", "local") == "remote":
        import numpy as np

        return np.asarray(await _embed_remote(texts), dtype="float32")
    model = _get_embed_model()
    return await asyncio.to_thread(model.encode, texts, normalize_embeddings=True)


# ────────────────────────────────────────────────────────────
# LightRAG 构建 / 索引 / 查询 / 可视化
# ────────────────────────────────────────────────────────────

def _get_rag(group: str):
    from lightrag import LightRAG
    from lightrag.utils import EmbeddingFunc

    working_dir = KG_DIR / group
    working_dir.mkdir(parents=True, exist_ok=True)
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
        # 关闭 gleaning 补抽：每个 chunk 少一次 LLM 调用，索引耗时减半；
        # PSC 结构化文档实体密度不高（实测每 chunk 10~29 实体，远低于 40 上限），几乎无损。
        entity_extract_max_gleaning=0,
    )


async def build_index(group: str, force: bool = False) -> dict:
    """全量建索引：收集文档 → 逐文档 ainsert。返回 {docs, storage}。"""
    from lightrag import LightRAG

    docs = _collect_docs(group)
    if not docs:
        raise RuntimeError(f"app/{group} 下没有可索引的设计文档")

    working_dir = KG_DIR / group
    if force and working_dir.is_dir():
        import shutil
        shutil.rmtree(working_dir)
        working_dir.mkdir(parents=True, exist_ok=True)

    rag = _get_rag(group)
    await rag.initialize_storages()
    try:
        for relpath, content in docs:
            await rag.ainsert(content, ids=relpath)
    finally:
        await rag.finalize_storages()
    return {"docs": len(docs), "storage": str(working_dir)}


async def add_doc(group: str, doc_id: str, content: str) -> None:
    """增量插入单份文档（幂等：同 doc_id + 同 content hash 自动跳过，命中 LLM 抽取缓存）。"""
    rag = _get_rag(group)
    await rag.initialize_storages()
    try:
        await rag.ainsert(content, ids=doc_id)
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


async def query(group: str, q: str, mode: str = "hybrid") -> str:
    """语义问答：沿图谱检索 + LLM 生成回答。"""
    from lightrag import QueryParam

    rag = _get_rag(group)
    await rag.initialize_storages()
    try:
        result = await rag.aquery(q, param=QueryParam(mode=mode))
    finally:
        await rag.finalize_storages()
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

    graphml = KG_DIR / group / "graph_chunk_entity_relation.graphml"
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

    args = ap.parse_args()

    if args.cmd == "index":
        r = asyncio.run(build_index(args.group, force=args.force))
        print(f"已索引 {r['docs']} 份文档 → {r['storage']}")
    elif args.cmd == "query":
        print(asyncio.run(query(args.group, args.query, args.mode)))
    elif args.cmd == "viz":
        print(f"已生成 {viz(args.group, args.out)}")
    elif args.cmd == "add":
        import pathlib as _pl
        content = _pl.Path(args.file).read_text(encoding="utf-8")
        asyncio.run(add_doc(args.group, args.doc_id, content))
        print(f"已增量插入 {args.doc_id}")
    elif args.cmd == "remove":
        asyncio.run(remove_doc(args.group, args.doc_id))
        print(f"已增量删除 {args.doc_id}")
