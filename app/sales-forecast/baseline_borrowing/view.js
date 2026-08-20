/* app/sales-forecast/baseline_borrowing/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "baseline_borrowing", name: "基线借用", ic: "⇋",
  title: "基线借用台账", crumb: "历史不足零件 · 基线例外登记与审核",
  order: 100,
};

export default function pageBaselineBorrowing() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    list: null,
    fStatus: "", fMethod: "",

    modal: { open: false, loading: false, d: null },
    review: { show: false, busy: false, approved: true, comment: "" },
    closeDlg: { show: false, busy: false, reason: "" },

    form: { show: false, busy: false, part_no: "", veh_model: "", hist_months: 0,
      borrow_method: "", borrow_source: "", source_params: "",
      derived_qty: "{}", proc_batch: "", calibration: "" },

    statusLabel(s) { return { "待审核": "待审核", "生效": "生效", "已转自产": "已转自产", "已关闭": "已关闭" }[s] || s || "—"; },
    methodLabel(m) { return m || "—"; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      self.list = pageable(async (q) => svc("baseline_borrowing", "list",
        { status: self.fStatus, borrow_method: self.fMethod, ...q }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    async viewJy(doc) {
      self.modal = { open: true, loading: true, d: null };
      self.review.show = false;
      self.closeDlg.show = false;
      try {
        self.modal.d = await svc("baseline_borrowing", "get", { jy_no: doc.jy_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

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

    resetForm() {
      const f = self.form;
      f.part_no = ""; f.veh_model = ""; f.hist_months = 0;
      f.borrow_method = ""; f.borrow_source = ""; f.source_params = "";
      f.derived_qty = "{}"; f.proc_batch = ""; f.calibration = "";
    },
    async saveForm() {
      const f = self.form;
      if (!f.part_no) return toast("零件号必填", "warn");
      if (!f.veh_model) return toast("适用车型必填", "warn");
      if (!f.borrow_method) return toast("借用方法必选", "warn");
      if (!f.borrow_source) return toast("借用来源必填", "warn");
      if (!f.source_params) return toast("来源参数必填", "warn");
      if (!f.proc_batch) return toast("关联加工批次必填", "warn");
      if (f.hist_months > 0 && !f.calibration) return toast("有早期数据必须填写校准记录（BR-02）", "warn");
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
