"""智能体角色定义（开发时定义，落盘即生效）。

角色 = 领域分工的投影：骨架（system prompt 模板 + 绑定的应用/工具集合）代码定义，
权限复用 FDE 授权体系（见 design-plus/多智能体方案.md §三）。

一个角色 = SubAgentTemplate（供 leader 建队）+ 绑定集合（供第 4 步工具隔离）。

两类角色：
- **业务角色**（ROLE_APPS）：绑定应用。下沉到各组 `app/<组>/_roles.py` 声明，平台扫描装配。
- **平台运维角色**（ROLE_PLATFORM_TOOLS）：绑定平台工具，映射平台配置 ——
  integration（接口集成）/ scheduler（定时任务）。仅 admin 建队时可用（底层工具 admin 专用）。
"""
import re
from pathlib import Path

from agentscope.app import SubAgentTemplate

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

_PLATFORM_LABEL: dict[str, str] = {
    "integration": "接口集成专家",
    "scheduler": "定时任务专家",
}


# ── 业务角色：下沉到各组 app/<组>/_roles.py 声明，平台扫描装配 ─────
# 约定：每个应用组在自身目录放 _roles.py，导出 ROLES = [{type, label, apps}]。
# 加新组 = 建目录 + 丢一份 _roles.py，无需改本文件。
_ROLES_DIR = Path(__file__).resolve().parents[1] / "app"


def _load_group_roles() -> tuple[dict[str, list[str]], dict[str, str]]:
    """扫描 app/<组>/_roles.py，装配 {role: [apps]} 与 {role: label}。

    任一文件出错仅跳过该组，不阻断平台启动；角色 type 全局唯一，冲突时按目录名排序后者覆盖前者。
    """
    role_apps: dict[str, list[str]] = {}
    role_label: dict[str, str] = {}
    if not _ROLES_DIR.is_dir():
        return role_apps, role_label
    for group_dir in sorted(_ROLES_DIR.iterdir()):
        if not group_dir.is_dir() or group_dir.name.startswith((".", "__")):
            continue
        roles_file = group_dir / "_roles.py"
        if not roles_file.is_file():
            continue
        ns: dict = {}
        try:
            exec(compile(roles_file.read_text(encoding="utf-8"), str(roles_file), "exec"), ns)
        except Exception:
            continue  # 组角色声明有误：跳过该组
        for r in ns.get("ROLES") or []:
            if not isinstance(r, dict):
                continue
            rtype = (r.get("type") or "").strip()
            apps = [a for a in (r.get("apps") or []) if a]
            if not rtype or not apps:
                continue
            role_apps[rtype] = apps
            role_label[rtype] = (r.get("label") or rtype).strip()
    return role_apps, role_label


ROLE_APPS, _BIZ_LABEL = _load_group_roles()
_ROLE_LABEL: dict[str, str] = {**_BIZ_LABEL, **_PLATFORM_LABEL}

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


def role_label(role: str) -> str | None:
    """角色中文标签（sales → 销售/需求专家）；未登记返回 None。"""
    return _ROLE_LABEL.get(role)


def leader_role_choices() -> str:
    """leader system prompt 用：可选 subagent_type 清单（从角色注册表动态生成，单一数据源）。

    业务角色带应用列表，平台运维角色只带标签；加新角色只需改 ROLE_APPS / ROLE_PLATFORM_TOOLS，
    leader prompt 自动跟上，无需改 web.py。
    """
    parts = []
    for role, apps in ROLE_APPS.items():
        parts.append(f"{role}（{_ROLE_LABEL[role]}：{'、'.join(_app_short(a) for a in apps)}）")
    for role in ROLE_PLATFORM_TOOLS:
        parts.append(f"{role}（{_ROLE_LABEL[role]}）")
    return "、".join(parts)


def role_group(role: str) -> str | None:
    """角色归属应用组：业务角色从其绑定应用推断组；平台角色返回 None（跨组）。"""
    apps = ROLE_APPS.get(role)
    if apps:
        return apps[0].split("/")[0]
    return None
