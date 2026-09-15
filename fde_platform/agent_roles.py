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


# ── 服务可见性：下沉到各组 app/<组>/_agent_tools.py 声明 ────────────
# 约定：导出 HIDDEN_FROM_AGENT = {"<组>/<应用>": ["服务名", ...]}，
# 列出**明确不该给 agent 调**的服务——内部回填、外部回执、被 batch 版取代的单行版。
#
# 为什么用黑名单而不是白名单：白名单要为 180 个服务逐一表态，加个应用就要同步改，
# 维护不动；而这些「agent 不该碰」的服务是少数、稳定、有明确特征。
# 依据：外部证据显示多余的候选会**主动伤害**工具选择准确率，能摘就摘。
def _load_agent_tools_decl() -> tuple[dict, dict]:
    """扫描各组 _agent_tools.py，装配 (HIDDEN_FROM_AGENT, GROUP_HINTS)。

    一次扫描两个声明：**服务可见性**（哪些服务不给 agent 调）与
    **组描述提示**（这个应用什么时候该激活）。两者都是「组级下沉的 agent 相关声明」，
    放同一个文件、同一次扫描，避免两处各扫一遍迟早不同步。

    任一文件出错仅跳过该组，不阻断平台启动（与 _load_group_roles 同策略）。
    """
    hidden: dict[str, set[str]] = {}
    hints: dict[str, str] = {}
    if not _ROLES_DIR.is_dir():
        return {}, {}
    for group_dir in sorted(_ROLES_DIR.iterdir()):
        if not group_dir.is_dir() or group_dir.name.startswith((".", "__")):
            continue
        decl = group_dir / "_agent_tools.py"
        if not decl.is_file():
            continue
        ns: dict = {}
        try:
            exec(compile(decl.read_text(encoding="utf-8"), str(decl), "exec"), ns)
        except Exception:
            continue  # 组声明有误：跳过该组
        for app, services in (ns.get("HIDDEN_FROM_AGENT") or {}).items():
            if not app:
                continue
            hidden.setdefault(str(app), set()).update(
                s for s in (services or []) if s)
        for app, hint in (ns.get("GROUP_HINTS") or {}).items():
            if app and (hint or "").strip():
                hints[str(app)] = hint.strip()
    return ({k: tuple(sorted(v)) for k, v in hidden.items()}, hints)


HIDDEN_FROM_AGENT, GROUP_HINTS = _load_agent_tools_decl()


def hidden_tools_for(app_name: str) -> tuple[str, ...]:
    """该应用声明为「不给 agent」的服务名；未声明返回空元组。"""
    return HIDDEN_FROM_AGENT.get((app_name or "").strip(), ())


def is_hidden_from_agent(app_name: str, service: str) -> bool:
    return (service or "") in HIDDEN_FROM_AGENT.get((app_name or "").strip(), ())


def group_hint_for(app_name: str) -> str:
    """该应用声明的组描述提示（什么时候激活、和哪个相邻应用别搞混）。"""
    return GROUP_HINTS.get((app_name or "").strip(), "")

# 平台运维角色（仅 admin 可建，见 agent_service 的 subagent_type 收口）
PLATFORM_ROLES = set(ROLE_PLATFORM_TOOLS)


def _app_short(app: str) -> str:
    return app.split("/")[-1]


# 常驻注入的是**精简版**《使用要点》HOWTOUSE.md，不是完整 README.md。
#
# 为什么不直接注入 README：README 是完整操作指南（约 3-4k tokens/应用），
# 一个角色 5-6 个应用就是 13k，每次调用都要重过一遍——实测每次调用约 2 倍延迟；
# 且研究显示指令密度过高会显著降低遵从率（arXiv:2607.19257：指令数到 ~80 条时
# 完美遵从率对所有模型归零；上下文 80% 位置的规则遵从率只有开头的 70%）。
#
# HOWTOUSE 只保留影响「工具选择与调用顺序」的部分（约 500 tokens/应用），
# 砍掉三块：对外服务表（工具名/参数/说明已在每次调用的工具 schema 里，抄一遍是零信息量的
# 重复）、错误处理表（出错时按需读 README）、聚合根/主键等 background。
# 这正是 Anthropic 的 L2/L3 分层：常驻放正文，大规则表按需加载。
#
# **不回落到 README**：新应用忘了写 HOWTOUSE 时宁可什么都不注入，
# 也不要悄悄把 4k tokens 的全量 README 塞回 prompt——那会让这次收敛白做。
_APP_HOWTO = "HOWTOUSE.md"


def _read_app_howtos(apps: list[str]) -> str:
    """读各应用的 HOWTOUSE.md，拼成一个注入块；没有的应用跳过。

    在模块加载时执行（AGENT_ROLES 是模块级常量）——只读文件、不碰平台运行时，
    所以不受「平台是否已 load_all」影响。
    """
    blocks = []
    for qn in apps:
        group, _, short = (qn or "").partition("/")
        if not group or not short:
            continue
        p = _ROLES_DIR / group / short / _APP_HOWTO
        try:
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8").strip()
        except OSError:
            continue  # 单个应用读失败不该拖垮整份角色定义
        if text:
            blocks.append(f'<howto app="{short}">\n{text}\n</howto>')
    return "\n\n".join(blocks)


def apps_missing_howto() -> list[str]:
    """角色绑定里那些**有应用但没写 HOWTOUSE.md** 的项。

    用于启动自检与回归测试：漏写不会报错、只是静默地不注入，
    而「静默地少了一块」正是这次收敛前后一路踩的坑（工具静默消失、README 静默漂移）。
    """
    out = []
    for apps in ROLE_APPS.values():
        for qn in apps:
            group, _, short = (qn or "").partition("/")
            if not group or not short:
                continue
            if not (_ROLES_DIR / group / short / _APP_HOWTO).is_file():
                out.append(qn)
    return sorted(set(out))


# 工作纪律：注入每个业务角色的 system prompt。
#
# 为什么单独拎出来：恢复率实测发现，**失败分两类，命运完全不同**——
#   · 「选错工具」：拿到真实返回后有一半能在下一轮自己换对（实测 2/4）
#   · 「压根不调工具/不开组」：它直接回一段文字，对话就此结束，**没有任何纠错机会**
# 后者是终端失败，占比还不低（C 条件 24 例里 5 例）。而 HOWTOUSE 管的是「按什么顺序调」，
# 管不到「该动手时不动手」，所以这条纪律必须单独写死在这里。
AGENT_DISCIPLINE = (
    "\n\n## 工作纪律（务必遵守）\n"
    "- **能用工具查证的事，一律先调工具再回答**；不要凭常识或上下文猜测后直接给结论。\n"
    "- 参数不全也先用工具查（比如拿不准物料号，就先 `list` 搜一下），确实查不到再问用户。\n"
    "- 一次调一个工具，拿到结果再决定下一步；**发现调错了就立刻换一个**，不要将错就错。\n"
    "- **回答分析类提问时不要改数据**：用户问「有哪些／多少／为什么／会不会／哪个」这类问题时，"
    "**只查询、不动手**——不要为了「确保数据最新」去调重算或写入类服务。这类服务包括但不限于："
    "`refresh`／`refresh_batch`／`scan_alert`／`calc`／`calc_batch`／`decide`／`decide_batch`／"
    "`build_gross`／`publish`／`calc_net`／`run`／`run_batch`／`approve`／`import_*`／`upsert`／"
    "`create`／`update`／`set_*`。**重算会改变系统状态**：用户看到的数据就不再是他问的那个样子了，"
    "同一句话再问一次可能得到不同答案。数据是否陈旧由用户判断，不由你代劳刷新。\n"
    "- 只有当用户**明确要求执行动作**时（「重算一下」「刷新推移表」「把这份表导进去」「重新决策」）"
    "才调上面这些服务；**拿不准是不是要执行，就先问一句**，不要自行开工。\n"
)


def _esc_braces(text: str) -> str:
    """把花括号转义成 format 字面量。

    `system_prompt_template` 是 **Python format 字符串**——AgentScope 用
    `.format(team_name=…, member_name=…)` 渲染它。README 里满是 `{"window": 6}`、
    `{material_no, customer_no, …}` 这类 JSON/占位片段，不转义会在建队那一刻
    直接 KeyError 把 AgentCreate 打挂（而且是运行期才炸，静态看不出来）。
    """
    return text.replace("{", "{{").replace("}", "}}")


def _build_app_template(role: str) -> SubAgentTemplate:
    """业务角色：绑定应用集合 + 注入各应用的《使用要点》（HOWTOUSE.md）。

    历史上（e7f04f1，2026-09-03）这条注入曾随应用级 Agent 一起被删掉，worker 只剩
    一串应用名，业务规则与工具调用顺序全丢——是「以前用 README 效果挺好」对应的那次回退。
    现以 HOWTOUSE 恢复：只带「标准工作流 + 前置条件与禁忌」，完整 README 留给按需查阅。
    """
    apps = ROLE_APPS[role]
    label = _ROLE_LABEL[role]
    app_list = "、".join(_app_short(a) for a in apps)
    docs = _read_app_howtos(apps)
    doc_block = (
        "\n\n下面是这几个应用的《使用要点》。**优先按其中的「标准工作流」推进**"
        "（那是经过验证的工具调用顺序），并遵守「前置条件与禁忌」；"
        "要点没覆盖的细节，用 platform_read_app_doc 读该应用的完整 README 再动手。\n"
        + _esc_braces(docs)
    ) if docs else ""

    # 普通字符串（非 f-string）：{member_name} 等占位符留给 AgentScope 的 AgentCreate 填充。
    # 首行埋机器标记 <!--FDE_ROLE:<role>-->，供工具过滤 middleware 可靠识别角色（不靠 LLM 起名）。
    prompt = (
        f"<!--FDE_ROLE:{role}-->\n"
        f"你是{{member_name}}，{label}，隶属团队'{{team_name}}'（由{{leader_name}}领导）。\n\n"
        f"团队目标：{{team_description}}\n"
        f"你的分工：{{member_description}}\n\n"
        f"你只负责以下应用的服务，不要越界调用其他角色的应用：\n{app_list}"
        + doc_block
        + _esc_braces(AGENT_DISCIPLINE)
        + "\n\n完成分配给你的任务后，用 TeamSay 向 {leader_name} 回报结果。"
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


def leader_role_choices(group: str | None = None) -> str:
    """leader system prompt 用：可选 subagent_type 清单（从角色注册表动态生成，单一数据源）。

    group 非空时只列该组业务角色 + 平台角色；None 列全部业务角色 + 平台角色。
    """
    parts = []
    for role, apps in ROLE_APPS.items():
        if group and role_group(role) != group:
            continue
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
