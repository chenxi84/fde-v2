/* app/nasa_pms/technical_measure/view.js —— 技术度量台账（与后端 technical_measure.py 同文件夹）
 *
 * 数据来源类型：**独立创建** —— 保留「新建度量」入口（对应 create）。
 * 交互要点：
 *   · 实测值序列与告警台账都是**聚合内子表**（无独立标识），随详情模态一起取（`get` 带 `readings`/`alerts`）；
 *   · **⚠ 本页最关键的语义差**：判定口径（优化方向 / 目标值 / 阈值）**只在「定义」态可改**。
 *     基线之后就冻结，且与同组 review / configuration_item 的"已结论即一律冻结、无解锁入口"**不同** ——
 *     这里"基线"是**可被 rebaseline 重新打开**的冻结，解锁入口在页脚（须带变更请求号）。
 *     照抄别的页的 `frozen()` 绑定会漏掉"定义态可改"这一半（本页实测踩过，见 前端测试用例.md §9）。
 *   · 「记实测值」是唯一写实测值的入口，**超阈值时同事务产生告警**（BR-01/I-1）——前端只负责在提交前
 *     给出"按当前口径会不会告警"的预判，判定权威仍在后端。
 *   · 「关闭度量」要求没有未了结告警（BR-06）—— 未了结时按钮**可见但禁用**并给出原因（不是只藏按钮）。
 *   · 「跨度量告警汇总」是**查询视图**（`list_alerts`），不是第二个聚合（材料 §6.7.1.2.1 的 alert zones）。
 */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "technical_measure", name: "技术度量", ic: "◎",
  title: "技术度量台账", crumb: "定义 · 度量中 · 超阈值 · 已纠正 · 已关闭",
  order: 670,
  // 列表渲染**全字段列**（CONVENTION §7：list 返回全字段）；这几列非关键，默认隐藏，
  // 经平台「列设置」按需开启。
  // ⚠ 「计量单位」与「基线版本」**不**藏：单位决定读数怎么读（12.5 是 12.5% 还是 12.5kg），
  //    基线版本是"当前生效的是哪一版口径"（BR-02 的可见证据）—— 两者都不是可有可无的列。
  col_default_hidden: "关联需求,关闭说明,所属项目",
};

/* 字典：业务名逐字取自《术语表.md》（技术绩效指标（TPM））与材料附录 A 缩略语表
   （MOP = Measure of Performance / KPP = Key Performance Parameter）；见 新增术语.md */
const CATEGORIES = [["tpm", "技术绩效指标（TPM）"], ["mop", "性能度量（MOP）"],
                    ["kpp", "关键性能参数（KPP）"]];
/* 优化方向：判定口径的一半（另一半是阈值）—— 材料未给这个词，属第②步工程口径（见 新增术语.md §5） */
const DIRECTIONS = [["higher", "越大越好"], ["lower", "越小越好"]];
/* 状态徽标用平台设计系统的 `.st` + `.st-<色>`（blue=流程中 / red=告警 / teal=已处置 /
   green=终态 / slate=初始）。
   ⚠ 不要写 `var(--ok)` / `var(--red)` 之类的内联色 —— 设计令牌里**没有**这两个变量，
   浏览器会静默回落成继承色，页面不报错但颜色全错（同组 requirement 样板即踩此坑）。 */
const STATUS = {
  defined: ["定义", "st-slate"],
  measuring: ["度量中", "st-blue"],
  exceeded: ["超阈值", "st-red"],
  corrected: ["已纠正", "st-teal"],
  closed: ["已关闭", "st-green"],
};
const ALERT_STATUS = { open: ["未了结", "st-red"], handled: ["已了结", "st-green"] };

export default function pageTechnicalMeasure() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    // 筛选（与后端 list 的可过滤参数一一对应）
    f_category: "", f_status: "", f_direction: "", f_req_no: "",
    // 详情 / 编辑（同一模态，mode 切换）
    modal: { open: false, loading: false, mode: "view", d: null, saving: false },
    // 新建度量
    form: { open: false, d: null, saving: false },
    // 「责任人」候选 —— 跨应用 stakeholder.list（**值仍是文本**，不落 sh_no）
    owners: [],
    // 记实测值（BR-01 的入口）
    rm: { open: false, tpm_no: "", name: "", direction: "", target_value: null,
          threshold_value: null, unit: "", saving: false,
          period: "", measured_value: "", note: "" },
    // 纠正（超阈值 → 已纠正）
    cm: { open: false, tpm_no: "", name: "", period: "", saving: false, action: "" },
    // 跨度量告警汇总（查询视图 list_alerts）
    sum: { status: "open", items: [], total: 0, loading: false },

    categories: CATEGORIES, directions: DIRECTIONS,

    categoryName(v) { const c = CATEGORIES.find((x) => x[0] === v); return c ? c[1] : (v || "—"); },
    /** 列表里类别列用**码**（TPM）+ 中文全名两行；选择器里用全名（业务名唯一来源是术语表） */
    categoryCode(v) { return v ? String(v).toUpperCase() : "—"; },
    directionName(v) { const d = DIRECTIONS.find((x) => x[0] === v); return d ? d[1] : (v || "—"); },
    /** 方向在列表里配一个箭头：↑ 越大越好 / ↓ 越小越好（扫读"这个量往哪边算好"） */
    directionArrow(v) { return v === "higher" ? "↑" : (v === "lower" ? "↓" : " "); },
    statusName(v) { return (STATUS[v] || [v, ""])[0]; },
    statusCls(v) { return (STATUS[v] || ["", "st-slate"])[1]; },
    alertStatusName(v) { return (ALERT_STATUS[v] || [v, ""])[0]; },
    alertStatusCls(v) { return (ALERT_STATUS[v] || ["", "st-slate"])[1]; },
    dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; },
    /** 判定的通过 / 未通过（子表 `passed` 是判定快照，前端只做展示） */
    passedName(v) { return Number(v) ? "在阈内" : "超阈值"; },
    passedCls(v) { return Number(v) ? "st-green" : "st-red"; },

    /* ── 本页与同组其它页的**语义差**：两条独立的锁定轴 ──
       · specFrozen：判定口径（方向 / 目标值 / 阈值）—— 「定义」态可改，**基线之后冻结**，
                     唯一解锁入口是 rebaseline（带变更请求号，BR-02）；
       · locked    ：整条度量（硬终态 `closed`）—— 一切只读，无解锁入口。
       别的页只有一个 frozen()；本页若照抄，"定义态改不了目标值"与"已关闭还能改"会同时错。 */
    specFrozen(d) { return !!d && d.status !== "defined"; },
    locked(d) { return !!d && d.status === "closed"; },
    /** BR-06：没有未了结告警的度量才谈得上关闭 */
    canClose(d) {
      return !!d && (d.status === "measuring" || d.status === "corrected")
        && !Number(d.alert_open || 0);
    },
    /* ⚠ 模态里读 `modal.d` 一律走下面这层**空安全**helper，模板里不写裸 `modal.d.status`：
       `x-if="modal.d"` 的子绑定**可能**在 openDetail 把 `modal.d` 置 null 的那一拍被再求值一次
       （Alpine 的销毁与子效果执行顺序不保证）—— 同组 review 页实测抛 4 条
       "Cannot read properties of null (reading 'status')"。 */
    isStatus(d, s) { return !!d && d.status === s; },
    inStatus(d, list) { return !!d && list.indexOf(d.status) >= 0; },
    stName(d) { return self.statusName(d && d.status); },
    stCls(d) { return self.statusCls(d && d.status); },
    specFrozenText(d) {
      return "判定口径已基线（" + ((d && d.baseline_ver) || "B1") + "）—— 目标值 / 阈值 / 优化方向"
        + "不可直接改写，须经变更请求（rebaseline + 变更请求号，BR-02）";
    },
    lockedText() { return "已关闭（终态）—— 不能再记录 / 纠正 / 修改（BR-06）"; },
    showCloseBlock(d) { return self.isStatus(d, "exceeded"); },
    closeBlockText(d) {
      return "还有 " + ((d && d.alert_open) || 0) + " 条告警未了结（超阈值未纠正）—— 先「纠正」"
        + "才能关闭度量（BR-06）";
    },
    readingsOf(d) { return (d && d.readings) || []; },
    alertsOf(d) { return (d && d.alerts) || []; },
    /** 新建 / 记实测值都要给"按当前口径会不会告警"的提示（判定权威仍在后端） */
    bandText(d) {
      if (!d) return "";
      const u = d.unit || "";
      return d.direction === "higher"
        ? "口径：" + d.target_value + u + " 为目标、阈值 " + d.threshold_value + u
          + " 为底线；实测值 < " + d.threshold_value + u + " 即触发告警（BR-01）"
        : "口径：" + d.target_value + u + " 为目标、阈值 " + d.threshold_value + u
          + " 为上限；实测值 > " + d.threshold_value + u + " 即触发告警（BR-01）";
    },

    async init() {
      // ⚠ 先把会被模板引用的响应式状态建好，再挂模板（模板一旦注入就立刻求值 `list.items`，
      //   此刻 list 还是 null 会喷 "reading 'items' of null"；见 pitfalls #37）
      const tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("technical_measure", "list", {
        category: self.f_category || undefined,
        status: self.f_status || undefined,
        direction: self.f_direction || undefined,
        req_no: self.f_req_no.trim() || undefined,
        ...q,
      }));
      self.tpl = tpl;
      await self.loadOwners();
      await self.list.load();
      await self.loadSummary();
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
    /** 主列表 + 告警汇总一起刷新（任一动作都会影响两处：如纠正会改了结状态） */
    async reload() {
      await self.list.load(self.list.page);
      await self.loadSummary();
    },

    /* ── 详情 / 编辑（同一模态）───────────────────────── */
    /** 取一条度量的详情并**规整选填字段**（统一成空串，编辑表单才不会显示 "null"）—— 唯一取数入口 */
    async fetchDetail(tpm_no) {
      const d = await svc("technical_measure", "get", { tpm_no: tpm_no });
      if (d) {
        d.unit = d.unit || "";
        d.req_no = d.req_no || "";
        d.owner = d.owner || "";
        d.change_no = d.change_no || "";
      }
      return d;
    },
    async openDetail(row, mode) {
      const m = mode || "view";
      self.modal = { open: true, loading: true, mode: m, d: null, saving: false };
      try {
        self.modal.d = await self.fetchDetail(row.tpm_no);
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },
    /** 详情模态若正开着这条度量，重取一次 —— 子表（实测值 / 告警）变了而详情不刷新会前后不一致 */
    async refreshDetail(tpm_no) {
      if (!self.modal.open || !self.modal.d || self.modal.d.tpm_no !== tpm_no) return;
      try {
        self.modal.d = await self.fetchDetail(tpm_no);
      } catch { /* api.js 已 toast */ }
    },

    async saveEdit() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        // 载荷里**没有** current_value / current_period / status / baseline_ver：
        // 它们是流转产物，只能经 record / baseline / rebaseline 写入
        const payload = {
          tpm_no: d.tpm_no, name: d.name, category: d.category,
          unit: d.unit || "", req_no: d.req_no || "", owner: d.owner || "",
        };
        // ⚠ 判定口径三件**只在未基线时**才发（已基线时后端会拒，BR-02）
        if (!self.specFrozen(d)) {
          payload.direction = d.direction;
          payload.target_value = d.target_value;
          payload.threshold_value = d.threshold_value;
        }
        await svc("technical_measure", "update", payload);
        toast("已保存");
        self.modal.open = false;
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /* ── 状态机动作（F-9：按钮按状态显隐）────────────── */

    /** 基线化：定义 → 度量中（同时冻结判定口径） */
    async baseline(row) {
      if (!confirm(`确定基线化 ${row.tpm_no}？\n\n基线后目标值 / 阈值 / 优化方向即冻结，`
        + `要改须经变更请求（rebaseline）。`)) return;
      try {
        await svc("technical_measure", "baseline", { tpm_no: row.tpm_no });
        toast("已基线化，开始度量");
        await self.refreshDetail(row.tpm_no);
        await self.reload();
      } catch { /* api.js 已 toast */ }
    },

    /** 关闭度量（BR-06：须无未了结告警；终态不可再改） */
    async closeMeasure(d) {
      if (!confirm(`确定关闭度量 ${d.tpm_no}？\n\n关闭后为终态：不能再记录 / 纠正 / 修改。`)) return;
      try {
        await svc("technical_measure", "close", { tpm_no: d.tpm_no });
        toast("度量已关闭");
        self.modal.open = false;
        await self.reload();
      } catch { /* api.js 已 toast */ }
    },

    /* ── 记实测值（唯一写实测值的入口，超阈值同事务出告警）── */
    openRecord(row) {
      self.rm = { open: true, tpm_no: row.tpm_no, name: row.name || "",
                  direction: row.direction, target_value: row.target_value,
                  threshold_value: row.threshold_value,
                  unit: row.unit || "", saving: false, period: "", measured_value: "", note: "" };
    },
    closeRecord() { self.rm.open = false; },
    /** F-2：期次与实测值必填，且实测值要能转成数字（BR-08 的前端镜像） */
    canRecord() {
      const r = self.rm;
      const v = String(r.measured_value === null || r.measured_value === undefined
        ? "" : r.measured_value).trim();
      return !!r.period.trim() && !!v && !isNaN(Number(v));
    },
    async saveRecord() {
      const r = self.rm;
      r.saving = true;
      try {
        await svc("technical_measure", "record", {
          tpm_no: r.tpm_no, period: r.period.trim(), measured_value: r.measured_value,
          note: r.note || undefined,
        });
        toast("已记录实测值");
        r.open = false;
        // 详情模态若开着，把它的子表一起刷新 —— 否则读数已进库、详情还停在旧快照
        await self.refreshDetail(r.tpm_no);
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { r.saving = false; }
    },

    /* ── 纠正（登记措施 + 了结未了结的告警）──────────── */
    openCorrect(row) {
      const open_alert = (self.alertsOf(row).find((a) => a.status === "open")) || null;
      self.cm = { open: true, tpm_no: row.tpm_no, name: row.name || "",
                  period: open_alert ? open_alert.period : "", saving: false, action: "" };
    },
    closeCorrect() { self.cm.open = false; },
    canCorrect() { return !!self.cm.action.trim(); },
    async saveCorrect() {
      const c = self.cm;
      c.saving = true;
      try {
        await svc("technical_measure", "correct", {
          tpm_no: c.tpm_no, corrective_action: c.action.trim(),
        });
        toast("已登记纠正措施，告警了结");
        c.open = false;
        await self.refreshDetail(c.tpm_no);
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { c.saving = false; }
    },

    /* ── 跨度量告警汇总（查询视图：list_alerts）─────── */
    async loadSummary() {
      self.sum.loading = true;
      try {
        const r = await svc("technical_measure", "list_alerts", {
          status: self.sum.status || undefined, page: 1, size: 20,
        });
        self.sum.items = (r && r.items) || [];
        self.sum.total = (r && r.total) || 0;
      } catch { self.sum.items = []; self.sum.total = 0; } finally { self.sum.loading = false; }
    },
    setSumStatus(s) { self.sum.status = s; return self.loadSummary(); },

    /* ── 新建度量 ──────────────────────────────────── */
    openForm() {
      self.form = { open: true, saving: false, d: {
        name: "", category: "", direction: "", target_value: "", threshold_value: "",
        unit: "", req_no: "", owner: "" } };
    },
    closeForm() { self.form.open = false; },
    /** F-1：名称 / 类别 / 方向 / 目标值 / 阈值五项齐备才可提交（类别与方向不给默认值） */
    canSubmit() {
      const d = self.form.d;
      if (!d) return false;
      const t = String(d.target_value === null || d.target_value === undefined
        ? "" : d.target_value).trim();
      const h = String(d.threshold_value === null || d.threshold_value === undefined
        ? "" : d.threshold_value).trim();
      return !!(d.name.trim() && d.category && d.direction && t && h
                && !isNaN(Number(t)) && !isNaN(Number(h)));
    },
    async saveForm() {
      const d = self.form.d;
      self.form.saving = true;
      try {
        await svc("technical_measure", "create", {
          name: d.name.trim(), category: d.category, direction: d.direction,
          target_value: d.target_value, threshold_value: d.threshold_value,
          unit: d.unit || undefined, req_no: d.req_no || undefined, owner: d.owner || undefined,
        });
        toast("已新建度量（定义态）");
        self.form.open = false;
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.form.saving = false; }
    },
  });
  return self;
}
