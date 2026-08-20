/* app/psc/sales_history/view.js —— 历史台账（物料销售历史）。
   数据源=ERP 经 import_batch/upsert 冗余回写；无手工新建入口（自动参考创建，参照 attainment）。
   列表 + 过滤 + 批量导入。 */
import { svc, dash, fmt } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "sales_history",
  name: "历史台账",
  ic: "📒",
  title: "历史台账",
  crumb: "历史数据 · 物料×客户×月度 干净需求",
  order: 170,
};

export default function pageSalesHistory() {
  const self = Alpine.reactive({
    tpl: "",
    dash, fmt,                        // 模板展示工具（fmt 非 window 全局，须挂组件作用域）

    list: null,
    fMaterial: "", fCustomer: "", fPeriod: "",

    materialOptions: [], materialMap: {},
    customerOptions: [], customerMap: {},

    imp: { open: false, busy: false, text: "", result: null },

    async init() {
      self.list = pageable(async (q) => svc("sales_history", "list", {
        material_no: self.fMaterial || undefined,
        customer_no: self.fCustomer || undefined,
        period: self.fPeriod || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.loadMaterials();
      self.loadCustomers();
      await self.list.load();
    },

    async loadMaterials() {
      try {
        const r = await svc("md_material", "list", {}, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.materialOptions = rows;
        const map = {};
        for (const m of rows) if (m && m.material_no) map[m.material_no] = m.material_name || "";
        self.materialMap = map;
      } catch { /* 兜底：名称原样展示 */ }
    },
    async loadCustomers() {
      try {
        const r = await svc("md_customer", "list", {}, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.customerOptions = rows;
        const map = {};
        for (const c of rows) if (c && c.customer_no) map[c.customer_no] = c.customer_name || "";
        self.customerMap = map;
      } catch { /* 兜底 */ }
    },
    materialName(no) { return self.materialMap[no] || ""; },
    customerName(no) { return self.customerMap[no] || ""; },

    search() { self.list.load(1); },
    resetFilters() { self.fMaterial = ""; self.fCustomer = ""; self.fPeriod = ""; self.list.load(1); },

    /* ---- 批量导入 ---- */
    openImport() { self.imp = { open: false, busy: false, text: "", result: null }; self.imp.open = true; },
    closeImport() {
      const done = !!self.imp.result;
      self.imp.open = false; self.imp.result = null;
      if (done) self.list.load(self.list.page);
    },
    onImportFile(evt) {
      const file = evt.target.files && evt.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => { self.imp.text = String(reader.result || ""); };
      reader.readAsText(file, "utf-8");
    },
    downloadTemplate() {
      const csv = "material_no,customer_no,period,qty\nM1,C001,2026-01,900\n";
      const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "历史台账导入模板.csv";
      a.click();
      URL.revokeObjectURL(a.href);
    },
    parseImportRows() {
      const text = (self.imp.text || "").replace(/^﻿/, "");
      const rows = [];
      for (const line of text.split(/\r?\n/)) {
        const s = line.trim();
        if (!s) continue;
        if (/^material_no\s*[,，\t]/.test(s)) continue;   // 跳过表头
        const parts = s.split(/[,，\t]/).map((x) => x.trim());
        if (parts.length < 4) continue;
        const [material_no, customer_no, period, q] = parts;
        rows.push({ material_no, customer_no, period, qty: q });
      }
      return rows;
    },
    async runImport() {
      const rows = self.parseImportRows();
      if (!rows.length) return toast("请粘贴或上传至少一行数据", "warn");
      self.imp.busy = true; self.imp.result = null;
      try {
        const r = await svc("sales_history", "import_batch", { rows });
        self.imp.result = r;
        toast(`导入完成 · 成功 ${r.success} 条 / 失败 ${r.fail} 条`);
      } catch { /* api.js 已 toast */ } finally { self.imp.busy = false; }
    },
  });
  return self;
}
