/* app/parts-fc/md_customer/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "md_customer", name: "客户主数据", ic: "🏢",
  title: "客户主数据", crumb: "主数据 · 客户/工厂",
  order: 15,
};

export default function pageMdCustomer() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    list: null,
    keyword: "",
    modalX: { open: false, loading: false, d: null },
    form: { open: false, busy: false, customer_code: "", customer_name: "", short_name: "", settlement_mode: "寄售", predict_behavior_label: "待评估" },
    plantList: [],
    plantForm: { show: false, busy: false, plant_code: "", plant_name: "" },

    statusLabel(s) { return { active: "启用", inactive: "停用" }[s] || s || "—"; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("md_customer", "list",
        { keyword: self.keyword, ...q }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    async viewX(doc) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("md_customer", "get", { customer_code: doc.customer_code });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeModal() { self.modalX.open = false; },

    openCreate() {
      self.form = { open: true, busy: false, customer_code: "", customer_name: "", short_name: "", settlement_mode: "寄售", predict_behavior_label: "待评估" };
    },
    closeCreate() { self.form.open = false; },

    async saveForm() {
      const f = self.form;
      if (!f.customer_code || !f.customer_name) return toast("必填字段缺失", "warn");
      f.busy = true;
      try {
        await svc("md_customer", "create", {
          customer_code: f.customer_code, customer_name: f.customer_name,
          short_name: f.short_name, settlement_mode: f.settlement_mode,
          predict_behavior_label: f.predict_behavior_label,
        });
        f.open = false; toast(`客户 ${f.customer_code} 创建成功`);
        await self.list.load(1);
      } catch { } finally { f.busy = false; }
    },

    async viewX(doc) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("md_customer", "get", { customer_code: doc.customer_code });
        self.plantList = await svc("md_customer", "get_plants", { customer_code: doc.customer_code }, { quiet: true }) || [];
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },

    /* ---- 工厂子表操作 ---- */
    openAddPlant() { self.plantForm = { show: true, busy: false, plant_code: "", plant_name: "" }; },
    async savePlant() {
      if (!self.plantForm.plant_code) return toast("工厂编码必填", "warn");
      self.plantForm.busy = true;
      try {
        self.plantList = await svc("md_customer", "add_plant", {
          customer_code: self.modalX.d.customer_code, plant_code: self.plantForm.plant_code, plant_name: self.plantForm.plant_name,
        });
        self.plantForm.show = false; toast("工厂已添加");
      } catch { } finally { self.plantForm.busy = false; }
    },
    async removePlant(plant_code) {
      if (!confirm("删除工厂 " + plant_code + "？")) return;
      try {
        self.plantList = await svc("md_customer", "remove_plant", {
          customer_code: self.modalX.d.customer_code, plant_code: plant_code,
        });
      } catch { }
    },
  });
  return self;
}
