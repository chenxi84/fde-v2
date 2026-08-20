/* app/parts-fc/md_material_history/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "md_material_history", name: "物料历史", ic: "📦",
  title: "物料历史数据", crumb: "主数据 · 实际调拨量",
  order: 18,
};

export default function pageMdMaterialHistory() {
  const self = Alpine.reactive({
    tpl: "", hue, fmt,
    list: null,
    keyword: "", fOem: "", fPeriod: "", oemOptions: [],
    form: { open: false, busy: false, part_no: "", project_no: "", period: "", actual_qty: 0, oem_code: "", plant_code: "", source: "手工" },
    importForm: { open: false, busy: false, text: "", result: null },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("md_material_history", "list",
        { keyword: self.keyword, oem_code: self.fOem || undefined, period: self.fPeriod || undefined, ...q }));
      await self.list.load();
      try {
        const all = await svc("md_material_history", "list", { page_size: 9999 }, { quiet: true });
        self.oemOptions = [...new Set((all.items || []).map(d => d.oem_code).filter(Boolean))];
      } catch {}
    },

    search() { self.list.load(1); },

    openCreate() {
      self.form = { open: true, busy: false, part_no: "", project_no: "", period: "", actual_qty: 0, oem_code: "", plant_code: "", source: "手工" };
    },
    closeCreate() { self.form.open = false; },
    async saveForm() {
      const f = self.form;
      if (!f.part_no || !f.period || !f.oem_code) return toast("零件号/期间/OEM 必填", "warn");
      f.busy = true;
      try {
        await svc("md_material_history", "create", f);
        toast("已录入"); f.open = false;
        await self.list.load(1);
      } catch {} finally { f.busy = false; }
    },

    openImport() { self.importForm = { open: true, busy: false, text: "", result: null }; },
    closeImport() { self.importForm.open = false; },
    async submitImport() {
      const txt = self.importForm.text.trim();
      if (!txt) return toast("请粘贴数据", "warn");
      self.importForm.busy = true; self.importForm.result = null;
      try {
        let lines;
        try { lines = JSON.parse(txt); } catch { return toast("JSON 格式错误", "warn"); }
        if (!Array.isArray(lines)) lines = [lines];
        const r = await svc("md_material_history", "bulk_import", { lines });
        self.importForm.result = r;
        toast("导入完成 · " + r.imported + " 条");
        await self.list.load(1);
      } catch {} finally { self.importForm.busy = false; }
    },
  });
  return self;
}
