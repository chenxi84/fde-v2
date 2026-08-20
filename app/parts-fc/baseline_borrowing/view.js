/* app/parts-fc/baseline_borrowing/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "baseline_borrowing", name: "基线借用", ic: "\u{1F4CE}",
  title: "基线借用", crumb: "例外登记 · 历史不足零件 · 五种借法",
  order: 60,
};

export default function pageBaselineBorrowing() {
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

    list: null,
    fPartNo: "", fStatus: "", fMethod: "",

    modal: { open: false, loading: false, d: null },
    review: { show: false, busy: false, approved: true, comment: "" },
    calibrateForm: { show: false, busy: false, calibration_data: "" },
    closeDlg: { show: false, busy: false, reason: "" },

    form: { show: false, busy: false, editMode: false, editJyNo: "",
      part_no: "", veh_model: "", hist_months: 0,
      borrow_method: "", borrow_source: "", source_params: "",
      derived_qty: "{}", proc_batch: "", calibration: "" },

    statusLabel(s) { return { "待审核": "待审核", "生效": "生效", "已转自产": "已转自产", "已关闭": "已关闭" }[s] || s || "—"; },
    methodLabel(m) { return m || "—"; },

    async init() {
      self.list = pageable(async (q) => svc("baseline_borrowing", "list",
        { part_no: self.fPartNo, status: self.fStatus, borrow_method: self.fMethod, ...q }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
      try { const r = await svc("md_part","list",{page_size:9999},{quiet:true}); self.partOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.part_no]=i.part_name||i.part_no}); } catch {}
      try { const r = await svc("md_vehicle","list",{page_size:9999},{quiet:true}); self.vehOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.vehicle_code]=i.vehicle_name||i.vehicle_code}); } catch {}
      try { const r = await svc("md_customer","list",{page_size:9999},{quiet:true}); self.custOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.customer_code]=i.customer_name||i.customer_code}); } catch {}
      try { const r = await svc("md_user","list",{page_size:9999},{quiet:true}); self.userOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.user_code]=i.user_name||i.user_code}); } catch {}
    },

    search() { self.list.load(1); },

    async viewJy(doc) {
      self.modal = { open: true, loading: true, d: null };
      self.review.show = false;
      self.calibrateForm.show = false;
      self.closeDlg.show = false;
      try {
        self.modal.d = await svc("baseline_borrowing", "get", { jy_no: doc.jy_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    /* ---- Review ---- */
    openReview() {
      self.review = { show: true, busy: false, approved: true, comment: "" };
    },
    async submitReview() {
      if (!self.review.comment) return toast("审核意见必填", "warn");
      self.review.busy = true;
      try {
        await svc("baseline_borrowing", "review", {
          jy_no: self.modal.d.jy_no, approved: self.review.approved, comment: self.review.comment,
        });
        toast(`借用单 ${self.modal.d.jy_no} 审核${self.review.approved ? "通过" : "驳回"}`);
        self.review.show = false;
        self.modal.d = await svc("baseline_borrowing", "get", { jy_no: self.modal.d.jy_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.review.busy = false; }
    },

    /* ---- Calibrate ---- */
    openCalibrate() {
      self.calibrateForm = { show: true, busy: false, calibration_data: self.modal.d.calibration || "" };
    },
    async submitCalibrate() {
      if (!self.calibrateForm.calibration_data) return toast("校准数据必填", "warn");
      self.calibrateForm.busy = true;
      try {
        await svc("baseline_borrowing", "calibrate", {
          jy_no: self.modal.d.jy_no, calibration_data: self.calibrateForm.calibration_data,
        });
        toast(`借用单 ${self.modal.d.jy_no} 已校准`);
        self.calibrateForm.show = false;
        self.modal.d = await svc("baseline_borrowing", "get", { jy_no: self.modal.d.jy_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.calibrateForm.busy = false; }
    },

    /* ---- Close ---- */
    openClose() {
      self.closeDlg = { show: true, busy: false, reason: "" };
    },
    async submitClose() {
      if (!self.closeDlg.reason) return toast("关闭原因必填", "warn");
      self.closeDlg.busy = true;
      try {
        await svc("baseline_borrowing", "close", {
          jy_no: self.modal.d.jy_no, reason: self.closeDlg.reason,
        });
        toast(`借用单 ${self.modal.d.jy_no} 已关闭`);
        self.closeDlg.show = false;
        self.modal.d = await svc("baseline_borrowing", "get", { jy_no: self.modal.d.jy_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.closeDlg.busy = false; }
    },

    /* ---- Get Derived Baseline ---- */
    async getDerivedBaseline(doc) {
      try {
        const r = await svc("baseline_borrowing", "get_derived_baseline", { jy_no: doc.jy_no });
        if (r && r.derived_qty) {
          self.modal.d = { ...self.modal.d, derived_qty: r.derived_qty };
          toast(`已取回推导基线 · ${doc.jy_no}`);
        }
      } catch { /* api.js 已 toast */ }
    },

    /* ---- Edit (reopen create form) ---- */
    editJy(doc) {
      const f = self.form;
      f.editMode = true;
      f.editJyNo = doc.jy_no;
      f.part_no = doc.part_no || "";
      f.veh_model = doc.veh_model || "";
      f.hist_months = doc.hist_months || 0;
      f.borrow_method = doc.borrow_method || "";
      f.borrow_source = doc.borrow_source || "";
      f.source_params = doc.source_params || "";
      f.derived_qty = doc.derived_qty || "{}";
      f.proc_batch = doc.proc_batch || "";
      f.calibration = doc.calibration || "";
      f.show = true;
    },

    /* ---- Create / Update ---- */
    resetForm() {
      const f = self.form;
      f.editMode = false; f.editJyNo = "";
      f.part_no = ""; f.veh_model = ""; f.hist_months = 0;
      f.borrow_method = ""; f.borrow_source = ""; f.source_params = "";
      f.derived_qty = "{}"; f.proc_batch = ""; f.calibration = "";
    },
    async saveForm() {
      const f = self.form;
      if (!f.part_no) return toast("零件号必填", "warn");
      if (!f.veh_model) return toast("适用车型必填", "warn");
      if (f.hist_months < 0) return toast("历史月数不能为负数", "warn");
      if (!f.borrow_method) return toast("借用方法必选", "warn");
      if (!f.borrow_source) return toast("借用来源必填", "warn");
      if (!f.source_params) return toast("来源参数必填", "warn");
      if (!f.derived_qty) return toast("推导基线值必填", "warn");
      if (!f.proc_batch) return toast("关联加工批次必填", "warn");
      if (f.hist_months > 0 && !f.calibration) return toast("有早期数据必须填写校准记录（BR-02）", "warn");
      if (f.editMode) return toast("编辑功能暂未开放，请联系管理员", "warn");
      f.busy = true;
      try {
        const r = await svc("baseline_borrowing", "create", {
          part_no: f.part_no, veh_model: f.veh_model, hist_months: Number(f.hist_months),
          borrow_method: f.borrow_method, borrow_source: f.borrow_source,
          source_params: f.source_params, derived_qty: f.derived_qty || "{}",
          proc_batch: f.proc_batch, calibration: f.calibration || undefined,
        });
        toast(`已创建 ${r.jy_no}`);
        f.show = false; self.resetForm();
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },
  });
  return self;
}
