/* app/parts-fc/md_part/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "md_part", name: "物料主数据", ic: "📦",
  title: "物料主数据", crumb: "主数据 · 零件/物料",
  order: 16,
};

export default function pageMdPart() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    list: null,
    keyword: "",
    modalX: { open: false, loading: false, d: null },
    form: { open: false, busy: false, part_no: "", part_name: "", status: "active" },

    statusLabel(s) { return { active: "启用", inactive: "停用" }[s] || s || "—"; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("md_part", "list",
        { keyword: self.keyword, ...q }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    async viewX(doc) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("md_part", "get", { part_no: doc.part_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeModal() { self.modalX.open = false; },

    openCreate() {
      self.form = { open: true, busy: false, part_no: "", part_name: "", status: "active" };
    },
    closeCreate() { self.form.open = false; },
    resetForm() {
      self.form.part_no = ""; self.form.part_name = ""; self.form.status = "active";
    },

    async saveForm() {
      const f = self.form;
      if (!f.part_no || !f.part_name) return toast("必填字段缺失", "warn");
      f.busy = true;
      try {
        await svc("md_part", "create", {
          part_no: f.part_no, part_name: f.part_name, status: f.status,
        });
        const code = f.part_no;
        f.open = false; self.resetForm();
        toast(`物料 ${code} 创建成功`);
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },
  });
  return self;
}
