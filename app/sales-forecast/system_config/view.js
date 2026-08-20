/* app/sales-forecast/system_config/view.js —— 系统配置（多 Tab：参数/模板库/类比库/信任折扣/外部数据源） */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "system_config", name: "系统配置", ic: "⚙",
  title: "系统配置", crumb: "参数 · 模板 · 类比 · 信任折扣 · 外部数据源",
  order: 90,
};

export default function pageSystemConfig() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,

    /* ---- Tab 管理 ---- */
    tab: "params",
    tabLabel(t) {
      return {
        params: "参数", templates: "模板库", analogy: "类比库",
        trust_discount: "信任折扣", external_source: "外部数据源",
      }[t] || t;
    },

    /* ---- 参数 Tab ---- */
    paramList: null,
    paramModal: { open: false, loading: false, d: null },
    paramForm: { show: false, busy: false, param_code: "", param_name: "", value: "", dimension: "" },

    /* ---- 模板库 Tab ---- */
    templateList: null,

    /* ---- 类比库 Tab ---- */
    analogyList: null,

    /* ---- 信任折扣 Tab ---- */
    trustList: null,
    trustModal: { open: false, loading: false, d: null },

    /* ---- 外部数据源 Tab ---- */
    externalList: null,

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());

      /* 所有 Tab 的 pageable 在所有 await 之前同步建好 */
      self.paramList = pageable(async (q) => svc("system_config", "list_params", { ...q }));
      self.templateList = pageable(async (q) => svc("system_config", "list_templates", { ...q }));
      self.analogyList = pageable(async (q) => svc("system_config", "list_templates", { ...q })); /* 类比库暂复用模板 */
      self.trustList = pageable(async (q) => svc("system_config", "list_params", { ...q })); /* 信任折扣复用 list 骨架 */
      self.externalList = pageable(async (q) => svc("system_config", "list_params", { ...q })); /* 外部数据源复用 */

      await self.loadTab();
    },

    async switchTab(t) {
      self.tab = t;
      await self.loadTab();
    },

    async loadTab() {
      const t = self.tab;
      if (t === "params" && self.paramList.items.length === 0) await self.paramList.load();
      else if (t === "templates" && self.templateList.items.length === 0) await self.templateList.load();
      else if (t === "analogy" && self.analogyList.items.length === 0) await self.analogyList.load();
      else if (t === "trust_discount" && self.trustList.items.length === 0) await self.trustList.load();
      else if (t === "external_source" && self.externalList.items.length === 0) await self.externalList.load();
    },

    /* ---- 参数详情 + 编辑 ---- */
    async viewParam(d) {
      self.paramModal = { open: true, loading: true, d: null };
      self.paramForm.show = false;
      try {
        self.paramModal.d = await svc("system_config", "get_param", { param_code: d.param_code });
        /* 预填编辑表单 */
        self.paramForm = {
          show: false, busy: false,
          param_code: self.paramModal.d.param_code,
          param_name: self.paramModal.d.param_name || "",
          value: self.paramModal.d.value ?? "",
          dimension: self.paramModal.d.dimension || "",
        };
      } catch { self.paramModal.open = false; } finally { self.paramModal.loading = false; }
    },
    closeParamModal() { self.paramModal.open = false; },

    openParamEdit() { self.paramForm.show = true; },
    closeParamEdit() { self.paramForm.show = false; },

    async saveParam() {
      const f = self.paramForm;
      if (!f.param_code) return toast("参数编码缺失", "warn");
      f.busy = true;
      try {
        await svc("system_config", "set_param", {
          param_code: f.param_code,
          value: f.value,
          dimension: f.dimension,
        });
        toast(`参数 ${f.param_code} 已更新`);
        f.show = false;
        self.paramModal.d = await svc("system_config", "get_param",
          { param_code: f.param_code }).catch(() => self.paramModal.d);
        await self.paramList.load(self.paramList.page);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },

    /* ---- 信任折扣详情 ---- */
    async viewTrust(d) {
      self.trustModal = { open: true, loading: true, d: null };
      try {
        self.trustModal.d = await svc("system_config", "get_trust_discount",
          { oem_code: d.oem_code });
      } catch { self.trustModal.open = false; } finally { self.trustModal.loading = false; }
    },
    closeTrustModal() { self.trustModal.open = false; },
  });
  return self;
}
