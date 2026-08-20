/* app/parts-fc/md_vehicle/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "md_vehicle", name: "车型主数据", ic: "🚗",
  title: "车型主数据", crumb: "主数据 · 车型/平台",
  order: 17,
};

export default function pageMdVehicle() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    list: null,
    keyword: "",
    modalX: { open: false, loading: false, d: null },
    form: { open: false, busy: false, vehicle_code: "", vehicle_name: "", status: "active" },

    statusLabel(s) { return { active: "启用", inactive: "停用" }[s] || s || "—"; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("md_vehicle", "list",
        { keyword: self.keyword, ...q }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    async viewX(doc) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("md_vehicle", "get", { vehicle_code: doc.vehicle_code });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeModal() { self.modalX.open = false; },

    openCreate() {
      self.form = { open: true, busy: false, vehicle_code: "", vehicle_name: "", status: "active" };
    },
    closeCreate() { self.form.open = false; },
    resetForm() {
      self.form.vehicle_code = ""; self.form.vehicle_name = ""; self.form.status = "active";
    },

    async saveForm() {
      const f = self.form;
      if (!f.vehicle_code || !f.vehicle_name) return toast("必填字段缺失", "warn");
      f.busy = true;
      try {
        await svc("md_vehicle", "create", {
          vehicle_code: f.vehicle_code, vehicle_name: f.vehicle_name, status: f.status,
        });
        const code = f.vehicle_code;
        f.open = false; self.resetForm();
        toast(`车型 ${code} 创建成功`);
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },
  });
  return self;
}
