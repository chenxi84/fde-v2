/* app/forecast/md_material/view.js —— 物料主数据 */
import { svc, hue, dash, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "md_material", name: "物料主数据", ic: "\u{1F4E6}",
  title: "物料主数据", crumb: "零件号 · 名称 · 单位",
  order: 120,
};

export default function pageMdMaterial() {
  const self = Alpine.reactive({
    tpl: "", hue, dash, fmt: (v) => dash(v),
    list: null,
    filterPart: "", filterName: "", filterType: "",
    modal: { open: false, loading: false, d: null },
    form: { open: false, mode: "create", part_no: "", part_name: "", uom: "件", mat_type: "" },

    async init() {
      self.list = pageable(async (q) => svc("md_material", "list", {
        part_no: self.filterPart || undefined,
        part_name: self.filterName || undefined,
        mat_type: self.filterType || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
    },

    search() { self.list.load(1); },

    showCreate() {
      self.form = { open: true, mode: "create", part_no: "", part_name: "", uom: "件", mat_type: "" };
    },

    async view(d) {
      self.modal = { open: true, loading: true, d: null };
      try { self.modal.d = await svc("md_material", "get", { part_no: d.part_no }); }
      catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    showEdit() {
      if (!self.modal.d) return;
      const d = self.modal.d;
      self.form = { open: true, mode: "edit", part_no: d.part_no, part_name: d.part_name, uom: d.uom, mat_type: d.mat_type };
    },

    async save() {
      const f = self.form;
      if (!f.part_no || !f.part_name || !f.uom) { toast("零件号、名称、单位均必填"); return; }
      try {
        if (f.mode === "create") {
          await svc("md_material", "create", { part_no: f.part_no, part_name: f.part_name, uom: f.uom, mat_type: f.mat_type || undefined });
          toast(`已创建 · ${f.part_no}`);
        } else {
          await svc("md_material", "update", { part_no: f.part_no, part_name: f.part_name, uom: f.uom, mat_type: f.mat_type || undefined });
          toast(`已更新 · ${f.part_no}`);
        }
        self.form.open = false; self.modal.open = false;
        await self.list.load();
      } catch (e) { /* api.js */ }
    },
  });
  return self;
}
