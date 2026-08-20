/* app/forecast/demand_release/view.js —— 毛需求发布 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "demand_release", name: "毛需求发布", ic: "📦",
  title: "毛需求发布", crumb: "加工链终点 · 净需求唯一输入 · 物料级",
  order: 60,
};

export default function pageDemandRelease() {
  const self = Alpine.reactive({
    tpl: "", hue, fmt,
    list: null,
    filterFcstVersion: "", filterStatus: "", filterPart: "", filterPeriod: "",
    versionOptions: [],

    /* Create draft modal */
    createModal: { open: false, prc_batch: "" },
    /* Detail modal */
    modal: { open: false, loading: false, d: null },
    /* Apply part_adj modal */
    adjModal: { open: false, part_no: "", period: "", adj_qty: 0, func_type: "通用件合并", basis: "" },
    /* Publish confirm */
    publishConfirm: { open: false },
    /* Diff view modal */
    diffModal: { open: false, loading: false, data: null },
    /* Add onetime (post-publish) */
    onetimeModal: { open: false, part_no: "", period: "", onetime_adj: 0, reason: "" },

    async init() {
      self.list = pageable(async (q) => svc("demand_release", "list", {
        fcst_version: self.filterFcstVersion || undefined,
        status: self.filterStatus || undefined,
        part_no: self.filterPart || undefined,
        period: self.filterPeriod || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      svc("md_fcst_version", "list", { page: 1, page_size: 50 }, { quiet: true })
        .then(r => { self.versionOptions = r.items || []; }).catch(() => {});
      await self.list.load();
    },

    search() { self.list.load(1); },

    /* Create draft */
    showCreate() { self.createModal = { open: true, prc_batch: "" }; },
    async doCreateDraft() {
      if (!self.createModal.prc_batch) { toast("加工批次必填", "warn"); return; }
      try {
        const r = await svc("demand_release", "create_draft", { prc_batch: self.createModal.prc_batch });
        toast(`发布草稿已创建：${r.rel_no}（${r.line_count} 行）`);
        self.createModal.open = false;
        await self.list.load(1);
      } catch { /* api.js */ }
    },

    /* Detail */
    async view(d) {
      self.modal = { open: true, loading: true, d: null };
      try {
        self.modal.d = await svc("demand_release", "get", { rel_no: d.rel_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    /* Apply part_adj */
    showAdj() {
      self.adjModal = { open: true, part_no: "", period: "", adj_qty: 0, func_type: "通用件合并", basis: "" };
    },
    async doApplyAdj() {
      const f = self.adjModal;
      if (!f.part_no || !f.period) { toast("零件号和期间均必填", "warn"); return; }
      if (!f.basis) { toast("依据必填", "warn"); return; }
      try {
        const r = await svc("demand_release", "apply_part_adj", {
          rel_no: self.modal.d.rel_no, part_no: f.part_no, period: f.period,
          adj_qty: f.adj_qty, func_type: f.func_type, basis: f.basis,
        });
        toast(`已应用 · rel_qty: ${r.rel_qty}`);
        self.adjModal.open = false;
        // Refresh detail
        self.modal.d = await svc("demand_release", "get", { rel_no: self.modal.d.rel_no });
      } catch { /* api.js */ }
    },

    /* Publish */
    showPublish() { self.publishConfirm = { open: true }; },
    async doPublish() {
      if (!confirm("发布后将联动锁定快照版本与月度版本，同时标记上一版本为「已替代」。确认发布？")) return;
      try {
        const r = await svc("demand_release", "publish", { rel_no: self.modal.d.rel_no });
        toast(`已发布 · ${r.rel_no}`);
        self.publishConfirm.open = false;
        self.modal.d = r;
        await self.list.load();
      } catch { /* api.js */ }
    },

    /* Diff view */
    async showDiff(d) {
      self.diffModal = { open: true, loading: true, data: null };
      try {
        self.diffModal.data = await svc("demand_release", "get_diff", { rel_no: d.rel_no });
      } catch { self.diffModal.open = false; } finally { self.diffModal.loading = false; }
    },
    closeDiff() { self.diffModal.open = false; },

    /* Add onetime item (post-publish) */
    showOnetime() {
      self.onetimeModal = { open: true, part_no: "", period: "", onetime_adj: 0, reason: "" };
    },
    async doAddOnetime() {
      const f = self.onetimeModal;
      if (!f.part_no || !f.period || !f.reason) { toast("零件号、期间、原因均必填", "warn"); return; }
      try {
        const r = await svc("demand_release", "add_onetime_item", {
          rel_no: self.modal.d.rel_no, part_no: f.part_no, period: f.period,
          onetime_adj: f.onetime_adj, reason: f.reason,
        });
        toast(`月中一次性已附加 · rel_qty: ${r.rel_qty}`);
        self.onetimeModal.open = false;
        self.modal.d = await svc("demand_release", "get", { rel_no: self.modal.d.rel_no });
      } catch { /* api.js */ }
    },

    /* Helpers */
    adjQtyClass(v) {
      return v > 0 ? 'color:var(--green)' : v < 0 ? 'color:var(--red)' : '';
    },
  });
  return self;
}
