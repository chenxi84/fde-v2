"""智能体角色定义（开发时定义，落盘即生效）。

角色 = 领域分工的投影：骨架（system prompt 模板 + 绑定的应用/工具集合）代码定义，
权限复用 FDE 授权体系（见 design-plus/多智能体方案.md §三）。

一个角色 = SubAgentTemplate（供 leader 建队）+ 绑定集合（供第 4 步工具隔离）。

两类角色：
- **业务角色**（ROLE_APPS）：绑定应用，映射产销协同链 —— sales/planning/inventory/delivery。
- **平台运维角色**（ROLE_PLATFORM_TOOLS）：绑定平台工具，映射平台配置 ——
  integration（接口集成）/ scheduler（定时任务）。仅 admin 建队时可用（底层工具 admin 专用）。
"""
import re

from agentscope.app import SubAgentTemplate

# ── 业务角色：角色 → 绑定的应用（qualname）─────────────────────────
ROLE_APPS: dict[str, list[str]] = {
    "sales": [
        "psc/md_customer", "psc/md_monthly_version", "psc/attainment",
        "psc/sales_forecast", "psc/sales_history", "psc/strategy_fitting",
    ],
    "planning": [
        "psc/md_project", "psc/md_project_part", "psc/demand",
        "psc/master_plan", "psc/demand_pool",
    ],
    "inventory": [
        "psc/md_material", "psc/md_breakpoint", "psc/md_part_replace",
        "psc/inventory_strategy", "psc/inventory_projection",
    ],
    "delivery": [
        "psc/outbound_plan",
    ],
}

# ── 平台运维角色：角色 → 绑定的平台工具（platform_<service>）────────
ROLE_PLATFORM_TOOLS: dict[str, list[str]] = {
    "integration": [
        "platform_list_integrations", "platform_discover_integrations",
        "platform_save_integration", "platform_delete_integration",
        "platform_integration_logs", "platform_test_integration",
    ],
    "scheduler": [
        "platform_list_jobs", "platform_create_job", "platform_update_job",
        "platform_delete_job", "platform_set_job_enabled", "platform_run_job_now",
    ],
}

_ROLE_LABEL: dict[str, str] = {
    "sales": "销售/需求专家",
    "planning": "计划/排产专家",
    "inventory": "物料/库存专家",
    "delivery": "交付/出库专家",
    "integration": "接口集成专家",
    "scheduler": "定时任务专家",
}

# 平台运维角色（仅 admin 可建，见 agent_service 的 subagent_type 收口）
PLATFORM_ROLES = set(ROLE_PLATFORM_TOOLS)


def _app_short(app: str) -> str:
    return app.split("/")[-1]


def _build_app_template(role: str) -> SubAgentTemplate:
    """业务角色：绑定应用集合。"""
    apps = ROLE_APPS[role]
    label = _ROLE_LABEL[role]
    app_list = "、".join(_app_short(a) for a in apps)
    # 普通字符串（非 f-string）：{member_name} 等占位符留给 AgentScope 的 AgentCreate 填充。
    # 首行埋机器标记 <!--FDE_ROLE:<role>-->，供工具过滤 middleware 可靠识别角色（不靠 LLM 起名）。
    prompt = (
        f"<!--FDE_ROLE:{role}-->\n"
        f"你是{{member_name}}，{label}，隶属团队'{{team_name}}'（由{{leader_name}}领导）。\n\n"
        f"团队目标：{{team_description}}\n"
        f"你的分工：{{member_description}}\n\n"
        f"你只负责以下应用的服务，不要越界调用其他角色的应用：\n{app_list}\n\n"
        f"完成分配给你的任务后，用 TeamSay 向 {{leader_name}} 回报结果。"
    )
    return SubAgentTemplate(
        type=role,
        description=f"{label}，负责 {app_list} 等应用",
        system_prompt_template=prompt,
    )


def _build_platform_template(role: str) -> SubAgentTemplate:
    """平台运维角色：绑定平台工具集合（integration / scheduler）。"""
    tools = ROLE_PLATFORM_TOOLS[role]
    label = _ROLE_LABEL[role]
    tool_list = "、".join(tools)
    prompt = (
        f"<!--FDE_ROLE:{role}-->\n"
        f"你是{{member_name}}，{label}，隶属团队'{{team_name}}'（由{{leader_name}}领导）。\n\n"
        f"团队目标：{{team_description}}\n"
        f"你的分工：{{member_description}}\n\n"
        f"你只负责以下平台工具，不要越界调用业务应用服务或其它平台工具：\n{tool_list}\n\n"
        f"完成分配给你的任务后，用 TeamSay 向 {{leader_name}} 回报结果。"
    )
    return SubAgentTemplate(
        type=role,
        description=f"{label}，负责 {tool_list} 等平台工具",
        system_prompt_template=prompt,
    )


# 供 create_app(custom_subagent_templates=AGENT_ROLES) 注册。
AGENT_ROLES: list[SubAgentTemplate] = (
    [_build_app_template(r) for r in ROLE_APPS]
    + [_build_platform_template(r) for r in ROLE_PLATFORM_TOOLS]
)

# 全部角色名（业务 + 平台运维）。
ALL_ROLES: set[str] = set(ROLE_APPS) | set(ROLE_PLATFORM_TOOLS)

# system_prompt 里的角色标记（机器可读，供工具过滤 middleware 识别角色）。
_ROLE_MARK = re.compile(r"<!--FDE_ROLE:(\w+)-->")


def extract_role(system_prompt: str) -> str | None:
    """从 worker 的 system_prompt 提取角色名；非角色 worker 返回 None。"""
    m = _ROLE_MARK.search(system_prompt or "")
    return m.group(1) if m else None


def allowed_tools_for_role(role: str, tool_defs: list[dict]) -> set[str]:
    """从 tool_schemas 返回的 tool 定义，计算某角色允许的工具名集合。

    - 业务角色：按 `_meta.app` ∈ ROLE_APPS[role] 匹配（组__应用__* 工具）。
    - 平台角色：按工具名 ∈ ROLE_PLATFORM_TOOLS[role] 匹配（platform_* 工具）。
    """
    allowed: set[str] = set()
    if role in ROLE_APPS:
        apps = set(ROLE_APPS[role])
        for t in tool_defs:
            if t["_meta"]["app"] in apps:
                allowed.add(t["function"]["name"])
    elif role in ROLE_PLATFORM_TOOLS:
        ptools = set(ROLE_PLATFORM_TOOLS[role])
        for t in tool_defs:
            if t["function"]["name"] in ptools:
                allowed.add(t["function"]["name"])
    return allowed
