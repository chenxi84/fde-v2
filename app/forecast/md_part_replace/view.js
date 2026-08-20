/* app/forecast/md_part_replace/view.js —— 替换关系 */
import { svc, hue, dash, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "md_part_replace", name: "替换关系", ic: "\u{1F504}",
  title: "替换关系", crumb: "替换 · 替代 · ECN",
  order: 150,
};

export default function pageMdPartReplace() {
  const self = Alpine.reactive({
    tpl: "", hue, dash, fmt: (v) => dash(v),
    list: null,
    filterType: "", filterOld: "", filterNew: "", filterStatus: "",
    modal: { open: false, loading: false, d: null },
    form: { open: false, mode: "create", rel_no: "", rel_type: "替换", old_part: "", new_part: "", switch_date: "", ecn_no: "" },
    partOptions: [],
    oldQuery: "", oldOpen: false,
    newQuery: "", newOpen: false,

    async init() {
      self.list = pageable(async (q) => svc("md_part_replace", "list", {
        rel_type: self.filterType || undefined,
        old_part: self.filterOld || undefined,
        new_part: self.filterNew || undefined,
        status: self.filterStatus || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
      svc("md_material", "list", { page: 1, page_size: 500 }, { quiet: true }).then(r => {
        self.partOptions = r ? (r.items || []) : [];
      }).catch(() => {});
    },

    search() { self.list.load(1); },

    get filteredParts() {
      const q = ((self.oldOpen ? self.oldQuery : self.newQuery) || "").toLowerCase();
      if (!q) return self.partOptions;
      return self.partOptions.filter(p =>
        (p.part_no || "").toLowerCase().includes(q) ||
        (p.part_name || "").toLowerCase().includes(q)
      );
    },
    selectOldPart(p) {
      self.form.old_part = p.part_no; self.oldQuery = ""; self.oldOpen = false;
    },
    selectNewPart(p) {
      self.form.new_part = p.part_no; self.newQuery = ""; self.newOpen = false;
    },

    showCreate() {
      self.form = { open: true, mode: "create", rel_no: "", rel_type: "替换", old_part: "", new_part: "", switch_date: "", ecn_no: "" };
      self.oldOpen = false; self.oldQuery = ""; self.newOpen = false; self.newQuery = "";
    },

    async view(d) {
      self.modal = { open: true, loading: true, d: null };
      try { self.modal.d = await svc("md_part_replace", "get", { rel_no: d.rel_no }); }
      catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    showEdit() {
      if (!self.modal.d) return;
      const d = self.modal.d;
      self.form = { open: true, mode: "edit", rel_no: d.rel_no, rel_type: d.rel_type, old_part: d.old_part, new_part: d.new_part, switch_date: d.switch_date || "", ecn_no: d.ecn_no || "" };
      self.oldOpen = false; self.oldQuery = ""; self.newOpen = false; self.newQuery = "";
    },

    async save() {
      const f = self.form;
      if (!f.rel_no || !f.rel_type || !f.old_part || !f.new_part) { toast("关系号、类型、旧件号、新件号均必填"); return; }
      try {
        const payload = {
          rel_no: f.rel_no, rel_type: f.rel_type, old_part: f.old_part, new_part: f.new_part,
          switch_date: f.switch_date || undefined, ecn_no: f.ecn_no || undefined,
        };
        if (f.mode === "create") {
          await svc("md_part_replace", "create", payload);
          toast(`已创建 · ${f.rel_no}`);
        } else {
          await svc("md_part_replace", "update", payload);
          toast(`已更新 · ${f.rel_no}`);
        }
        self.form.open = false; self.modal.open = false;
        await self.list.load();
      } catch (e) { /* api.js */ }
    },

    async doDisable(d) {
      if (!confirm("确认将替换关系设为失效？失效后零件级处理中将排除此关系")) return;
      try {
        await svc("md_part_replace", "disable", { rel_no: d.rel_no });
        toast("替换关系已设为失效");
        if (self.modal.d && self.modal.d.rel_no === d.rel_no) {
          self.modal.d = await svc("md_part_replace", "get", { rel_no: d.rel_no });
        }
        await self.list.load();
      } catch (e) { /* api.js */ }
    },
  });
  return self;
}
