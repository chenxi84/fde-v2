"""Agent 共享基座（进度表 + system prompt 组装 + 会话 helper）。

``agent.py``（ReAct 后端）与 ``agent_agentscope.py``（AgentScope 后端）**只换编排循环**，
不换「提示词组装 / 进度表 / 会话持久化」——这三样抽到这里共用。

Phase 3 灰度替换后，``agent.py`` 里剩下的只是 ReAct 循环（可回退开关），
AgentScope 后端不再依赖 ``AgentSession``。
"""
import threading
import time

from fde_platform import agent_state, users
from fde_platform.runtime import tool_prefix

# ── 执行进度（对话「执行中」可见性）──────────────────────
_PROGRESS_LOCK = threading.Lock()
AGENT_PROGRESS: dict = {}


def _progress_key(app_name, session_id: str) -> str:
    return f"{app_name or '__platform__'}|{session_id}"


def get_progress(app_name, session_id: str) -> dict | None:
    """读指定会话的在途进度快照（None = 无在途对话）。"""
    with _PROGRESS_LOCK:
        p = AGENT_PROGRESS.get(_progress_key(app_name, session_id))
        return dict(p) if p else None


def set_progress(app_name, session_id: str, **fields) -> None:
    key = _progress_key(app_name, session_id)
    with _PROGRESS_LOCK:
        p = AGENT_PROGRESS.setdefault(key, {"started_at": time.time()})
        p.update(fields)
        p["updated_at"] = time.time()


def clear_progress(app_name, session_id: str) -> None:
    with _PROGRESS_LOCK:
        AGENT_PROGRESS.pop(_progress_key(app_name, session_id), None)


def tool_disp(tool_name: str) -> str:
    """qualname 化工具名的简短展示：`demo__sales_order__create` → `sales_order.create`。"""
    parts = tool_name.split("__")
    return ".".join(parts[-2:]) if len(parts) >= 3 else tool_name


# ── 会话归属 / 持久化 helper ────────────────────────────

def sanitize_history(msgs: list) -> list:
    """净化持久化历史，避免 LLM API 400（tool_calls 后必须紧跟完整的 tool 应答）。

    服务在工具调用轮次中途被打断（重启/崩溃）时，已落库的 assistant(tool_calls)
    消息可能缺失部分或全部 tool 应答。这里做通用修复：发现任一带 tool_calls 的 assistant
    后续 tool 应答 id 集合不完整，或出现孤立 tool 消息，即从该处截断（只改送入 LLM 副本）。
    """
    cut = None
    i = 0
    while i < len(msgs):
        m = msgs[i]
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            need = {tc.get("id") for tc in m["tool_calls"]}
            got, j = set(), i + 1
            while j < len(msgs) and msgs[j].get("role") == "tool":
                got.add(msgs[j].get("tool_call_id"))
                j += 1
            if got != need:
                cut = i
                break
            i = j
        elif role == "tool":
            cut = i
            break
        else:
            i += 1
    return msgs[:cut] if cut is not None else msgs


def ensure_session(app_name, session_id: str) -> None:
    """首次接触某 session_id 时落库（owner 取登录名；CLI 无登录态取身份 userno）。"""
    if agent_state.get_session(session_id) is not None:
        return
    u = users.session_user()
    ctx = users.current_caller_ctx()
    owner = (u["username"] if u else ((ctx or {}).get("userno") or "cli"))
    scope = app_name or "__platform__"
    agent_state.create_session(session_id, owner, scope)


def auto_title(session_id: str, first_message: str) -> None:
    """首条用户消息自动生成会话标题（空标题时）。"""
    sess = agent_state.get_session(session_id)
    if sess is not None and not sess["title"]:
        title = first_message.strip().replace("\n", " ")[:20]
        agent_state.set_title(session_id, title or "新对话")


def reset_session(session_id: str) -> None:
    """清空该会话的全部历史（保留会话本身）。"""
    agent_state.clear_state(session_id)


# ── system prompt 组装 ─────────────────────────────────

# 架构文档候选文件名（按优先级）：旧「应用组设计」产出中文名，新「应用组构建」三步法产出英文名。
_ARCH_FILENAMES = ("架构设计.md", "architecture.md")


def _read_arch_docs(platform) -> str:
    """逐应用组读取架构设计文档（`app/<组>/架构设计.md` 或 `architecture.md`），拼成跨应用编排依据。"""
    parts = []
    apps_dir = platform.apps_dir
    for group in platform.groups():
        text = ""
        for fname in _ARCH_FILENAMES:
            p = apps_dir / group / fname
            try:
                if p.is_file():
                    text = p.read_text(encoding="utf-8").strip()
                    if text:
                        break
            except OSError:
                continue
        if text:
            parts.append(f"# 应用组：{group}\n\n{text}")
    return "\n\n---\n\n".join(parts)


def build_system_prompt(platform, app_name: str | None) -> str:
    """组装 system 提示词（应用级：README+服务目录；平台级：授权过滤的全平台目录+架构文档）。

    返回 system 消息的 content 字符串（调用方自行包成 {"role":"system"}）。
    """
    if app_name is None:
        return _platform_prompt(platform)
    return _app_prompt(platform, app_name)


def _app_prompt(platform, app_name: str) -> str:
    services = platform.services(app_name)
    lines = []
    for s in services:
        params = ", ".join(
            p["name"] + ("" if p["required"] else f"={p['default']!r}")
            for p in s["parameters"]
        )
        lines.append(f"- {s['name']}({params})：{s['description'] or '（无说明）'}")
    catalog = "\n".join(lines) or "（该应用暂无对外服务）"
    readme = platform.readme(app_name).strip() or "（该应用暂无 README.md）"

    return f"""你是 FDE 技术平台「{app_name}」应用的操作助手。
你通过工具（function calling）调用该应用对外提供的服务来满足用户请求。

下面是该应用的说明文档（业务背景 / 标准工作流 / 注意事项 / 错误处理），请优先遵循：
<readme>
{readme}
</readme>

可用工具（名称均为 {tool_prefix(app_name)}__<服务名>，参数以下列签名为准）：
{catalog}

数据导入（平台内置文件工具，名称为 {tool_prefix(app_name)}__platform_*）：
- {tool_prefix(app_name)}__platform_list_files：列出 resource/import-file/（用户上传的待导入文件）或 export-file/ 下的文件
- {tool_prefix(app_name)}__platform_read_file：读取文件内容（csv / 文本 / xlsx）以解析
- {tool_prefix(app_name)}__platform_write_file：向 resource/export-file/ 写入结果文本（import-file 为人工上传区，不可写）
典型导入流程：platform_list_files(import-file) 查看上传了哪些文件 → platform_read_file 读取并解析 →
调用本应用服务写入数据 → 必要时 platform_write_file 导出处理报告。

操作规则：
1. 优先按 README「标准工作流」的顺序调用工具；出错时按 README「错误处理·Agent 应对策略」处理。
2. 用中文回复。
3. 需要多步时按合理顺序调用工具，每步完成后向用户简要汇报。
4. 涉及删除等危险操作，先向用户确认再执行。
5. 工具返回中含 "error" 字段时，把错误原因如实告知用户，不要臆造成功。
6. 当前调用身份由平台统一注入，你无需也无法指定身份。
"""


def _platform_prompt(platform) -> str:
    sections = []
    for name in sorted(platform.app_names()):
        svcs = platform.services(name)
        visible = set(users.visible_service_names(name, [s["name"] for s in svcs]))
        lines = []
        for s in svcs:
            if s["name"] not in visible:
                continue
            params = ", ".join(
                p["name"] + ("" if p["required"] else f"={p['default']!r}")
                for p in s["parameters"]
            )
            lines.append(f"  - {tool_prefix(name)}__{s['name']}({params})：{s['description'] or '（无说明）'}")
        if not lines:
            continue
        doc = (platform.handle(name).cls.__doc__ or "").strip().split("\n")[0]
        sections.append(f"## {name} — {doc}\n" + "\n".join(lines))
    catalog = "\n".join(sections) or "（当前身份没有任何可用服务）"

    arch = _read_arch_docs(platform)
    arch_block = f"""
下面是本平台**各应用组**的架构设计（每组一份 `app/<组>/架构设计.md` 或 `architecture.md`：
聚合根划分、各应用职责、跨应用引用与调用链、状态机）。跨应用编排时以它为业务依据
（哪个应用管什么、谁调谁、状态如何流转）：
<architecture>
{arch}
</architecture>
""" if arch else "（未找到任何应用组的架构设计文档，仅凭工具目录编排）"

    groups_desc = "、".join(platform.groups()) or "（无）"
    return f"""你是 FDE 技术平台的**平台级操作助手**，可跨应用编排调用服务。
平台现有 {len(platform.app_names())} 个应用，分布在以下应用组：{groups_desc}。
工具名形如 <组>__<应用名>__<服务名>（未分组应用为 <应用名>__<服务名>）；
凡出现在下方清单中的应用（含各组）均已在平台注册并可调用，不要以「未注册/未部署」为由拒绝。
下面是按当前身份授权过滤后可用的工具（参数以下列签名为准）：

{catalog}
{arch_block}
操作规则：
1. 跨应用任务按**对应应用组架构设计**中的应用关系与业务链路顺序编排（哪个应用管什么、
   谁调谁、状态如何流转，以该组架构文档为准）；不同应用组相互独立，勿把一组的链路套到另一组。
   架构文档中标注为暂停/不可用（如 ⏸）的应用或能力本期不要调用。
2. 单应用的详细指南（标准工作流 / 错误处理）见其应用详情页的 Agent；本助手面向跨应用组合操作。
3. 用中文回复。
4. 需要多步时按合理顺序调用工具，每步完成后向用户简要汇报。
5. 涉及删除等危险操作，先向用户确认再执行。
6. 工具返回中含 "error" 字段时，把错误原因如实告知用户，不要臆造成功。
7. 当前调用身份由平台统一注入，你无需也无法指定身份；未授权的服务不会出现在上方清单中。
"""
