"""FDE 工具过滤 middleware（第 4 步：软隔离 + 硬兜底）。

按 worker 角色过滤 FDE 工具：
- **软隔离**：`on_model_call` 改写 `tools` 列表，剔除越界的 FDE 工具（LLM 看不到）。
- **硬兜底**：`on_check_permission` 拦截越界调用返回 DENY（即使 LLM 调了也执行不了）。

只过滤 FDE 工具（`组__应用__服务` 或 `platform_*`），AgentScope 内置工具
（TeamSay/TeamCreate/Bash/Read/TaskCreate 等）不受影响——worker 仍需 TeamSay 回报 leader。

角色识别靠 system_prompt 里的 `<!--FDE_ROLE:<role>-->` 标记（见 agent_roles），
不依赖 LLM 起的 member name，因此可靠。
"""
from agentscope.middleware import MiddlewareBase
from agentscope.permission import PermissionBehavior, PermissionDecision

# 全员可用的平台工具（skill 沉淀，非角色域）。
GLOBAL_PLATFORM_TOOLS = {"platform_propose_skill"}


def is_fde_tool(name: str) -> bool:
    """FDE 工具名特征：platform_ 前缀（平台工具）或含 __（组__应用__服务）。"""
    return name.startswith("platform_") or "__" in name


def _tool_name(schema: dict) -> str:
    """从 OpenAI 工具 schema 提取工具名。"""
    if not isinstance(schema, dict):
        return ""
    fn = schema.get("function") or {}
    return fn.get("name") or schema.get("name") or ""


class RoleToolFilterMiddleware(MiddlewareBase):
    """按角色过滤 FDE 工具。"""

    def __init__(self, role: str, allowed: set[str]):
        self.role = role
        self.allowed = allowed | GLOBAL_PLATFORM_TOOLS

    async def on_model_call(self, agent, input_kwargs, next_handler):
        tools = input_kwargs.get("tools") or []
        kept = []
        for t in tools:
            name = _tool_name(t)
            if is_fde_tool(name) and name not in self.allowed:
                continue  # 越界 FDE 工具：从喂给 LLM 的 schema 里剔除
            kept.append(t)
        input_kwargs["tools"] = kept
        return await next_handler(**input_kwargs)

    async def on_check_permission(self, agent, input_kwargs, next_handler):
        tool = input_kwargs.get("tool")
        name = getattr(tool, "name", "") if tool else ""
        if is_fde_tool(name) and name not in self.allowed:
            return PermissionDecision(
                behavior=PermissionBehavior.DENY,
                message=f"角色 {self.role} 无权调用 {name}",
            )
        return await next_handler(**input_kwargs)


# leader 是编排者：只保留查询类服务（回答简单问题）+ propose_skill；
# 写操作（create/update/delete/import/publish 等）与文件工具交给 worker 承担。
_QUERY_PREFIXES = ("list", "get", "query", "calc", "fit", "search")
_QUERY_KEYWORDS = ("summary", "history", "sequence", "purchasing", "water", "latest")


def is_query_service(service: str) -> bool:
    """按服务名判定查询类服务（无副作用，leader 可安全直调）。"""
    return service.startswith(_QUERY_PREFIXES) or any(k in service for k in _QUERY_KEYWORDS)


class LeaderToolFilterMiddleware(MiddlewareBase):
    """leader 工具收窄：只保留查询类服务 + propose_skill。

    leader 是编排者：查询可直调（如「查客户数」），写操作/文件工具交给 worker。
    仅过滤 FDE 工具（``组__应用__服务`` / ``platform_*``），AgentScope 内置工具不受影响。
    """

    async def on_model_call(self, agent, input_kwargs, next_handler):
        tools = input_kwargs.get("tools") or []
        kept = []
        for t in tools:
            name = _tool_name(t)
            if not is_fde_tool(name):
                kept.append(t)  # 内置工具（TeamSay/Bash 等）保留
                continue
            if name in GLOBAL_PLATFORM_TOOLS:
                kept.append(t)  # propose_skill 保留
                continue
            service = name.rsplit("__", 1)[-1]
            if is_query_service(service):
                kept.append(t)  # 查询类业务服务保留
        input_kwargs["tools"] = kept
        return await next_handler(**input_kwargs)
