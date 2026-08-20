/* app/sales-forecast/common_part_aggregation/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "common_part_aggregation", name: "通用件汇总", ic: "⊞",
  title: "通用件汇总修正", crumb: "总量层去重 · 对抗公地悲剧",
  order: 110,
};

export default function pageCommonPartAggregation() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    list: null,
    fStatus: "", fPartNo: "", fPeriod: "",

    modal: { open: false, loading: false, d: null },
    dedup: { show: false, busy: false, dedup_qty: "", dedup_reason: "" },

    form: { show: false, busy: false, part_no: "", period: "" },

    statusLabel(s) { return { "待汇总": "待汇总", "已修正": "已修正", "已确认": "已确认" }[s] || s || "—"; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      self.list = pageable(async (q) => svc("common_part_aggregation", "list",
        { part_no: self.fPartNo, period: self.fPeriod, status: self.fStatus, ...q }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    async viewAgg(doc) {
      self.modal = { open: true, loading: true, d: null };
      self.dedup.show = false;
      try {
        self.modal.d = await svc("common_part_aggregation", "get", { agg_no: doc.agg_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    openDedup() {
      const h = self.modal.d.header;
      self.dedup = { show: true, busy: false, dedup_qty: h.sum_qty || "", dedup_reason: "" };
    },
    async submitDedup() {
      if (!self.dedup.dedup_reason) return toast("折减依据必填（BR-02）", "warn");
      if (!self.dedup.dedup_qty && self.dedup.dedup_qty !== 0) return toast("修正后总量必填", "warn");
      self.dedup.busy = true;
      try {
        await svc("common_part_aggregation", "set_dedup", {
          agg_no: self.modal.d.header.agg_no,
          dedup_qty: Number(self.dedup.dedup_qty),
          dedup_reason: self.dedup.dedup_reason,
        });
        toast(`汇总单 ${self.modal.d.header.agg_no} 已修正`);
        self.dedup.show = false;
        self.modal.d = await svc("common_part_aggregation", "get", { agg_no: self.modal.d.header.agg_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.dedup.busy = false; }
    },

    async confirmAgg() {
      if (!confirm("确认该汇总单？确认后转入 D08 牛鞭修正。")) return;
      try {
        await svc("common_part_aggregation", "confirm", { agg_no: self.modal.d.header.agg_no });
        toast(`汇总单 ${self.modal.d.header.agg_no} 已确认`);
        self.modal.d = await svc("common_part_aggregation", "get", { agg_no: self.modal.d.header.agg_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    resetForm() {
      self.form.part_no = ""; self.form.period = "";
    },
    async saveForm() {
      const f = self.form;
      if (!f.part_no) return toast("通用件号必填", "warn");
      if (!f.period) return toast("期间必填", "warn");
      f.busy = true;
      try {
        const r = await svc("common_part_aggregation", "create", {
          part_no: f.part_no, period: f.period,
        });
        toast(`已创建汇总单 ${r.agg_no}（请逐客户添加明细）`);
        f.show = false; self.resetForm();
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },
  });
  return self;
}
