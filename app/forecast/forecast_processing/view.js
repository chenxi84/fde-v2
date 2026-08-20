/* app/forecast/forecast_processing/view.js —— 预测加工 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "forecast_processing", name: "预测加工", ic: "⚙",
  title: "预测加工", crumb: "基线→调整→独立需求 · 计划与销售制衡",
  order: 40,
};

export default function pageFcstProcessing() {
  const self = Alpine.reactive({
    tpl: "", hue, fmt,
    /* Batch list */
    listBatches: null,
    filterFcstVersion: "", filterBatchStatus: "",
    versionOptions: [],
    /* Line list (switched on click) */
    viewMode: "batches",
    currentBatch: null,
    listLines: null,
    filterLineOem: "", filterLinePart: "", filterLineChk: "",
    custOptions: [],

    /* Create batch modal */
    createModal: { open: false, base_batch: "", fcst_version: "" },
    /* Detail/line modal */
    modal: { open: false, loading: false, d: null },
    /* Fill adjustment form in modal */
    fillForm: { open: false, conf_adj: 0, conf_reason: "", trend_adj: 0, trend_reason: "",
      onetime_adj: 0, onetime_reason: "", onetime_tag: "一次性", editing: false },
    /* Review modal */
    reviewModal: { open: false, chk_result: "通过", chk_comment: "", d: null },
    /* Add onetime modal */
    onetimeModal: { open: false, oem_code: "", plant_code: "", part_no: "", period: "",
      onetime_adj: 0, onetime_reason: "", onetime_tag: "一次性" },

    async init() {
      self.listBatches = pageable(async (q) => svc("forecast_processing", "list_batches", {
        fcst_version: self.filterFcstVersion || undefined,
        status: self.filterBatchStatus || undefined,
        ...q,
      }));
      self.listLines = pageable(async (q) => svc("forecast_processing", "list_lines", {
        prc_batch: self.currentBatch ? self.currentBatch.prc_batch : "",
        oem_code: self.filterLineOem || undefined,
        part_no: self.filterLinePart || undefined,
        chk_result: self.filterLineChk || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      svc("md_fcst_version", "list", { page: 1, page_size: 50 }, { quiet: true })
        .then(r => { self.versionOptions = r.items || []; }).catch(() => {});
      svc("md_customer", "list", { page: 1, page_size: 200 }, { quiet: true })
        .then(r => { self.custOptions = r.items || []; }).catch(() => {});
      await self.listBatches.load();
    },

    /* Computed indep_qty preview */
    get previewIndep() {
      const d = self.modal.d;
      if (!d) return 0;
      return (d.base_qty || 0) + (Number(self.fillForm.conf_adj) || 0)
        + (Number(self.fillForm.trend_adj) || 0) + (Number(self.fillForm.onetime_adj) || 0);
    },

    searchBatches() { self.listBatches.load(1); },

    /* Switch to batch detail view */
    async viewBatch(d) {
      self.viewMode = "lines";
      self.currentBatch = d;
      self.filterLineOem = ""; self.filterLinePart = ""; self.filterLineChk = "";
      await self.listLines.load(1);
    },
    backToBatches() { self.viewMode = "batches"; self.currentBatch = null; },

    searchLines() { self.listLines.load(1); },

    /* Create batch */
    showCreate() { self.createModal = { open: true, base_batch: "", fcst_version: "" }; },
    async doCreateBatch() {
      if (!self.createModal.base_batch) { toast("基线批次必填", "warn"); return; }
      if (!self.createModal.fcst_version) { toast("预测版本必填", "warn"); return; }
      try {
        const r = await svc("forecast_processing", "create_batch", {
          base_batch: self.createModal.base_batch,
          fcst_version: self.createModal.fcst_version,
        });
        toast(`加工批次已创建：${r.prc_batch}（${r.line_count} 行）`);
        self.createModal.open = false;
        await self.listBatches.load(1);
      } catch { /* api.js */ }
    },

    /* View line detail (get batch info + open fill form) */
    async viewLine(d) {
      self.modal = { open: true, loading: true, d: null };
      try {
        self.modal.d = await svc("forecast_processing", "get_line", {
          prc_batch: self.currentBatch.prc_batch,
          oem_code: d.oem_code, plant_code: d.plant_code,
          part_no: d.part_no, period: d.period,
        });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; self.fillForm.open = false; },

    /* Fill adjustment form in modal */
    showFill() {
      const d = self.modal.d;
      self.fillForm = {
        open: true,
        conf_adj: d.conf_adj || 0, conf_reason: d.conf_reason || "",
        trend_adj: d.trend_adj || 0, trend_reason: d.trend_reason || "",
        onetime_adj: d.onetime_adj || 0, onetime_reason: d.onetime_reason || "",
        onetime_tag: d.onetime_tag || "一次性",
      };
    },
    async doFill() {
      const d = self.modal.d;
      const f = self.fillForm;
      if (f.conf_adj && !f.conf_reason) { toast("置信度调整不为0时原因必填", "warn"); return; }
      if (f.trend_adj && !f.trend_reason) { toast("趋势调整不为0时原因必填", "warn"); return; }
      if (f.onetime_adj && !f.onetime_reason) { toast("一次性调整不为0时原因必填", "warn"); return; }
      try {
        const r = await svc("forecast_processing", "fill_line", {
          prc_batch: d.prc_batch, oem_code: d.oem_code, plant_code: d.plant_code,
          part_no: d.part_no, period: d.period,
          conf_adj: f.conf_adj, conf_reason: f.conf_reason || undefined,
          trend_adj: f.trend_adj, trend_reason: f.trend_reason || undefined,
          onetime_adj: f.onetime_adj, onetime_reason: f.onetime_reason || undefined,
          onetime_tag: f.onetime_tag,
        });
        toast(`已录入 · ${r.part_no} / ${r.period} · indep=${r.indep_qty}`);
        self.modal.d = r;
        self.fillForm.open = false;
        await self.listLines.load();
      } catch { /* api.js */ }
    },

    /* Review */
    showReview(d) {
      self.reviewModal = { open: true, chk_result: "通过", chk_comment: "", d: d };
    },
    async doReview() {
      const d = self.reviewModal.d;
      if (self.reviewModal.chk_result === "退回" && !self.reviewModal.chk_comment) {
        toast("退回必须附理由", "warn"); return;
      }
      try {
        const r = await svc("forecast_processing", "review_line", {
          prc_batch: d.prc_batch, oem_code: d.oem_code, plant_code: d.plant_code,
          part_no: d.part_no, period: d.period,
          chk_result: self.reviewModal.chk_result,
          chk_comment: self.reviewModal.chk_comment || undefined,
        });
        toast(`核定完成 · ${r.chk_result}`);
        self.reviewModal.open = false;
        await self.listLines.load();
      } catch { /* api.js */ }
    },

    /* Finalize */
    async doFinalize() {
      const d = self.currentBatch;
      if (!confirm(`锁定加工批次 ${d.prc_batch}？全部行须通过核定。`)) return;
      try {
        const r = await svc("forecast_processing", "finalize", { prc_batch: d.prc_batch });
        toast(`已锁定 · ${r.prc_batch}`);
        self.currentBatch = { ...self.currentBatch, status: "已锁定" };
        await self.listBatches.load(1);
      } catch { /* api.js */ }
    },

    /* Add onetime line */
    showOnetime() {
      self.onetimeModal = { open: true, oem_code: "", plant_code: "", part_no: "",
        period: "", onetime_adj: 0, onetime_reason: "", onetime_tag: "一次性" };
    },
    async doAddOnetime() {
      const f = self.onetimeModal;
      if (!f.oem_code || !f.plant_code || !f.part_no || !f.period) {
        toast("客户、工厂、零件号、期间均必填", "warn"); return;
      }
      if (!f.onetime_reason) { toast("一次性调整原因必填", "warn"); return; }
      try {
        const r = await svc("forecast_processing", "add_onetime_line", {
          prc_batch: self.currentBatch.prc_batch,
          oem_code: f.oem_code, plant_code: f.plant_code, part_no: f.part_no, period: f.period,
          onetime_adj: f.onetime_adj, onetime_reason: f.onetime_reason,
          onetime_tag: f.onetime_tag,
        });
        toast(`一次性行已附加 · ${r.part_no} / ${r.period}`);
        self.onetimeModal.open = false;
        await self.listLines.load();
      } catch { /* api.js */ }
    },
  });
  return self;
}
