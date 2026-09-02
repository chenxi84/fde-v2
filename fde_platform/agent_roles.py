"""psc 智能体角色定义（开发时定义，落盘即生效）。

角色 = 领域分工的投影：骨架（system prompt 模板 + 绑定的应用集合）代码定义，
权限复用 FDE 授权体系（见 design-plus/多智能体方案.md §三）。

一个角色 = SubAgentTemplate（供 leader 建队）+ 绑定的应用集合（供第 4 步工具隔离）。

psc 四角色（产销协同链）：
- sales      销售/需求侧 —— 预测、历史、拟合、客户、月度版本、达成率
- planning   计划/排产侧 —— 项目、零件、需求、主计划、需求池
- inventory  物料/库存侧 —— 物料、断点、替换、库存策略、库存推移
- delivery   交付/出库侧 —— 出库计划
"""
from agentscope.app import SubAgentTemplate

# 角色 → 绑定的应用（qualname）。供 system prompt 描述 + 第 4 步工具隔离 middleware。
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

_ROLE_LABEL: dict[str, str] = {
    "sales": "销售/需求专家",
    "planning": "计划/排产专家",
    "inventory": "物料/库存专家",
    "delivery": "交付/出库专家",
}


def _app_short(app: str) -> str:
    return app.split("/")[-1]


def _build_template(role: str) -> SubAgentTemplate:
    apps = ROLE_APPS[role]
    label = _ROLE_LABEL[role]
    app_list = "、".join(_app_short(a) for a in apps)
    # 普通字符串（非 f-string）：{member_name} 等占位符留给 AgentScope 的 AgentCreate 填充。
    prompt = (
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


# 供 create_app(custom_subagent_templates=AGENT_ROLES) 注册。
AGENT_ROLES: list[SubAgentTemplate] = [_build_template(r) for r in ROLE_APPS]
