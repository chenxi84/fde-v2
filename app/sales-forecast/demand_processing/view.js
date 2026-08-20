/* app/sales-forecast/demand_processing/view.js —— 毛需求加工表（D04），加工链总账 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "demand_processing",
  name: "需求加工",
  ic: "⚙",
  title: "需求加工",
  crumb: "毛需求加工 · 基线生成 / 销售修正 / 核对 · 加工链总账",
  order: 30,
};

export default function pageDemandProcessing() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,

    /* ---- 列表 + 过滤 ---- */
    list: null,
    fStatus: "",

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 修正弹窗 ---- */
    adjForm: { open: false, busy: false, proc_batch: "", part_no: "", veh_model: "", period: "",
               adj_qty: 0, adj_reason_cat: "", adj_evidence: "" },

    /* ---- 核对弹窗 ---- */
    chkForm: { open: false, busy: false, proc_batch: "", part_no: "", veh_model: "", period: "",
               chk_result: "通过", chk_reason: "", chk_adj_qty: null },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("demand_processing", "list", {
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
        self.modalX.d = await svc("demand_processing", "get", { proc_batch: d.proc_batch });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 基线生成 ---- */
    async genBaseline(d) {
      const no = d.proc_batch || (d.header && d.header.proc_batch);
      if (!confirm("系统将根据 D03 拆解结果生成双路径基线，确定继续？")) return;
      try {
        const r = await svc("demand_processing", "generate_baseline", { proc_batch: no });
        toast("基线生成完成 · " + r.lines_generated + " 行");
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await svc("demand_processing", "get", { proc_batch: no });
        }
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    /* ---- 销售修正 ---- */
    openAdj(d) {
      const no = d.proc_batch || (d.header && d.header.proc_batch);
      self.adjForm = { open: true, busy: false, proc_batch: no, part_no: "", veh_model: "", period: "",
                       adj_qty: 0, adj_reason_cat: "", adj_evidence: "" };
    },
    closeAdj() { self.adjForm.open = false; },
    async submitAdj() {
      const f = self.adjForm;
      if (!f.part_no.trim()) return toast("请填写零件号", "warn");
      if (!f.veh_model.trim()) return toast("请填写车型", "warn");
      if (!f.period.trim()) return toast("请填写期间", "warn");
      if (!f.adj_reason_cat.trim()) return toast("请填写原因类别（三件套强制）", "warn");
      f.busy = true;
      try {
        await svc("demand_processing", "submit_adjustment", {
          proc_batch: f.proc_batch,
          part_no: f.part_no.trim(),
          veh_model: f.veh_model.trim(),
          period: f.period.trim(),
          adj_qty: parseFloat(f.adj_qty) || 0,
          adj_reason_cat: f.adj_reason_cat.trim(),
          adj_evidence: f.adj_evidence.trim() || undefined,
        });
        toast("修正已提交");
        self.closeAdj();
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await svc("demand_processing", "get", { proc_batch: f.proc_batch });
        }
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },

    /* ---- 核对 ---- */
    openChk(d) {
      const no = d.proc_batch || (d.header && d.header.proc_batch);
      self.chkForm = { open: true, busy: false, proc_batch: no, part_no: "", veh_model: "", period: "",
                       chk_result: "通过", chk_reason: "", chk_adj_qty: null };
    },
    closeChk() { self.chkForm.open = false; },
    async submitChk() {
      const f = self.chkForm;
      if (!f.part_no.trim()) return toast("请填写零件号", "warn");
      if (!f.veh_model.trim()) return toast("请填写车型", "warn");
      if (!f.period.trim()) return toast("请填写期间", "warn");
      if (f.chk_result === "退回" && !f.chk_reason.trim()) return toast("退回必须附书面理由", "warn");
      f.busy = true;
      try {
        await svc("demand_processing", "check_line", {
          proc_batch: f.proc_batch,
          part_no: f.part_no.trim(),
          veh_model: f.veh_model.trim(),
          period: f.period.trim(),
          chk_result: f.chk_result,
          chk_reason: f.chk_reason.trim() || undefined,
          chk_adj_qty: f.chk_adj_qty != null && f.chk_adj_qty !== "" ? parseFloat(f.chk_adj_qty) : undefined,
        });
        toast("核对完成 · " + f.chk_result);
        self.closeChk();
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await svc("demand_processing", "get", { proc_batch: f.proc_batch });
        }
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },

    statusLabel(s) {
      return { "进行中": "进行中", "全部核定": "全部核定", "已锁定": "已锁定" }[s] || s || "—";
    },
  });
  return self;
}
