/* 进度活动台账 · IMS 里的一个离散可度量工作单元（活动 / 里程碑）。
   日期是**派生量**（由工期与逻辑链正推），所以有两个视图：台账 + 排程。
   依据：NASA/SP-2010-3403《Schedule Management Handbook》Rev 1（§5.5.5 命名 / §5.5.8 逻辑链 /
   §5.5.9 工期 / §7.3 基线与变更控制） */
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

export default function pageActivity() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    view: "list",                       // list | schedule
    // 筛选（与后端 list 的可过滤参数一一对应）
    f_status: "", f_kind: "", f_wbs: "", f_keyword: "",
    // 派生排程 / 网络体检（都是服务现算，不落库）
    schedule: null, check: null,
    // 详情 / 编辑
    modal: { open: false, d: null, mode: "view", busy: false },
    // 新建（活动 / 里程碑同一表单，kind 选）
    form: { open: false, saving: false, name: "", kind: "activity", wbs_no: "",
            duration_days: 1, predecessors: "", owner: "", phase: "", note: "" },
    // 连前置
    lm: { open: false, d: null, predecessor_no: "", saving: false },
    // 发起修订
    fm: { open: false, d: null, change_no: "", note: "", saving: false },
    // 回填实绩
    pm: { open: false, d: null, percent_complete: 0, actual_start: "", actual_finish: "",
          note: "", saving: false },
    // 候选集 —— 跨应用只读（**值仍是文本**）：叶子元素 ← wbs、变更号 ← change_request、责任方 ← stakeholder
    leaves: [], crs: [], owners: [],

    kinds: KINDS,
    kindName(v) { const k = KINDS.find((x) => x[0] === v); return k ? k[1] : (v || "—"); },
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
    /* ⚠ 模态里读 `modal.d` 一律走空安全 helper，模板里不写裸 `modal.d.status` */
    isStatus(d, s) { return !!d && d.status === s; },
    inStatus(d, list) { return !!d && list.indexOf(d.status) >= 0; },
    ro(d) { return self.modal.mode === "view"; },
    /** 已基线的活动改计划字段要走变更流程（BR-07 的前端镜像：这里只提示，判据在后端） */
    lockedPlan(d) { return self.baselined(d); },
    /** 排程视图里的派生列 */
    schOf(act_no) {
      const it = ((self.schedule && self.schedule.items) || []).find((x) => x.act_no === act_no);
      return it || {};
    },
    critCls(act_no) { return self.schOf(act_no).critical ? "st-amber" : "st-slate"; },
    critText(act_no) { return self.schOf(act_no).critical ? "关键路径" : "—"; },

    async init() {
      // ⚠ 先把会被模板引用的响应式状态建好，再挂模板（模板注入即求值 `list.items`）
      const tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("activity", "list", {
        status: self.f_status || undefined,
        kind: self.f_kind || undefined,
        wbs_no: self.f_wbs || undefined,
        keyword: self.f_keyword || undefined,
        ...q,
      }));
      self.tpl = tpl;
      await Promise.all([self.loadLeaves(), self.loadCrs(), self.loadOwners()]);
      await self.list.load();
    },

    /** 叶子元素候选（`wbs`）：只做候选、值仍是文本 `wbs_no`。失败静默兜底。 */
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

    search() { self.list.load(1); },
    async reload() {
      await self.list.load(self.list.page);
      if (self.view === "schedule") await self.loadSchedule();
    },
    async switchView(v) {
      self.view = v;
      if (v === "schedule") await self.loadSchedule();
    },
    /** 排程视图：**派生**（正推日期 + 浮时 + 关键路径），不落库 */
    async loadSchedule() {
      try {
        self.schedule = await svc("activity", "schedule_view", {}, { quiet: true });
      } catch (e) { self.schedule = null; toast(String(e.message || e)); }
    },
    /** 网络体检：开口端 / 冗余 / 环 / 工期 / 非叶子挂靠 */
    async runCheck() {
      try {
        self.check = await svc("activity", "check_network", {}, { quiet: true });
      } catch (e) { toast(String(e.message || e)); }
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
    canEdit(d) { return !!d && !self.baselined(d); },
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

    /* ── 连前置 ───────────────────────────────────────── */
    openLink(d) { self.lm = { open: true, d, predecessor_no: "", saving: false }; },
    async submitLink() {
      const f = self.lm;
      if (f.saving) return;
      if (!f.predecessor_no) { toast("请选择一个前置活动"); return; }
      f.saving = true;
      try {
        await svc("activity", "link", { act_no: f.d.act_no,
                                        predecessor_no: f.predecessor_no });
        toast(`已给 ${f.d.act_no} 连上前置 ${f.predecessor_no}`);
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
          act_nos: [d.act_no], project_start: (self.schedule && self.schedule.project_start) || undefined });
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
