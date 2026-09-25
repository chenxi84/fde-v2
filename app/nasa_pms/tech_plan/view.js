/* app/nasa_pms/tech_plan/view.js —— 技术计划台账（与后端 tech_plan.py 同文件夹）
 *
 * 数据来源类型：**独立创建** —— 保留「新建计划」入口（对应 create）。
 * 交互要点：
 *   · 版本台账是**聚合内子表**（无独立标识），随详情模态一起取（`get` 带 `versions`）；
 *   · **⚠ 本页最关键的语义差：本页没有硬终态**。状态机是**环** ——
 *     草稿 → 审批中 → 已批准 → 已修订 → （提交）审批中 → 已批准 → …
 *     与同组 technical_measure / review / configuration_item 的"终态一律拒"**不同**：
 *     内容锁定只有两个状态，且**各有自己的解锁入口** ——
 *       「审批中」锁的是"审的这一版" → 解锁入口 **撤回**（withdraw，退回提交前状态）；
 *       「已批准」锁的是"已生效的那一版" → 解锁入口 **修订**（revise，**版本递增**，不是原地改）。
 *     照抄别的页的 `locked()`（`status==='closed'`）会同时错两处：已批准改不了（该走修订）、
 *     以及"永远锁死"（其实可以修订出下一版）。
 *   · 「批准」是 BR-03（I-1 的「生效唯一」面）的落点：同一阶段同一类型只允许一份已批准 ——
 *     被拒时前端把后端的原因原样弹出（判定权威在后端）。
 *   · 「阶段覆盖」卡片是**查询视图**（`coverage`），不是第二个聚合 ——
 *     它是卡片 I-1 里「每个阶段至少有一份已批准的该类计划」的可见面（材料附录 K TABLE K-1 那张矩阵）。
 */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "tech_plan", name: "技术计划", ic: "▤",
  title: "技术计划台账", crumb: "草稿 · 审批中 · 已批准 · 已修订",
  order: 700,
  // 列表渲染**全字段列**（CONVENTION §7：list 返回全字段）；这两列非关键，默认隐藏，
  // 经平台「列设置」按需开启。
  // ⚠ 「版本」「已批准版本」「成熟度」与「覆盖阶段」**不**藏：
  //    版本号是 I-2「随阶段推进更新版本」的可见证据，成熟度是附录 K TABLE K-1 的那一格，
  //    覆盖阶段是 I-1「计划与阶段绑定」的可见证据 —— 藏了它们，这张台账就只剩一列名字。
  col_default_hidden: "修订说明,所属项目",
};

/* 字典：业务名逐字取自《术语表.md》（系统工程管理计划（SEMP）/ 验证与确认计划（V&V Plan）/
   集成计划（Integration Plan）/ 技术开发计划 / 人因集成计划（HSI Plan））；
   风险管理 / 评审 / 配置管理三种计划取自材料附录 K TABLE K-1 的「Key Technical Plans」
   清单（见 新增术语.md）。 */
const PLAN_TYPES = [
  ["semp", "系统工程管理计划（SEMP）"],
  ["verification", "验证与确认计划（V&V Plan）"],
  ["integration", "集成计划（Integration Plan）"],
  ["technology_dev", "技术开发计划"],
  ["hsi", "人因集成计划（HSI Plan）"],
  ["risk_mgmt", "风险管理计划（Risk Management Plan）"],
  ["review", "评审计划（Review Plan）"],
  ["cm", "配置管理计划（Configuration Management Plan）"],
];
/* 阶段字典：与同组 review 同口径（术语表的 Pre-Phase A / Phase A..E） */
const PHASES = [
  ["pre_a", "预 A 阶段（Pre-Phase A）"], ["a", "A 阶段（Phase A）"],
  ["b", "B 阶段（Phase B）"], ["c", "C 阶段（Phase C）"],
  ["d", "D 阶段（Phase D）"], ["e", "E 阶段（Phase E）"],
];
/* 成熟度字典：材料附录 K TABLE K-1 的图例 "A = Approach / B = Baseline /
   P = Preliminary / U = Update" —— 业务名就地中文并列（见 新增术语.md） */
const MATURITIES = [
  ["approach", "方法（Approach）"], ["preliminary", "初步（Preliminary）"],
  ["baseline", "基线（Baseline）"], ["update", "更新（Update）"],
];
/* 状态徽标用平台设计系统的 `.st` + `.st-<色>`（slate=初始 / blue=流程中 / green=已批准 /
   amber=已修订待提交）。
   ⚠ 不要写 `var(--ok)` / `var(--red)` 之类的内联色 —— 设计令牌里**没有**这两个变量，
   浏览器会静默回落成继承色，页面不报错但颜色全错（同组 requirement 样板即踩此坑）。 */
const STATUS = {
  draft: ["草稿", "st-slate"],
  in_review: ["审批中", "st-blue"],
  approved: ["已批准", "st-green"],
  revised: ["已修订", "st-amber"],
};
/* 覆盖矩阵的来源标记（`coverage` 视图的 covered_by） */
const COVERED_BY = {
  current: ["此刻生效", "st-green"],
  history: ["历史版本", "st-teal"],
};

export default function pageTechPlan() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    // 筛选（与后端 list 的可过滤参数一一对应）
    f_type: "", f_phase: "", f_status: "", f_owner: "",
    // 详情 / 编辑（同一模态，mode 切换）
    modal: { open: false, loading: false, mode: "view", d: null, saving: false },
    // 新建计划
    form: { open: false, d: null, saving: false },
    // 「责任人」候选 —— 跨应用 stakeholder.list（**值仍是文本**，不落 sh_no）
    owners: [],
    // 批准（BR-08：批准要记名）
    am: { open: false, plan_no: "", name: "", version: 1, saving: false, approver: "", note: "" },
    // 修订（卡片 I-2：版本递增 + 阶段推进）
    rm: { open: false, plan_no: "", name: "", version: 1, saving: false,
          summary: "", phase: "", maturity: "" },
    // 阶段覆盖矩阵（查询视图 coverage —— 卡片 I-1 的「至少一份」面）
    cov: { phase: "", items: [], total: 0, loading: false },

    planTypes: PLAN_TYPES, phases: PHASES, maturities: MATURITIES,

    typeName(v) { const t = PLAN_TYPES.find((x) => x[0] === v); return t ? t[1] : (v || "—"); },
    phaseName(v) { const p = PHASES.find((x) => x[0] === v); return p ? p[1] : (v || "—"); },
    maturityName(v) { const m = MATURITIES.find((x) => x[0] === v); return m ? m[1] : (v || "—"); },
    /** 阶段在台账里用短名（`A 阶段`），全名只在选择器与覆盖矩阵里给（一行放得下才是台账） */
    phaseShort(v) { const p = PHASES.find((x) => x[0] === v); return p ? p[1].split("（")[0] : (v || "—"); },
    statusName(v) { return (STATUS[v] || [v, ""])[0]; },
    statusCls(v) { return (STATUS[v] || ["", "st-slate"])[1]; },
    coveredName(v) { return (COVERED_BY[v] || ["", ""])[0]; },
    coveredCls(v) { return (COVERED_BY[v] || ["", "st-slate"])[1]; },
    dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; },
    /** 版本号一律带 V 前缀显示（`—` 表示"还没有获批过的版本"） */
    verText(v) { return (v === null || v === undefined || v === "") ? "—" : "V" + v; },

    /* ── 本页与同组其它页的**语义差**：没有硬终态，锁定的是两个"过程态" ──
       · editable：草稿 / 已修订 —— 内容还没定下来，随便改；
       · frozen：审批中（审的就是这一版）/ 已批准（生效的那一版）—— 各有解锁入口。
       别的页只有一个 locked()（终态一律锁死、无解锁入口）；本页若照抄，
       "已批准不能改"会变成"已批准永远不能改"、且"审批中能改"（其实不能）。 */
    editable(d) { return !!d && (d.status === "draft" || d.status === "revised"); },
    isStatus(d, s) { return !!d && d.status === s; },
    inStatus(d, list) { return !!d && list.indexOf(d.status) >= 0; },
    canSubmit(d) { return self.inStatus(d, ["draft", "revised"]); },
    canApprove(d) { return self.isStatus(d, "in_review"); },
    canWithdraw(d) { return self.isStatus(d, "in_review"); },
    canRevise(d) { return self.isStatus(d, "approved"); },
    /* ⚠ 模态里读 `modal.d` 一律走下面这层**空安全**helper，模板里不写裸 `modal.d.status`：
       `x-if="modal.d"` 的子绑定**可能**在 openDetail 把 `modal.d` 置 null 的那一拍被再求值一次
       （Alpine 的销毁与子效果执行顺序不保证）—— 同组 review 页实测抛 4 条
       "Cannot read properties of null (reading 'status')"。 */
    stName(d) { return self.statusName(d && d.status); },
    stCls(d) { return self.statusCls(d && d.status); },
    versionsOf(d) { return (d && d.versions) || []; },
    headText(d) {
      if (!d) return "";
      return "已批准 " + (d.version_total || 0) + " 版"
        + (d.latest_approved_ver ? "（最近 V" + d.latest_approved_ver + " by "
          + (d.latest_approver || "—") + "）" : "");
    },
    frozenText(d) {
      if (!d) return "";
      if (d.status === "in_review") {
        return "审批中：内容已锁定 —— 审的就是这一版；要改请先「撤回」再改（BR-05）";
      }
      return "已批准（第 " + d.version + " 版）：内容不可直接修改 —— 要改请「修订」出下一版"
        + "（版本递增，BR-04 / BR-05）";
    },
    /** 修订模态里的提示：不传阶段 / 成熟度即沿用当前（BR-06） */
    reviseHint(d) {
      if (!d) return "";
      return "当前 V" + d.version + "（" + self.phaseShort(d.phase) + " · "
        + self.maturityName(d.maturity) + "）→ 修订后成为 V" + (Number(d.version) + 1)
        + "；不选阶段 / 成熟度则沿用当前";
    },

    async init() {
      // ⚠ 先把会被模板引用的响应式状态建好，再挂模板（模板一旦注入就立刻求值 `list.items`，
      //   此刻 list 还是 null 会喷 "reading 'items' of null"；见 pitfalls #37）
      const tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("tech_plan", "list", {
        plan_type: self.f_type || undefined,
        phase: self.f_phase || undefined,
        status: self.f_status || undefined,
        owner: self.f_owner.trim() || undefined,
        ...q,
      }));
      self.tpl = tpl;
      await self.loadOwners();
      await self.list.load();
      await self.loadCoverage();
    },


    /** 责任人候选（`stakeholder` 主数据）：**只做候选、值仍是文本姓名**（不落 sh_no ——
     * 全组 `owner` 都是文本口径）；失败静默兜底为空列表。 */
    async loadOwners() {
      try {
        const r = await svc("stakeholder", "list", {}, { quiet: true });
        self.owners = (r && r.items) || [];
      } catch { self.owners = []; }
    },

    search() { self.list.load(1); },
    /** 主列表 + 覆盖矩阵一起刷新（任一动作都会影响两处：批准 / 修订都会改覆盖） */
    async reload() {
      await self.list.load(self.list.page);
      await self.loadCoverage();
    },

    /* ── 详情 / 编辑（同一模态）───────────────────────── */
    /** 取一份计划的详情并**规整选填字段**（统一成空串，编辑表单才不会显示 "null"）—— 唯一取数入口 */
    async fetchDetail(plan_no) {
      const d = await svc("tech_plan", "get", { plan_no: plan_no });
      if (d) {
        d.scope = d.scope || "";
        d.owner = d.owner || "";
        d.revise_note = d.revise_note || "";
      }
      return d;
    },
    async openDetail(row, mode) {
      const m = mode || "view";
      self.modal = { open: true, loading: true, mode: m, d: null, saving: false };
      try {
        self.modal.d = await self.fetchDetail(row.plan_no);
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },
    /** 详情模态若正开着这份计划，重取一次 —— 版本台账变了而详情不刷新会前后不一致 */
    async refreshDetail(plan_no) {
      if (!self.modal.open || !self.modal.d || self.modal.d.plan_no !== plan_no) return;
      try {
        self.modal.d = await self.fetchDetail(plan_no);
      } catch { /* api.js 已 toast */ }
    },

    async saveEdit() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        // 载荷里**没有** version / status / revise_note：它们是流转产物，
        // 只能经 submit / approve / revise 写入（在 update 的字段白名单之外）
        await svc("tech_plan", "update", {
          plan_no: d.plan_no, name: d.name, plan_type: d.plan_type, phase: d.phase,
          maturity: d.maturity, scope: d.scope || "", owner: d.owner || "",
        });
        toast("已保存");
        self.modal.open = false;
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /* ── 状态机动作（按状态显隐，两条解锁路径各归其位）── */

    /** 提交审批：草稿 / 已修订 → 审批中（提交后内容锁定） */
    async submitPlan(row) {
      if (!confirm(`确定提交 ${row.plan_no}（V${row.version}）审批？\n\n`
        + `提交后内容即锁定 —— 审批对着的必须是定下来的那一版。`)) return;
      try {
        await svc("tech_plan", "submit", { plan_no: row.plan_no });
        toast("已提交审批");
        await self.refreshDetail(row.plan_no);
        await self.reload();
      } catch { /* api.js 已 toast */ }
    },

    /** 撤回审批：审批中 → 回到提交前的状态（V1 回草稿、V2 及以后回已修订） */
    async withdrawPlan(row) {
      if (!confirm(`确定撤回 ${row.plan_no}（V${row.version}）的审批？\n\n`
        + `撤回后回到提交前的状态，可继续修改内容再提交。`)) return;
      try {
        await svc("tech_plan", "withdraw", { plan_no: row.plan_no });
        toast("已撤回，可继续修改");
        await self.refreshDetail(row.plan_no);
        await self.reload();
      } catch { /* api.js 已 toast */ }
    },

    /* ── 批准（BR-08 记名；BR-03 同阶段同类型唯一由后端拦）── */
    openApprove(row) {
      self.am = { open: true, plan_no: row.plan_no, name: row.name || "",
                  version: row.version, saving: false, approver: "", note: "" };
    },
    closeApprove() { self.am.open = false; },
    canApproveSubmit() { return !!self.am.approver.trim(); },
    async saveApprove() {
      const a = self.am;
      a.saving = true;
      try {
        await svc("tech_plan", "approve", {
          plan_no: a.plan_no, approver: a.approver.trim(), note: a.note || undefined,
        });
        toast("已批准，版本台账落一行");
        a.open = false;
        await self.refreshDetail(a.plan_no);
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { a.saving = false; }
    },

    /* ── 修订（卡片 I-2：版本递增 + 可选阶段推进）────── */
    openRevise(row) {
      self.rm = { open: true, plan_no: row.plan_no, name: row.name || "",
                  version: row.version, saving: false, summary: "",
                  phase: row.phase || "", maturity: row.maturity || "" };
    },
    closeRevise() { self.rm.open = false; },
    canReviseSubmit() { return !!self.rm.summary.trim(); },
    async saveRevise() {
      const r = self.rm;
      r.saving = true;
      try {
        await svc("tech_plan", "revise", {
          plan_no: r.plan_no, summary: r.summary.trim(),
          phase: r.phase || undefined, maturity: r.maturity || undefined,
        });
        toast("已修订出新版本（待提交审批）");
        r.open = false;
        await self.refreshDetail(r.plan_no);
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { r.saving = false; }
    },

    /* ── 阶段覆盖矩阵（查询视图 coverage —— I-1 的「至少一份」面）── */
    async loadCoverage() {
      self.cov.loading = true;
      try {
        const r = await svc("tech_plan", "coverage", {
          phase: self.cov.phase || undefined, page: 1, size: 100,
        });
        self.cov.items = (r && r.items) || [];
        self.cov.total = (r && r.total) || 0;
      } catch { self.cov.items = []; self.cov.total = 0; } finally { self.cov.loading = false; }
    },
    setCovPhase(p) { self.cov.phase = p; return self.loadCoverage(); },
    coveredCount() { return self.cov.items.filter((r) => r.covered).length; },
    covCellText(r) {
      if (!r || !r.covered) return "—";
      return r.approved_no + " " + self.verText(r.approved_ver);
    },

    /* ── 新建计划 ──────────────────────────────────── */
    openForm() {
      self.form = { open: true, saving: false, d: {
        name: "", plan_type: "", phase: "", maturity: "approach", scope: "", owner: "" } };
    },
    closeForm() { self.form.open = false; },
    /** F-1：名称 / 计划类型 / 覆盖阶段三项齐备才可提交（类型与阶段不给默认值 ——
        它们是 I-1「计划与阶段绑定」的那两个键，不该被默认值悄悄替人做主） */
    canSubmitForm() {
      const d = self.form.d;
      return !!(d && d.name.trim() && d.plan_type && d.phase);
    },
    async saveForm() {
      const d = self.form.d;
      self.form.saving = true;
      try {
        await svc("tech_plan", "create", {
          name: d.name.trim(), plan_type: d.plan_type, phase: d.phase,
          maturity: d.maturity || undefined, scope: d.scope || undefined,
          owner: d.owner || undefined,
        });
        toast("已新建计划（草稿态 V1）");
        self.form.open = false;
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.form.saving = false; }
    },
  });
  return self;
}
