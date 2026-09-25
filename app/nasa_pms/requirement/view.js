/* app/nasa_pms/requirement/view.js —— 需求台账（与后端 requirement.py 同文件夹）
 *
 * 数据来源类型：**独立创建** —— 保留「新建需求」入口（对应 create）。
 * 交互要点：类型=派生 时上游需求变必填（BR-02）；已基线时正文/验证方法置灰，
 * 须填变更号才解锁（BR-04）；作废需二次确认且文案说明"记录保留"（下游仍可见）。
 */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "requirement", name: "需求", ic: "📋",
  title: "需求台账", crumb: "需求 · 派生 · 基线",
  order: 610,
};

/* 字典：后端约束见 CONVENTION，业务名取自《术语表.md》 */
const TYPES = [["system", "系统需求"], ["technical", "技术需求"],
               ["interface", "接口需求"], ["derived", "派生需求"]];
const METHODS = [["inspection", "检验"], ["analysis", "分析"],
                 ["demonstration", "演示"], ["test", "测试"]];
/* 状态徽标：色名取自平台设计系统（`fde.css` 的 `.st-<色>`，七种：slate/blue/green/amber/red/teal/live）。
   ⚠ **不要写内联 `var(--x)`** —— `fde.css` 里只有 `--amber/--prime/--line/--muted/--accent` 等，
   写个不存在的（如曾经的 `--ok`/`--red`）浏览器会**静默回落成继承色**：页面不报错、颜色全不对。 */
const STATUS = {
  draft: ["草稿", "slate"],
  pending_review: ["待评审", "amber"],
  baselined: ["已基线", "green"],
  obsolete: ["已废弃", "slate"],
  // ⚠ `in_change`（变更中）**已收敛**（2026-09-25）：需求侧的"变更中"由 `change_request`
  //   应用承载（已提交→影响分析→审批→已实施），在这里再维护一个状态只会造第二个真相源。
  //   需求侧保留的是 BR-04 的轻量口径：已基线须带变更号才可改写。
};

export default function pageRequirement() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    // 筛选
    f_type: "", f_status: "",
    // 详情 / 编辑
    modal: { open: false, loading: false, mode: "view", d: null, changeNo: "", saving: false },
    // 新建
    form: { open: false, d: null, saving: false },

    types: TYPES, methods: METHODS,

    /** 「上游需求」候选：本应用自身 list（**值仍是 req_no 文本**；BR-02 只校验非空） */
    reqs: [],

    /** 「责任人」候选：跨应用只读调用 `stakeholder.list`（**值仍是文本姓名**，见前端详设 §7） */
    owners: [],

    typeName(v) { const t = TYPES.find((x) => x[0] === v); return t ? t[1] : (v || "—"); },
    methodName(v) { const m = METHODS.find((x) => x[0] === v); return m ? m[1] : (v || "—"); },
    statusName(v) { return (STATUS[v] || [v, ""])[0]; },
    statusHue(v) { return (STATUS[v] || ["", "slate"])[1]; },
    /** 已基线/已废弃的需求：正文与验证方法锁定（BR-04） */
    locked(d) { return d && (d.status === "baselined" || d.status === "obsolete"); },
    dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("requirement", "list", {
        req_type: self.f_type || undefined,
        status: self.f_status || undefined,
        ...q,
      }));
      await self.loadOwners();
      await self.loadReqs();
      await self.list.load();
    },

    /** 上游需求候选（本应用自身）：失败静默兜底为空列表 */
    async loadReqs() {
      try {
        const r = await svc("requirement", "list", {}, { quiet: true });
        self.reqs = (r && r.items) || [];
      } catch { self.reqs = []; }
    },

    /** 责任人候选（`stakeholder` 主数据）：**只做候选、值仍是文本姓名** ——
     * 不落 `sh_no` 是有意的：全组 11 个应用的 `owner` 都是文本口径，单给本页上外键会造成
     * 「同一件事两种口径」（2026-09-25 决策，见 `应用详设.md` §6.3）。失败静默兜底为空列表。 */
    async loadOwners() {
      try {
        const r = await svc("stakeholder", "list", {}, { quiet: true });
        self.owners = (r && r.items) || [];
      } catch { self.owners = []; }
    },

    search() { self.list.load(1); },

    /* 详情 / 编辑：同一个模态，mode 切换 */
    async openDetail(row, mode) {
      self.modal = { open: true, loading: true, mode: mode || "view", d: null, changeNo: "", saving: false };
      try {
        self.modal.d = await svc("requirement", "get", { req_no: row.req_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    async saveEdit() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        // 已基线：必须带变更号（BR-04）；带了才允许改正文与验证方法
        const payload = { req_no: d.req_no, title: d.title, owner: d.owner };
        if (!self.locked(d) || self.modal.changeNo) {
          payload.statement = d.statement;
          payload.verify_method = d.verify_method;
        }
        if (self.modal.changeNo) payload.change_no = self.modal.changeNo;
        await svc("requirement", "update", payload);
        toast("已保存");
        self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /* 新建 */
    openForm() {
      self.form = { open: true, saving: false, d: {
        title: "", statement: "", req_type: "technical",
        verify_method: "", source_req_no: "", owner: "" } };
    },
    closeForm() { self.form.open = false; },
    /** F-1/F-2：提交按钮可用性 —— 验证方法必选；派生时上游必填 */
    canSubmit() {
      const d = self.form.d;
      if (!d.title.trim() || !d.statement.trim() || !d.verify_method) return false;
      if (d.req_type === "derived" && !d.source_req_no.trim()) return false;
      return true;
    },
    async saveForm() {
      const d = self.form.d;
      self.form.saving = true;
      try {
        await svc("requirement", "create", {
          title: d.title.trim(), statement: d.statement.trim(),
          req_type: d.req_type, verify_method: d.verify_method,
          source_req_no: d.req_type === "derived" ? d.source_req_no.trim() : undefined,
          owner: d.owner || undefined,
        });
        toast("已新建需求");
        self.form.open = false;
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.form.saving = false; }
    },

    /* 作废：二次确认，文案强调记录保留（F-6 / BR-02） */
    /** 提交评审：草稿 → 待评审（2026-09-25 补的服务；也是纳入基线的前置门） */
    async submitReview(row) {
      try {
        await svc("requirement", "submit_review", { req_no: row.req_no });
        toast(`需求 ${row.req_no} 已提交评审`);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    async obsolete(row) {
      if (!confirm(`确定作废需求 ${row.req_no}？\n\n记录会保留 —— 由它派生的下游需求仍能看到该编号与「已废弃」状态。`)) return;
      // 作废理由：**选填**，但填了会落库（`void_reason`）并在详情里显示 —— 作废是要交代理由的动作
      const reason = (prompt(`作废 ${row.req_no} 的理由（选填，会留痕）`) || "").trim();
      try {
        await svc("requirement", "obsolete",
                  reason ? { req_no: row.req_no, reason } : { req_no: row.req_no });
        toast("已作废（记录保留）");
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },
  });
  return self;
}
