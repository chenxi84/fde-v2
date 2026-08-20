/* app/forecast/md_project/view.js —— 项目台账 */
import { svc, hue, dash, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "md_project", name: "项目台账", ic: "\u{1F4CB}",
  title: "项目台账", crumb: "生命周期 · SOP/EOP · 活跃项目",
  order: 130,
};

export default function pageMdProject() {
  const self = Alpine.reactive({
    tpl: "", hue, dash, fmt: (v) => dash(v),
    list: null,
    filterProj: "", filterStage: "", filterOem: "", filterPlant: "",
    modal: { open: false, loading: false, d: null },
    form: { open: false, mode: "create", project_no: "", project_name: "", stage: "待定点", oem_code: "", plant_code: "", veh_model: "", platform: "", sop: "", eop: "", owner: "" },
    custOptions: [],
    custQuery: "", custOpen: false,

    async init() {
      self.list = pageable(async (q) => svc("md_project", "list", {
        project_no: self.filterProj || undefined,
        stage: self.filterStage || undefined,
        oem_code: self.filterOem || undefined,
        plant_code: self.filterPlant || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
      svc("md_customer", "list", { page: 1, page_size: 200 }, { quiet: true }).then(r => {
        self.custOptions = r ? (r.items || []) : [];
      }).catch(() => {});
    },

    search() { self.list.load(1); },

    get filteredCusts() {
      const q = (self.custQuery || "").toLowerCase();
      if (!q) return self.custOptions;
      return self.custOptions.filter(c =>
        (c.oem_code || "").toLowerCase().includes(q) ||
        (c.oem_name || "").toLowerCase().includes(q) ||
        (c.plant_code || "").toLowerCase().includes(q)
      );
    },
    selectCust(c) {
      self.form.oem_code = c.oem_code;
      self.form.plant_code = c.plant_code;
      self.custQuery = "";
      self.custOpen = false;
    },

    showCreate() {
      self.form = { open: true, mode: "create", project_no: "", project_name: "", stage: "待定点", oem_code: "", plant_code: "", veh_model: "", platform: "", sop: "", eop: "", owner: "" };
      self.custOpen = false; self.custQuery = "";
    },

    async view(d) {
      self.modal = { open: true, loading: true, d: null };
      try { self.modal.d = await svc("md_project", "get", { project_no: d.project_no }); }
      catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    showEdit() {
      if (!self.modal.d) return;
      const d = self.modal.d;
      self.form = { open: true, mode: "edit", project_no: d.project_no, project_name: d.project_name, stage: d.stage, oem_code: d.oem_code, plant_code: d.plant_code, veh_model: d.veh_model || "", platform: d.platform || "", sop: d.sop || "", eop: d.eop || "", owner: d.owner || "" };
      self.custOpen = false; self.custQuery = "";
    },

    async save() {
      const f = self.form;
      if (!f.project_no || !f.project_name || !f.stage || !f.oem_code || !f.plant_code) {
        toast("项目号、名称、阶段、客户编码、工厂编码均必填"); return;
      }
      try {
        if (f.mode === "create") {
          await svc("md_project", "create", {
            project_no: f.project_no, project_name: f.project_name, stage: f.stage,
            oem_code: f.oem_code, plant_code: f.plant_code,
            veh_model: f.veh_model || undefined, platform: f.platform || undefined,
            sop: f.sop || undefined, eop: f.eop || undefined, owner: f.owner || undefined,
          });
          toast(`已创建 · ${f.project_no}`);
        } else {
          await svc("md_project", "update", {
            project_no: f.project_no, project_name: f.project_name, stage: f.stage,
            veh_model: f.veh_model || undefined, platform: f.platform || undefined,
            sop: f.sop || undefined, eop: f.eop || undefined, owner: f.owner || undefined,
          });
          toast(`已更新 · ${f.project_no}`);
        }
        self.form.open = false; self.modal.open = false;
        await self.list.load();
      } catch (e) { /* api.js */ }
    },
  });
  return self;
}
