"""AgentScope 2.0 Agent 后端（默认，Phase 3 起唯一后端）。

编排循环、模型重试/回落、工具权限、状态恢复交由 AgentScope；FDE 平台继续做
「工具清单 + 身份注入 + 服务级授权 fail-closed + 文件工具 + 视图装配」。

能力：
- **每会话 Agent 缓存**：AgentScope 的 ``AgentState``（sessionId 记忆）跨轮次复用，
  续聊不重放全量历史；跨进程重启经 ``agent_state`` 持久化原生恢复（不再用 chatstore）。
- **HITL 危险操作确认**：危险服务（delete/publish/lock 等）经 AgentScope 原生
  ``ask_rules`` 触发「执行前需人确认」——Agent 停车、前端弹确认、确认后继续。
- **SSE 流式**：文本增量 + 工具调用事件 + 确认请求（confirm_required）逐帧推送。

可插拔：本模块惰性 import AgentScope；失败即 ``AGENTSCOPE_AVAILABLE=False``，
``web._build_agent`` 据此返回降级提示。
"""
import asyncio
import json
import os
import queue
import re
import threading

from fde_platform import agentscope_bridge as bridge
from fde_platform import agent_state, llm, skills, users
from fde_platform.agent_common import (
    auto_title,
    build_system_prompt,
    clear_progress,
    ensure_session,
    reset_session,
    set_progress,
)

# ── 惰性导入 AgentScope（import 失败即整体回落）──────────────
try:
    from agentscope.agent import Agent
    from agentscope.credential import AnthropicCredential, OpenAICredential
    from agentscope.event import (
        ConfirmResult,
        RequireUserConfirmEvent,
        TextBlockDeltaEvent,
        ToolCallStartEvent,
        UserConfirmResultEvent,
    )
    from agentscope.message import Msg, UserMsg
    from agentscope.model import AnthropicChatModel, OpenAIChatModel
    from agentscope.permission import (
        PermissionBehavior,
        PermissionContext,
        PermissionMode,
        PermissionRule,
    )
    from agentscope.state import AgentState
    from agentscope.tool import FunctionTool, Toolkit

    AGENTSCOPE_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    AGENTSCOPE_AVAILABLE = False
    _IMPORT_ERROR = _exc

AGENT_NAME = "assistant"

# 模型 context_size：与旧 agent 一致地「全量发送」——平台级 615 工具的 token 量大，
# 调高到远超实际用量以禁用 AgentScope 的摘要压缩。
_CONTEXT_SIZE = 1_000_000

# ── 危险服务判定（HITL 需人确认）──────────────────────────

_DANGEROUS_PATTERNS = (
    "delete", "remove", "publish", "unpublish", "lock", "deprecate", "cancel",
    "approve", "reject", "archive", "drop", "truncate", "destroy", "deactivate",
    "close",
)


def _dangerous_patterns() -> tuple:
    extra = os.environ.get("FDE_DANGEROUS_SERVICES", "")
    return _DANGEROUS_PATTERNS + tuple(x.strip() for x in extra.split(",") if x.strip())


def is_dangerous_tool(tool_name: str) -> bool:
    """工具名（<组>__<应用>__<服务>）的**服务名**是否命中危险模式（需人确认）。"""
    service = tool_name.rsplit("__", 1)[-1].lower()
    return any(p in service for p in _dangerous_patterns())


# ── 模型构建（llm 配置中心 → AgentScope 模型）────────────────────────

def build_model(role: str = "operator"):
    """把某 role 的 LLM profile 映射为 AgentScope ChatModel；未配置返回 None。"""
    if not AGENTSCOPE_AVAILABLE:
        return None
    p = llm.load_profile(role)
    if p and p.get("enabled") and (p.get("model") or "").strip():
        provider = p["provider"]
        api_key = llm.decrypt_key(p.get("api_key_enc") or "")
        base_url = (p.get("base_url") or "").strip() or None
        model = p["model"].strip()
    else:
        ep = llm._env_fallback()
        if not ep:
            return None
        provider, api_key, base_url, model = (
            ep["provider"], ep["api_key"], ep["base_url"], ep["model"],
        )
    if provider == "anthropic":
        return AnthropicChatModel(
            AnthropicCredential(api_key=api_key, base_url=base_url), model=model,
            context_size=_CONTEXT_SIZE,
        )
    return OpenAIChatModel(
        OpenAICredential(api_key=api_key, base_url=base_url), model=model,
        context_size=_CONTEXT_SIZE,
    )


class AgentScopeSession:
    """AgentScope 编排的 Agent 会话。app_name=None 为平台级（跨应用）。"""

    def __init__(self, platform, app_name: str | None = None, role: str = "operator"):
        self.platform = platform
        self.app_name = app_name
        self.role = role
        # 每会话 Agent 缓存：session_id -> {"agent", "state", "pending"}；
        # pending 非空 = 该会话正停在「需人确认」处等 confirm。
        self._agents: dict = {}
        self._lock = threading.Lock()

    # ── 对外（阻塞式，CLI/演示用）──────────────────────────
    def chat(self, user_message: str, session_id: str = "default") -> dict:
        """处理一条用户消息，返回 {"reply", "tool_calls", "done"}；危险操作停车返回 needs_confirm。"""
        return self._collect(self._dispatch(user_message, session_id))

    def confirm_chat(self, session_id: str, decisions) -> dict:
        """确认/拒绝危险操作后继续（阻塞式，供 CLI/测试；前端走 SSE confirm）。"""
        return self._collect(self._dispatch_confirm(session_id, decisions))

    def _collect(self, q) -> dict:
        reply, tool_calls, confirm = "", [], None
        for evt in iter(q.get, None):
            e = evt["event"]
            if e == "delta":
                reply += evt["data"]
            elif e == "done":
                reply = evt.get("data") or reply
                tool_calls = evt.get("tool_log") or []
            elif e == "confirm_required":
                confirm = evt["data"]
            elif e == "error" and not reply:
                reply = "⚠ " + evt["data"]
        if confirm is not None:
            return {"reply": reply, "tool_calls": tool_calls, "done": False,
                    "needs_confirm": True, "confirm": confirm}
        return {"reply": reply, "tool_calls": tool_calls, "done": True}

    def reset(self, session_id: str = "default"):
        reset_session(session_id)
        with self._lock:
            self._agents.pop(session_id, None)

    # ── SSE 流式（供前端薄客户端）───────────────────────────
    def stream_chat(self, user_message: str, session_id: str = "default"):
        """流式对话：同步生成器，逐条 yield ``data: {json}\n\n``（SSE 帧）。"""
        yield from self._sse_events(user_message, session_id)

    def confirm(self, session_id: str, decisions):
        """用户确认/拒绝后继续（同步生成器，SSE 帧）。decisions=[{id, confirmed}]。"""
        yield from self._sse_confirm(session_id, decisions)

    # ── 事件收集（阻塞式 chat 用）──────────────────────────
    def _events(self, user_message: str, session_id: str):
        q = self._dispatch(user_message, session_id)
        for evt in iter(q.get, None):
            yield evt

    # ── SSE 生成器（stream_chat 用）────────────────────────
    def _sse_events(self, user_message: str, session_id: str):
        q = self._dispatch(user_message, session_id)
        for evt in iter(q.get, None):
            yield "data: " + json.dumps(evt, ensure_ascii=False) + "\n\n"

    def _sse_confirm(self, session_id: str, decisions):
        q = self._dispatch_confirm(session_id, decisions)
        for evt in iter(q.get, None):
            yield "data: " + json.dumps(evt, ensure_ascii=False) + "\n\n"

    # ── 调度：起后台线程跑 asyncio，事件经 queue 回主线程 ─────
    def _dispatch(self, user_message: str, session_id: str) -> queue.Queue:
        if not AGENTSCOPE_AVAILABLE:
            q = queue.Queue()
            q.put({"event": "error", "data": "AgentScope 后端不可用"})
            q.put(None)
            return q
        ensure_session(self.app_name, session_id)
        system_text = build_system_prompt(self.platform, self.app_name) + skills.agent_prompt()
        auto_title(session_id, user_message)
        set_progress(self.app_name, session_id, phase="llm", round=1, tool="", tools_done=0)

        q = queue.Queue()

        def _runner():
            try:
                asyncio.run(self._start_turn(session_id, system_text, user_message, q))
            except Exception as e:
                import traceback
                traceback.print_exc()
                q.put({"event": "error", "data": f"{type(e).__name__}: {e}"})
            finally:
                clear_progress(self.app_name, session_id)
                q.put(None)

        threading.Thread(target=_runner, daemon=True).start()
        return q

    def _dispatch_confirm(self, session_id: str, decisions) -> queue.Queue:
        q = queue.Queue()

        def _runner():
            try:
                asyncio.run(self._resume(session_id, decisions, q))
            except Exception as e:
                import traceback
                traceback.print_exc()
                q.put({"event": "error", "data": f"{type(e).__name__}: {e}"})
            finally:
                q.put(None)

        threading.Thread(target=_runner, daemon=True).start()
        return q

    # ── 异步核心 ─────────────────────────────────────────
    async def _start_turn(self, session_id, system_text, user_message, q):
        with self._lock:
            entry = self._agents.get(session_id)
        if entry is not None and entry.get("pending") is None:
            # 复用缓存 Agent：增量续聊，不重放历史
            agent, state = entry["agent"], entry["state"]
            inputs = UserMsg("user", user_message)
        else:
            prep = await self._build_agent(session_id, system_text, user_message)
            if prep is None:
                label = llm.ROLE_LABELS.get(self.role, self.role)
                q.put({"event": "error",
                       "data": f"Agent「{label}」未配置 LLM。请在 /llm 配置或设 LLM_* 环境变量。"})
                return
            agent, state, inputs = prep
        await self._stream_loop(session_id, agent, state, inputs, q)

    async def _resume(self, session_id, decisions, q):
        with self._lock:
            entry = self._agents.get(session_id)
        if entry is None or not entry.get("pending"):
            q.put({"event": "error", "data": "会话无待确认操作"})
            return
        agent, state = entry["agent"], entry["state"]
        pending = entry["pending"]
        reply_id = entry.get("reply_id")
        by_id = {tc.id: tc for tc in pending}
        results = []
        for d in decisions or []:
            tc = by_id.get((d or {}).get("id"))
            if tc is not None:
                results.append(ConfirmResult(confirmed=bool(d.get("confirmed")), tool_call=tc))
        await self._stream_loop(
            session_id, agent, state,
            UserConfirmResultEvent(reply_id=reply_id, confirm_results=results), q,
        )

    async def _stream_loop(self, session_id, agent, state, inputs, q):
        """跑 reply_stream：推事件；遇确认停车；结束落库并缓存 Agent。"""
        tools = []
        final_text = ""
        async for evt in agent.reply_stream(inputs, yield_final_msg=True):
            if isinstance(evt, Msg):
                final_text = evt.get_text_content() or ""
            elif isinstance(evt, TextBlockDeltaEvent):
                q.put({"event": "delta", "data": evt.delta})
            elif isinstance(evt, ToolCallStartEvent):
                tools.append(evt.tool_call_name)
                q.put({"event": "tool", "data": evt.tool_call_name})
            elif isinstance(evt, RequireUserConfirmEvent):
                with self._lock:
                    self._agents[session_id] = {"agent": agent, "state": state,
                                                "pending": evt.tool_calls,
                                                "reply_id": evt.reply_id}
                q.put({"event": "confirm_required", "data": [
                    {"id": tc.id, "name": tc.name, "input": tc.input}
                    for tc in evt.tool_calls
                ]})
                return  # 停车，等 confirm

        tool_log = self._extract_tool_log(state)
        skills.note_usage([t["tool"] for t in tool_log])
        # 持久化 AgentScope 原生 state（跨进程恢复：load_state → model_validate 重建）
        agent_state.save_state(session_id, agent.state.model_dump(mode="json"))
        with self._lock:
            self._agents[session_id] = {"agent": agent, "state": state, "pending": None}
        q.put({"event": "done", "data": final_text, "tools": tools, "tool_log": tool_log})

    async def _build_agent(self, session_id, system_text, user_message):
        """取/建 Agent：有持久化 state 则原生恢复（跨进程），否则新建。未配置模型返回 None。"""
        model = build_model(self.role)
        if model is None:
            return None
        u = users.session_user()
        tk, ask_rules = await self._build_toolkit(u)
        pc = PermissionContext(mode=PermissionMode.BYPASS, ask_rules=ask_rules)
        saved = agent_state.load_state(session_id)
        if saved is not None:
            state = AgentState.model_validate(saved)
            state.permission_context = pc  # 授权可能已变，刷新为当前 ask_rules
            agent = Agent(
                name=AGENT_NAME, system_prompt=system_text, model=model, toolkit=tk, state=state,
            )
            return agent, state, UserMsg("user", user_message)
        state = AgentState(session_id=session_id, permission_context=pc)
        agent = Agent(
            name=AGENT_NAME, system_prompt=system_text, model=model, toolkit=tk, state=state,
        )
        return agent, state, UserMsg("user", user_message)

    # ── 工具清单（含危险服务 ask_rules）─────────────────────
    async def _build_toolkit(self, user):
        tk = Toolkit()
        dangerous = []

        def _make(tool_name):
            # 闭包捕获工具名，避免与工具自身参数（如 propose_skill 的 name）冲突
            def _call(**kwargs):
                return bridge.execute(self.platform, user, tool_name, kwargs)
            return _call

        for t in bridge.tool_schemas(self.platform, user):
            app = t["_meta"]["app"]
            # 平台级工具（如 platform_propose_skill）恒保留；应用级按 app_name 收窄
            if app != "__platform__" and self.app_name is not None and app != self.app_name:
                continue
            name = t["function"]["name"]
            ft = FunctionTool(_make(name), name=name, description=t["function"]["description"])
            ft.input_schema = t["function"]["parameters"]
            await tk.add_tool(ft)
            if is_dangerous_tool(name) or t["_meta"].get("dangerous"):
                dangerous.append(name)

        ask_rules = {
            n: [PermissionRule(tool_name=n, rule_content=None,
                               behavior=PermissionBehavior.ASK, source="fde")]
            for n in dangerous
        }
        return tk, ask_rules

    # ── 本轮工具调用提取（按 reply_id 过滤本轮 assistant 消息）────
    def _extract_tool_log(self, state) -> list:
        rid = state.reply_id
        log = []
        for m in (state.context or []):
            if m.role != "assistant" or m.name != AGENT_NAME or m.id != rid:
                continue
            results = {b.id: b for b in m.get_content_blocks("tool_result")}
            for b in m.get_content_blocks("tool_call"):
                r = results.get(b.id)
                try:
                    args = json.loads(b.input or "{}")
                except (ValueError, TypeError):
                    args = {}
                out = r.output if r else ""
                if isinstance(out, list):
                    out = "".join(getattr(x, "text", "") for x in out)
                log.append({
                    "tool": b.name,
                    "args": args,
                    "result": out,
                    "_id": b.id,
                    "_llm": {"id": b.id, "type": "function",
                             "function": {"name": b.name, "arguments": b.input}},
                })
        return log


# ── 前端历史派生（AgentState.context → OpenAI 格式）──────────────

def context_to_messages(context) -> list:
    """把 AgentState.context（AgentScope Msg 列表）派生为 OpenAI 格式消息，供前端历史展示。

    与旧 chatstore.load_messages 同形状：user / assistant(tool_calls) / tool 消息。
    """
    msgs = []
    for m in context or []:
        role = getattr(m, "role", None)
        if role == "user":
            msgs.append({"role": "user", "content": (m.get_text_content() or "")})
        elif role == "assistant":
            text = m.get_text_content() or ""
            calls, results = [], []
            for b in m.content:
                t = getattr(b, "type", None)
                if t == "tool_call":
                    calls.append({"id": b.id, "type": "function",
                                  "function": {"name": b.name, "arguments": b.input}})
                elif t == "tool_result":
                    out = b.output
                    if isinstance(out, list):
                        out = "".join(getattr(x, "text", "") for x in out)
                    results.append({"tool_call_id": b.id, "content": out or ""})
            if calls:
                msgs.append({"role": "assistant", "content": text, "tool_calls": calls})
                for r in results:
                    msgs.append({"role": "tool", "tool_call_id": r["tool_call_id"],
                                 "content": r["content"]})
            elif text:
                msgs.append({"role": "assistant", "content": text})
    return msgs


def load_session_messages(session_id: str) -> list:
    """从持久化 AgentState 派生 OpenAI 格式消息（供 web 的历史端点）。"""
    if not AGENTSCOPE_AVAILABLE:
        return []
    saved = agent_state.load_state(session_id)
    if not saved:
        return []
    try:
        state = AgentState.model_validate(saved)
    except Exception:
        return []
    return context_to_messages(state.context)


if __name__ == "__main__":  # CLI 自检：python -m fde_platform.agent_agentscope [<app名>]
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fde_platform.runtime import FdePlatform

    pf = FdePlatform()
    pf.load_all()
    arg = sys.argv[1] if len(sys.argv) > 1 else "platform"
    name = None if arg in ("platform", "all", "-") else arg
    agent = AgentScopeSession(pf, name)
    scope = "平台级 · 跨应用" if name is None else f"应用 {name}"
    print(f"AgentScope 后端就绪（{scope}）。输入消息对话，quit 退出，reset 重置。\n")
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
        if r.get("needs_confirm"):
            print("（需确认操作：" + "、".join(c["name"] for c in r["confirm"]) + "）")
        if r["tool_calls"]:
            print("（调用工具：" + "、".join(t["tool"] for t in r["tool_calls"]) + "）")
