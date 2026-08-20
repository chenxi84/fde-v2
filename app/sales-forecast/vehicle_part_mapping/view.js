/* app/sales-forecast/vehicle_part_mapping/view.js —— 车型零件映射管理 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "vehicle_part_mapping", name: "车型零件映射", ic: "🔗",
  title: "车型零件映射", crumb: "车型与零件关联 · 用量与份额",
  order: 70,
};

export default function pageVehiclePartMapping() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,

    /* ---- 列表 + 搜索 ---- */
    list: null,
    fLcStage: "",

    /* ---- 详情模态 ---- */
    modal: { open: false, loading: false, d: null },

    /* ---- 用量编辑 ---- */
    usageForm: { show: false, busy: false, usage: "" },

    /* ---- 份额编辑 ---- */
    shareForm: { show: false, busy: false, share: "" },

    /* ---- 创建表单 ---- */
    form: {
      show: false, busy: false, more: false,
      part_no: "", veh_model: "", usage: "", share: "",
      lc_stage: "", lc_shape: "", sop: "", eop: "", source: "",
    },

    lcStageOptions: ["定点", "A样", "B样", "C样", "D样", "SOP", "EOP"],

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("vehicle_part_mapping", "list",
        { lc_stage: self.fLcStage, ...q }));
      await self.list.load();
    },

    /* ---- 详情模态 ---- */
    async viewMapping(d) {
      self.modal = { open: true, loading: true, d: null };
      self.usageForm.show = false;
      self.shareForm.show = false;
      try {
        self.modal.d = await svc("vehicle_part_mapping", "get",
          { part_no: d.part_no, veh_model: d.veh_model });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    /* ---- 用量编辑 ---- */
    openUsageEdit() {
      self.usageForm = { show: true, busy: false, usage: self.modal.d.usage ?? "" };
    },
    closeUsageEdit() { self.usageForm.show = false; },
    async saveUsage() {
      const u = self.usageForm;
      if (u.usage === "") return toast("请填写用量", "warn");
      u.busy = true;
      try {
        await svc("vehicle_part_mapping", "set_usage", {
          part_no: self.modal.d.part_no,
          veh_model: self.modal.d.veh_model,
          usage: Number(u.usage),
        });
        toast("用量已更新");
        u.show = false;
        self.modal.d = await svc("vehicle_part_mapping", "get",
          { part_no: self.modal.d.part_no, veh_model: self.modal.d.veh_model })
          .catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { u.busy = false; }
    },

    /* ---- 份额编辑 ---- */
    openShareEdit() {
      self.shareForm = { show: true, busy: false, share: self.modal.d.share ?? "" };
    },
    closeShareEdit() { self.shareForm.show = false; },
    async saveShare() {
      const s = self.shareForm;
      if (s.share === "") return toast("请填写份额", "warn");
      s.busy = true;
      try {
        await svc("vehicle_part_mapping", "set_share", {
          part_no: self.modal.d.part_no,
          veh_model: self.modal.d.veh_model,
          share: Number(s.share),
        });
        toast("份额已更新");
        s.show = false;
        self.modal.d = await svc("vehicle_part_mapping", "get",
          { part_no: self.modal.d.part_no, veh_model: self.modal.d.veh_model })
          .catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { s.busy = false; }
    },

    /* ---- 禁用 ---- */
    async disableMapping(d) {
      if (!confirm(`确认禁用 ${d.part_no} → ${d.veh_model} 的映射？`)) return;
      try {
        await svc("vehicle_part_mapping", "disable",
          { part_no: d.part_no, veh_model: d.veh_model });
        toast(`${d.part_no} → ${d.veh_model} 已禁用`);
        if (self.modal.d) self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    /* ---- 创建表单 ---- */
    openCreate() {
      self.form = {
        show: true, busy: false, more: false,
        part_no: "", veh_model: "", usage: "", share: "",
        lc_stage: "", lc_shape: "", sop: "", eop: "", source: "",
      };
    },
    closeForm() { self.form.show = false; },
    resetForm() {
      self.form.part_no = ""; self.form.veh_model = ""; self.form.usage = "";
      self.form.share = ""; self.form.lc_stage = ""; self.form.lc_shape = "";
      self.form.sop = ""; self.form.eop = ""; self.form.source = "";
    },

    async saveForm() {
      const f = self.form;
      if (!f.part_no) return toast("请填写零件号", "warn");
      if (!f.veh_model) return toast("请填写车型", "warn");
      f.busy = true;
      try {
        await svc("vehicle_part_mapping", "create", {
          part_no: f.part_no, veh_model: f.veh_model,
          usage: Number(f.usage || 0),
          share: Number(f.share || 0),
          lc_stage: f.lc_stage, lc_shape: f.lc_shape,
          sop: f.sop, eop: f.eop, source: f.source,
        });
        toast(`${f.part_no} → ${f.veh_model} 映射已创建`);
        f.show = false; self.resetForm();
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },
  });
  return self;
}
