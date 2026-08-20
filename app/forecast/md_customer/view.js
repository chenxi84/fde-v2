/* app/forecast/md_customer/view.js —— 客户主数据 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "md_customer", name: "客户主数据", ic: "🏢",
  title: "客户主数据", crumb: "OEM工厂 · 结算模式",
  order: 110,
};

export default function pageMdCustomer() {
  const self = Alpine.reactive({
    tpl: "", hue, fmt,
    list: null,
    filterOem: "", filterSettle: "",
    modal: { open: false, loading: false, d: null },
    form: { open: false, mode: "create", oem_code: "", oem_name: "", plant_code: "", plant_name: "", settle_mode: "寄售" },

    async init() {
      self.list = pageable(async (q) => svc("md_customer", "list", {
        oem_code: self.filterOem || undefined,
        settle_mode: self.filterSettle || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
    },

    search() { self.list.load(1); },

    showCreate() {
      self.form = { open: true, mode: "create", oem_code: "", oem_name: "", plant_code: "", plant_name: "", settle_mode: "寄售" };
    },

    async view(d) {
      self.modal = { open: true, loading: true, d: null };
      try { self.modal.d = await svc("md_customer", "get", { oem_code: d.oem_code, plant_code: d.plant_code }); }
      catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    showEdit() {
      if (!self.modal.d) return;
      const d = self.modal.d;
      self.form = { open: true, mode: "edit", oem_code: d.oem_code, plant_code: d.plant_code, oem_name: d.oem_name, plant_name: d.plant_name, settle_mode: d.settle_mode };
    },

    async save() {
      const f = self.form;
      if (!f.oem_code || !f.plant_code || !f.oem_name || !f.plant_name) { toast("客户编码、工厂编码、名称均必填"); return; }
      try {
        if (f.mode === "create") {
          await svc("md_customer", "create", { oem_code: f.oem_code, oem_name: f.oem_name, plant_code: f.plant_code, plant_name: f.plant_name, settle_mode: f.settle_mode });
          toast(`已创建 · ${f.oem_code}/${f.plant_code}`);
        } else {
          await svc("md_customer", "update", { oem_code: f.oem_code, plant_code: f.plant_code, oem_name: f.oem_name, plant_name: f.plant_name, settle_mode: f.settle_mode });
          toast(`已更新 · ${f.oem_code}/${f.plant_code}`);
        }
        self.form.open = false; self.modal.open = false;
        await self.list.load();
      } catch (e) { /* api.js */ }
    },
  });
  return self;
}
