/* app/parts-fc/vehicle_part_map/view.js —— 车型零件映射 */
import { svc, hue, fmt, dash, fmtTime, tryParse, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "vehicle_part_map", name: "车型零件映射", ic: "🔗",
  title: "车型零件映射", crumb: "主数据 · 量纲权威源 · 用量/份额/生命周期",
  order: 30,
};

export default function pageVehiclePartMap() {
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
    fPartNo: "", fVehModel: "", fLcStage: "", fStatus: "",

    /* ---- 详情模态 ---- */
    modal: { open: false, loading: false, d: null },

    /* ---- 用量变更模态 ---- */
    usageForm: { show: false, busy: false, new_usage: "", effective_date: "", basis: "" },

    /* ---- 份额变更模态 ---- */
    shareForm: { show: false, busy: false, new_share: "", effective_date: "", basis: "" },

    /* ---- 停用确认 ---- */
    disableForm: { show: false, busy: false, reason: "" },

    /* ---- 创建/编辑表单 ---- */
    form: {
      show: false, busy: false, more: false, mode: "create",
      edit_part_no: "", edit_veh_model: "",
      part_no: "", veh_model: "", platform: "", usage: "", share: "",
      lc_stage: "", lc_shape: "", sop: "", eop: "", source: "", status: "生效",
    },

    lcStageOptions: ["爬坡", "成熟", "衰退", "EOP临近"],
    lcShapeOptions: ["传统", "上市高后下滑"],
    statusOptions: ["生效", "停用"],

    async init() {
      self.list = pageable(async (q) => svc("vehicle_part_map", "list", {
        part_no: self.fPartNo || undefined,
        veh_model: self.fVehModel || undefined,
        lc_stage: self.fLcStage || undefined,
        status: self.fStatus || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
      try { const r = await svc("md_part","list",{page_size:9999},{quiet:true}); self.partOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.part_no]=i.part_name||i.part_no}); } catch {}
      try { const r = await svc("md_vehicle","list",{page_size:9999},{quiet:true}); self.vehOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.vehicle_code]=i.vehicle_name||i.vehicle_code}); } catch {}
      try { const r = await svc("md_customer","list",{page_size:9999},{quiet:true}); self.custOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.customer_code]=i.customer_name||i.customer_code}); } catch {}
      try { const r = await svc("md_user","list",{page_size:9999},{quiet:true}); self.userOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.user_code]=i.user_name||i.user_code}); } catch {}
    },

    search() { self.list.load(1); },
    clearFilters() {
      self.fPartNo = ""; self.fVehModel = ""; self.fLcStage = ""; self.fStatus = "";
      self.search();
    },

    /* ---- 详情模态 ---- */
    async viewDetail(d) {
      self.modal = { open: true, loading: true, d: null };
      self.usageForm.show = false;
      self.shareForm.show = false;
      self.disableForm.show = false;
      try {
        const [detail, usageHistory] = await Promise.all([
          svc("vehicle_part_map", "get", { part_no: d.part_no, veh_model: d.veh_model }),
          svc("vehicle_part_map", "get_usage_history", { part_no: d.part_no, veh_model: d.veh_model }).catch(() => []),
        ]);
        self.modal.d = { ...detail, usage_history: usageHistory };
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    /* ---- 用量变更 ---- */
    openUsageForm() {
      self.usageForm = { show: true, busy: false, new_usage: "", effective_date: "", basis: "" };
    },
    closeUsageForm() { self.usageForm.show = false; },
    async saveUsage() {
      const u = self.usageForm;
      if (!u.new_usage) return toast("请填写新用量", "warn");
      if (!u.effective_date) return toast("请填写生效日期", "warn");
      if (!u.basis) return toast("请填写变更依据", "warn");
      u.busy = true;
      try {
        await svc("vehicle_part_map", "set_usage", {
          part_no: self.modal.d.part_no,
          veh_model: self.modal.d.veh_model,
          new_usage: Number(u.new_usage),
          effective_date: u.effective_date,
          basis: u.basis,
        });
        toast("用量已更新");
        u.show = false;
        self.modal.d = await svc("vehicle_part_map", "get",
          { part_no: self.modal.d.part_no, veh_model: self.modal.d.veh_model })
          .catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { } finally { u.busy = false; }
    },

    /* ---- 份额变更 ---- */
    openShareForm() {
      self.shareForm = { show: true, busy: false, new_share: "", effective_date: "", basis: "" };
    },
    closeShareForm() { self.shareForm.show = false; },
    async saveShare() {
      const s = self.shareForm;
      if (!s.new_share) return toast("请填写新份额", "warn");
      if (!s.effective_date) return toast("请填写生效日期", "warn");
      if (!s.basis) return toast("请填写变更依据", "warn");
      s.busy = true;
      try {
        await svc("vehicle_part_map", "set_share", {
          part_no: self.modal.d.part_no,
          veh_model: self.modal.d.veh_model,
          new_share: Number(s.new_share),
          effective_date: s.effective_date,
          basis: s.basis,
        });
        toast("份额已更新");
        s.show = false;
        self.modal.d = await svc("vehicle_part_map", "get",
          { part_no: self.modal.d.part_no, veh_model: self.modal.d.veh_model })
          .catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { } finally { s.busy = false; }
    },

    /* ---- 停用 ---- */
    openDisable() {
      self.disableForm = { show: true, busy: false, reason: "" };
    },
    closeDisable() { self.disableForm.show = false; },
    async saveDisable() {
      const d = self.disableForm;
      if (!d.reason) return toast("请填写停用原因", "warn");
      d.busy = true;
      try {
        await svc("vehicle_part_map", "disable", {
          part_no: self.modal.d.part_no,
          veh_model: self.modal.d.veh_model,
          reason: d.reason,
        });
        toast(`${self.modal.d.part_no} → ${self.modal.d.veh_model} 已停用`);
        d.show = false;
        self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { } finally { d.busy = false; }
    },

    /* ---- 创建/编辑表单 ---- */
    openCreate() {
      self.form = {
        show: true, busy: false, more: false, mode: "create",
        edit_part_no: "", edit_veh_model: "",
        part_no: "", veh_model: "", platform: "", usage: "", share: "",
        lc_stage: "", lc_shape: "", sop: "", eop: "", source: "", status: "生效",
      };
    },
    openEdit(d) {
      self.form = {
        show: true, busy: false, more: false, mode: "edit",
        edit_part_no: d.part_no, edit_veh_model: d.veh_model,
        part_no: d.part_no, veh_model: d.veh_model,
        platform: d.platform || "",
        lc_stage: d.lc_stage || "", lc_shape: d.lc_shape || "",
        sop: (d.sop || "").slice(0, 10), eop: (d.eop || "").slice(0, 10),
        source: d.source || "", status: d.status || "生效",
        usage: d.usage || "", share: d.share || "",
      };
    },
    closeForm() { self.form.show = false; },

    async saveForm() {
      const f = self.form;
      if (!f.part_no) return toast("请填写零件号", "warn");
      if (!f.veh_model) return toast("请填写车型", "warn");
      if (f.mode === "create") {
        if (!f.usage && f.usage !== 0) return toast("请填写用量", "warn");
        if (!f.share && f.share !== 0) return toast("请填写份额", "warn");
        if (!f.lc_stage) return toast("请选择LC阶段", "warn");
        if (!f.lc_shape) return toast("请选择LC形态", "warn");
        if (!f.sop) return toast("请填写SOP", "warn");
        if (!f.source) return toast("请填写数据来源", "warn");
      }
      f.busy = true;
      try {
        if (f.mode === "edit") {
          await svc("vehicle_part_map", "update", {
            part_no: f.edit_part_no, veh_model: f.edit_veh_model,
            kwargs: {
              platform: f.platform, lc_stage: f.lc_stage, lc_shape: f.lc_shape,
              sop: f.sop, eop: f.eop, source: f.source, status: f.status,
            },
          });
          toast(`映射 ${f.edit_part_no} → ${f.edit_veh_model} 已更新`);
        } else {
          await svc("vehicle_part_map", "create", {
            part_no: f.part_no, veh_model: f.veh_model,
            platform: f.platform, usage: Number(f.usage), share: Number(f.share),
            lc_stage: f.lc_stage, lc_shape: f.lc_shape,
            sop: f.sop, eop: f.eop, source: f.source,
          });
          toast(`${f.part_no} → ${f.veh_model} 映射已创建`);
        }
        f.show = false;
        await self.list.load(self.list.page);
      } catch { } finally { f.busy = false; }
    },
  });
  return self;
}
