/* 进度活动台账 · IMS 里的一个离散可度量工作单元（活动 / 里程碑）。
   三种视图：台账 / 排程（派生表）/ 甘特（派生条图）—— 日期都是**派生量**，不落库。
   依据：NASA/SP-2010-3403《Schedule Management Handbook》Rev 1
   （§5.5.5 命名 / §5.5.8.2 四种关系模型与滞后 / §5.5.9 工期与日历 / §7.3 基线与变更控制） */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "activity", name: "进度活动", ic: "📅",
  title: "进度活动台账", crumb: "活动 · 逻辑链 · 基线 · 实绩",
  order: 730,
};

const KINDS = [
  ["summary", "汇总"],
  ["activity", "活动"],
  ["milestone", "里程碑"],
];
const STATUS = {
  planned: ["计划", "st-slate"],
  in_progress: ["进行中", "st-amber"],
  completed: ["已完成", "st-green"],
};
/* 四种关系模型（§5.5.8.2）；非 FS 必须写理由 */
const RELS = [["FS", "完成→开始"], ["SS", "开始→开始"],
              ["FF", "完成→完成"], ["SF", "开始→完成"]];

export default function pageActivity() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    view: "list",                       // list | schedule | gantt
    f_status: "", f_kind: "", f_wbs: "", f_keyword: "",
    schedule: null, check: null,
    modal: { open: false, d: null, mode: "view", busy: false },
    form: { open: false, saving: false, name: "", kind: "activity", wbs_no: "",
            duration_days: 1, predecessors: "", owner: "", phase: "", note: "" },
    // 连前置（四种关系 + 滞后 + 理由）
    lm: { open: false, d: null, predecessor_no: "", rel_type: "FS", lag_days: 0,
          reason: "", saving: false },
    fm: { open: false, d: null, change_no: "", note: "", saving: false },
    pm: { open: false, d: null, percent_complete: 0, actual_start: "", actual_finish: "",
          note: "", saving: false },
    // 候选集 —— 跨应用只读（**值仍是文本**）
    leaves: [], crs: [], owners: [],
    // 日历（工期口径与假日表）
    cals: [], cal_no: "",

    kinds: KINDS, rels: RELS,
    kindName(v) { const k = KINDS.find((x) => x[0] === v); return k ? k[1] : (v || "—"); },
    relName(v) { const r = RELS.find((x) => x[0] === v); return r ? r[1] : (v || "—"); },
    statusName(v) { return (STATUS[v] || [v, ""])[0]; },
    statusCls(v) { return (STATUS[v] || ["", "st-slate"])[1]; },
    dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; },
    stName(d) { return self.statusName(d && d.status); },
    stCls(d) { return self.statusCls(d && d.status); },
    kindOf(d) { return self.kindName(d && d.kind); },
    baseText(d) {
      return (d && d.baseline_start) ? (d.baseline_start + " → " + d.baseline_finish) : "未基线";
    },
    baselined(d) { return !!(d && d.baseline_start); },
    isStatus(d, s) { return !!d && d.status === s; },
    inStatus(d, list) { return !!d && list.indexOf(d.status) >= 0; },
    ro(d) { return self.modal.mode === "view"; },
    canEdit(d) { return !!d && !self.baselined(d); },
    /** 逻辑链的可读写法：`ACT-001` / `ACT-002·SS+2`（带上关系与滞后） */
    relsText(d) {
      const ps = (d && d.pred_list) || [];
      if (!ps.length) return "—";
      return ps.map((x) => x.type === "FS" && !x.lag ? x.pred
        : x.pred + "·" + x.type + (x.lag ? (x.lag > 0 ? "+" : "") + x.lag : "")).join("、");
    },
    /** 排程视图里的派生列 */
    schOf(act_no) {
      return ((self.schedule && self.schedule.items) || []).find((x) => x.act_no === act_no) || {};
    },
    calText() {
      const c = self.cals.find((x) => x.cal_no === self.cal_no);
      return c ? (c.name + " · " + (c.unit === "edays" ? "日历天" : "工作日")
                  + (c.holidays ? (" · 假日 " + c.holidays.split(",").length + " 天") : "")) : "";
    },

    async init() {
      const tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("activity", "list", {
        status: self.f_status || undefined,
        kind: self.f_kind || undefined,
        wbs_no: self.f_wbs || undefined,
        keyword: self.f_keyword || undefined,
        ...q,
      }));
      self.tpl = tpl;
      await Promise.all([self.loadLeaves(), self.loadCrs(), self.loadOwners(), self.loadCals()]);
      await self.applyPreset();                    // WBS 侧跳过来带的预置（叶子 / 新建）
      await self.list.load();
    },

    /** WBS 台账跳过来的预置：`fde.activity_preset` = `{wbs_no, mode}`（mode = filter | new）。
     *
     *  ⚠ 跨页传参走 sessionStorage 而不是 hash —— 平台的 route key 取的是**整段 hash**
     *  （`location.hash.replace(/^#\//,"")`），写成 `#/activity?wbs=x` 会变成页名
     *  `activity?wbs=x` 匹配不上任何页，直接白屏。读完即清，二次进入不再弹。
     */
    async applyPreset() {
      let raw = null;
      try { raw = sessionStorage.getItem("fde.activity_preset"); } catch { raw = null; }
      if (!raw) return;
      try { sessionStorage.removeItem("fde.activity_preset"); } catch { /* 忽略 */ }
      let p = null;
      try { p = JSON.parse(raw); } catch { p = null; }
      if (!p || !p.wbs_no) return;
      if (!self.leaves.some((x) => x.wbs_no === p.wbs_no)) {
        toast(`WBS 元素 ${p.wbs_no} 不是叶子元素，活动只能挂最底层元素`);
        return;
      }
      if (p.mode === "new") { self.openForm("activity"); self.form.wbs_no = p.wbs_no; }
      else { self.f_wbs = p.wbs_no; }              // filter：挂靠元素筛选，随后的 list.load 生效
    },

    async loadLeaves() {
      try {
        const r = await svc("wbs", "list", {}, { quiet: true });
        const all = (r && r.items) || [];
        const parents = new Set(all.map((x) => x.parent_no).filter(Boolean));
        self.leaves = all.filter((x) => !parents.has(x.wbs_no));
      } catch { self.leaves = []; }
    },
    async loadCrs() {
      try {
        const r = await svc("change_request", "list", { status: "approved" }, { quiet: true });
        self.crs = (r && r.items) || [];
      } catch { self.crs = []; }
    },
    async loadOwners() {
      try {
        const r = await svc("stakeholder", "list", {}, { quiet: true });
        self.owners = (r && r.items) || [];
      } catch { self.owners = []; }
    },
    async loadCals() {
      try {
        const r = await svc("activity", "list_calendars", {}, { quiet: true });
        self.cals = (r && r.items) || [];
        const dft = self.cals.find((x) => x.is_default) || self.cals[0];
        self.cal_no = self.cal_no || (dft && dft.cal_no) || "";
      } catch { self.cals = []; }
    },

    search() { self.list.load(1); },
    async reload() {
      await self.list.load(self.list.page);
      if (self.view !== "list") await self.loadSchedule();
    },
    async switchView(v) {
      self.view = v;
      if (v !== "list") await self.loadSchedule();
    },
    async changeCal() { await self.loadSchedule(); },
    async loadSchedule() {
      try {
        self.schedule = await svc("activity", "schedule_view",
                                  { calendar_no: self.cal_no || undefined }, { quiet: true });
      } catch (e) { self.schedule = null; toast(String(e.message || e)); }
    },
    async runCheck() {
      try {
        self.check = await svc("activity", "check_network", {}, { quiet: true });
      } catch (e) { toast(String(e.message || e)); }
    },

    /** 甘特视图的行：把派生日期折算成时间轴上的百分比（x 轴 = 项目起止之间的**日历天**） */
    ganttRows() {
      const s = self.schedule;
      if (!s || !(s.items || []).length) return [];
      const base = Date.parse(s.project_start + "T00:00:00Z");
      const end = Date.parse(s.project_finish + "T00:00:00Z");
      const total = Math.max(1, Math.round((end - base) / 86400000) + 1);
      return s.items.map((x) => {
        const a = Math.round((Date.parse(x.early_start + "T00:00:00Z") - base) / 86400000);
        const b = Math.round((Date.parse(x.early_finish + "T00:00:00Z") - base) / 86400000);
        return {
          act_no: x.act_no, name: x.name, kind: x.kind, critical: x.critical,
          early_start: x.early_start, early_finish: x.early_finish, float_days: x.float_days,
          left: Math.max(0, a) / total * 100,
          width: Math.max((b - a + 1) / total * 100, x.kind === "milestone" ? 1.2 : 0.8),
          is_ms: x.kind === "milestone",
        };
      });
    },
    /** 时间轴的刻度（每周一个，标签用 MM-DD） */
    ganttTicks() {
      const s = self.schedule;
      if (!s) return [];
      const base = Date.parse(s.project_start + "T00:00:00Z");
      const end = Date.parse(s.project_finish + "T00:00:00Z");
      const total = Math.max(1, Math.round((end - base) / 86400000) + 1);
      const out = [];
      for (let d = 0; d < total; d += 7) {
        const dt = new Date(base + d * 86400000);
        out.push({ left: d / total * 100,
                   label: String(dt.getUTCMonth() + 1).padStart(2, "0") + "-" +
                          String(dt.getUTCDate()).padStart(2, "0") });
      }
      return out;
    },

    /* ── 详情 / 编辑 ──────────────────────────────────── */
    async openDetail(row, mode) {
      self.modal.open = true;
      self.modal.mode = mode || "view";
      self.modal.d = row;
      try {
        const d = await svc("activity", "get", { act_no: row.act_no });
        if (d) self.modal.d = d;
      } catch (e) { toast(String(e.message || e)); }
    },
    closeModal() { self.modal.open = false; self.modal.d = null; },
    async saveEdit() {
      const d = self.modal.d;
      if (!d || self.modal.busy) return;
      self.modal.busy = true;
      try {
        const r = await svc("activity", "update", {
          act_no: d.act_no, name: d.name || undefined,
          duration_days: d.duration_days === null ? undefined : Number(d.duration_days),
          owner: d.owner || undefined, note: d.note || undefined,
        });
        toast(`已保存 ${r.act_no}`);
        self.modal.mode = "view";
        self.modal.d = r;
        await self.reload();
      } catch (e) { toast(String(e.message || e)); }
      finally { self.modal.busy = false; }
    },

    /* ── 新建（活动 / 里程碑）──────────────────────────── */
    openForm(kind) {
      self.form = { open: true, saving: false, name: "", kind: kind || "activity",
                    wbs_no: (self.leaves[0] && self.leaves[0].wbs_no) || "",
                    duration_days: (kind === "milestone" ? 0 : 5),
                    predecessors: "", owner: (self.owners[0] && self.owners[0].name) || "",
                    phase: "", note: "" };
    },
    async submitForm() {
      const f = self.form;
      if (f.saving) return;
      if (!f.name.trim()) { toast("活动名称不能为空"); return; }
      if (!f.wbs_no) { toast("请先选择要挂靠的 WBS 叶子元素"); return; }
      f.saving = true;
      try {
        const r = await svc("activity", "create", {
          name: f.name.trim(), wbs_no: f.wbs_no, kind: f.kind,
          duration_days: Number(f.duration_days || 0),
          predecessors: f.predecessors || undefined,
          owner: f.owner || undefined, phase: f.phase || undefined,
          note: f.note || undefined,
        });
        toast(`已建立 ${r.act_no}（${self.kindName(r.kind)}）`);
        f.open = false;
        await self.reload();
      } catch (e) { toast(String(e.message || e)); }
      finally { f.saving = false; }
    },

    /* ── 连前置（四种关系 + 滞后 + 理由）───────────────── */
    openLink(d) {
      self.lm = { open: true, d, predecessor_no: "", rel_type: "FS", lag_days: 0,
                  reason: "", saving: false };
    },
    async submitLink() {
      const f = self.lm;
      if (f.saving) return;
      if (!f.predecessor_no) { toast("请选择一个前置活动"); return; }
      if (f.rel_type !== "FS" && !String(f.reason || "").trim()) {
        toast(`非标准关系（${f.rel_type} ${self.relName(f.rel_type)}）必须写明理由（材料 §5.5.8.2）`);
        return;
      }
      f.saving = true;
      try {
        await svc("activity", "link", { act_no: f.d.act_no, predecessor_no: f.predecessor_no,
                                        rel_type: f.rel_type, lag_days: Number(f.lag_days || 0),
                                        reason: f.reason || undefined });
        toast(`已给 ${f.d.act_no} 连上前置 ${f.predecessor_no}（${f.rel_type}`
              + (Number(f.lag_days) ? (" 滞后 " + f.lag_days + " 天") : "") + "）");
        f.open = false;
        await self.reload();
      } catch (e) { toast(String(e.message || e)); }
      finally { f.saving = false; }
    },

    /* ── 基线 / 修订 / 实绩 ───────────────────────────── */
    async baseline(d) {
      self.modal.busy = true;
      try {
        const r = await svc("activity", "baseline", {
          act_nos: [d.act_no],
          project_start: (self.schedule && self.schedule.project_start) || undefined,
          calendar_no: self.cal_no || undefined });
        toast(`已基线：${r.items[0].baseline_start} → ${r.items[0].baseline_finish}`);
        self.modal.d = r.items[0];
        await self.reload();
      } catch (e) { toast(String(e.message || e)); }
      finally { self.modal.busy = false; }
    },
    openChange(d) {
      self.fm = { open: true, d, change_no: (self.crs[0] && self.crs[0].cr_no) || "",
                  note: "", saving: false };
    },
    async submitChange() {
      const f = self.fm;
      if (f.saving) return;
      if (!f.change_no) { toast("请选择一个已批准的变更请求"); return; }
      f.saving = true;
      try {
        const r = await svc("activity", "change", { act_no: f.d.act_no,
                                                    change_no: f.change_no,
                                                    note: f.note || undefined });
        toast(`已挂上变更 ${f.change_no}，现在可以改计划字段了`);
        f.open = false;
        self.modal.d = r;
        await self.reload();
      } catch (e) { toast(String(e.message || e)); }
      finally { f.saving = false; }
    },
    openProgress(d) {
      self.pm = { open: true, d, percent_complete: (d && d.percent_complete) || 0,
                  actual_start: (d && d.actual_start) || "",
                  actual_finish: (d && d.actual_finish) || "", note: "", saving: false };
    },
    async submitProgress() {
      const f = self.pm;
      if (f.saving) return;
      f.saving = true;
      try {
        const r = await svc("activity", "record_progress", {
          act_no: f.d.act_no, percent_complete: Number(f.percent_complete || 0),
          actual_start: f.actual_start || undefined,
          actual_finish: f.actual_finish || undefined, note: f.note || undefined,
        });
        toast(`实绩已回填：${r.percent_complete}%（基线不动）`);
        f.open = false;
        self.modal.d = r;
        await self.reload();
      } catch (e) { toast(String(e.message || e)); }
      finally { f.saving = false; }
    },
  });
  return self;
}
