/* app/forecast/forecast_baseline/view.js —— 统计基线 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "forecast_baseline", name: "统计基线", ic: "\u{1F4C8}",
  title: "统计基线", crumb: "客观统计锚 · 系统预计算+计划确认",
  order: 30,
};

export default function pageFcstBaseline() {
  const self = Alpine.reactive({
    tpl: "", hue, fmt,
    list: null,
    filterBaseBatch: "", filterOem: "", filterPart: "", filterStatus: "", filterPath: "",
    batchOptions: [], custOptions: [],

    /* Generate modal */
    genModal: { open: false, base_batch: "", fcst_version: "" },
    /* Detail modal */
    modal: { open: false, loading: false, d: null },
    /* Update method modal */
    methodModal: { open: false, base_method: "", d: null },
    /* Confirm batch confirm */
    confirmBatchModal: { open: false, base_batch: "" },

    async init() {
      self.list = pageable(async (q) => svc("forecast_baseline", "list", {
        base_batch: self.filterBaseBatch || undefined,
        oem_code: self.filterOem || undefined,
        part_no: self.filterPart || undefined,
        status: self.filterStatus || undefined,
        base_path: self.filterPath || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      svc("md_customer", "list", { page: 1, page_size: 200 }, { quiet: true })
        .then(r => { self.custOptions = r.items || []; }).catch(() => {});
      await self.list.load();
      self._loadBatchOptions();
    },

    async _loadBatchOptions() {
      try {
        const r = await svc("forecast_baseline", "list", { page_size: 1000 }, { quiet: true });
        const seen = new Set();
        self.batchOptions = [];
        for (const it of (r.items || [])) {
          if (!seen.has(it.base_batch)) {
            seen.add(it.base_batch);
            self.batchOptions.push(it.base_batch);
          }
        }
      } catch { /* quiet */ }
    },

    search() { self.list.load(1); },

    /* Generate */
    showGen() { self.genModal = { open: true, base_batch: "", fcst_version: "" }; },
    async doGenerate() {
      if (!self.genModal.base_batch) { toast("基线批次必填", "warn"); return; }
      if (!self.genModal.fcst_version) { toast("预测版本必填", "warn"); return; }
      try {
        const r = await svc("forecast_baseline", "generate", {
          base_batch: self.genModal.base_batch,
          fcst_version: self.genModal.fcst_version,
        });
        toast(`生成基线完成：${r.created} 行`);
        self.genModal.open = false;
        self.filterBaseBatch = self.genModal.base_batch;
        await self._loadBatchOptions();
        await self.list.load(1);
      } catch { /* api.js */ }
    },

    /* Confirm single row */
    async confirmRow(d) {
      if (!confirm(`确认基线行：${d.part_no} / ${d.period}？`)) return;
      try {
        await svc("forecast_baseline", "confirm", {
          base_batch: d.base_batch, oem_code: d.oem_code, plant_code: d.plant_code,
          part_no: d.part_no, period: d.period,
        });
        toast("已确认");
        await self.list.load();
      } catch { /* api.js */ }
    },

    /* Confirm batch */
    showConfirmBatch(d) {
      self.confirmBatchModal = { open: true, base_batch: d.base_batch };
    },
    async doConfirmBatch() {
      if (!confirm(`确认整批 ${self.confirmBatchModal.base_batch} 的全部预计算行？`)) return;
      try {
        const r = await svc("forecast_baseline", "confirm_batch", {
          base_batch: self.confirmBatchModal.base_batch,
        });
        toast(`整批确认完成：${r.confirmed} 行`);
        self.confirmBatchModal.open = false;
        await self.list.load();
      } catch { /* api.js */ }
    },

    /* Update method */
    showMethod(d) {
      self.methodModal = { open: true, base_method: d.base_method || "", d: d };
    },
    async doUpdateMethod() {
      const d = self.methodModal.d;
      if (!self.methodModal.base_method) { toast("方法/参数描述必填（变更须登记依据）", "warn"); return; }
      try {
        await svc("forecast_baseline", "update_method", {
          base_batch: d.base_batch, oem_code: d.oem_code, plant_code: d.plant_code,
          part_no: d.part_no, period: d.period,
          base_method: self.methodModal.base_method,
        });
        toast("方法已更新");
        self.methodModal.open = false;
        await self.list.load();
      } catch { /* api.js */ }
    },

    /* Detail */
    async view(d) {
      self.modal = { open: true, loading: true, d: null };
      try {
        self.modal.d = await svc("forecast_baseline", "get", {
          base_batch: d.base_batch, oem_code: d.oem_code, plant_code: d.plant_code,
          part_no: d.part_no, period: d.period,
        });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },
  });
  return self;
}
