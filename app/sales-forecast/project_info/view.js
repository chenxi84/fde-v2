/* app/sales-forecast/project_info/view.js —— 项目信息管理 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "project_info", name: "项目信息", ic: "📋",
  title: "项目信息", crumb: "量产项目生命周期 · 定点 → EOP",
  order: 60,
};

export default function pageProjectInfo() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,

    /* ---- 列表 + 搜索 ---- */
    list: null,
    fStage: "", keyword: "",

    /* ---- 详情模态 ---- */
    modal: { open: false, loading: false, d: null },

    /* ---- 阶段流转模态 ---- */
    stageForm: { show: false, busy: false, new_stage: "", reason: "" },

    /* ---- 创建/编辑表单 ---- */
    form: {
      show: false, busy: false, more: false, mode: "create",
      edit_project_no: "", edit_part_no: "",
      project_no: "", part_no: "", stage: "待定点", oem_code: "",
      plant_code: "", veh_model: "", part_kind: "",
      sop: "", eop: "", owner_sales: "", lc_shape: "",
    },

    stageOptions: ["待定点", "定点中", "进行中", "EOP关闭"],

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("project_info", "list",
        { stage: self.fStage, keyword: self.keyword, ...q }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    /* ---- 详情模态 ---- */
    async viewProject(d) {
      self.modal = { open: true, loading: true, d: null };
      try {
        self.modal.d = await svc("project_info", "get",
          { project_no: d.project_no, part_no: d.part_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    /* ---- 阶段流转 ---- */
    openStageForm() {
      self.stageForm = { show: true, busy: false, new_stage: "", reason: "" };
    },
    closeStageForm() { self.stageForm.show = false; },
    async saveStage() {
      const s = self.stageForm;
      if (!s.new_stage) return toast("请选择目标阶段", "warn");
      if (!s.reason) return toast("请填写变更原因", "warn");
      s.busy = true;
      try {
        await svc("project_info", "set_stage", {
          project_no: self.modal.d.project_no,
          part_no: self.modal.d.part_no,
          new_stage: s.new_stage,
          reason: s.reason,
        });
        toast(`项目 ${self.modal.d.project_no} 阶段已更新为 ${s.new_stage}`);
        s.show = false;
        self.modal.d = await svc("project_info", "get",
          { project_no: self.modal.d.project_no, part_no: self.modal.d.part_no })
          .catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { s.busy = false; }
    },

    /* ---- 创建/编辑表单 ---- */
    openCreate() {
      self.form = {
        show: true, busy: false, more: false, mode: "create",
        edit_project_no: "", edit_part_no: "",
        project_no: "", part_no: "", stage: "待定点", oem_code: "",
        plant_code: "", veh_model: "", part_kind: "",
        sop: "", eop: "", owner_sales: "", lc_shape: "",
      };
    },
    openEdit(d) {
      self.form = {
        show: true, busy: false, more: false, mode: "edit",
        edit_project_no: d.project_no, edit_part_no: d.part_no,
        project_no: d.project_no, part_no: d.part_no, stage: d.stage || "进行中",
        oem_code: d.oem_code || "", plant_code: d.plant_code || "",
        veh_model: d.veh_model || "", part_kind: d.part_kind || "",
        sop: (d.sop || "").slice(0, 10), eop: (d.eop || "").slice(0, 10),
        owner_sales: d.owner_sales || "", lc_shape: d.lc_shape || "",
      };
    },
    closeForm() { self.form.show = false; },
    resetForm() {
      self.form.project_no = ""; self.form.part_no = ""; self.form.stage = "待定点";
      self.form.oem_code = ""; self.form.plant_code = ""; self.form.veh_model = "";
      self.form.part_kind = ""; self.form.sop = ""; self.form.eop = "";
      self.form.owner_sales = ""; self.form.lc_shape = ""; self.form.more = false;
    },

    async saveForm() {
      const f = self.form;
      if (!f.project_no) return toast("请填写项目编号", "warn");
      if (!f.part_no) return toast("请填写零件号", "warn");
      f.busy = true;
      try {
        if (f.mode === "edit") {
          await svc("project_info", "update", {
            project_no: f.edit_project_no, part_no: f.edit_part_no,
            stage: f.stage, oem_code: f.oem_code, plant_code: f.plant_code,
            veh_model: f.veh_model, part_kind: f.part_kind,
            sop: f.sop, eop: f.eop, owner_sales: f.owner_sales, lc_shape: f.lc_shape,
          });
          toast(`项目 ${f.edit_project_no} 已更新`);
        } else {
          await svc("project_info", "create", {
            project_no: f.project_no, part_no: f.part_no, stage: f.stage,
            oem_code: f.oem_code, plant_code: f.plant_code,
            veh_model: f.veh_model, part_kind: f.part_kind,
            sop: f.sop, eop: f.eop, owner_sales: f.owner_sales, lc_shape: f.lc_shape,
          });
          toast(`项目 ${f.project_no} 已创建`);
        }
        f.show = false; self.resetForm();
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },
  });
  return self;
}
