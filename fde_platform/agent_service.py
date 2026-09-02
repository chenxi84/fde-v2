"""AgentScope agent_service 入口（多智能体编排层，独立 FastAPI 进程）。

通过 ``extra_agent_tools`` 把 FDE 业务服务桥接为 AgentScope 工具（按 ``X-User-ID``
映射的 FDE 用户服务授权过滤，fail-closed）。多智能体 team 能力由 AgentScope app
框架内置（Leader 自治建队：TeamCreate/AgentCreate/TeamSay）。

角色工具隔离（软隔离 + 硬兜底）见 design-plus/多智能体方案.md §五，后续经
``extra_agent_middlewares`` 实现；本文件当前只打通「FDE 工具可被 agent_service 调用」。

启动：python -m fde_platform.agent_service  → http://127.0.0.1:4100
"""
import os
from pathlib import Path

from agentscope.app import create_app
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.storage import AsyncSQLAlchemyStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import FunctionTool, ToolGroup

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

# 危险服务判定（与 agent_agentscope.is_dangerous_tool 同口径）：命中即走 HITL 确认。
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


# app qualname → 角色（供 leader 查询工具按领域分组懒加载）
_APP_ROLE: dict[str, str] = {}
for _r, _apps in agent_roles.ROLE_APPS.items():
    for _a in _apps:
        _APP_ROLE[_a] = _r

# 角色 → 查询组描述（ResetTools 的 input_schema 用，LLM 据此决定激活哪个组）
_QUERY_GROUP_DESC = {
    "sales": "销售/需求域查询（预测/历史/客户/月度版本/达成率）",
    "planning": "计划/排产域查询（项目/需求/主计划/需求池）",
    "inventory": "物料/库存域查询（物料/断点/替换/策略/推移）",
    "delivery": "交付/出库域查询（出库计划）",
    "other": "其他应用查询",
}


async def _fde_tool_factory(user_id: str, agent_id: str, session_id: str):
    """把 FDE 业务服务桥接为 AgentScope 工具。

    返回 ``(tools, tool_groups)`` 元组（配合 [FDE-PATCH] 的 get_toolkit）：
    - leader：propose_skill 进 basic；查询类服务按领域装进 ToolGroup（懒加载压首 token）
    - worker：全量工具进 basic，由 RoleToolFilterMiddleware 按角色过滤
    每次组装 agent 时调用（授权变更即时生效）；未知用户返回空（fail-closed）。
    """
    user = users.get_user_by_name(user_id)
    if user is None:
        return ([], [])

    def _make_call(tool_name: str):
        # 闭包捕获工具名 + user，避免与工具自身参数（如 propose_skill 的 name）冲突
        def _call(**kwargs):
            return bridge.execute(_platform, user, tool_name, kwargs)
        return _call

    def _mk_ft(t):
        name = t["function"]["name"]
        ft = FunctionTool(_make_call(name), name=name, description=t["function"]["description"])
        ft.input_schema = _slim_schema(t["function"]["parameters"])
        # 权限：普通工具 ALLOW（授权已由 execute 层 fail-closed）；危险工具 ASK（HITL）。
        ft.check_permissions = _mk_ask() if _is_dangerous(name) else _mk_allow()
        return ft

    defs = bridge.tool_schemas(_platform, user)

    # 区分 leader / worker
    record = await _storage.get_agent(user_id, agent_id)
    if record is not None and record.source == "team":
        # worker：全量工具（middleware 按角色过滤）
        return ([_mk_ft(t) for t in defs], [])

    # leader：propose_skill 进 basic，查询工具按领域分组（懒加载）
    basic = []
    groups: dict[str, list] = {}
    for t in defs:
        app = t["_meta"]["app"]
        name = t["function"]["name"]
        service = name.rsplit("__", 1)[-1]
        if app == "__platform__":
            if name.endswith("propose_skill"):
                basic.append(_mk_ft(t))
            continue
        if not agent_tool_filter.is_query_service(service):
            continue  # 写服务/文件工具：leader 编排不需要
        role = _APP_ROLE.get(app, "other")
        groups.setdefault(role, []).append(_mk_ft(t))
    tool_groups = [
        ToolGroup(name=f"{r}_query", description=_QUERY_GROUP_DESC.get(r, r), tools=fts)
        for r, fts in sorted(groups.items())
    ]
    return (basic, tool_groups)


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
    # leader：去掉内置文件工具 + 平台配置工具（编排不需要，收窄缓解全量工具慢）
    return [agent_tool_filter.LeaderToolFilterMiddleware()]


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

    uvicorn.run("fde_platform.agent_service:app", host="127.0.0.1", port=4100)
