/* app/parts-fc/project_ledger/view.js —— 项目信息台账（Project → Parts 两级结构） */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "project_ledger", name: "项目信息台账", ic: "📋",
  title: "项目信息台账", crumb: "主数据 · 项目×零件六维底座",
  order: 20,
};

export default function pageProjectLedger() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,

    /* ---- 主数据 autocomplete ---- */
    partOptions: [], vehOptions: [], custOptions: [], userOptions: [], autoFiltered: [], autoShow: "", autoDisplay: {},

    async loadAutoOptions(source, field, nameField) {
      try {
        const r = await svc(source, "list", {page_size: 9999}, {quiet:true});
        const items = r.items || [];
        self.autoOptions = items;
        items.forEach(item => {
          self.autoDisplay[item[field]] = item[nameField] || item[field];
        });
      } catch { self.autoOptions = []; }
    },

    filterAuto(field, query) {
      const q = (query || "").toLowerCase();
      const src = field === "part_no" ? self.partOptions : field === "vehicle_code" ? self.vehOptions : field === "customer_code" ? self.custOptions : field === "user_code" ? self.userOptions : [];
      self.autoFiltered = src.filter(item => {
        const code = (item[field] || "").toLowerCase();
        const name = (self.autoDisplay[item[field]] || "").toLowerCase();
        return code.includes(q) || name.includes(q);
      }).slice(0, 50);
    },


    toggleAuto(showKey, dataField) {
      if (self.autoShow === showKey) { self.autoShow = ""; return; }
      self.autoShow = showKey;
      self.filterAuto(dataField || showKey, "");
    },

    selectAuto(item, formObj, field, dataField) {
      formObj[field] = item[dataField || field];
      self.autoShow = "";
    },

    openAuto(showKey, dataField) {
      self.autoShow = showKey;
      self.filterAuto(dataField || showKey, "");
    },

    /* ---- 列表 + 过滤 ---- */
    list: null,
    projects: [],
    expandedProjects: {},
    fStage: "", fOemCode: "", fOwnerSales: "",
    oemCodeOptions: [], ownerSalesOptions: [],


    /* ---- 详情模态 ---- */
    modal: { open: false, loading: false, d: null },

    /* ---- 阶段迁移模态 ---- */
    stageForm: { show: false, busy: false, new_stage: "", reason: "", project: null },

    /* ---- 创建项目表单（项目 + 首个零件） ---- */
    projectForm: {
      show: false, busy: false,
      project_no: "", oem_code: "", plant_code: "", veh_model: "",
      platform: "", stage: "待定点", status: "待启用", replacement_for: "",
      part_kind: "专用", lc_shape: "",
      part_no: "", sop: "", eop: "", owner_sales: "",
      usage: "", share: "",
    },

    /* ---- 添加零件表单 ---- */
    partForm: {
      show: false, busy: false, project: null, projectParts: [],
      part_no: "", sop: "", eop: "", owner_sales: "",
      status: "待启用", replacement_for: "",
      usage: "", share: "",
    },

    /* ---- 编辑零件表单 ---- */
    get editProjectParts() {
      if (!self.form.edit_project_no) return [];
      const proj = (self.projects || []).find(p => p.project_no === self.form.edit_project_no);
      return proj ? (proj.parts || []).filter(p => p.part_no !== self.form.edit_part_no) : [];
    },

    /* ---- 编辑项目级字段表单 ---- */
    editProjectForm: {
      show: false, busy: false, project: null,
      oem_code: "", plant_code: "", veh_model: "",
      platform: "", part_kind: "", lc_shape: "",
    },

    /* ---- 编辑单个零件表单 ---- */
    form: {
      show: false, busy: false, mode: "edit",
      edit_project_no: "", edit_part_no: "",
      project_no: "", part_no: "", status: "待启用", replacement_for: "",
      oem_code: "", plant_code: "", veh_model: "",
      platform: "", part_kind: "", sop: "", eop: "", owner_sales: "",
      award_prob: "", lc_shape: "", usage: "", share: "",
    },

    stageOptions: ["待定点", "定点中", "进行中", "EOP关闭"],
    partKindOptions: ["专用", "通用"],
    lcShapeOptions: ["传统", "上市高后下滑"],

    async init() {
      self.list = pageable(async (q) => svc("project_ledger", "list", {
        stage: self.fStage || undefined,
        oem_code: self.fOemCode || undefined,
        owner_sales: self.fOwnerSales || undefined,
        ...q,
      }), 500);
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
      self.rebuildProjects();
      await self.loadFilterOptions();
      try { const r = await svc("md_part","list",{page_size:9999},{quiet:true}); self.partOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.part_no]=i.part_name||i.part_no}); } catch {}
      try { const r = await svc("md_vehicle","list",{page_size:9999},{quiet:true}); self.vehOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.vehicle_code]=i.vehicle_name||i.vehicle_code}); } catch {}
      try { const r = await svc("md_customer","list",{page_size:9999},{quiet:true}); self.custOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.customer_code]=i.customer_name||i.customer_code}); } catch {}
      try { const r = await svc("md_user","list",{page_size:9999},{quiet:true}); self.userOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.user_code]=i.user_name||i.user_code}); } catch {}
    },

    /* ---- 按 project_no 分组 ---- */
    rebuildProjects() {
      const items = self.list?.items || [];
      const map = new Map();
      for (const item of items) {
        if (!map.has(item.project_no)) {
          map.set(item.project_no, {
            project_no: item.project_no,
            oem_code: item.oem_code,
            plant_code: item.plant_code,
            stage: item.stage,
            part_kind: item.part_kind,
            lc_shape: item.lc_shape,
            veh_model: item.veh_model,
            platform: item.platform,
            parts: [],
            expanded: !!self.expandedProjects[item.project_no],
          });
        }
        map.get(item.project_no).parts.push(item);
      }
      self.projects = [...map.values()];
    },

    toggleProject(project_no) {
      self.expandedProjects[project_no] = !self.expandedProjects[project_no];
      self.rebuildProjects();
    },

    async loadFilterOptions() {
      try {
        const all = await svc("project_ledger", "list", {}, { quiet: true });
        if (Array.isArray(all)) {
          const oemSet = new Set(), salesSet = new Set();
          all.forEach(d => {
            if (d.oem_code) oemSet.add(d.oem_code);
            if (d.owner_sales) salesSet.add(d.owner_sales);
          });
          self.oemCodeOptions = [...oemSet].sort();
          self.ownerSalesOptions = [...salesSet].sort();
        }
      } catch { /* quiet */ }
    },

    async search() {
      await self.list.load(1);
      self.rebuildProjects();
    },

    /* ---- 创建项目 + 首个零件 ---- */
    openProjectForm() {
      self.projectForm = {
        show: true, busy: false,
        project_no: "", oem_code: "", plant_code: "", veh_model: "",
        platform: "", stage: "待定点", part_kind: "专用", lc_shape: "",
        part_no: "", sop: "", eop: "", owner_sales: "",
        usage: "", share: "",
      };
    },
    closeProjectForm() { self.projectForm.show = false; },
    async saveProjectForm() {
      const f = self.projectForm;
      if (!f.project_no) return toast("请填写项目编号", "warn");
      if (!f.part_no) return toast("请填写零件号", "warn");
      if (!f.oem_code) return toast("请填写OEM代码", "warn");
      if (!f.plant_code) return toast("请填写工厂代码", "warn");
      if (!f.veh_model) return toast("请填写车型", "warn");
      if (!f.part_kind) return toast("请选择零件类型", "warn");
      if (!f.sop) return toast("请填写SOP", "warn");
      if (!f.owner_sales) return toast("请填写销售负责人", "warn");
      f.busy = true;
      try {
        await svc("project_ledger", "create", {
          project_no: f.project_no,
          part_no: f.part_no,
          status: f.status || "待启用",
          replacement_for: f.replacement_for || undefined,
          oem_code: f.oem_code,
          plant_code: f.plant_code,
          veh_model: f.veh_model,
          platform: f.platform,
          part_kind: f.part_kind,
          stage: f.stage,
          lc_shape: f.lc_shape,
          sop: f.sop,
          eop: f.eop,
          owner_sales: f.owner_sales,
          usage: Number(f.usage || 0),
          share: Number(f.share || 0),
        });
        toast(`项目 ${f.project_no} 已创建`);
        f.show = false;
        await self.list.load(self.list.page);
        self.rebuildProjects();
        self.loadFilterOptions();
      } catch { /* api layer handles toast */ } finally { f.busy = false; }
    },

    /* ---- 添加零件到已有项目 ---- */
    openPartForm(project) {
      self.partForm = {
        show: true, busy: false, project, projectParts: project.parts || [],
        part_no: "", sop: "", eop: "", owner_sales: "",
        status: "待启用", replacement_for: "",
        usage: "", share: "",
      };
    },
    closePartForm() { self.partForm.show = false; },
    async savePartForm() {
      const f = self.partForm;
      if (!f.part_no) return toast("请填写零件号", "warn");
      if (!f.sop) return toast("请填写SOP", "warn");
      if (!f.owner_sales) return toast("请填写销售负责人", "warn");
      f.busy = true;
      try {
        await svc("project_ledger", "create", {
          project_no: f.project.project_no,
          part_no: f.part_no,
          status: f.status || "待启用",
          replacement_for: f.replacement_for || undefined,
          oem_code: f.project.oem_code,
          plant_code: f.project.plant_code,
          veh_model: f.project.veh_model,
          platform: f.project.platform,
          part_kind: f.project.part_kind,
          stage: f.project.stage,
          lc_shape: f.project.lc_shape,
          sop: f.sop,
          eop: f.eop,
          owner_sales: f.owner_sales,
          usage: Number(f.usage || 0),
          share: Number(f.share || 0),
        });
        toast(`零件 ${f.part_no} 已添加到项目 ${f.project.project_no}`);
        f.show = false;
        await self.list.load(self.list.page);
        self.rebuildProjects();
        self.loadFilterOptions();
      } catch { /* api layer handles toast */ } finally { f.busy = false; }
    },

    /* ---- 编辑项目级字段（更新全部零件） ---- */
    openEditProjectForm(project) {
      self.editProjectForm = {
        show: true, busy: false, project,
        oem_code: project.oem_code || "",
        plant_code: project.plant_code || "",
        veh_model: project.veh_model || "",
        platform: project.platform || "",
        part_kind: project.part_kind || "",
        lc_shape: project.lc_shape || "",
      };
    },
    closeEditProjectForm() { self.editProjectForm.show = false; },
    async saveEditProjectForm() {
      const p = self.editProjectForm;
      if (!p.oem_code) return toast("请填写OEM代码", "warn");
      if (!p.plant_code) return toast("请填写工厂代码", "warn");
      if (!p.veh_model) return toast("请填写车型", "warn");
      if (!p.part_kind) return toast("请选择零件类型", "warn");
      p.busy = true;
      try {
        for (const part of p.project.parts) {
          await svc("project_ledger", "update", {
            project_no: p.project.project_no,
            part_no: part.part_no,
            kwargs: {
              oem_code: p.oem_code,
              plant_code: p.plant_code,
              veh_model: p.veh_model,
              platform: p.platform,
              part_kind: p.part_kind,
              lc_shape: p.lc_shape,
            },
          });
        }
        toast(`项目 ${p.project.project_no} 已更新`);
        p.show = false;
        await self.list.load(self.list.page);
        self.rebuildProjects();
        self.loadFilterOptions();
      } catch { /* api layer handles toast */ } finally { p.busy = false; }
    },

    /* ---- 移除零件 ---- */
    async removePart(d) {
      if (!confirm(`确认从项目 ${d.project_no} 中移除零件 ${d.part_no}？此操作不可撤销。`)) return;
      try {
        await svc("project_ledger", "delete", { project_no: d.project_no, part_no: d.part_no });
        toast(`零件 ${d.part_no} 已移除`);
        await self.list.load(self.list.page);
        self.rebuildProjects();
        self.loadFilterOptions();
      } catch { /* api layer handles toast */ }
    },

    /* ---- 详情模态 ---- */
    async viewDetail(d) {
      self.modal = { open: true, loading: true, d: null };
      try {
        const [detail, changeLog] = await Promise.all([
          svc("project_ledger", "get", { project_no: d.project_no, part_no: d.part_no }),
          svc("project_ledger", "get_change_log", { project_no: d.project_no, part_no: d.part_no }).catch(() => ({ items: [] })),
        ]);
        self.modal.d = { ...detail, change_log: changeLog.items || changeLog };
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    /* ---- 阶段迁移 ---- */
    openStageForm(projectOrD) {
      // projectOrD 可以是项目组对象或单条记录
      if (projectOrD && projectOrD.parts) {
        self.stageForm = { show: true, busy: false, new_stage: "", reason: "", project: projectOrD };
      } else {
        self.stageForm = { show: true, busy: false, new_stage: "", reason: "", project: null };
      }
    },
    closeStageForm() { self.stageForm.show = false; },
    async saveStage() {
      const s = self.stageForm;
      if (!s.new_stage) return toast("请选择目标阶段", "warn");
      if (!s.reason) return toast("请填写变更原因", "warn");
      s.busy = true;
      try {
        if (s.project) {
          // 项目级阶段迁移：更新全部零件
          for (const part of s.project.parts) {
            await svc("project_ledger", "set_stage", {
              project_no: s.project.project_no,
              part_no: part.part_no,
              new_stage: s.new_stage,
              reason: s.reason,
            });
          }
          toast(`项目 ${s.project.project_no} 阶段已更新为 ${s.new_stage}`);
        } else if (self.modal.d) {
          // 单零件阶段迁移（来自详情模态）
          await svc("project_ledger", "set_stage", {
            project_no: self.modal.d.project_no,
            part_no: self.modal.d.part_no,
            new_stage: s.new_stage,
            reason: s.reason,
          });
          toast(`项目 ${self.modal.d.project_no} 阶段已更新为 ${s.new_stage}`);
          self.modal.d = await svc("project_ledger", "get",
            { project_no: self.modal.d.project_no, part_no: self.modal.d.part_no })
            .catch(() => self.modal.d);
        }
        s.show = false;
        await self.list.load(self.list.page);
        self.rebuildProjects();
      } catch { /* api layer handles toast */ } finally { s.busy = false; }
    },

    /* ---- 编辑单个零件 ---- */
    openEdit(d) {
      self.form = {
        show: true, busy: false, mode: "edit",
        edit_project_no: d.project_no, edit_part_no: d.part_no,
        project_no: d.project_no, part_no: d.part_no,
        status: d.status || "待启用", replacement_for: d.replacement_for || "",
        oem_code: d.oem_code || "", plant_code: d.plant_code || "",
        veh_model: d.veh_model || "", platform: d.platform || "",
        part_kind: d.part_kind || "", sop: (d.sop || "").slice(0, 10),
        eop: (d.eop || "").slice(0, 10), owner_sales: d.owner_sales || "",
        award_prob: d.award_prob ?? "", lc_shape: d.lc_shape || "",
        usage: d.usage ?? "", share: d.share ?? "",
      };
    },
    closeForm() { self.form.show = false; },

    async saveForm() {
      const f = self.form;
      if (!f.oem_code) return toast("请填写OEM代码", "warn");
      if (!f.plant_code) return toast("请填写工厂代码", "warn");
      if (!f.veh_model) return toast("请填写车型", "warn");
      if (!f.part_kind) return toast("请选择零件类型", "warn");
      if (!f.sop) return toast("请填写SOP", "warn");
      if (!f.owner_sales) return toast("请填写销售负责人", "warn");
      f.busy = true;
      try {
        await svc("project_ledger", "update", {
          project_no: f.edit_project_no, part_no: f.edit_part_no,
          kwargs: {
            oem_code: f.oem_code, plant_code: f.plant_code,
            veh_model: f.veh_model, platform: f.platform,
            part_kind: f.part_kind, sop: f.sop, eop: f.eop,
            owner_sales: f.owner_sales, award_prob: Number(f.award_prob || 0),
            lc_shape: f.lc_shape,
            usage: Number(f.usage || 0), share: Number(f.share || 0),
            status: f.status || "待启用", replacement_for: f.replacement_for || None,
          },
        });
        toast(`项目 ${f.edit_project_no} 已更新`);
        f.show = false;
        await self.list.load(self.list.page);
        self.rebuildProjects();
        self.loadFilterOptions();
      } catch { /* api layer handles toast */ } finally { f.busy = false; }
    },
  });
  return self;
}
