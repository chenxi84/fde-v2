/* app/nasa_pms/decision/view.js —— 决策台账（与后端 decision.py 同文件夹）
 *
 * 数据来源类型：**独立创建** —— 保留「新建议题」入口（对应 create）。
 * 交互要点：
 *   · 评价准则与备选方案都是**聚合内子表**（无独立标识），随详情模态一起取（`get` 带 criteria/options）；
 *   · **已决策后内容冻结**（结论是快照，BR-06）—— 字段置灰、加准则/加方案入口消失、保存按钮不再出现；
 *     与配置项页不同，这里**没有"填变更号解锁"**：结论一旦落库就不再改写（语义差异，别照抄那边的绑定）；
 *   · 「权衡打分」是**唯一**给方案打分的入口（仅权衡中，BR-06），0 分是有效的分（不是"没打分"）；
 *   · 「决策」是唯一写结论的入口：备选方案**少于两个**不许决策（I-2）、选中的方案**必须有得分**（I-1）、
 *     选中**非最高分**方案时**必须给出依据**（BR-04）；
 *   · 「实施」只在已决策后出现，落库即硬终态。
 */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "decision", name: "决策", ic: "⚖",
  title: "决策台账", crumb: "提出 · 权衡中 · 已决策 · 已实施",
  order: 680,
  // 列表渲染**全字段列**（CONVENTION §7：list 返回全字段）；这几列非关键，默认隐藏，
  // 经平台「列设置」按需开启（与同组 review 页同口径）
  col_default_hidden: "来源度量,议题说明,决策依据,风险与收益,异议,实施说明,所属项目",
};

/* 评价方法字典（材料 §6.8.1.2.3 的典型方法 + §6.8.2 的工具清单 + §6.8.1.2.4 NOTE
   "Completing the decision matrix can be thought of as a default evaluation method"）。
   ⚠ `<option>` 一律**静态元素**（本数组只用来渲染过滤下拉/表单下拉的文案）——
   `x-model` + `x-for` 渲染的 option 会让**回填静默停在第一项**（同组实测踩过）。 */
const METHODS = [
  ["weighted_matrix", "加权决策矩阵"], ["trade_study", "权衡研究"],
  ["cost_benefit", "成本收益分析"], ["decision_tree", "决策树"],
  ["influence_diagram", "影响图"], ["ahp", "层次分析法"], ["borda", "波达计数"],
  ["utility", "效用分析"], ["simulation", "仿真"], ["testing", "测试验证"],
  ["review_meeting", "评审会商"],
];
/* 状态徽标用平台设计系统的 `.st` + `.st-<色>`（green=完成 / amber=进行中 / red=失败 /
   blue=流程中 / teal=跟踪中 / slate=中性）。
   ⚠ 不要写 `var(--ok)` / `var(--red)` 之类的内联色 —— 设计令牌里**没有**这两个变量，
   浏览器会静默回落成继承色，页面不报错但颜色全错（同组 requirement 样板即踩此坑）。 */
const STATUS = {
  proposed: ["提出", "st-slate"],
  weighing: ["权衡中", "st-amber"],
  decided: ["已决策", "st-blue"],
  implemented: ["已实施", "st-green"],
};
/* BR-06：已决策后**内容冻结**（结论是快照），已实施是**硬终态** —— 两者的前端表现都是"字段只读"，
   但文案不同（一个说冻结、一个说终态）。 */
const FROZEN = ["decided", "implemented"];

export default function pageDecision() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    // 筛选（与后端 list 的可过滤参数一一对应）
    f_eval: "", f_status: "", f_owner: "",
    // 详情 / 编辑（同一模态，mode 切换）
    modal: { open: false, loading: false, mode: "view", d: null, saving: false,
             criterion: "", weight: "1", option: "", description: "" },
    // 新建议题
    form: { open: false, d: null, saving: false },
    // 候选集 —— 跨应用只读（**值仍是文本**）：来源度量 ← technical_measure、责任人 ← stakeholder
    measures: [],
    owners: [],
    // 权衡打分（含动态评分行：seq / name / score / note）
    wm: { open: false, loading: false, dec_no: "", topic: "", criteria: [], rows: [],
          saving: false, busySeq: 0 },
    // 决策（选方案 + 依据 + 风险与收益 + 异议）
    cm: { open: false, dec_no: "", topic: "", options: [], chosen: "", rationale: "",
          risk_note: "", dissent: "", saving: false },

    methods: METHODS,

    methodName(v) { const m = METHODS.find((x) => x[0] === v); return m ? m[1] : (v || "—"); },
    statusName(v) { return (STATUS[v] || [v, ""])[0]; },
    statusCls(v) { return (STATUS[v] || ["", "st-slate"])[1]; },
    dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; },
    /** BR-06：已决策后内容冻结、已实施为终态 —— 字段一律只读，且**没有解锁入口** */
    frozen(d) { return !!d && FROZEN.indexOf(d.status) >= 0; },
    /* ⚠ 模态里读 `modal.d` 一律走下面这层**空安全**helper，模板里不写裸 `modal.d.status`：
       `x-if="modal.d"` 的子绑定**可能**在 openDetail 把 `modal.d` 置 null 的那一拍被再求值一次
       （同组 review 页实测抛 4 条 "Cannot read properties of null" —— 正是页脚那几个
        `x-show="modal.mode === 'view' && modal.d.status === ..."`；x-if 的销毁与子效果的
        执行顺序不保证，写裸取值就会漏）。 */
    isStatus(d, s) { return !!d && d.status === s; },
    inStatus(d, list) { return !!d && list.indexOf(d.status) >= 0; },
    stName(d) { return self.statusName(d && d.status); },
    stCls(d) { return self.statusCls(d && d.status); },
    methodOf(d) { return self.methodName(d && d.eval_method); },
    frozenText(d) {
      return self.isStatus(d, "implemented")
        ? "已实施（终态）—— 不能再修改内容、准则或备选方案（BR-06）"
        : "已作出决策（结论是快照）—— 内容、准则与备选方案已冻结（BR-06）";
    },
    /** 列表/信息条派生展示 */
    chosenText(d) { return (d && d.chosen_name) ? d.chosen_name : "—"; },
    topText(d) {
      return (d && d.top_seq) ? ("方案" + d.top_seq + " · " + d.top_score) : "—";
    },
    scoredText(d) {
      return (d ? (d.scored_total || 0) : 0) + "/" + (d ? (d.option_total || 0) : 0);
    },
    /** BR-01：准则清单为空时不能开始权衡（按钮禁用 + 详情给原因） */
    canStart(d) { return (d ? (d.criterion_total || 0) : 0) > 0; },
    showStartBlock(d) { return self.isStatus(d, "proposed") && !self.canStart(d); },
    /** I-2 / I-1 的前端镜像：方案少于两个、或一个都没打分时，决策按钮禁用 */
    canDecide(d) {
      return (d ? (d.option_total || 0) : 0) >= 2 && (d ? (d.scored_total || 0) : 0) >= 1;
    },
    showDecideBlock(d) { return self.isStatus(d, "weighing") && !self.canDecide(d); },
    decideBlockText(d) {
      if (((d && d.option_total) || 0) < 2) {
        return "备选方案少于两个 —— 决策必须有权衡，不允许作结论（BR-02）";
      }
      return "还没有方案被打分 —— 结论必须指向一个有评价得分的备选方案（BR-03）";
    },
    /** 评价准则 / 备选方案为空时的占位（`get` 一定有这两个数组，缺了按空处理） */
    criteriaOf(d) { return (d && d.criteria) || []; },
    optionsOf(d) { return (d && d.options) || []; },
    /** 最高分方案的序号：得分高者优先，**同分取序号小者**（与后端 `_top` 同口径） */
    topSeqOf(options) {
      const scored = (options || []).filter((o) => o.score !== null && o.score !== undefined);
      if (!scored.length) return null;
      let best = scored[0];
      for (const o of scored) {
        if (o.score > best.score || (o.score === best.score && o.seq < best.seq)) best = o;
      }
      return best.seq;
    },

    async init() {
      // ⚠ 先把会被模板引用的响应式状态建好，再挂模板（模板一旦注入就立刻求值 `list.items`，
      //   此刻 list 还是 null 会喷 "reading 'items' of null"；见 pitfalls #37）
      const tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("decision", "list", {
        eval_method: self.f_eval || undefined,
        status: self.f_status || undefined,
        owner: self.f_owner || undefined,
        ...q,
      }));
      self.tpl = tpl;
      await self.loadMeasures();
      await self.loadOwners();
      await self.list.load();
    },

    /** 「来源度量」候选（`technical_measure` 编号）：**只做候选、值仍是文本**（弱引用 `measure_no`）。
     * 跨应用只读、失败静默兜底为空列表。 */
    async loadMeasures() {
      try {
        const r = await svc("technical_measure", "list", {}, { quiet: true });
        self.measures = (r && r.items) || [];
      } catch { self.measures = []; }
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

    search() { self.list.load(1); },
    async reload() { await self.list.load(self.list.page); },

    /* ── 详情 / 编辑（同一模态）───────────────────────── */
    async openDetail(row, mode) {
      const m = mode || "view";
      self.modal = { open: true, loading: true, mode: m, d: null, saving: false,
                     criterion: "", weight: "1", option: "", description: "" };
      try {
        const d = await svc("decision", "get", { dec_no: row.dec_no });
        if (d) {
          // 弱引用 / 选填字段统一成空串，编辑表单才不会显示 "null"
          d.measure_no = d.measure_no || "";
          d.issue = d.issue || "";
          d.owner = d.owner || "";
          d.project_no = d.project_no || "";
        }
        self.modal.d = d;
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    async saveEdit() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        // 载荷里**没有** chosen_seq / rationale / implement_note：它们是 conclude / implement 的产物（BR-06）
        await svc("decision", "update", {
          dec_no: d.dec_no, topic: d.topic, eval_method: d.eval_method,
          measure_no: d.measure_no || "", issue: d.issue || "",
          owner: d.owner || "", project_no: d.project_no || "",
        });
        toast("已保存");
        self.modal.open = false;
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /* ── 两条聚合内子表：加准则 / 加方案（结论前可加，结论后冻结）── */
    canAddCriterion() {
      const d = self.modal.d;
      return !!(d && !self.frozen(d) && self.modal.criterion.trim());
    },
    async saveCriterion() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        self.modal.d = await svc("decision", "add_criterion", {
          dec_no: d.dec_no, criterion: self.modal.criterion.trim(),
          weight: self.modal.weight || 1,
        });
        self.modal.criterion = "";
        self.modal.weight = "1";
        toast("已加入评价准则");
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },
    canAddOption() {
      const d = self.modal.d;
      return !!(d && !self.frozen(d) && self.modal.option.trim());
    },
    async saveOption() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        self.modal.d = await svc("decision", "add_option", {
          dec_no: d.dec_no, name: self.modal.option.trim(),
          description: self.modal.description.trim() || undefined,
        });
        self.modal.option = "";
        self.modal.description = "";
        toast("已加入备选方案");
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /* ── 状态机动作（F-9：按钮按状态显隐）────────────── */

    /** 启动权衡：提出 → 权衡中（准则为空时后端会拒，BR-01） */
    async start(row) {
      try {
        await svc("decision", "start", { dec_no: row.dec_no });
        toast("已开始权衡");
        if (self.modal.open) self.modal.d = await svc("decision", "get", { dec_no: row.dec_no });
        await self.reload();
      } catch { /* api.js 已 toast */ }
    },

    /** 实施：已决策 → 已实施（硬终态） */
    async implement(d) {
      if (!confirm(`确定实施决策 ${d.dec_no}？\n\n实施后为终态：内容、准则与备选方案均不可再改。`)) return;
      try {
        await svc("decision", "implement", { dec_no: d.dec_no });
        toast("决策已实施");
        self.modal.open = false;
        await self.reload();
      } catch { /* api.js 已 toast */ }
    },

    /* ── 权衡打分（仅权衡中；0 分是有效的分）────────── */
    openWeigh(row) {
      self.wm = { open: true, loading: true, dec_no: row.dec_no, topic: row.topic || "",
                  criteria: [], rows: [], saving: false, busySeq: 0 };
      self.loadWeigh(row.dec_no);
    },
    async loadWeigh(dec_no) {
      try {
        const d = await svc("decision", "get", { dec_no: dec_no });
        self.wm.criteria = self.criteriaOf(d);
        self.wm.rows = self.optionsOf(d).map((o) => ({
          seq: o.seq, name: o.name, score: self.inText(o.score), note: o.note || "" }));
      } catch { /* api.js 已 toast */ } finally { self.wm.loading = false; }
    },
    /** 得分回填成**字符串**：0 要显示成 "0"（不是空、更不是 "null"） */
    inText(v) { return (v === null || v === undefined) ? "" : String(v); },
    closeWeigh() { self.wm.open = false; },
    /** 某行是否可提交：得分非空即视为"要有一次打分动作"；0 也有效 */
    rowOk(r) { return !!(r && String(r.score).trim() !== ""); },
    async saveRow(r) {
      self.wm.busySeq = r.seq;
      try {
        const d = await svc("decision", "score_option", {
          dec_no: self.wm.dec_no, seq: r.seq, score: String(r.score).trim(),
          note: String(r.note || "").trim() || undefined,
        });
        self.wm.rows = self.optionsOf(d).map((o) => ({
          seq: o.seq, name: o.name, score: self.inText(o.score), note: o.note || "" }));
        if (self.modal.open && self.modal.d && self.modal.d.dec_no === d.dec_no) {
          self.modal.d = d;
        }
        const hit = self.optionsOf(d).filter((o) => Number(o.seq) === Number(r.seq))[0];
        toast("方案" + r.seq + " 已记 " + (hit ? hit.score : "") + " 分");
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { self.wm.busySeq = 0; }
    },

    /* ── 决策（选方案 + 依据，两条不变量 + BR-04）────── */
    // ⚠ 方案清单只在 `get` 里（列表行没有 options）—— 开模态前先取详情，与 openWeigh 同口径
    async openConclude(row) {
      self.cm = { open: true, dec_no: row.dec_no, topic: row.topic || "", options: [],
                  chosen: "", rationale: "", risk_note: "", dissent: "", saving: false };
      try {
        const d = await svc("decision", "get", { dec_no: row.dec_no });
        self.cm.topic = (d && d.topic) || self.cm.topic;
        self.cm.options = self.optionsOf(d).map((o) => ({ seq: o.seq, name: o.name,
                                                          score: o.score }));
      } catch { self.cm.open = false; }
    },
    closeConclude() { self.cm.open = false; },
    /** 与后端同口径：得分高者优先、同分取序号小者 */
    cmTopSeq() { return self.topSeqOf(self.cm.options); },
    cmChosen() {
      const c = Number(self.cm.chosen);
      return self.cm.options.filter((o) => Number(o.seq) === c)[0] || null;
    },
    /** BR-04：选中的不是最高分方案 ⇒ 依据必填（材料 §6.8.1.2.5） */
    cmNeedRationale() {
      const t = self.cmTopSeq();
      const o = self.cmChosen();
      return !!(t !== null && o && o.score !== null && Number(o.seq) !== Number(t));
    },
    /** 决策模态的提示文案（唯一一处给"为什么不能提交"） */
    cmHint() {
      if (!self.cm.options.length) return "还没有备选方案 —— 少于两个不允许作结论（BR-02）";
      const o = self.cmChosen();
      if (!o) return "请选择一个已打分的备选方案 —— 未打分的方案不能作为结论（BR-03）";
      if (o.score === null) return "该方案还没有评价得分，不能作为结论（BR-03）";
      if (self.cmNeedRationale()) {
        return "选中的不是最高分方案（最高分是方案" + self.cmTopSeq() + "）—— 必须给出依据（BR-04）";
      }
      return "选中得分最高的方案，依据选填（BR-04）";
    },
    canConclude() {
      const o = self.cmChosen();
      if (!o || o.score === null) return false;
      if (self.cmNeedRationale() && !String(self.cm.rationale || "").trim()) return false;
      return true;
    },
    /** 「为什么不能提交」的**唯一**文案（与 cmHint 的分工：一个说该怎么选，一个说还差什么） */
    canConcludeReason() {
      if (!self.cm.options.length) return "还没有备选方案 —— 少于两个不允许作结论（BR-02）";
      const o = self.cmChosen();
      if (!o) return "请选择一个已打分的备选方案 —— 未打分的方案不能作为结论（BR-03）";
      if (o.score === null) return "该方案还没有评价得分，不能作为结论（BR-03）";
      if (self.cmNeedRationale()) return "选中的不是最高分方案 —— 必须给出依据（BR-04）";
      return "";
    },
    async saveConclude() {
      const c = self.cm;
      c.saving = true;
      try {
        await svc("decision", "conclude", {
          dec_no: c.dec_no, chosen_seq: Number(c.chosen),
          rationale: String(c.rationale || "").trim() || undefined,
          risk_note: String(c.risk_note || "").trim() || undefined,
          dissent: String(c.dissent || "").trim() || undefined,
        });
        toast("已作出决策");
        c.open = false;
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { c.saving = false; }
    },

    /* ── 新建议题 ──────────────────────────────────── */
    openForm() {
      self.form = { open: true, saving: false, d: {
        topic: "", eval_method: "weighted_matrix", measure_no: "", issue: "",
        owner: "", project_no: "" } };
    },
    closeForm() { self.form.open = false; },
    /** F-1：议题与评价方法齐备才可提交 */
    canSubmit() {
      const d = self.form.d;
      return !!(d && d.topic.trim() && d.eval_method);
    },
    async saveForm() {
      const d = self.form.d;
      self.form.saving = true;
      try {
        await svc("decision", "create", {
          topic: d.topic.trim(), eval_method: d.eval_method,
          measure_no: d.measure_no || undefined, issue: d.issue || undefined,
          owner: d.owner || undefined, project_no: d.project_no || undefined,
        });
        toast("已新建议题（提出态）");
        self.form.open = false;
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.form.saving = false; }
    },
  });
  return self;
}
