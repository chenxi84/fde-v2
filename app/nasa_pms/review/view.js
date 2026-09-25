/* app/nasa_pms/review/view.js —— 评审台账（与后端 review.py 同文件夹）
 *
 * 数据来源类型：**独立创建** —— 保留「新建评审」入口（对应 create）。
 * 交互要点：
 *   · 评审项清单与行动项都是**聚合内子表**（无独立标识），随详情模态一起取（`get` 带 `items`/`actions`）；
 *   · **已结论后内容冻结**（结论是快照，BR-06）—— 字段置灰、加评审项入口消失、保存按钮不再出现；
 *     与配置项页不同，这里**没有"填变更号解锁"**：结论一旦落库就不再改写（语义差异，别照抄那边的绑定）；
 *   · 「出结论」是唯一产生行动项的入口（BR-01 有条件通过必须有行动项），行动项与结论同事务落库；
 *   · 「关闭评审」要求行动项全部完成（BR-07）—— 未清零时按钮不出现并给出原因。
 *   · 「跨评审行动项汇总」是**查询视图**（`list_actions`），不是第二个聚合。
 */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "review", name: "评审", ic: "☑",
  title: "评审台账", crumb: "计划 · 进行中 · 已结论 · 行动项跟踪 · 已关闭",
  order: 650,
  // 列表渲染**全字段列**（CONVENTION §7：list 返回全字段）；这几列非关键，默认隐藏，
  // 经平台「列设置」按需开启（与 app/nasa_pms 其余三页的"只渲染关键列"做法不同，取前者口径）
  col_default_hidden: "依据计划,评审纪要,关闭说明,所属项目",
};

/* 字典：业务名逐字取自《术语表.md》（MCR/SRR/SDR/PDR/CDR/SIR/TRR/PRR/SIR 八种），
   ORR / FRR / SAR 取自材料附录 A 缩略语表与 §6.7 TABLE 6.7-1（本步回填，见 新增术语.md） */
const REVIEW_TYPES = [
  ["mcr", "任务概念评审（MCR）"], ["srr", "系统需求评审（SRR）"], ["sdr", "系统定义评审（SDR）"],
  ["pdr", "初步设计评审（PDR）"], ["cdr", "关键设计评审（CDR）"], ["sir", "系统集成评审（SIR）"],
  ["trr", "测试就绪评审（TRR）"], ["prr", "生产就绪评审（PRR）"], ["orr", "运行就绪评审（ORR）"],
  ["frr", "飞行就绪评审（FRR）"], ["sar", "系统验收评审（SAR）"],
];
/* 阶段：术语表的 Pre-Phase A / Phase A..E —— 阶段在本聚合里是**枚举属性**，不独立成聚合 */
const PHASES = [["pre_a", "预 A 阶段"], ["a", "A 阶段"], ["b", "B 阶段"],
                ["c", "C 阶段"], ["d", "D 阶段"], ["e", "E 阶段"]];
const CONCLUSIONS = [["pass", "通过"], ["conditional", "有条件通过"], ["fail", "不通过"]];
/* 状态徽标用平台设计系统的 `.st` + `.st-<色>`（green=完成 / amber=进行中 / red=失败 /
   blue=流程中 / teal=跟踪中 / slate=中性）。
   ⚠ 不要写 `var(--ok)` / `var(--red)` 之类的内联色 —— 设计令牌里**没有**这两个变量，
   浏览器会静默回落成继承色，页面不报错但颜色全错（同组 requirement 样板即踩此坑）。 */
const STATUS = {
  planned: ["计划", "st-slate"],
  in_progress: ["进行中", "st-amber"],
  concluded: ["已结论", "st-blue"],
  tracking: ["行动项跟踪中", "st-teal"],
  closed: ["已关闭", "st-green"],
};
const CONCLUSION_CLS = { pass: "st-green", conditional: "st-amber", fail: "st-red" };
const ACTION_STATUS = { open: ["未完成", "st-amber"], done: ["已完成", "st-green"] };
/* BR-06：已结论后**内容冻结**（结论是快照），已关闭是**硬终态** —— 两者的前端表现都是"字段只读"，
   但文案不同（一个说冻结、一个说终态）。 */
const FROZEN = ["concluded", "tracking", "closed"];

export default function pageReview() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    // 筛选（与后端 list 的可过滤参数一一对应）
    f_type: "", f_phase: "", f_status: "", f_conclusion: "",
    // 详情 / 编辑（同一模态，mode 切换）
    modal: { open: false, loading: false, mode: "view", d: null, saving: false,
             item: "", criterion: "" },
    // 新建评审
    form: { open: false, d: null, saving: false },
    // 出结论（含动态行动项行：content / owner / due_date）
    cm: { open: false, review_no: "", title: "", saving: false,
          conclusion: "", minutes: "", actions: [] },
    // 跨评审行动项汇总（查询视图 list_actions）
    sum: { status: "open", items: [], total: 0, loading: false },

    types: REVIEW_TYPES, phases: PHASES, conclusions: CONCLUSIONS,

    typeName(v) { const t = REVIEW_TYPES.find((x) => x[0] === v); return t ? t[1] : (v || "—"); },
    /** 列表里类型列用**码**（PDR）+ 中文全名两行；选择器里用全名（业务名唯一来源是术语表） */
    typeCode(v) { return v ? String(v).toUpperCase() : "—"; },
    phaseName(v) { const p = PHASES.find((x) => x[0] === v); return p ? p[1] : (v || "—"); },
    conclusionName(v) { const c = CONCLUSIONS.find((x) => x[0] === v); return c ? c[1] : (v || "—"); },
    conclusionCls(v) { return CONCLUSION_CLS[v] || ""; },
    statusName(v) { return (STATUS[v] || [v, ""])[0]; },
    statusCls(v) { return (STATUS[v] || ["", "st-slate"])[1]; },
    actionStatusName(v) { return (ACTION_STATUS[v] || [v, ""])[0]; },
    actionStatusCls(v) { return (ACTION_STATUS[v] || ["", "st-slate"])[1]; },
    dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; },
    /** BR-06：已结论后内容冻结、已关闭为终态 —— 字段一律只读，且**没有解锁入口** */
    frozen(d) { return !!d && FROZEN.indexOf(d.status) >= 0; },
    /** BR-07：只有已结论 / 跟踪中、且行动项全部完成的评审才谈得上关闭 */
    canClose(d) {
      return !!d && (d.status === "concluded" || d.status === "tracking")
        && !Number(d.action_open || 0);
    },
    /* ⚠ 模态里读 `modal.d` 一律走下面这层**空安全**helper，模板里不写裸 `modal.d.status`：
       `x-if="modal.d"` 的子绑定**可能**在 openDetail 把 `modal.d` 置 null 的那一拍被再求值一次
       （实测抛 4 条 "Cannot read properties of null (reading 'status')" —— 正是页脚那几个
        `x-show="modal.mode === 'view' && modal.d.status === ..."`；x-if 的销毁与子效果的
        执行顺序不保证，写裸取值就会漏）。 */
    isStatus(d, s) { return !!d && d.status === s; },
    inStatus(d, list) { return !!d && list.indexOf(d.status) >= 0; },
    stName(d) { return self.statusName(d && d.status); },
    stCls(d) { return self.statusCls(d && d.status); },
    conclCls(d) { return (d && d.conclusion) ? self.conclusionCls(d.conclusion) : ""; },
    conclName(d) { return self.conclusionName(d && d.conclusion); },
    frozenText(d) {
      return self.isStatus(d, "closed")
        ? "已关闭（终态）—— 不能再修改内容或评审项（BR-06）"
        : "已出结论（结论是快照）—— 内容与评审项清单已冻结（BR-06）";
    },
    showCloseBlock(d) { return self.inStatus(d, ["concluded", "tracking"]) && !self.canClose(d); },
    closeBlockText(d) {
      return "还有 " + ((d && d.action_open) || 0) + " 条行动项未完成 —— 全部完成后才能关闭评审（BR-07）";
    },
    /** 评审项清单 / 行动项为空时的占位文案（`get` 一定有这两个数组，缺了按空处理） */
    itemsOf(d) { return (d && d.items) || []; },
    actionsOf(d) { return (d && d.actions) || []; },

    /** 「依据计划」候选：跨应用只读 `tech_plan.list`（**值仍是 plan_no 文本**，弱引用不变） */
    plans: [],
    /** 「责任人」候选：跨应用只读 `stakeholder.list`（**值仍是文本姓名**，同 requirement/risk 口径） */
    owners: [],

    async init() {
      // ⚠ 先把会被模板引用的响应式状态建好，再挂模板（模板一旦注入就立刻求值 `list.items`，
      //   此刻 list 还是 null 会喷 "reading 'items' of null"；见 pitfalls #37）
      const tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("review", "list", {
        review_type: self.f_type || undefined,
        phase: self.f_phase || undefined,
        status: self.f_status || undefined,
        conclusion: self.f_conclusion || undefined,
        ...q,
      }));
      self.tpl = tpl;
      await self.loadCandidates();
      await self.list.load();
      await self.loadSummary();
    },

    /** 「依据计划」候选（`tech_plan.list`）：失败静默兜底为空列表（不喷 toast） */
    async loadPlans() {
      try {
        const r = await svc("tech_plan", "list", {}, { quiet: true });
        self.plans = (r && r.items) || [];
      } catch { self.plans = []; }
    },

    /** 「责任人」候选（`stakeholder.list`）：同上 */
    async loadOwners() {
      try {
        const r = await svc("stakeholder", "list", {}, { quiet: true });
        self.owners = (r && r.items) || [];
      } catch { self.owners = []; }
    },

    /** 两个候选集一起拉（互不依赖，并发） */
    async loadCandidates() {
      await Promise.all([self.loadPlans(), self.loadOwners()]);
    },

    search() { self.list.load(1); },
    /** 主列表 + 行动项汇总一起刷新（任一动作都会影响两处：如完成行动项会影响清单行计数） */
    async reload() {
      await self.list.load(self.list.page);
      await self.loadSummary();
    },

    /* ── 详情 / 编辑（同一模态）───────────────────────── */
    async openDetail(row, mode) {
      const m = mode || "view";
      self.modal = { open: true, loading: true, mode: m, d: null, saving: false,
                     item: "", criterion: "" };
      try {
        const d = await svc("review", "get", { review_no: row.review_no });
        if (d) {
          // 弱引用 / 选填字段统一成空串，编辑表单才不会显示 "null"
          d.plan_no = d.plan_no || "";
          d.owner = d.owner || "";
          d.minutes = d.minutes || "";
        }
        self.modal.d = d;
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    async saveEdit() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        // 载荷里**没有** conclusion / minutes：结论只能经「出结论」写入（BR-06）
        await svc("review", "update", {
          review_no: d.review_no, title: d.title, review_type: d.review_type,
          phase: d.phase, subject: d.subject,
          plan_no: d.plan_no || "", owner: d.owner || "",
        });
        toast("已保存");
        self.modal.open = false;
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /* ── 评审项清单（聚合内子表：结论前可加，结论后冻结）── */
    canAddItem() {
      const d = self.modal.d;
      return !!(d && !self.frozen(d) && self.modal.item.trim());
    },
    async saveItem() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        self.modal.d = await svc("review", "add_item", {
          review_no: d.review_no, item: self.modal.item.trim(),
          criterion: self.modal.criterion.trim() || undefined,
        });
        self.modal.item = "";
        self.modal.criterion = "";
        toast("已加入评审项清单");
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /* ── 状态机动作（F-9：按钮按状态显隐）────────────── */

    /** 启动评审：计划 → 进行中 */
    async start(row) {
      try {
        await svc("review", "start", { review_no: row.review_no });
        toast("评审已启动");
        if (self.modal.open) self.modal.d = await svc("review", "get", { review_no: row.review_no });
        await self.reload();
      } catch { /* api.js 已 toast */ }
    },

    /** 完成一条行动项（open → done）—— 汇总表与详情模态共用 */
    async completeAction(review_no, seq) {
      if (!confirm(`确认第 ${seq} 条行动项已完成？`)) return;
      try {
        const d = await svc("review", "close_action", { review_no: review_no, seq: seq });
        toast("行动项已完成");
        if (self.modal.open && self.modal.d && self.modal.d.review_no === review_no) {
          self.modal.d = d;
        }
        await self.reload();
      } catch { /* api.js 已 toast */ }
    },

    /** 关闭评审（BR-07：行动项须全部完成；终态不可再改） */
    async closeReview(d) {
      if (!confirm(`确定关闭评审 ${d.review_no}？\n\n关闭后为终态：内容与评审项清单均不可再改。`)) return;
      try {
        await svc("review", "close", { review_no: d.review_no });
        toast("评审已关闭");
        self.modal.open = false;
        await self.reload();
      } catch { /* api.js 已 toast */ }
    },

    /* ── 出结论（含行动项动态行）────────────────────── */
    openConclude(row) {
      self.cm = { open: true, review_no: row.review_no, title: row.title || "",
                  saving: false, conclusion: "", minutes: "", actions: [] };
    },
    closeConclude() { self.cm.open = false; },
    addActionRow() { self.cm.actions.push({ content: "", owner: "", due_date: "" }); },
    delActionRow(i) { self.cm.actions.splice(i, 1); },
    /** 一行行动项填全才有效（BR-02：内容 + 责任人 + 期限） */
    actionRowOk(a) {
      return !!(a && String(a.content || "").trim() && String(a.owner || "").trim() && a.due_date);
    },
    /** F-4：结论必选；行动项行要么不填要么填全；「有条件通过」必须有行动项（BR-01 的前端镜像） */
    canConclude() {
      const c = self.cm;
      if (!c.conclusion) return false;
      if (c.actions.some((a) => !self.actionRowOk(a))) return false;
      if (c.conclusion === "conditional" && !c.actions.length) return false;
      return true;
    },
    async saveConclude() {
      const c = self.cm;
      c.saving = true;
      try {
        await svc("review", "conclude", {
          review_no: c.review_no, conclusion: c.conclusion,
          minutes: c.minutes || undefined,
          actions: c.actions.map((a) => ({
            content: String(a.content).trim(), owner: String(a.owner).trim(),
            due_date: a.due_date,
          })),
        });
        toast("已出结论");
        self.cm.open = false;
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { c.saving = false; }
    },

    /* ── 跨评审行动项汇总（查询视图：list_actions）──── */
    async loadSummary() {
      self.sum.loading = true;
      try {
        const r = await svc("review", "list_actions", {
          status: self.sum.status || undefined, page: 1, size: 20,
        });
        self.sum.items = (r && r.items) || [];
        self.sum.total = (r && r.total) || 0;
      } catch { self.sum.items = []; self.sum.total = 0; } finally { self.sum.loading = false; }
    },
    setSumStatus(s) { self.sum.status = s; return self.loadSummary(); },

    /* ── 新建评审 ──────────────────────────────────── */
    openForm() {
      self.form = { open: true, saving: false, d: {
        title: "", review_type: "", phase: "", subject: "", plan_no: "", owner: "" } };
    },
    closeForm() { self.form.open = false; },
    /** F-1：标题 / 类型 / 阶段 / 评审对象 四项齐备才可提交（类型与阶段不给默认值） */
    canSubmit() {
      const d = self.form.d;
      return !!(d && d.title.trim() && d.review_type && d.phase && d.subject.trim());
    },
    async saveForm() {
      const d = self.form.d;
      self.form.saving = true;
      try {
        await svc("review", "create", {
          title: d.title.trim(), review_type: d.review_type, phase: d.phase,
          subject: d.subject.trim(),
          plan_no: d.plan_no || undefined, owner: d.owner || undefined,
        });
        toast("已新建评审（计划态）");
        self.form.open = false;
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.form.saving = false; }
    },
  });
  return self;
}
