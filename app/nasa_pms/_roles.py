"""nasa_pms 组角色声明（九步法第⑩步 · 可选增强；规格见 `design-plus/智能体角色声明.md`）。

平台扫描本文件装配业务角色，**零平台代码改动**。角色有两个用处：
  ① 智能体建队时按角色派活（`subagent_type`）；
  ② `_flow_*.yaml` 的节点按 `role` **收窄工具面**（该角色只能调 `apps` 里那些应用的服务）。

分法照 NASA SE Handbook 的**技术管理职能**（§6 Crosscutting Technical Management 的几条主线）：
需求与验证 · 风险与度量 · 配置与变更 · 技术与评审。11 个聚合根一个不落（允许跨角色复用）。
⚠ `type` 是**全局**键（跨组撞名时按目录序后者覆盖），故都带 `nasa_` 前缀。
⚠ 角色绑定的应用必须有 `HOWTOUSE.md`（`scripts/verify_agent_tools.py` 会查）——
   漏写不会报错，只是**静默地不注入**，所以本组 11 个应用都补齐了。
"""

ROLES = [
    {
        "type": "nasa_requirements",
        "label": "需求与验证工程师",
        "apps": ["nasa_pms/requirement", "nasa_pms/verification", "nasa_pms/stakeholder"],
    },
    {
        "type": "nasa_risk_tpm",
        "label": "风险与度量分析师",
        "apps": ["nasa_pms/risk", "nasa_pms/technical_measure", "nasa_pms/decision"],
    },
    {
        "type": "nasa_cm",
        "label": "配置与变更管理员",
        "apps": ["nasa_pms/configuration_item", "nasa_pms/change_request", "nasa_pms/interface"],
    },
    {
        "type": "nasa_planner",
        "label": "技术计划与评审主管",
        # ⚠ WBS 归这一域：材料里它是"技术规划过程的产物"（SE 手册 6.1 与 SEMP、进度表并列），
        #   2026-09-26 并入。角色绑定的应用**必须有 HOWTOUSE.md**，否则 verify_agent_tools 查不到
        #   （漏写不报错，只是静默地不注入 —— 所以 wbs 也补了那份文件）。
        "apps": ["nasa_pms/tech_plan", "nasa_pms/wbs", "nasa_pms/review"],
    },
]
