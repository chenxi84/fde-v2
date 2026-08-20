/* app/sales-forecast/demand_collection/view.js —— 主机厂原始需求收集表（D03），加工链入口 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "demand_collection",
  name: "需求收集",
  ic: "📥",
  title: "需求收集",
  crumb: "主机厂原始需求收集 · 版本化收集 + 信号拆解 · 加工链入口",
  order: 20,
};

export default function pageDemandCollection() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,

    /* ---- 列表 + 过滤 ---- */
    list: null,
    fStatus: "",
    keyword: "",

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 新建表单 ---- */
    form: { show: false, busy: false, oem_code: "", plant_code: "", fcst_version: "",
            base_period: "", demand_type: "月度滚动预测", source_channel: "", recv_date: "", remark: "" },

    /* ---- 作废弹窗 ---- */
    cancelForm: { open: false, busy: false, collect_no: "", reason: "" },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("demand_collection", "list", {
        status: self.fStatus || undefined,
        ...q,
      }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("demand_collection", "get", { collect_no: d.collect_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 操作 ---- */
    async confirmDecomp(d) {
      const no = d.collect_no || (d.header && d.header.collect_no);
      if (!confirm("确认拆解后将冻结版本并生成脉冲事件，确定继续？")) return;
      try {
        await svc("demand_collection", "confirm_decomposition", { collect_no: no });
        toast("拆解已确认 · " + no);
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d.header.status = "已拆解";
        }
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    openCancel(d) {
      const no = d.collect_no || (d.header && d.header.collect_no);
      self.cancelForm = { open: true, busy: false, collect_no: no, reason: "" };
    },
    closeCancel() { self.cancelForm.open = false; },
    async submitCancel() {
      const f = self.cancelForm;
      if (!f.reason.trim()) return toast("请填写作废原因", "warn");
      f.busy = true;
      try {
        await svc("demand_collection", "cancel", { collect_no: f.collect_no, reason: f.reason.trim() });
        toast("已作废 · " + f.collect_no);
        self.cancelForm.open = false;
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d.header.status = "已作废";
        }
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },

    /* ---- 新建收集单 ---- */
    resetForm() {
      const f = self.form;
      f.oem_code = ""; f.plant_code = ""; f.fcst_version = ""; f.base_period = "";
      f.demand_type = "月度滚动预测"; f.source_channel = ""; f.recv_date = ""; f.remark = "";
    },
    async saveForm() {
      const f = self.form;
      if (!f.oem_code) return toast("客户编码必填", "warn");
      if (!f.plant_code) return toast("工厂编码必填", "warn");
      if (!f.fcst_version) return toast("预测版本必填", "warn");
      if (!f.base_period) return toast("基准期间必填", "warn");
      f.busy = true;
      try {
        const r = await svc("demand_collection", "create", {
          oem_code: f.oem_code, plant_code: f.plant_code, fcst_version: f.fcst_version,
          base_period: f.base_period, demand_type: f.demand_type,
          source_channel: f.source_channel, recv_date: f.recv_date, remark: f.remark,
        });
        toast("已创建收集单 · " + r.collect_no);
        f.show = false; self.resetForm();
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },

    statusLabel(s) {
      return { "草稿": "草稿", "已拆解": "已拆解", "已锁定": "已锁定", "已替代": "已替代", "已作废": "已作废" }[s] || s || "—";
    },
  });
  return self;
}
