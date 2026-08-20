/* app/forecast/part_level_adj/view.js —— 零件级处理 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "part_level_adj", name: "零件级处理", ic: "🔧",
  title: "零件级处理", crumb: "通用件合并 · 替换件合并 · 断点处理",
  order: 50,
};

export default function pagePartLevelAdj() {
  const self = Alpine.reactive({
    tpl: "", hue, fmt,
    list: null,
    filterFcstVersion: "", filterFuncType: "", filterPart: "",
    versionOptions: [],

    /* Create forms (three types) */
    createModal: { open: false, mode: "", fcst_version: "", period: "",
      part_no: "", adj_qty: 0, basis: "",
      old_part: "", new_part: "", old_adj: 0, new_adj: 0, ecn_no: "" },
    /* Detail modal */
    modal: { open: false, loading: false, d: null },
    /* Summarize modal */
    summaryModal: { open: false, fcst_version: "", rows: [], loading: false },

    async init() {
      self.list = pageable(async (q) => svc("part_level_adj", "list", {
        fcst_version: self.filterFcstVersion || undefined,
        func_type: self.filterFuncType || undefined,
        part_no: self.filterPart || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      svc("md_fcst_version", "list", { page: 1, page_size: 50 }, { quiet: true })
        .then(r => { self.versionOptions = r.items || []; }).catch(() => {});
      await self.list.load();
    },

    search() { self.list.load(1); },

    /* Show create form */
    showCreate(mode) {
      self.createModal = { open: true, mode: mode,
        fcst_version: self.filterFcstVersion || "", period: "",
        part_no: "", adj_qty: 0, basis: "",
        old_part: "", new_part: "", old_adj: 0, new_adj: 0, ecn_no: "" };
    },
    async doCreate() {
      const f = self.createModal;
      if (!f.fcst_version) { toast("版本号必填", "warn"); return; }
      if (!f.period) { toast("期间必填", "warn"); return; }

      if (f.mode === "breakpoint") {
        if (!f.old_part || !f.new_part) { toast("旧件和新件零件号均必填", "warn"); return; }
        if (!f.ecn_no) { toast("ECN号必填（断点依据）", "warn"); return; }
        try {
          const r = await svc("part_level_adj", "create_breakpoint_adj", {
            fcst_version: f.fcst_version, period: f.period,
            old_part: f.old_part, new_part: f.new_part,
            old_adj: f.old_adj, new_adj: f.new_adj, ecn_no: f.ecn_no,
          });
          toast(`断点成对创建 · pair_no: ${r.pair_no}`);
          self.createModal.open = false;
          await self.list.load(1);
        } catch { /* api.js */ }
      } else {
        if (!f.part_no) { toast("零件号必填", "warn"); return; }
        if (!f.basis) { toast("原因/依据必填", "warn"); return; }
        const svcName = f.mode === "generic" ? "create_generic_merge" : "create_replace_merge";
        try {
          const r = await svc("part_level_adj", svcName, {
            fcst_version: f.fcst_version, period: f.period,
            part_no: f.part_no, adj_qty: f.adj_qty, basis: f.basis,
          });
          toast(`已创建 · ${r.adj_no}`);
          self.createModal.open = false;
          await self.list.load(1);
        } catch { /* api.js */ }
      }
    },

    /* Detail */
    async view(d) {
      self.modal = { open: true, loading: true, d: null };
      try {
        self.modal.d = await svc("part_level_adj", "get", { adj_no: d.adj_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    /* Summarize */
    showSummary() {
      self.summaryModal = { open: true, fcst_version: self.filterFcstVersion || "", rows: [], loading: false };
    },
    async doSummarize() {
      if (!self.summaryModal.fcst_version) { toast("版本号必填", "warn"); return; }
      self.summaryModal.loading = true;
      try {
        const r = await svc("part_level_adj", "summarize", { fcst_version: self.summaryModal.fcst_version });
        self.summaryModal.rows = r;
      } catch { /* api.js */ } finally { self.summaryModal.loading = false; }
    },
  });
  return self;
}
