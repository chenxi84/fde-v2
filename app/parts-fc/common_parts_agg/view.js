/* app/parts-fc/common_parts_agg/view.js */
import { svc, hue, fmt, dash, fmtTime, tryParse, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "common_parts_agg", name: "通用件汇总", ic: "📊",
  title: "通用件汇总修正", crumb: "汇总修正 · 跨销售去重 · 对抗公地悲剧",
  order: 90,
};

export default function pageCommonPartsAgg() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,

    /* ---- 主数据 autocomplete ---- */
    partOptions: [], vehOptions: [], custOptions: [], userOptions: [], autoFiltered: [], autoShow: "", autoDisplay: {},

    
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
    fStatus: "", fPartNo: "", fPeriod: "",

    modal: { open: false, loading: false, d: null },
    detailForm: { show: false, busy: false, oem_code: "", owner_sales: "", approved_qty: "", evidence_qty: "0", verbal_qty: "0" },
    dedup: { show: false, busy: false, dedup_qty: "", dedup_reason: "", anchor_ref: "" },
    split: { show: false, busy: false, split_detail: "" },

    form: { show: false, busy: false, part_no: "", period: "" },

    statusLabel(s) { return { "待汇总": "待汇总", "待修正": "待修正", "已修正": "已修正", "已确认": "已确认" }[s] || s || "—"; },

    async init() {
      self.list = pageable(async (q) => svc("common_parts_agg", "list",
        { part_no: self.fPartNo, period: self.fPeriod, status: self.fStatus, ...q }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
      try { const r = await svc("md_part","list",{page_size:9999},{quiet:true}); self.partOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.part_no]=i.part_name||i.part_no}); } catch {}
      try { const r = await svc("md_vehicle","list",{page_size:9999},{quiet:true}); self.vehOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.vehicle_code]=i.vehicle_name||i.vehicle_code}); } catch {}
      try { const r = await svc("md_customer","list",{page_size:9999},{quiet:true}); self.custOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.customer_code]=i.customer_name||i.customer_code}); } catch {}
      try { const r = await svc("md_user","list",{page_size:9999},{quiet:true}); self.userOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.user_code]=i.user_name||i.user_code}); } catch {}
    },

    search() { self.list.load(1); },

    async viewAgg(doc) {
      self.modal = { open: true, loading: true, d: null };
      self.dedup.show = false; self.detailForm.show = false; self.split.show = false;
      try {
        self.modal.d = await svc("common_parts_agg", "get", { agg_no: doc.agg_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    /* ---- 添加明细 ---- */
    openDetailForm() {
      self.detailForm = { show: true, busy: false, oem_code: "", owner_sales: "", approved_qty: "", evidence_qty: "0", verbal_qty: "0" };
    },
    async submitDetail() {
      const f = self.detailForm;
      if (!f.oem_code) return toast("OEM代码必填", "warn");
      if (!f.owner_sales) return toast("归属销售必填", "warn");
      if (!f.approved_qty && f.approved_qty !== 0) return toast("核定值必填", "warn");
      f.busy = true;
      try {
        await svc("common_parts_agg", "add_detail", {
          agg_no: self.modal.d.header.agg_no,
          oem_code: f.oem_code, owner_sales: f.owner_sales,
          approved_qty: Number(f.approved_qty),
          evidence_qty: Number(f.evidence_qty) || 0,
          verbal_qty: Number(f.verbal_qty) || 0,
        });
        toast("明细已添加");
        f.show = false;
        self.modal.d = await svc("common_parts_agg", "get", { agg_no: self.modal.d.header.agg_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },

    /* ---- 去重修正 ---- */
    openDedup() {
      const h = self.modal.d.header;
      self.dedup = { show: true, busy: false, dedup_qty: h.dedup_qty || h.sum_qty || "", dedup_reason: "", anchor_ref: "" };
    },
    async submitDedup() {
      if (!self.dedup.dedup_reason || self.dedup.dedup_reason.length < 50) return toast("折减依据至少50字（BR-02）", "warn");
      if (!self.dedup.dedup_qty && self.dedup.dedup_qty !== 0) return toast("修正后总量必填", "warn");
      self.dedup.busy = true;
      try {
        const payload = {
          agg_no: self.modal.d.header.agg_no,
          dedup_qty: Number(self.dedup.dedup_qty),
          dedup_reason: self.dedup.dedup_reason,
        };
        if (self.dedup.anchor_ref) payload.anchor_ref = tryParse(self.dedup.anchor_ref);
        await svc("common_parts_agg", "set_dedup", payload);
        toast(`汇总单 ${self.modal.d.header.agg_no} 已修正`);
        self.dedup.show = false;
        self.modal.d = await svc("common_parts_agg", "get", { agg_no: self.modal.d.header.agg_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.dedup.busy = false; }
    },

    /* ---- 拆回分配 ---- */
    openSplit() {
      self.split = { show: true, busy: false, split_detail: "" };
    },
    async submitSplit() {
      if (!self.split.split_detail) return toast("拆回分配JSON必填", "warn");
      let parsed;
      try { parsed = JSON.parse(self.split.split_detail); } catch { return toast("拆回分配格式须为合法JSON", "warn"); }
      self.split.busy = true;
      try {
        await svc("common_parts_agg", "set_split", {
          agg_no: self.modal.d.header.agg_no,
          split_detail: parsed,
        });
        toast("拆回分配已提交");
        self.split.show = false;
        self.modal.d = await svc("common_parts_agg", "get", { agg_no: self.modal.d.header.agg_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.split.busy = false; }
    },

    /* ---- 确认 ---- */
    async confirmAgg() {
      if (!confirm("确认该汇总单？确认后转入牛鞭修正。")) return;
      try {
        await svc("common_parts_agg", "confirm", { agg_no: self.modal.d.header.agg_no });
        toast(`汇总单 ${self.modal.d.header.agg_no} 已确认`);
        self.modal.d = await svc("common_parts_agg", "get", { agg_no: self.modal.d.header.agg_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    /* ---- 新建汇总单 ---- */
    resetForm() {
      self.form.part_no = ""; self.form.period = "";
    },
    async saveForm() {
      const f = self.form;
      if (!f.part_no) return toast("通用件号必填", "warn");
      if (!f.period) return toast("期间必填", "warn");
      f.busy = true;
      try {
        const r = await svc("common_parts_agg", "create", {
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
