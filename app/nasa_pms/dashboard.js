/* app/nasa_pms/dashboard.js —— nasa_pms 组级看板（无后端应用的聚合页 · 默认落地页 key=dashboard）
 *
 * ⚠ **每个模块必备**（VIEW_CONVENTION.md §2 / view-convention/pitfalls.md #36）：平台壳默认路由写死
 * `route: "dashboard"`（`view/lib/shell.js`），缺本页会首帧把空 `{}` 挂上默认路由、
 * `x-html="tpl"` 对 undefined 求值 → 整片 console error。**不是可选聚合页。**
 *
 * 与 PSC 的看板**同构**（对齐反馈"风格要和 PSC 一致、要能点、状态要中文"）：
 *   KPI 指标带（**数字本身是链接**）→ 主链管道（本组是**四个职能域**，每域最近 3 行、行内编号可点）
 *   → 待办队列 3 列（各带 total 与最近条目）。
 * 全部 `svc(...)` 字面量 + `{quiet:true}` 探测（失败零值兜底，不喷 toast）；跳转目标字面量 key。
 * **不做裸数组兜底** —— `list` 契约是 `{items,total}`，形状不对就该红（见《测试用例.md》TC-28）。
 *
 * ⚠ 状态**一律中文 + 语义色**：每个应用的状态字典**取自它自己的 `view.js` 的 `STATUS`**（一字不差，
 *   与本组各台账页同口径）。**颜色在本页本地映射** —— 平台基座 `view/lib/api.js` 的 `hue()` 只认
 *   PSC 的状态名（草稿/审批中/已提交…），本组绝大多数状态会**回落 slate 并显示英文原文**；
 *   基座"只 import 不修改"，故不扩基座、在本页建表。
 */
import { svc, fmt, dash } from "/view/lib/api.js";

export const PAGE_META = {
  key: "dashboard", name: "系统工程看板", ic: "📊",
  title: "系统工程看板", crumb: "KPI · 四个职能域 · 待办队列",
  order: 1,          // 最小 order，居侧栏首位（VIEW_CONVENTION §4）
};

/* 各应用的状态字典（逐字取自 `app/nasa_pms/<应用>/view.js` 的 `STATUS`；
   stakeholder 是主数据、无状态机，故不在表内） */
const STATUS = {
  requirement: { draft: "草稿", pending_review: "待评审", baselined: "已基线", obsolete: "已废弃" },
  risk: { identified: "识别", analyzing: "分析中", mitigating: "缓解中", closed: "已关闭", accepted: "已接受" },
  configuration_item: { draft: "草稿", controlled: "受控", released: "已发布", archived: "已归档" },
  change_request: { submitted: "已提交", analyzing: "影响分析", reviewing: "审批中",
                    approved: "已批准", rejected: "已拒绝", implemented: "已实施" },
  review: { planned: "计划", in_progress: "进行中", concluded: "已结论", tracking: "行动项跟踪中", closed: "已关闭" },
  verification: { planned: "规划", executing: "执行中", passed: "通过", failed: "不通过", closed: "关闭" },
  technical_measure: { defined: "定义", measuring: "度量中", exceeded: "超阈值", corrected: "已纠正", closed: "已关闭" },
  decision: { proposed: "提出", weighing: "权衡中", decided: "已决策", implemented: "已实施" },
  interface: { defined: "定义中", released: "已发布", changing: "变更中", frozen: "已冻结" },
  tech_plan: { draft: "草稿", in_review: "审批中", approved: "已批准", revised: "已修订" },
};

/* 状态 → 徽标色（**语义**映射，本页本地维护）：起始/中性 slate · 进行中 amber · 终态-好 green · 终态-坏 red */
const HUE_BY_NAME = {
  草稿: "slate", 识别: "slate", 定义: "slate", 计划: "slate", 提出: "slate", 规划: "slate",
  受控: "slate", 定义中: "slate", 已提交: "blue",
  待评审: "amber", 分析中: "amber", 影响分析: "amber", 缓解中: "amber", 审批中: "amber",
  进行中: "amber", 度量中: "amber", 变更中: "amber", 权衡中: "amber", 行动项跟踪中: "amber",
  已修订: "amber", 执行中: "amber",
  已基线: "green", 已关闭: "green", 已接受: "green", 已决策: "green", 已实施: "green",
  已批准: "green", 已发布: "green", 已冻结: "green", 已归档: "green", 通过: "green",
  已结论: "green", 已纠正: "green",
  超阈值: "red", 已废弃: "red", 已拒绝: "red", 不通过: "red",
};

export default function pageDashboard() {
  const self = Alpine.reactive({
    tpl: "",
    fmt, dash,
    loading: true,

    /* KPI（数量型，零值兜底 0）—— 每张的 `.v` 是**可点按钮**（与 PSC 一致） */
    kpi: { req: 0, baselined: 0, pending: 0, alerts: 0, reviewing: 0, mitigating: 0 },

    /* 四个职能域的管道（各域最近 3 行） */
    pipe: {
      req: { items: [] },          // ① 需求与验证域
      risk: { items: [] },         // ② 风险与度量域
      cm: { items: [] },           // ③ 配置与变更域
      plan: { items: [] },         // ④ 计划与评审域
    },

    /* 待办队列（total + 最近条目） */
    todo: {
      draftReq: { total: 0, items: [] },      // 待提交评审的需求（草稿）
      alerts: { total: 0, items: [] },        // 未了结的技术度量告警
      tracking: { total: 0, items: [] },      // 行动项跟踪中的评审
    },

    statusCn(app, v) { return (STATUS[app] || {})[v] || v || "—"; },
    statusCls(app, v) { return "st-" + (HUE_BY_NAME[self.statusCn(app, v)] || "slate"); },
    /** 风险等级中文（列表里 `risk_level` 是英文码） */
    levelCn(v) { return ({ low: "低", medium: "中", high: "高", critical: "严重" })[v] || "—"; },
    levelCls(v) { return "st-" + ({ low: "slate", medium: "blue", high: "amber", critical: "red" }[v] || "slate"); },

    async init() {
      self.tpl = await fetch(new URL("dashboard.html", import.meta.url)).then((r) => r.text());
      await self.loadAll();
    },

    gotoPage(key) { window.location.hash = "#/" + key; },

    async loadAll() {
      self.loading = true;
      const q = (app, s, kw) => svc(app, s, kw || {}, { quiet: true }).catch(() => null);
      const [req, base, pend, alerts, reviewing, mitigating,
             reqRows, riskRows, crRows, rvRows, draftRows, alertRows, trackRows] = await Promise.all([
        q("requirement", "list", { page: 1, size: 1 }),
        q("requirement", "list", { status: "baselined", page: 1, size: 1 }),
        q("requirement", "list", { status: "pending_review", page: 1, size: 1 }),
        q("technical_measure", "list_alerts", { status: "open", page: 1, size: 1 }),
        q("change_request", "list", { status: "reviewing", page: 1, size: 1 }),
        q("risk", "list", { status: "mitigating", page: 1, size: 1 }),
        q("requirement", "list", { page: 1, size: 3 }),
        q("risk", "list", { page: 1, size: 3 }),
        q("change_request", "list", { page: 1, size: 3 }),
        q("review", "list", { page: 1, size: 3 }),
        q("requirement", "list", { status: "draft", page: 1, size: 3 }),
        q("technical_measure", "list_alerts", { status: "open", page: 1, size: 3 }),
        q("review", "list", { status: "tracking", page: 1, size: 3 }),
      ]);
      const n = (r) => (r && r.total) ?? 0;

      self.kpi = { req: n(req), baselined: n(base), pending: n(pend),
                   alerts: n(alerts), reviewing: n(reviewing), mitigating: n(mitigating) };
      self.pipe = {
        req: { items: (reqRows && reqRows.items) || [] },
        risk: { items: (riskRows && riskRows.items) || [] },
        cm: { items: (crRows && crRows.items) || [] },
        plan: { items: (rvRows && rvRows.items) || [] },
      };
      self.todo = {
        draftReq: { total: n(draftRows), items: (draftRows && draftRows.items) || [] },
        alerts: { total: n(alertRows), items: (alertRows && alertRows.items) || [] },
        tracking: { total: n(trackRows), items: (trackRows && trackRows.items) || [] },
      };
      self.loading = false;
    },
  });
  return self;
}
