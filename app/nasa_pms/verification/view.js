/* app/nasa_pms/verification/view.js —— 验证矩阵（与后端 verification.py 同文件夹）
 *
 * 数据来源类型：**跨应用派生** —— 一行验证项由一条已存在的需求派生而来（create 必带 req_no）。
 * 交互要点：对应需求是**强关联**，创建时从需求台账选（跨应用 requirement.list），建成后只读
 * （换需求 = 换一行，应另建验证项，BR-01）；判定结果**不是可填字段**，只能经「记录判定」动作产生
 * （BR-06）；「不通过」必须同时给后续处置（BR-02）；已判定的验证项不能再改验证方法与验证阶段（BR-03）；
 * 关闭为终态，动作按钮全部收起。
 * 页眉另给一条**验证矩阵覆盖**读数（I-1：每条已基线需求至少有一条验证项）—— 组合级口径，
 * 写路径上无法违反（写验证项只会增加覆盖），故以查询视图呈现。
 */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "verification", name: "验证项", ic: "☑",
  title: "验证矩阵", crumb: "规划 · 执行 · 判定 · 关闭",
  order: 660,
};

/* 字典：验证方法 = 材料 §5.3.1.2「METHODS OF VERIFICATION」的四种（与 requirement 同字典） */
const METHODS = [["inspection", "检验"], ["analysis", "分析"],
                 ["demonstration", "演示"], ["test", "测试"]];
/* 验证阶段 = 材料附录 D TABLE D-1「Phases」列的 8 个执行序列位置 */
const PHASES = [["pre_development", "研制前声明阶段"],
                ["box_functional", "单机功能级"],
                ["box_environmental", "单机环境级"],
                ["system_environmental", "系统环境级"],
                ["system_functional", "系统功能级"],
                ["end_to_end", "端到端功能级"],
                ["integrated_vehicle", "集成飞行器功能级"],
                ["on_orbit", "在轨功能级"]];
const RESULTS = [["pass", "通过"], ["fail", "不通过"]];
/* 状态徽章用平台设计系统的 `.st` + `.st-<色>`（`design-plus/view-convention/design-system.md`）。
   ⚠ 不要写 `var(--ok)` / `var(--red)` 之类的内联色 —— 设计令牌里**没有**这两个变量，
   浏览器会静默回落成继承色，页面不报错但颜色全错（requirement 样板即踩此坑）。 */
const STATUS = {
  planned: ["规划", "st-slate"],
  executing: ["执行中", "st-blue"],
  passed: ["通过", "st-green"],
  failed: ["不通过", "st-red"],
  closed: ["关闭", "st-slate"],
};
const RESULT_CLS = { pass: "st-green", fail: "st-red" };
const DECIDED = ["passed", "failed"];   // 已判定：BR-03 之后不得改写验证方法 / 阶段
const TERMINAL = ["closed"];            // 终态：BR-03 之后一律不得再改

const MODE_TITLE = { view: "验证项详情", edit: "编辑验证项",
                     record: "记录判定结果", close: "关闭验证项" };

export default function pageVerification() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    // 筛选（与后端 list 的可过滤参数一一对应）
    f_req: "", f_method: "", f_phase: "", f_status: "",
    // 详情 / 编辑 / 记录判定 / 关闭 —— 同一个模态，mode 切换
    modal: { open: false, loading: false, mode: "view", d: null, saving: false,
             record: { result: "", evidence: "", followUp: "" },
             close: { note: "" } },
    // 规划验证项
    form: { open: false, saving: false, d: null },
    // 跨应用：需求台账（下拉选项源 + 覆盖率读数）
    reqs: [],
    // 「责任人」候选 —— 跨应用 stakeholder.list（**值仍是文本姓名**，同 requirement/risk）
    owners: [],
    reqReady: true,
    cov: { baselined: 0, covered: 0 },

    // ⚠ 上面三本字典只用于「值 → 中文名」的展示映射；**选项本身写在 view.html 的静态 <option> 里**
    //   （不能用 x-for 生成：x-model 的数据→DOM 回填跑在 option 插入之前，会静默停在第一项，见前端详设 §8）

    methodName(v) { const m = METHODS.find((x) => x[0] === v); return m ? m[1] : (v || "—"); },
    phaseName(v) { const p = PHASES.find((x) => x[0] === v); return p ? p[1] : (v || "—"); },
    resultName(v) { const r = RESULTS.find((x) => x[0] === v); return r ? r[1] : "未判定"; },
    resultCls(v) { return RESULT_CLS[v] || "st-slate"; },
    statusName(v) { return (STATUS[v] || [v, ""])[0]; },
    statusCls(v) { return (STATUS[v] || ["", "st-slate"])[1]; },
    dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; },
    /** 已判定（通过 / 不通过）：验证方法与验证阶段自此**冻结**（BR-03） */
    decided(d) { return !!d && DECIDED.indexOf(d.status) >= 0; },
    /** 终态（关闭）：任何修改都拒绝（BR-03） */
    terminal(d) { return !!d && TERMINAL.indexOf(d.status) >= 0; },
    /** 验证方法 / 阶段是否锁定：已判定或已关闭都锁死 */
    locked(d) { return self.decided(d) || self.terminal(d); },
    reqLabel(no) {
      const r = self.reqs.find((x) => x.req_no === no);
      return r ? (no + " · " + r.title) : no;
    },

    async init() {
      // ⚠ 一切会被模板引用的 reactive 状态必须在**第一个 await 之前**建好（pitfalls #37）
      self.list = pageable(async (q) => svc("verification", "list", {
        req_no: self.f_req || undefined,
        method: self.f_method || undefined,
        phase: self.f_phase || undefined,
        status: self.f_status || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      await self.loadReqs();
      await self.loadOwners();
      await self.list.load();
      await self.loadCoverage();
    },

    /** 需求台账（跨应用只读）：下拉选项源；失败静默兜底为空列表（不喷 toast） */
    async loadReqs() {
      try {
        const r = await svc("requirement", "list", {}, { quiet: true });
        self.reqs = (r && r.items) || [];
        self.reqReady = true;
      } catch { self.reqs = []; self.reqReady = false; }
    },

    /** 责任人候选（`stakeholder` 主数据）：**只做候选、值仍是文本姓名** ——
     * 不落 `sh_no` 是有意的：全组 `owner` 都是文本口径，单页上外键会造成"同一件事两种口径"。
     * 失败静默兜底为空列表（不喷 toast）。 */
    async loadOwners() {
      try {
        const r = await svc("stakeholder", "list", {}, { quiet: true });
        self.owners = (r && r.items) || [];
      } catch { self.owners = []; }
    },

    /** 验证矩阵覆盖读数（I-1）：已基线需求里有多少条已挂上验证项 */
    async loadCoverage() {
      try {
        const r = await svc("verification", "list", {}, { quiet: true });
        const has = new Set(((r && r.items) || []).map((x) => x.req_no));
        const base = self.reqs.filter((x) => x.status === "baselined");
        self.cov = { baselined: base.length,
                     covered: base.filter((x) => has.has(x.req_no)).length };
      } catch { self.cov = { baselined: 0, covered: 0 }; }
    },
    coverageText() {
      if (!self.reqReady) return "验证矩阵覆盖：需求台账不可用，暂无法计算（I-1）";
      const c = self.cov;
      return "验证矩阵覆盖：已基线需求 " + c.baselined + " 条 · 已覆盖 " + c.covered
             + " 条 · 缺口 " + (c.baselined - c.covered) + " 条";
    },
    coverageGap() { return self.reqReady && (self.cov.baselined - self.cov.covered) > 0; },

    search() { self.list.load(1); },

    /* 详情 / 编辑 / 记录判定 / 关闭：同一个模态，mode 切换 */
    async openDetail(row, mode) {
      const m = mode || "view";
      self.modal = { open: true, loading: true, mode: m, d: null, saving: false,
                     record: { result: "", evidence: "", followUp: "" },
                     close: { note: "" } };
      try {
        self.modal.d = await svc("verification", "get", { ver_no: row.ver_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },
    modalTitle() { return MODE_TITLE[self.modal.mode] || "验证项"; },

    async saveEdit() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        // ⚠ 载荷里**没有** req_no / status / result —— 强关联与判定都不是可改字段（BR-01 / BR-06）
        const payload = { ver_no: d.ver_no, criteria: d.criteria || "", owner: d.owner || "" };
        // 已判定（通过 / 不通过）时不下发验证方法与阶段 —— 它们是判定的事实前提（BR-03）
        if (!self.locked(d)) {
          payload.method = d.method;
          payload.phase = d.phase;
        }
        await svc("verification", "update", payload);
        toast("已保存");
        self.modal.open = false;
        await self.list.load(self.list.page);
        await self.loadCoverage();
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /** F-4：判定结果必选 + 证据必填 + 「不通过」必须给后续处置（BR-02） */
    canRecord() {
      const r = self.modal.record;
      if (!r.result) return false;
      if (!r.evidence.trim()) return false;
      if (r.result === "fail" && !r.followUp.trim()) return false;
      return true;
    },
    async saveRecord() {
      const r = self.modal.record;
      self.modal.saving = true;
      try {
        await svc("verification", "record_result", {
          ver_no: self.modal.d.ver_no, result: r.result,
          evidence: r.evidence.trim(),
          follow_up: r.result === "fail" ? r.followUp.trim() : (r.followUp.trim() || undefined),
        });
        toast("已记录判定结果");
        self.modal.open = false;
        await self.list.load(self.list.page);
        await self.loadCoverage();
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /** 关闭：给判定收尾（关闭说明选填） */
    async saveClose() {
      self.modal.saving = true;
      try {
        await svc("verification", "close", {
          ver_no: self.modal.d.ver_no, note: self.modal.close.note || undefined,
        });
        toast("已关闭验证项（记录保留）");
        self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /* 开始执行：规划 → 执行中 */
    async start(row) {
      try {
        await svc("verification", "start", { ver_no: row.ver_no });
        toast("已开始执行");
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    /* 规划验证项 */
    openForm() {
      self.form = { open: true, saving: false, d: {
        req_no: "", method: "", phase: "", criteria: "", owner: "" } };
    },
    closeForm() { self.form.open = false; },
    /** F-1：对应需求 / 验证方法 / 验证阶段三者齐备才可提交（不给默认值，须显式选择） */
    canSubmit() {
      const d = self.form.d;
      return !!d && !!d.req_no && !!d.method && !!d.phase;
    },
    async saveForm() {
      const d = self.form.d;
      self.form.saving = true;
      try {
        await svc("verification", "create", {
          req_no: d.req_no, method: d.method, phase: d.phase,
          criteria: d.criteria || undefined, owner: d.owner || undefined,
        });
        toast("已规划验证项");
        self.form.open = false;
        await self.list.load(1);
        await self.loadCoverage();
      } catch { /* api.js 已 toast */ } finally { self.form.saving = false; }
    },
  });
  return self;
}
