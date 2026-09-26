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
from fde_platform import agent_surface
from fde_platform import agent_tool_filter
from fde_platform import builtin_tools
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
# 走 HITL（人工确认）的业务服务 —— **显式清单，不按名字猜**。
#
# 为什么不再用名字子串匹配：原来那套（delete/publish/cancel/approve/close…）既漏又误伤——
#   · 漏：`calc_net` 名字里没有关键词，但它会**联动冻结月度版本**（全链转只读）；
#         `freeze` / `disable` / `rollback` 同样漏网。
#   · 误伤：`close_expired` 只是「到期自动关闭」的惰性结算（读列表时顺带触发），
#         拦它等于每次查询都要点确认。
#
# 判据两条，任一成立即拦：
#   ① **需要人拍板**（即使技术上可逆）—— 它是「对全公司的宣布」或「要人担责的复核」
#   ② **不可逆**（现有服务里没有能回到原状的操作）
#
# ⚠️ 只作用于「智能体对话里调工具」这条路径。API 定时任务与 flow 节点走的是
#    `_platform.call` / `bridge.execute`，**不经过这里**——所以无人值守不会因此卡住。
_HITL_SERVICES = {
    # ① 需要人拍板
    "publish",     # 版本锁定：等于宣布「本月定了」，下游全线转只读
    "approve",     # 拟合复核通过：回填物料主数据，影响全链预测参数
    "reject",      # 拟合否决：同样改变全链参数状态
    # ② 不可逆
    "delete",      # 真删除（出库计划）
    "disable",     # 软失效（断点/替换关系）：没有对应的 enable，做完回不去
    "rollback",    # 作废已生效的拟合版本
    "cancel",      # 补库单作废（终态）
    # ③ 名字看不出、但副作用不可逆
    "calc_net",    # 净需求运算会**联动冻结月度版本** —— 名字里的 calc 掩盖了这一点
    "freeze",      # 版本冻结
}


def _is_dangerous(tool: dict) -> bool:
    """该工具是否走 HITL。

    平台工具用它们**自己声明的** `_meta.dangerous`（定义处就标好了，18/31 为 True）；
    业务工具没有这个字段，回落 `_HITL_SERVICES`。
    """
    meta = tool.get("_meta") or {}
    if "dangerous" in meta:                     # 平台工具：以显式声明为准
        return bool(meta["dangerous"])
    return (meta.get("service") or "").lower() in _HITL_SERVICES


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


# 分组与「按授权收窄」的口径已抽到 agent_surface：权限视图页（跑在 Flask 进程）
# 也要用同一份，而它不该为此把 AgentScope 拉进主进程。这里保留同名别名，
# 装配侧与回归测试仍按这个名字调它。
_split_by_app = agent_surface.split_by_app


# 懒加载下模型可能同时开多个组，工具面就叠加回去了。
# 外部证据（arXiv:2605.24660）：多余候选会**主动伤害**选择准确率，
# 所以「用完就关」不是洁癖，是准确率问题。这条随组激活一起下发。
_GROUP_INSTRUCTIONS = (
    "完成本域任务后，若接下来要处理其他应用，请先停用本组再激活目标组，"
    "避免同时挂着多组工具——同时激活的工具越多，选错工具的概率越高。"
)

# ── 权限前置：按调用者授权给「组」打标 ──────────────────────────
#
# 为什么打在组上、而不是把工具面收窄掉：
#   ResetTools 的动态 schema 把**每个组的名字+描述**常驻呈现给模型，这是它判断
#   「系统有什么能力」的唯一依据（= 全貌）；组内工具 schema 只在激活后才进上下文
#   （= 动作空间）。所以「全貌」与「动作空间」本来就在两层上——组描述正是声明
#   边界的地方：全貌照给，无授权的组把工具清空，模型既看得到、又不会去撞墙。
#
# 为什么清空工具而不是只在描述里提醒：放了也调不动（bridge.execute 会拒），
#   只会让模型白烧 ReAct 轮次，还可能把「无权调用」当成业务结论写进回答。
_NO_GRANT_NOTE = "｜**你没有权限调用本组工具**，仅供了解系统能力"
_NO_GRANT_INSTRUCTIONS = (
    "本组工具对当前用户不可用：你没有调用本组任何工具的授权。"
    "不要尝试调用本组工具，直接说明缺少哪一项权限即可。"
)
_PARTIAL_NOTE = "｜本组你只能调用："


def _group_plan(keep, user, page_derived=None) -> list[dict]:
    """按应用算出「每组留哪些服务」——分组与打标口径的**唯一实现**。

    两个消费方：`_make_tool_groups`（装配真实工具面）与权限视图页（`/agent-admin/permission`
    展示"这个人的数字员工实际能调什么"）。两边各写一份的后果见 `_split_by_app` 的说明——
    这次要修的 bug 本身就是"两处口径对不上"。

    每项：`{app, all, usable, fts, desc, instructions}`
    """
    plan: list[dict] = []
    for row in agent_surface.app_surface(keep, user, page_derived):
        app, all_svcs, usable = row["app"], row["all"], row["usable"]
        desc = _app_group_desc(app)
        instructions = _GROUP_INSTRUCTIONS
        if not usable:
            desc += _NO_GRANT_NOTE
            instructions = _NO_GRANT_INSTRUCTIONS
        elif len(usable) < len(all_svcs):
            desc += _PARTIAL_NOTE + "、".join(sorted(usable))
        plan.append({"app": app, "all": all_svcs, "usable": usable,
                     "fts": row["fts"], "desc": desc, "instructions": instructions})
    return plan


def _make_tool_groups(keep, user, mk_ft):
    """业务工具 → 按应用分组的 ToolGroup，并按调用者**有效授权**打标。

      · 全可用   → 原描述、工具全留
      · 部分可用 → 描述追加「本组你只能调用：a、b、c」，**组内只留可用的那些**
      · 全不可用 → 描述追加「你没有权限调用本组工具」，组内清空

    **组内工具一律 = 该用户真能调的**。不保留调不动的工具：留着只会让模型去试、
    撞 execute 的拒绝、白烧 ReAct 轮次；而"这个应用还有哪些能力"由组名+描述承载，
    全貌不受影响。

    admin / `user is None` 时 `effective_service_names` 直接返回全部 → 不打标，
    与改动前逐字一致（这是最容易写错的地方：admin 本身 `service_grants` 是空的，
    实测 `has_app_access` 对任何应用都为 False，一旦按它判就会把 admin 权限清空）。

    返回 `(groups, marked)`，marked = 被打成"不可用"的组数，供日志可见性。
    """
    plan = _group_plan(keep, user)
    groups = [ToolGroup(
        name=p["app"].split("/")[-1], description=p["desc"],
        instructions=p["instructions"],
        tools=[mk_ft(t) for t in p["fts"] if t["_meta"].get("service", "") in set(p["usable"])])
        for p in plan]
    return groups, sum(1 for p in plan if not p["usable"])


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

    # 该 agent 的**应用组**：闭包捕获一个可变格子，下面定完 leader/worker 再回填。
    # 工具是**之后**才被调用的，所以回填来得及；但值必须等 `_toolkit` 里算完组才知道
    # （leader 从 system_prompt 的 FDE_GROUP 标记取，worker 从角色反推）。
    # 用途：平台级工具（skill 沉淀 / 告警上报）按它落归属 —— AI管家的 SKILL / 告警要组隔离。
    _grp = {"m": ""}

    def _make_call(tool_name: str):
        # 闭包捕获工具名 + user，避免与工具自身参数（如 propose_skill 的 name）冲突
        def _call(**kwargs):
            return _as_tool_result(bridge.execute(_platform, user, tool_name, kwargs,
                                                  module=_grp["m"]))
        return _call

    def _mk_ft(t):
        name = t["function"]["name"]
        ft = FunctionTool(_make_call(name), name=name, description=t["function"]["description"])
        ft.input_schema = _slim_schema(t["function"]["parameters"])
        # 权限：普通工具 ALLOW（授权已由 execute 层 fail-closed）；危险工具 ASK（HITL）。
        ft.check_permissions = _mk_ask() if _is_dangerous(t) else _mk_allow()
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
        _grp["m"] = agent_roles.role_group(role) or ""
        allowed = agent_roles.allowed_tools_for_role(role, defs)
        basic, keep = [], []
        for t in defs:
            if t["_meta"]["app"] == "__platform__":
                if t["_meta"].get("service") in _WORKER_PLATFORM_TOOLS:
                    basic.append(_mk_ft(t))
                continue
            if t["function"]["name"] in allowed:
                keep.append(t)
        tool_groups, marked = _make_tool_groups(keep, user, _mk_ft)
        _log_surface(f"worker/{role}", basic, tool_groups, marked)
        return (basic, tool_groups)

    # ── leader：按组收窄业务工具（从 system_prompt 的 FDE_GROUP 标记提取组）──
    group = _extract_group(record.data.system_prompt) if record is not None else None
    _grp["m"] = "" if group == "__platform__" else (group or "")
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
    tool_groups, marked = _make_tool_groups(keep, user, _mk_ft)
    _log_surface(f"leader/{group or 'all'}", basic, tool_groups, marked)
    return (basic, tool_groups)


def _log_surface(who: str, basic: list, tool_groups: list, marked: int = 0) -> None:
    """记录本次装配的工具面。

    「单次呈现 schema 数」是这套收敛方案的验收指标（见 宣传/工具面收敛方案.md §七），
    没有这行日志就只能靠猜——出事那次（工具静默消失）正是因为没有可见性。

    `marked` = 被打成"你无权调用"的组数。它也必须可见：改判据时最容易出的错就是把
    有权限的人（尤其 admin）一起标了，那种错在日志里一眼能看出来，不看就得上演示才发现。
    """
    _logger.info("工具装配 [%s]：常驻 %d + 懒加载 %d 组（无权限打标 %d）%s",
                 who, len(basic), len(tool_groups), marked,
                 {g.name: len(g.tools) for g in tool_groups} or "—")


# storage 提到模块级：middleware 工厂需闭包捕获它查 AgentRecord（识别 worker 角色）。
_storage = AsyncSQLAlchemyStorage(_DB_URL, create_tables=True)


# 平台智能体**不读代码库**：封掉 AgentScope 工作区的代码/文件工具。
#
# 为什么必须封：这 6 个工具**不受应用授权约束**（它们操作的是工作区/文件系统，不走服务闸门）。
# 实测 planner01（权限被收窄的用户）的 leader 用 `Glob`+`Read` 读了 `app/psc/_contracts.md`
# 与各应用源码，把**未授权应用的完整服务清单**列了出来——「按用户收窄工具面」只覆盖
# **服务面**，文件面是漏的；理论上还能读到 `config/` 下的 `.env`、`llm_master.key`。
#
# 平台智能体不需要它们：要应用设计文档用 `platform_read_app_doc`（按授权过滤，
# 见 agent_common），要读写应用资源用平台自己的 resource 工具（限定在应用目录内）。
# worker 走的是角色**白名单**（只列平台工具），本来就不含这些；漏的是 leader（它只按名禁）。
_NO_CODE_TOOLS = ("PowerShell", "Edit", "Glob", "Grep", "Read", "Write")


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
    extra_deny = set(_NO_CODE_TOOLS)
    try:
        sess = await _storage.get_session(user_id, agent_id, session_id)
        if sess is not None and str(sess.source) == "schedule":
            extra_deny.add("ScheduleCreate")
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
