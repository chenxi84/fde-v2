"""AgentScope agent_service 入口（多智能体编排层，独立 FastAPI 进程）。

通过 ``extra_agent_tools`` 把 FDE 业务服务桥接为 AgentScope 工具（按 ``X-User-ID``
映射的 FDE 用户服务授权过滤，fail-closed）。多智能体 team 能力由 AgentScope app
框架内置（Leader 自治建队：TeamCreate/AgentCreate/TeamSay）。

角色工具隔离（软隔离 + 硬兜底）见 design-plus/多智能体方案.md §五，后续经
``extra_agent_middlewares`` 实现；本文件当前只打通「FDE 工具可被 agent_service 调用」。

启动：python -m fde_platform.agent_service  → http://127.0.0.1:4100
"""
import json
import logging
import os
import re
from pathlib import Path

_logger = logging.getLogger(__name__)

# AgentScope 只给自家那个 "as" logger 挂了 handler 并设 propagate=False，
# 根 logger 没有任何 handler —— 于是 fde_platform.* 的 INFO 日志**一条也打不出来**。
# 工具面装配日志是这套收敛方案的验收手段（见 宣传/工具面收敛方案.md §七），
# 看不到就等于没有，所以这里给本模块挂一个 handler。
if not _logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(module)s:%(funcName)s - %(message)s"))
    _logger.addHandler(_h)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False

from agentscope.app import create_app
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.storage import AsyncSQLAlchemyStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.message import Base64Source, DataBlock, TextBlock
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import FunctionTool, ToolChunk, ToolGroup

from fde_platform import agentscope_bridge as bridge
from fde_platform import agent_roles
from fde_platform import agent_tool_filter
from fde_platform import users
from fde_platform.runtime import FdePlatform

# 加载 FDE 应用服务清单。服务调用（bridge.execute → platform.call）每次开短连接、
# 用完即关，与主进程（main.py）WAL 并发安全。
_platform = FdePlatform()
_platform.load_all()

# 数据落 config/（与 FDE 的 auth.db/skills.db 同级，零外部依赖）
_BASE = Path(__file__).resolve().parents[1] / "config"
_DB_URL = os.environ.get(
    "AGENT_SERVICE_DB",
    f"sqlite+aiosqlite:///{(_BASE / 'agent_service.db').as_posix()}",
)
_WORKDIR = str(_BASE / "agent_workspaces")

# 危险服务判定：命中即走 HITL 确认。
_DANGEROUS_PATTERNS = (
    "delete", "remove", "publish", "unpublish", "lock", "deprecate", "cancel",
    "approve", "reject", "archive", "drop", "truncate", "destroy", "deactivate",
    "close",
)


def _is_dangerous(tool_name: str) -> bool:
    service = tool_name.rsplit("__", 1)[-1].lower()
    return any(p in service for p in _DANGEROUS_PATTERNS)


def _mk_allow():
    """普通 FDE 工具：直接放行（FDE 的服务级授权已在 execute 层 fail-closed）。"""

    async def _allow(*_a, **_k):
        return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="")

    return _allow


def _mk_ask():
    """危险 FDE 工具：需人工确认（HITL）。"""

    async def _ask(*_a, **_k):
        return PermissionDecision(
            behavior=PermissionBehavior.ASK,
            message="危险操作，需人工确认",
        )

    return _ask


def _slim_schema(schema: dict) -> dict:
    """精简 JSON schema：去掉 description 与字段名相同的冗余（introspect 生成），压 LLM 首 token 延迟。"""
    if not isinstance(schema, dict):
        return schema
    props = schema.get("properties")
    if isinstance(props, dict):
        for k, v in props.items():
            if isinstance(v, dict) and v.get("description") == k:
                v.pop("description")
    return schema


_VISION_PROMPT = "请提取图片中的全部文字与表格数据，尽量保留行列结构；若为图表请描述关键信息与数值。"


def _as_tool_result(raw: str):
    """工具 JSON 结果 → 纯文本或多模态 ToolChunk（图片多模态 / vision 兜底）。

    read_file 读图片时返回含 image 字段的 JSON：
    - 若配置了 vision 兜底模型，先「看图转文字」把文字喂回主模型（纯文本）；
    - 否则回退为带 DataBlock 的 ToolChunk，把图片直接给当前模型（需视觉模型）。
    """
    if not raw:
        return raw
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if isinstance(data, dict) and isinstance(data.get("image"), dict):
        img = data["image"]
        desc = _vision_fallback(img)
        if desc:
            return ToolChunk(content=[TextBlock(text=(
                f"图片文件 {data.get('name', '')} 的识别结果：\n{desc}"))])
        return ToolChunk(content=[
            TextBlock(text=f"图片文件 {data.get('name', '')}（{data.get('size', 0)} 字节）："),
            DataBlock(source=Base64Source(
                data=img.get("base64", ""),
                media_type=img.get("media_type", "image/png"),
            )),
        ])
    return raw


def _vision_fallback(img: dict) -> str:
    """用 vision 兜底模型「看图转文字」；未配置或失败返回空串（调用方回退图片直通）。"""
    from fde_platform import llm

    prov = llm.get_provider("vision")
    if isinstance(prov, llm.NotConfiguredProvider):
        return ""
    media_type = img.get("media_type", "image/png")
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": _VISION_PROMPT},
            {"type": "image_url", "image_url": {
                "url": f"data:{media_type};base64,{img.get('base64', '')}"}},
        ],
    }]
    try:
        result = prov.chat(messages)
    except Exception:
        return ""
    text = (result or {}).get("content", "").strip()
    if not text or text.startswith("LLM 调用失败") or "未安装" in text:
        return ""
    return text


# app qualname → 角色（供 leader 查询工具按领域分组懒加载）
_APP_ROLE: dict[str, str] = {}
for _r, _apps in agent_roles.ROLE_APPS.items():
    for _a in _apps:
        _APP_ROLE[_a] = _r


# ── 平台工具下发策略（显式声明，单一事实来源）────────────────────
#
# 为什么不用 if/continue 隐式排除：**漏写 = 工具静默消失且无人察觉**。
# 2026-09 踩过——「排除 admin 配置工具」那一句 continue 把流程编排工具一并连坐，
# 「让数字员工跑工作流」「让大模型创建工作流」两条路都不通；而工具定义在
# _platform_tool_defs 里、middleware 的 GLOBAL_PLATFORM_TOOLS 也放行，
# 运行期没有任何报错，只有真的去调才发现工具根本不在。
#
# 约定：新增平台工具必须登记到下面两个集合之一。
# `verify_agent_tools.py` 的登记完整性测试会盯着这件事，漏登记即失败。
_LEADER_PLATFORM_TOOLS = {
    # 知识 / skill 沉淀（全员能力）
    "propose_skill", "read_app_doc", "query_knowledge", "raise_alert",
    # 流程编排：查、跑、看进度、存删。
    # save_flow 在这里是必须的——「让大模型创建工作流」就靠它，
    # 少了它 A3 那类需求只能人工去画布上拖。
    "list_flows", "run_flow", "flow_progress", "save_flow", "delete_flow",
}

_LEADER_PLATFORM_DENIED = {
    # 集成配置：改的是外部系统连接与凭证，属 admin 职责，leader 编排用不到
    "list_integrations", "discover_integrations", "save_integration",
    "delete_integration", "test_integration", "integration_logs",
    # 定时任务配置：配错了会周期性失控，不给 leader
    "list_jobs", "create_job", "update_job", "delete_job",
    "set_job_enabled", "run_job_now",
    # 用户与角色：权限面，绝不下放
    "list_users", "create_user", "delete_user", "reset_password",
    "set_user_role", "set_user_grants",
    "list_roles", "create_role", "delete_role", "set_role_grants",
}


# 内置文件工具里，哪些**不给 agent**。
#
# 每个应用都会挂 3 个内置文件工具（list_files / read_file / write_file）。
# read_file 是刚需——读人工上传的导入文件、图片附件（图片导入那条演示就靠它）。
# 但 list_files / write_file 对 agent 边际价值低，而实测它们在组内**抢选择**：
# A/B 评测里 B 的 9 条未命中中有 4 条是这个原因（3 次错选 list_files）。
# 外部证据说「多余候选会主动伤害准确率」——这里就是那条结论的具体体现。
_AGENT_HIDDEN_BUILTINS = {"platform_list_files", "platform_write_file"}


# worker 常驻的平台工具：直接对齐 middleware 的 GLOBAL_PLATFORM_TOOLS，
# 不另写一份——两处写两份迟早对不上，而「对不上」正是这次事故的形态。
_WORKER_PLATFORM_TOOLS = {
    t["_meta"]["service"] for t in bridge._platform_tool_defs(user=None)
    if t["_meta"]["app"] == "__platform__"
    and t["function"]["name"] in agent_tool_filter.GLOBAL_PLATFORM_TOOLS
}


def platform_tool_registry_gaps() -> set[str]:
    """有定义、却没登记下发策略的平台工具 service 名。

    正常应为空集。非空说明加了平台工具但忘了登记——那它就会静默地不进任何
    agent 的工具表。启动时自检 + 回归测试都调这个函数。
    """
    all_services = {t["_meta"]["service"] for t in bridge._platform_tool_defs(user=None)
                    if t["_meta"]["app"] == "__platform__"}
    return all_services - _LEADER_PLATFORM_TOOLS - _LEADER_PLATFORM_DENIED


def _leader_gets_platform_tool(service: str) -> bool:
    """leader 是否拿到该平台工具。未登记的默认不给（fail-closed），并已在启动时告警。"""
    return service in _LEADER_PLATFORM_TOOLS


# 启动自检：登记缺口一出现就吼一声，别等到演示当天才发现工具没了
_gaps = platform_tool_registry_gaps()
if _gaps:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "平台工具未登记下发策略（默认不下发给 leader）：%s —— 请补进 "
        "agent_service._LEADER_PLATFORM_TOOLS 或 _LEADER_PLATFORM_DENIED",
        "、".join(sorted(_gaps)))


# ── 工具分组：一律按**应用**，不按角色 ─────────────────────────────
#
# 曾经 leader 按角色分组、worker 平铺。按角色分组看着更贴「领域」，
# 实测却踩坑：psc 一个 sales 角色就是 6 个应用、58 个工具，一激活直接进塌陷区
# （外部证据：单次呈现 >~60 即塌陷，且多余候选主动伤害准确率）。
# 按应用分则每组 ≤ ~14，且「应用」是平台天然的语义单元（一个应用一个库一个聚合根），
# 组描述用应用中文名就能说清，不需要额外维护映射。
def _app_group_desc(app: str) -> str:
    """应用分组的描述：中文名 + 一句话职责 + 归属角色。

    优先级：**组级声明的提示** > 前端页面注册表（PAGE_META 的 name/crumb）> 应用短名。

    为什么要有「组级提示」这一层：初版只用注册表的 crumb，实测 A/B 评测里
    **最大的新增失败模式就是「组选错」**（demand_pool 选成 demand、md_project 选成
    master_plan），因为相邻应用的 crumb 都是「计划/排产专家域：xxx」这种同构文案，
    模型分不出该开哪个。提示层专门写「什么时候用它、什么时候用隔壁那个」。
    注册表仍是默认来源——它是应用自述的单一事实来源，不该在平台侧复制一份。
    """
    hint = agent_roles.group_hint_for(app)
    if hint:
        return hint
    short = app.split("/")[-1]
    role = _APP_ROLE.get(app, "")
    label = agent_roles.role_label(role) if role else ""
    try:
        from fde_platform import view_registry
        group, _, key = app.partition("/")
        for m in (view_registry.registry().get("modules") or []):
            if m.get("module") != group:
                continue
            for page in (m.get("pages") or []):
                if page.get("id") == f"{group}:{key}":
                    name = page.get("name") or short
                    crumb = (page.get("crumb") or "").split("·")[0].strip()
                    tail = f"（{label}域）" if label else ""
                    return f"{name}{tail}：{crumb}" if crumb else f"{name}{tail}"
    except Exception:
        pass
    return f"{short}（{label}域）" if label else short


def _split_by_app(defs: list) -> dict[str, list]:
    """把工具定义按 `_meta.app` 分组，跳过平台工具。**分组口径的唯一实现**。

    工厂与回归测试都调这个函数——两边各写一份迟早对不上，
    而「对不上」正是这次事故的形态（工厂少发工具，测试却以为一切正常）。
    """
    by_app: dict[str, list] = {}
    for t in defs:
        app = t["_meta"]["app"]
        if app == "__platform__":
            continue
        by_app.setdefault(app, []).append(t)
    return by_app


# 懒加载下模型可能同时开多个组，工具面就叠加回去了。
# 外部证据（arXiv:2605.24660）：多余候选会**主动伤害**选择准确率，
# 所以「用完就关」不是洁癖，是准确率问题。这条随组激活一起下发。
_GROUP_INSTRUCTIONS = (
    "完成本域任务后，若接下来要处理其他应用，请先停用本组再激活目标组，"
    "避免同时挂着多组工具——同时激活的工具越多，选错工具的概率越高。"
)


# leader system_prompt 里的组标记（供工具工厂按组收窄业务工具）
_GROUP_MARK = re.compile(r"<!--FDE_GROUP:(\w+)-->")


def _extract_group(system_prompt: str) -> str | None:
    """从 leader 的 system_prompt 提取所属应用组；无标记（worker/旧数据）返回 None。"""
    m = _GROUP_MARK.search(system_prompt or "")
    return m.group(1) if m else None


async def _fde_tool_factory(user_id: str, agent_id: str, session_id: str):
    """把 FDE 业务服务桥接为 AgentScope 工具。

    返回 ``(tools, tool_groups)`` 元组（配合 [FDE-PATCH] 的 get_toolkit）：

    - **leader**：平台工具按白名单进 basic，业务工具按**角色**分组懒加载
    - **worker**：平台工具按白名单进 basic，业务工具按**应用**分组懒加载

    两者都走「常驻少量 + 其余懒加载」——外部证据显示单次呈现的工具数超过 ~60
    进入选择塌陷区，且**多余候选会主动伤害准确率**；worker 原来是把角色可见的
    全部工具平铺（sales 66 个），这里补齐与 leader 一致的懒加载。

    每次组装 agent 时调用（授权变更即时生效）；未知用户返回空（fail-closed）。
    """
    user = users.get_user_by_name(user_id)
    if user is None:
        return ([], [])

    def _make_call(tool_name: str):
        # 闭包捕获工具名 + user，避免与工具自身参数（如 propose_skill 的 name）冲突
        def _call(**kwargs):
            return _as_tool_result(bridge.execute(_platform, user, tool_name, kwargs))
        return _call

    def _mk_ft(t):
        name = t["function"]["name"]
        ft = FunctionTool(_make_call(name), name=name, description=t["function"]["description"])
        ft.input_schema = _slim_schema(t["function"]["parameters"])
        # 权限：普通工具 ALLOW（授权已由 execute 层 fail-closed）；危险工具 ASK（HITL）。
        ft.check_permissions = _mk_ask() if _is_dangerous(name) else _mk_allow()
        return ft

    defs = bridge.tool_schemas(_platform, user)

    # 剪枝：摘掉 ①各组声明为「不给 agent」的服务（内部回填、外部回执、被 batch 版取代的单行版）
    # 与 ②对 agent 边际价值低、却会在组内抢选择的内置文件工具。
    # 依据外部证据「多余候选会主动伤害选择准确率」——能摘就摘，摘掉比留着强。
    _before = len(defs)
    defs = [t for t in defs
            if t["_meta"].get("service") not in _AGENT_HIDDEN_BUILTINS
            and not agent_roles.is_hidden_from_agent(
                t["_meta"]["app"], t["_meta"].get("service", ""))]
    if len(defs) != _before:
        _logger.debug("工具剪枝：%d → %d", _before, len(defs))

    # 区分 leader / worker
    record = await _storage.get_agent(user_id, agent_id)

    if record is not None and record.source == "team":
        # ── worker：按角色收窄，再按**应用**子分组懒加载 ──
        # 组粒度选「应用」而非更细的动作：组描述要能一句话说清何时激活，
        # 应用的职责边界天然适合；更细会让模型多几次开关组往返，而研究指出
        # 纯分组不减往返时反而 +15% 开销。
        role = agent_roles.extract_role(record.data.system_prompt)
        allowed = agent_roles.allowed_tools_for_role(role, defs)
        basic, keep = [], []
        for t in defs:
            if t["_meta"]["app"] == "__platform__":
                if t["_meta"].get("service") in _WORKER_PLATFORM_TOOLS:
                    basic.append(_mk_ft(t))
                continue
            if t["function"]["name"] in allowed:
                keep.append(t)
        tool_groups = [
            ToolGroup(name=a.split("/")[-1], description=_app_group_desc(a),
                      instructions=_GROUP_INSTRUCTIONS, tools=[_mk_ft(t) for t in fts])
            for a, fts in sorted(_split_by_app(keep).items())
        ]
        _log_surface(f"worker/{role}", basic, tool_groups)
        return (basic, tool_groups)

    # ── leader：按组收窄业务工具（从 system_prompt 的 FDE_GROUP 标记提取组）──
    group = _extract_group(record.data.system_prompt) if record is not None else None
    if group and group != "__platform__":
        defs = [t for t in defs
                if t["_meta"]["app"] == "__platform__"
                or t["_meta"]["app"].startswith(group + "/")]

    # 平台工具走显式白名单（见文件上方 _LEADER_PLATFORM_TOOLS 的说明）；
    # 业务工具按应用分组懒加载（与 worker 同口径，见 _split_by_app 的说明）。
    basic, keep = [], []
    for t in defs:
        if t["_meta"]["app"] == "__platform__":
            if _leader_gets_platform_tool(t["_meta"].get("service", "")):
                basic.append(_mk_ft(t))
            continue
        keep.append(t)
    tool_groups = [
        ToolGroup(name=a.split("/")[-1], description=_app_group_desc(a),
                  instructions=_GROUP_INSTRUCTIONS, tools=[_mk_ft(t) for t in fts])
        for a, fts in sorted(_split_by_app(keep).items())
    ]
    _log_surface(f"leader/{group or 'all'}", basic, tool_groups)
    return (basic, tool_groups)


def _log_surface(who: str, basic: list, tool_groups: list) -> None:
    """记录本次装配的工具面。

    「单次呈现 schema 数」是这套收敛方案的验收指标（见 宣传/工具面收敛方案.md §七），
    没有这行日志就只能靠猜——出事那次（工具静默消失）正是因为没有可见性。
    """
    _logger.info("工具装配 [%s]：常驻 %d + 懒加载 %d 组 %s",
                 who, len(basic), len(tool_groups),
                 {g.name: len(g.tools) for g in tool_groups} or "—")


# storage 提到模块级：middleware 工厂需闭包捕获它查 AgentRecord（识别 worker 角色）。
_storage = AsyncSQLAlchemyStorage(_DB_URL, create_tables=True)


async def _fde_middleware_factory(
    user_id: str, agent_id: str, session_id: str, workspace=None,
) -> list:
    """工具过滤 middleware 工厂：按 worker 角色返回 RoleToolFilterMiddleware。

    签名固定为 AgentMiddlewareFactory。只对 team 来源的 worker 生效（leader 不过滤）；
    角色从 system_prompt 的 <!--FDE_ROLE:xxx--> 标记提取，可靠不依赖 LLM 起名。
    """
    record = await _storage.get_agent(user_id, agent_id)
    if record is None:
        return []
    if record.source == "team":
        # worker：按角色过滤到各自域
        role = agent_roles.extract_role(record.data.system_prompt)
        if role is None:
            return []
        user = users.get_user_by_name(user_id)
        tool_defs = bridge.tool_schemas(_platform, user)
        allowed = agent_roles.allowed_tools_for_role(role, tool_defs)
        return [agent_tool_filter.RoleToolFilterMiddleware(role, allowed)]
    # leader：去掉平台配置工具；scheduled session 再禁 ScheduleCreate（防失控循环）。
    # 读写边界交给 AgentScope 原生 permission_mode（定时任务默认 DONT_ASK，ASK 转 DENY）。
    extra_deny = set()
    try:
        sess = await _storage.get_session(user_id, agent_id, session_id)
        if sess is not None and str(sess.source) == "schedule":
            extra_deny = {"ScheduleCreate"}
    except Exception:
        pass  # 查 session 失败不阻断组装（默认不额外禁）
    return [agent_tool_filter.LeaderToolFilterMiddleware(extra_deny=extra_deny)]


# 提高 AgentScope 工具 offload 阈值（默认 10s）：知识图谱查询 platform_query_knowledge
# 耗时 30~70s（LightRAG 检索 + LLM 生成），10s 必被 offload 到后台异步执行，而 wakeup
# 触发的下一轮 reply 不通过原 SSE stream 推送，导致前端收不到最终答案。提高到 180s 让查询
# 同步完成、答案随本轮流返回（与 web.py 的 read timeout 协调一致）。
from agentscope.app.middleware import ToolOffloadMiddleware as _ToolOffloadMiddleware

_orig_offload_init = _ToolOffloadMiddleware.__init__


def _patched_offload_init(self, bg_manager, message_bus, user_id, agent_id, timeout_secs=10.0):
    return _orig_offload_init(self, bg_manager, message_bus, user_id, agent_id, timeout_secs=180.0)


_ToolOffloadMiddleware.__init__ = _patched_offload_init


app = create_app(
    storage=_storage,
    message_bus=InMemoryMessageBus(),
    workspace_manager=LocalWorkspaceManager(basedir=_WORKDIR),
    extra_agent_tools=_fde_tool_factory,
    extra_agent_middlewares=_fde_middleware_factory,
    custom_subagent_templates=agent_roles.AGENT_ROLES,
    title="FDE Agent Service",
)


if __name__ == "__main__":
    import uvicorn

    # host 可配置：本机默认 127.0.0.1；容器部署设 AGENT_HOST=0.0.0.0 供 fde-v2 反代
    uvicorn.run("fde_platform.agent_service:app",
                host=os.environ.get("AGENT_HOST", "127.0.0.1"), port=4100)
