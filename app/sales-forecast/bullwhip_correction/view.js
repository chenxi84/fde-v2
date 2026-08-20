/* app/sales-forecast/bullwhip_correction/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "bullwhip_correction", name: "牛鞭修正", ic: "↯",
  title: "牛鞭修正处理", crumb: "终端口径锚定 · 发布前最后一道修正",
  order: 120,
};

export default function pageBullwhipCorrection() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    list: null,
    fStatus: "", fTier: "", fPartNo: "",

    modal: { open: false, loading: false, d: null },
    correction: { show: false, busy: false, corr_action: "", final_qty: "" },

    form: { show: false, busy: false, part_no: "", period: "", tier: "",
      derived_qty: "", end_qty: "", end_source: "结算" },

    statusLabel(s) { return { "待处理": "待处理", "维持": "维持", "已修正": "已修正", "已确认": "已确认" }[s] || s || "—"; },
    tierLabel(t) { return t || "—"; },
    verdictLabel(v) { return v || "—"; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      self.list = pageable(async (q) => svc("bullwhip_correction", "list",
        { part_no: self.fPartNo, tier: self.fTier, status: self.fStatus, ...q }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    async viewBw(doc) {
      self.modal = { open: true, loading: true, d: null };
      self.correction.show = false;
      try {
        self.modal.d = await svc("bullwhip_correction", "get", { bw_no: doc.bw_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    async maintainBw() {
      if (!confirm(`确认维持 ${self.modal.d.bw_no}？将转入已确认状态。`)) return;
      try {
        await svc("bullwhip_correction", "maintain", { bw_no: self.modal.d.bw_no });
        toast(`${self.modal.d.bw_no} 已确认`);
        self.modal.d = await svc("bullwhip_correction", "get", { bw_no: self.modal.d.bw_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    openCorrection() {
      self.correction = { show: true, busy: false, corr_action: "", final_qty: self.modal.d.end_qty || "" };
    },
    async submitCorrection() {
      if (!self.correction.corr_action) return toast("修正须登记所落机制与依据（BR-04）", "warn");
      if (!self.correction.final_qty && self.correction.final_qty !== 0) return toast("最终量必填", "warn");
      self.correction.busy = true;
      try {
        await svc("bullwhip_correction", "set_correction", {
          bw_no: self.modal.d.bw_no,
          corr_action: self.correction.corr_action,
          final_qty: Number(self.correction.final_qty),
        });
        toast(`${self.modal.d.bw_no} 已修正`);
        self.correction.show = false;
        self.modal.d = await svc("bullwhip_correction", "get", { bw_no: self.modal.d.bw_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.correction.busy = false; }
    },

    async confirmBw() {
      if (!confirm(`确认 ${self.modal.d.bw_no}？确认后转入发布。`)) return;
      try {
        await svc("bullwhip_correction", "confirm", { bw_no: self.modal.d.bw_no });
        toast(`${self.modal.d.bw_no} 已确认`);
        self.modal.d = await svc("bullwhip_correction", "get", { bw_no: self.modal.d.bw_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    resetForm() {
      const f = self.form;
      f.part_no = ""; f.period = ""; f.tier = ""; f.derived_qty = ""; f.end_qty = ""; f.end_source = "结算";
    },
    async saveForm() {
      const f = self.form;
      if (!f.part_no) return toast("零件号必填", "warn");
      if (!f.period) return toast("期间必填", "warn");
      if (!f.tier) return toast("层级必选", "warn");
      if (!f.derived_qty) return toast("派生需求量必填", "warn");
      if (!f.end_qty) return toast("终端需求量必填", "warn");
      f.busy = true;
      try {
        const r = await svc("bullwhip_correction", "create", {
          part_no: f.part_no, period: f.period, tier: f.tier,
          derived_qty: Number(f.derived_qty), end_qty: Number(f.end_qty), end_source: f.end_source,
        });
        toast(`已创建 ${r.bw_no}（放大系数 ${r.amp_factor} · ${r.amp_verdict}）`);
        f.show = false; self.resetForm();
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },
  });
  return self;
}
