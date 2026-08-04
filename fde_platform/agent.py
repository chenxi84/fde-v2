"""FDE v2 Agent（需求 1.3 的 AGENT 入口 + 平台级跨应用 Agent）。

两种作用域：
- 应用级（app_name=应用名）：工具 = 该应用的服务 + 其内置文件工具，system prompt 注入该应用 README。
- 平台级（app_name=None）：工具 = 当前身份在**所有应用**下被授权的服务（+ 有可见性应用的
  内置文件工具），system prompt 为按授权过滤的全平台服务目录——用于跨应用编排。

工具调用统一经 `platform.call` 路由（与手工调用、MCP 走同一条路，身份由平台注入），
服务级授权在 `_to_llm_tools`（清单过滤）与 `_exec_tool`（执行兜底）两处一致强制。

LLM 走兼容 OpenAI 的接口（DeepSeek/通义/智谱等），由环境变量配置：
    LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
未配置时优雅降级（返回提示，不报错、不阻断）。
"""
import json
import os
import threading
import time
from pathlib import Path

from fde import FdeError
from fde_platform import builtin_tools, chatstore, introspect, llm, users
from fde_platform.runtime import tool_prefix


# ── 执行进度（对话「执行中」可见性）──────────────────────
# 在途对话进度表："scope|session_id" -> {phase, round, tool, tools_done, started_at, updated_at}。
# phase: "llm"（第 round 轮推理中）/ "tool"（正在调用 tool，已完成 tools_done 个）。
# 前端经 web 的 /progress 端点轮询本表渲染「执行中」状态（阶段信号，不含工具返回数据）；
# 对话结束（任一返回路径）即清条目。
_PROGRESS_LOCK = threading.Lock()
AGENT_PROGRESS: dict = {}


def _progress_key(app_name, session_id: str) -> str:
    return f"{app_name or '__platform__'}|{session_id}"


def get_progress(app_name, session_id: str) -> dict | None:
    """读指定会话的在途进度快照（None = 无在途对话）。"""
    with _PROGRESS_LOCK:
        p = AGENT_PROGRESS.get(_progress_key(app_name, session_id))
        return dict(p) if p else None


def _tool_disp(tool_name: str) -> str:
    """qualname 化工具名的简短展示：`demo__sales_order__create` → `sales_order.create`。"""
    parts = tool_name.split("__")
    return ".".join(parts[-2:]) if len(parts) >= 3 else tool_name


class AgentSession:
    """Agent 会话管理器（多 session_id）。app_name=None 为平台级（跨应用）。

    对话历史持久化在 chatstore（config/chat_history.db）：切页面/重启不丢；
    system 提示词不入库，每次续聊按当前身份与授权动态组装。
    """

    # 单次对话最大工具调用轮次（复杂跨应用编排可达数十步；AGENT_MAX_ROUNDS 可继续调高，
    # 但注意隐患：历史随轮次膨胀→后续调用变慢/变贵、极端情况撞模型上下文上限，
    # 以及失控循环的空烧放大——已有「连续 3 轮同签名」检测兜底完全重复循环）
    MAX_ROUNDS = int(os.environ.get("AGENT_MAX_ROUNDS", "60"))

    def __init__(self, platform, app_name: str | None = None, role: str = "operator"):
        self.platform = platform
        self.app_name = app_name
        # 模型角色：operator(操作助手) / builder(构建器)，各自独立配模型（见 fde_platform/llm.py）
        self.role = role

    # ── 对外 ────────────────────────────────────────────────
    def chat(self, user_message: str, session_id: str = "default") -> dict:
        """处理一条用户消息，返回 {"reply", "tool_calls", "done"}（历史持久化）。"""
        self._ensure_session(session_id)
        history = self._sanitize_history(chatstore.load_messages(session_id))
        messages = self._init_session() + history  # system 动态组装 + 已净化历史
        chatstore.append_message(session_id, "user", user_message)
        messages.append({"role": "user", "content": user_message})
        self._auto_title(session_id, user_message)

        llm_tools = self._to_llm_tools()
        tool_log = []
        round_sigs = []  # 每轮工具调用签名，用于原地打转检测
        tools_done = 0   # 已完成工具数（进度展示用）

        try:
            for round_idx in range(self.MAX_ROUNDS):
                self._set_progress(session_id, phase="llm", round=round_idx + 1,
                                   tool="", tools_done=tools_done)
                resp = self._call_llm(messages, llm_tools)

                if not resp.get("tool_calls"):  # LLM 给出最终回复
                    reply = resp.get("content", "")
                    chatstore.append_message(session_id, "assistant", reply)
                    return {"reply": reply, "tool_calls": tool_log, "done": True}

                messages.append(
                    {
                        "role": "assistant",
                        "content": resp.get("content", ""),
                        "tool_calls": resp["tool_calls"],
                    }
                )
                chatstore.append_message(session_id, "assistant", resp.get("content", ""),
                                         tool_calls=resp["tool_calls"])
                for tc in resp["tool_calls"]:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        args = {}
                    self._set_progress(session_id, phase="tool", tool=_tool_disp(name),
                                       tools_done=tools_done)
                    result_text = self._exec_tool(name, args)
                    tools_done += 1
                    self._set_progress(session_id, phase="tool", tool="", tools_done=tools_done)
                    tool_log.append({"tool": name, "args": args, "result": result_text})
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result_text,
                        }
                    )
                    chatstore.append_message(session_id, "tool", result_text,
                                             tool_call_id=tc["id"])

                # 原地打转检测：连续 3 轮重复同一组（工具+参数）→ 提前停止，避免空烧
                round_sigs.append(json.dumps(
                    [(tc["function"]["name"], tc["function"]["arguments"])
                     for tc in resp["tool_calls"]], sort_keys=True, ensure_ascii=False))
                if len(round_sigs) >= 3 and len(set(round_sigs[-3:])) == 1:
                    fallback = (f"检测到连续 3 轮重复调用同一组工具（最近调用："
                                f"{tool_log[-1]['tool']}），可能陷入循环，已停止。\n"
                                f"最近一次工具返回：{str(tool_log[-1]['result'])[:300]}\n"
                                f"请检查上述错误后换种说法重试。")
                    chatstore.append_message(session_id, "assistant", fallback)
                    return {"reply": fallback, "tool_calls": tool_log, "done": False}

            summary = "、".join(t["tool"] for t in tool_log[-10:]) or "（无）"
            fallback = (f"已达到单次对话最大调用轮次（{self.MAX_ROUNDS}），本轮已调用 "
                        f"{len(tool_log)} 个工具，最近：{summary}。\n"
                        f"若任务未完成，可直接回复「继续」接着执行（对话历史已保留）；"
                        f"或把请求拆小后重试。")
            chatstore.append_message(session_id, "assistant", fallback)
            return {"reply": fallback, "tool_calls": tool_log, "done": False}
        finally:
            self._clear_progress(session_id)   # 任一返回路径都清进度，避免残留「执行中」

    def reset(self, session_id: str = "default"):
        """清空该会话的全部历史（保留会话本身）。"""
        chatstore.clear_messages(session_id)

    # ── 执行进度埋点（供前端轮询「执行中」状态）────────────
    def _set_progress(self, session_id: str, **fields):
        key = _progress_key(self.app_name, session_id)
        with _PROGRESS_LOCK:
            p = AGENT_PROGRESS.setdefault(key, {"started_at": time.time()})
            p.update(fields)
            p["updated_at"] = time.time()

    def _clear_progress(self, session_id: str):
        with _PROGRESS_LOCK:
            AGENT_PROGRESS.pop(_progress_key(self.app_name, session_id), None)

    # ── 会话归属 ────────────────────────────────────────────
    @staticmethod
    def _sanitize_history(msgs: list) -> list:
        """净化持久化历史，避免 LLM API 400（tool_calls 后必须紧跟完整的 tool 应答）。

        服务在工具调用轮次中途被打断（重启/崩溃）时，已落库的 assistant(tool_calls)
        消息可能缺失部分或全部 tool 应答。chatstore 仅截断「结尾悬挂」一种情形；
        这里做通用修复：发现任一带 tool_calls 的 assistant 后续 tool 应答 id 集合
        不完整，或出现孤立 tool 消息，即从该处截断（只影响送入 LLM 的副本，不改库）。
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
                if got != need:      # 应答缺失/不完整 → 截断
                    cut = i
                    break
                i = j
            elif role == "tool":     # 孤立 tool（前面不是成对的 assistant）→ 截断
                cut = i
                break
            else:
                i += 1
        return msgs[:cut] if cut is not None else msgs

    def _ensure_session(self, session_id: str):
        """首次接触某 session_id 时落库（owner 取登录名；CLI 无登录态取身份 userno）。"""
        if chatstore.get_session(session_id) is not None:
            return
        u = users.session_user()
        ctx = users.current_caller_ctx()
        owner = (u["username"] if u else ((ctx or {}).get("userno") or "cli"))
        scope = self.app_name or "__platform__"
        chatstore.create_session(session_id, owner, scope)

    def _auto_title(self, session_id: str, first_message: str):
        """首条用户消息自动生成会话标题（空标题时）。"""
        sess = chatstore.get_session(session_id)
        if sess is not None and not sess["title"]:
            title = first_message.strip().replace("\n", " ")[:20]
            chatstore.set_title(session_id, title or "新对话")

    # ── 工具执行（与手工调用/MCP 同走 platform.call）──────────
    def _tool_index(self) -> dict:
        """工具名 → (应用 qualname, 服务名) 反查表（含内置文件工具），首次调用时缓存。

        qualname 化工具名形如 `<组>__<名>__<服务>`（前缀 `组__名` 本身含 `__`），
        不能再按 `split('__', 1)` 拆解（会把 app 误判为组名）。与 MCP 一致，按平台
        工具注册表的 `_meta`（app=qualname / service）反查才权威。工具集在 load_all
        后静态，会话内缓存安全。
        """
        idx = getattr(self, "_tool_index_cache", None)
        if idx is None:
            idx = {
                t["name"]: (t["_meta"]["app"], t["_meta"]["service"])
                for t in self.platform.all_mcp_tools()
            }
            self._tool_index_cache = idx
        return idx

    def _exec_tool(self, tool_name: str, args: dict) -> str:
        """执行一次工具调用，返回给 LLM 的文本结果。"""
        args = dict(args or {})
        args.pop("context", None)  # 身份只由平台注入，拒绝伪造（§4.1）
        resolved = self._tool_index().get(tool_name)
        if resolved is None:
            return json.dumps({"error": f"未知工具：{tool_name}"}, ensure_ascii=False)
        app, service = resolved  # app 为 qualname（如 crm/customer），与授权/路由口径一致
        # 服务级授权校验：Agent 经 platform.call 直调、不经闸门，须在此兜住
        u = users.session_user()
        if u is not None and not u.get("is_admin"):
            if builtin_tools.is_builtin_service(service):
                if not users.has_app_access(u["id"], app):
                    return json.dumps({"error": f"无权访问应用：{app}"}, ensure_ascii=False)
            elif not users.is_service_granted(u["id"], app, service):
                return json.dumps({"error": f"无权调用服务：{app}.{service}"}, ensure_ascii=False)
        try:
            if builtin_tools.is_builtin_service(service):
                # 平台内置文件工具：操作该应用文件夹下的 resource 目录
                result = builtin_tools.call_builtin(
                    self.platform.handle(app).folder, service, args
                )
            else:
                # 身份来自登录态（Web 对话有会话）；CLI/MCP 无会话 → None → 平台默认身份
                result = self.platform.call(app, service, ctx=users.current_caller_ctx(), **args)
            return json.dumps(result, ensure_ascii=False)
        except FdeError as e:
            return json.dumps({"error": f"业务失败：{e}"}, ensure_ascii=False)
        except TypeError as e:
            return json.dumps({"error": f"参数错误：{e}"}, ensure_ascii=False)
        except Exception as e:  # 系统异常：记全量、对 LLM 归一（§7）
            import traceback

            traceback.print_exc()
            return json.dumps({"error": f"系统错误：{type(e).__name__}"}, ensure_ascii=False)

    # ── 会话与提示词 ────────────────────────────────────────
    def _read_readme(self) -> str:
        """读取应用 README.md（复用 platform.readme，CONVENTION §11）。"""
        return self.platform.readme(self.app_name).strip()

    def _init_session(self) -> list:
        if self.app_name is None:
            return self._init_platform_session()
        services = self.platform.services(self.app_name)
        lines = []
        for s in services:
            params = ", ".join(
                p["name"] + ("" if p["required"] else f"={p['default']!r}")
                for p in s["parameters"]
            )
            lines.append(f"- {s['name']}({params})：{s['description'] or '（无说明）'}")
        catalog = "\n".join(lines) or "（该应用暂无对外服务）"
        readme = self._read_readme() or "（该应用暂无 README.md）"

        system = f"""你是 FDE 技术平台「{self.app_name}」应用的操作助手。
你通过工具（function calling）调用该应用对外提供的服务来满足用户请求。

下面是该应用的说明文档（业务背景 / 标准工作流 / 注意事项 / 错误处理），请优先遵循：
<readme>
{readme}
</readme>

可用工具（名称均为 {tool_prefix(self.app_name)}__<服务名>，参数以下列签名为准）：
{catalog}

数据导入（平台内置文件工具，名称为 {tool_prefix(self.app_name)}__platform_*）：
- {tool_prefix(self.app_name)}__platform_list_files：列出 resource/import-file/（用户上传的待导入文件）或 export-file/ 下的文件
- {tool_prefix(self.app_name)}__platform_read_file：读取文件内容（csv / 文本 / xlsx）以解析
- {tool_prefix(self.app_name)}__platform_write_file：向 resource/export-file/ 写入结果文本（import-file 为人工上传区，不可写）
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
        return [{"role": "system", "content": system}]

    # 架构文档候选文件名（按优先级）：旧「应用组设计」产出中文名，新「应用组构建」
    # 三步法产出英文名；两者都受支持，取第一个存在的（见 groupbuild_runner / design_runner）。
    _ARCH_FILENAMES = ("架构设计.md", "architecture.md")

    def _read_arch_docs(self) -> str:
        """逐应用组读取架构设计文档（`app/<组>/架构设计.md` 或 `architecture.md`，
        架构创建步骤产出），拼成平台级 Agent 的跨应用编排依据；某组缺失即跳过，
        全部缺失返回空串。

        每个应用组各有一份架构文件（组 = `app/` 下的一级目录，见 runtime.discover_apps）；
        各组文档以「# 应用组：<组>」分节、用分隔线串联后注入 system prompt。
        """
        parts = []
        apps_dir = self.platform.apps_dir
        for group in self.platform.groups():
            text = ""
            for fname in self._ARCH_FILENAMES:
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

    def _init_platform_session(self) -> list:
        """平台级 system prompt：按当前身份授权过滤的全平台服务目录 + 架构设计（跨应用编排用）。"""
        sections = []
        for name in sorted(self.platform.app_names()):
            svcs = self.platform.services(name)
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
            doc = (self.platform.handle(name).cls.__doc__ or "").strip().split("\n")[0]
            sections.append(f"## {name} — {doc}\n" + "\n".join(lines))
        catalog = "\n".join(sections) or "（当前身份没有任何可用服务）"

        arch = self._read_arch_docs()
        arch_block = f"""
下面是本平台**各应用组**的架构设计（每组一份 `app/<组>/架构设计.md` 或 `architecture.md`：
聚合根划分、各应用职责、跨应用引用与调用链、状态机）。跨应用编排时以它为业务依据
（哪个应用管什么、谁调谁、状态如何流转）：
<architecture>
{arch}
</architecture>
""" if arch else "（未找到任何应用组的架构设计文档，仅凭工具目录编排）"

        groups_desc = "、".join(self.platform.groups()) or "（无）"
        system = f"""你是 FDE 技术平台的**平台级操作助手**，可跨应用编排调用服务。
平台现有 {len(self.platform.app_names())} 个应用，分布在以下应用组：{groups_desc}。
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
        return [{"role": "system", "content": system}]

    def _to_llm_tools(self) -> list:
        """服务 + 平台内置文件工具 → OpenAI function calling 工具定义。

        按当前会话用户的服务级授权过滤：聚合服务仅含被授权者；
        内置文件工具在有应用可见性时提供（_exec_tool 再做一次校验）。
        平台级（app_name=None）时遍历全部应用汇总。
        """
        u = users.session_user()
        defs = []
        names = sorted(self.platform.app_names()) if self.app_name is None else [self.app_name]
        for name in names:
            handle = self.platform.handle(name)
            prefix = tool_prefix(name)
            all_svcs = self.platform.services(name)
            visible = set(users.visible_service_names(name, [s["name"] for s in all_svcs]))
            defs += [
                introspect.to_mcp_tool(prefix, s, qualname=name,
                                       group=handle.group, app_name=handle.name)
                for s in all_svcs if s["name"] in visible
            ]
            if u is None or u.get("is_admin") or users.has_app_access(u["id"], name):
                defs += builtin_tools.builtin_tool_defs(prefix, qualname=name,
                                                        group=handle.group, app_name=handle.name)
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["inputSchema"],
                },
            }
            for t in defs
        ]

    # ── LLM 调用 ────────────────────────────────────────────
    def _call_llm(self, messages: list, tools: list) -> dict:
        """返回 {"content": str, "tool_calls": list|None}。

        模型取自 llm 配置中心，按 ``self.role`` 取（operator/builder 各自独立配置）；
        未在「大模型配置」页配置时回退环境变量 LLM_*，仍未配置则优雅降级（不报错、不阻断）。
        实现见 fde_platform/llm.py。
        """
        return llm.get_provider(self.role).chat(messages, tools)


if __name__ == "__main__":  # CLI 自检：python -m fde_platform.agent <app名>
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fde_platform.runtime import FdePlatform

    pf = FdePlatform()
    pf.load_all()
    arg = sys.argv[1] if len(sys.argv) > 1 else "customer"
    name = None if arg in ("platform", "all", "-") else arg
    agent = AgentSession(pf, name)
    scope = "平台级 · 跨应用" if name is None else f"应用 {name}"
    print(f"Agent 就绪（{scope}）。输入消息对话，quit 退出，reset 重置。\n")
    while True:
        try:
            msg = input("你: ")
        except (EOFError, KeyboardInterrupt):
            break
        if msg.strip().lower() == "quit":
            break
        if msg.strip().lower() == "reset":
            agent.reset()
            print("（已重置）")
            continue
        if not msg.strip():
            continue
        r = agent.chat(msg)
        print(f"Agent: {r['reply']}")
        if r["tool_calls"]:
            print("（调用工具：" + "、".join(t["tool"] for t in r["tool_calls"]) + "）")
