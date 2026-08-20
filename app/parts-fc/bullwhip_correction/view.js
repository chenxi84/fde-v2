/* app/parts-fc/bullwhip_correction/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "bullwhip_correction", name: "牛鞭修正", ic: "📈",
  title: "牛鞭修正处理", crumb: "口径修正 · 派生需求vs终端消耗 · 发布前最后一道修正",
  order: 100,
};

const MECHANISMS = [
  "终端需求可见", "信息共享上传", "按预测准确率分配",
  "减小批量平准化", "安全库存协同", "缩短提前期",
];

export default function pageBullwhipCorrection() {
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
    fStatus: "", fTier: "", fPartNo: "", fPeriod: "",

    modal: { open: false, loading: false, d: null },
    correction: { show: false, busy: false, mech: {}, corr_note: "", final_qty: "" },

    form: { show: false, busy: false, more: false, part_no: "", period: "", tier: "",
      derived_qty: "", end_qty: "", end_source: "结算" },

    statusLabel(s) { return { "待处理": "待处理", "维持": "维持", "已修正": "已修正", "已确认": "已确认" }[s] || s || "—"; },
    tierLabel(t) { return t || "—"; },
    verdictLabel(v) { return v || "—"; },

    async init() {
      self.list = pageable(async (q) => svc("bullwhip_correction", "list",
        { part_no: self.fPartNo, period: self.fPeriod, tier: self.fTier, status: self.fStatus, ...q }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
      try { const r = await svc("md_part","list",{page_size:9999},{quiet:true}); self.partOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.part_no]=i.part_name||i.part_no}); } catch {}
      try { const r = await svc("md_vehicle","list",{page_size:9999},{quiet:true}); self.vehOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.vehicle_code]=i.vehicle_name||i.vehicle_code}); } catch {}
      try { const r = await svc("md_customer","list",{page_size:9999},{quiet:true}); self.custOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.customer_code]=i.customer_name||i.customer_code}); } catch {}
      try { const r = await svc("md_user","list",{page_size:9999},{quiet:true}); self.userOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.user_code]=i.user_name||i.user_code}); } catch {}
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
      const initMech = {};
      MECHANISMS.forEach(m => { initMech[m] = false; });
      self.correction = { show: true, busy: false, mech: initMech, corr_note: "", final_qty: self.modal.d.end_qty || "" };
    },
    corrActionSummary() {
      const selected = MECHANISMS.filter(m => self.correction.mech[m]);
      let s = selected.join("; ");
      if (self.correction.corr_note) s += (s ? " | " : "") + self.correction.corr_note;
      return s;
    },
    async submitCorrection() {
      const action = self.corrActionSummary();
      if (!action) return toast("至少勾选一项修正机制（BR-04）", "warn");
      if (!self.correction.final_qty && self.correction.final_qty !== 0) return toast("最终量必填", "warn");
      self.correction.busy = true;
      try {
        await svc("bullwhip_correction", "set_correction", {
          bw_no: self.modal.d.bw_no,
          corr_action: action,
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
      f.more = false;
    },
    async saveForm() {
      const f = self.form;
      if (!f.part_no) return toast("零件号必填", "warn");
      if (!f.period) return toast("期间必填", "warn");
      if (!f.tier) return toast("层级必选", "warn");
      f.busy = true;
      try {
        const r = await svc("bullwhip_correction", "create", {
          part_no: f.part_no, period: f.period, tier: f.tier,
          derived_qty: f.derived_qty ? Number(f.derived_qty) : undefined,
          end_qty: f.end_qty ? Number(f.end_qty) : undefined,
          end_source: f.end_source,
        });
        toast(`已创建 ${r.bw_no}（放大系数 ${r.amp_factor} · ${r.amp_verdict}）`);
        f.show = false; self.resetForm();
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },
  });
  return self;
}
