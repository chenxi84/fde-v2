/* app/forecast/md_project_part/view.js —— 项目-零件映射 */
import { svc, hue, dash, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "md_project_part", name: "项目-零件映射", ic: "\u{1F517}",
  title: "项目-零件映射", crumb: "用量 · 份额 · 生效期间",
  order: 140,
};

export default function pageMdProjectPart() {
  const self = Alpine.reactive({
    tpl: "", hue, dash, fmt,
    list: null,
    filterProj: "", filterPart: "", filterVeh: "",
    modal: { open: false, loading: false, d: null },
    form: { open: false, mode: "create", project_no: "", part_no: "", veh_model: "", usage: "", share: "1", eff_from: "", eff_to: "" },
    projectOptions: [], partOptions: [],
    projQuery: "", projOpen: false,
    partQuery: "", partOpen: false,

    async init() {
      self.list = pageable(async (q) => svc("md_project_part", "list", {
        project_no: self.filterProj || undefined,
        part_no: self.filterPart || undefined,
        veh_model: self.filterVeh || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
      svc("md_project", "list", { page: 1, page_size: 200 }, { quiet: true }).then(r => {
        self.projectOptions = r ? (r.items || []) : [];
      }).catch(() => {});
      svc("md_material", "list", { page: 1, page_size: 500 }, { quiet: true }).then(r => {
        self.partOptions = r ? (r.items || []) : [];
      }).catch(() => {});
    },

    search() { self.list.load(1); },

    get filteredProjects() {
      const q = (self.projQuery || "").toLowerCase();
      if (!q) return self.projectOptions;
      return self.projectOptions.filter(p =>
        (p.project_no || "").toLowerCase().includes(q) ||
        (p.project_name || "").toLowerCase().includes(q)
      );
    },
    get filteredParts() {
      const q = (self.partQuery || "").toLowerCase();
      if (!q) return self.partOptions;
      return self.partOptions.filter(p =>
        (p.part_no || "").toLowerCase().includes(q) ||
        (p.part_name || "").toLowerCase().includes(q)
      );
    },
    selectProject(p) {
      self.form.project_no = p.project_no;
      self.projQuery = ""; self.projOpen = false;
    },
    selectPart(p) {
      self.form.part_no = p.part_no;
      self.partQuery = ""; self.partOpen = false;
    },

    showCreate() {
      self.form = { open: true, mode: "create", project_no: "", part_no: "", veh_model: "", usage: "", share: "1", eff_from: "", eff_to: "" };
      self.projOpen = false; self.projQuery = "";
      self.partOpen = false; self.partQuery = "";
    },

    async view(d) {
      self.modal = { open: true, loading: true, d: null };
      try { self.modal.d = await svc("md_project_part", "get", { project_no: d.project_no, part_no: d.part_no }); }
      catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    showEdit() {
      if (!self.modal.d) return;
      const d = self.modal.d;
      self.form = { open: true, mode: "edit", project_no: d.project_no, part_no: d.part_no, veh_model: d.veh_model || "", usage: d.usage != null ? String(d.usage) : "", share: d.share != null ? String(d.share) : "1", eff_from: d.eff_from || "", eff_to: d.eff_to || "" };
      self.projOpen = false; self.projQuery = "";
      self.partOpen = false; self.partQuery = "";
    },

    async save() {
      const f = self.form;
      if (!f.project_no || !f.part_no) { toast("项目号和零件号均必填"); return; }
      try {
        const payload = {
          project_no: f.project_no, part_no: f.part_no,
          veh_model: f.veh_model || undefined,
          usage: f.usage ? parseFloat(f.usage) : undefined,
          share: f.share ? parseFloat(f.share) : undefined,
          eff_from: f.eff_from || undefined,
          eff_to: f.eff_to || undefined,
        };
        if (f.mode === "create") {
          await svc("md_project_part", "create", payload);
          toast(`已创建 · ${f.project_no}/${f.part_no}`);
        } else {
          await svc("md_project_part", "update", payload);
          toast(`已更新 · ${f.project_no}/${f.part_no}`);
        }
        self.form.open = false; self.modal.open = false;
        await self.list.load();
      } catch (e) { /* api.js */ }
    },
  });
  return self;
}
