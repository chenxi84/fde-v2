/* app/forecast/attainment/view.js —— 达成率与置信度 */
import { svc, hue, dash, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "attainment", name: "达成率置信度", ic: "\u{1F3AF}",
  title: "达成率与置信度", crumb: "月度闭环自动生成 · 分horizon",
  order: 170,
};

export default function pageAttainment() {
  const self = Alpine.reactive({
    tpl: "", hue, dash, fmt,
    list: null,
    filterOem: "", filterPeriod: "", filterHorizon: "",
    modal: { open: false, loading: false, d: null, rows: [] },
    computeForm: { open: false, fcst_version: "", busy: false },
    custMap: {},

    async init() {
      self.list = pageable(async (q) => svc("attainment", "list", {
        oem_code: self.filterOem || undefined,
        period: self.filterPeriod || undefined,
        horizon: self.filterHorizon || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
      svc("md_customer", "list", { page: 1, page_size: 200 }, { quiet: true }).then(r => {
        if (r && r.items) {
          const map = {};
          r.items.forEach(c => { map[c.oem_code] = c; });
          self.custMap = map;
        }
      }).catch(() => {});
    },

    search() { self.list.load(1); },

    custName(oemCode) {
      const c = self.custMap[oemCode];
      return c ? c.oem_name : "";
    },

    showCompute() {
      self.computeForm = { open: true, fcst_version: "", busy: false };
    },

    async doCompute() {
      const f = self.computeForm;
      if (!f.fcst_version) { toast("请填写版本号"); return; }
      f.busy = true;
      try {
        const r = await svc("attainment", "compute_batch", { fcst_version: f.fcst_version });
        toast(`批量计算完成，共处理 ${r.computed || 0} 条记录，覆盖 ${r.oem_count || 0} 个客户`);
        f.open = false;
        await self.list.load(1);
      } catch (e) { /* api.js */ } finally { f.busy = false; }
    },

    async view(d) {
      self.modal = { open: true, loading: true, d: d, rows: [] };
      try {
        self.modal.rows = await svc("attainment", "get", { oem_code: d.oem_code, period: d.period });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    isLowRate(d) {
      return d.attain_rate != null && d.attain_rate > 0 && d.attain_rate < 0.9;
    },
  });
  return self;
}
