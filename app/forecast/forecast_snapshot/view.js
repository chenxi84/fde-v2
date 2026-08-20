/* app/forecast/forecast_snapshot/view.js —— 预测快照 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "forecast_snapshot", name: "预测快照", ic: "📷",
  title: "预测快照", crumb: "客户N+1~N+3月度滚动预测 · 版本化管理",
  order: 20,
};

export default function pageFcstSnapshot() {
  const self = Alpine.reactive({
    tpl: "", hue, fmt,
    list: null,
    filterVersion: "", filterOem: "", filterPart: "", filterPeriod: "", filterFlag: "",
    versionOptions: [], custOptions: [],
    // Opening
    openingModal: { open: false, fcst_version: "" },
    // Detail modal
    modal: { open: false, loading: false, d: null },
    // Fill form
    fillForm: { open: false, orig_qty: 0, data_flag: "正常", source_channel: "销售转录" },

    async init() {
      self.list = pageable(async (q) => svc("forecast_snapshot", "list", {
        fcst_version: self.filterVersion || undefined,
        oem_code: self.filterOem || undefined,
        part_no: self.filterPart || undefined,
        period: self.filterPeriod || undefined,
        data_flag: self.filterFlag || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      // 加载下拉数据
      svc("md_fcst_version", "list", { page: 1, page_size: 50 }, { quiet: true })
        .then(r => { self.versionOptions = r.items || []; }).catch(() => {});
      svc("md_customer", "list", { page: 1, page_size: 200 }, { quiet: true })
        .then(r => { self.custOptions = r.items || []; }).catch(() => {});
      await self.list.load();
    },

    search() { self.list.load(1); },

    // Opening
    showOpening() { self.openingModal = { open: true, fcst_version: "" }; },
    async doOpen() {
      if (!self.openingModal.fcst_version) { toast("请输入版本号"); return; }
      try {
        const r = await svc("forecast_snapshot", "open_version", { fcst_version: self.openingModal.fcst_version });
        toast(`Opening 完成：生成 ${r.created} 行`);
        self.openingModal.open = false;
        self.filterVersion = self.openingModal.fcst_version;
        await self.list.load(1);
      } catch (e) { /* api.js 统一 toast */ }
    },

    // Detail
    async view(d) {
      self.modal = { open: true, loading: true, d: null };
      try {
        self.modal.d = await svc("forecast_snapshot", "get", {
          fcst_version: d.fcst_version, oem_code: d.oem_code, plant_code: d.plant_code,
          part_no: d.part_no, period: d.period,
        });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    // Fill — open detail modal first, then show fill form inside it
    async showFill(d) {
      self.modal = { open: true, loading: true, d: null };
      self.fillForm = { open: true, orig_qty: d.orig_qty || 0, data_flag: "正常", source_channel: "销售转录" };
      try {
        self.modal.d = await svc("forecast_snapshot", "get", {
          fcst_version: d.fcst_version, oem_code: d.oem_code, plant_code: d.plant_code,
          part_no: d.part_no, period: d.period,
        });
      } catch { self.modal.open = false; self.fillForm.open = false; }
      finally { self.modal.loading = false; }
    },
    async doFill() {
      if (!self.modal.d) return;
      const d = self.modal.d;
      try {
        const r = await svc("forecast_snapshot", "fill", {
          fcst_version: d.fcst_version, oem_code: d.oem_code, plant_code: d.plant_code,
          part_no: d.part_no, period: d.period,
          orig_qty: self.fillForm.orig_qty, data_flag: self.fillForm.data_flag,
          source_channel: self.fillForm.source_channel,
        });
        toast(`已录入 · ${r.part_no} / ${r.period}`);
        self.fillForm.open = false;
        self.modal.d = r;
        await self.list.load();
      } catch (e) { /* api.js */ }
    },
  });
  return self;
}
