/* app/parts-fc/independent_event/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "independent_event", name: "独立事件", ic: "⚡",
  title: "独立事件登记", crumb: "事件台账 · 水位脉冲/断点/其他 · 趋势归趋势、事件归事件",
  order: 70,
};

export default function pageIndependentEvent() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,

    /* ---- 主数据 autocomplete ---- */
    partOptions: [], vehOptions: [], custOptions: [], userOptions: [], versionOptions: [], autoFiltered: [], autoShow: "", autoDisplay: {},

    
    filterAuto(field, query) {
      const q = (query || "").toLowerCase();
      const src = field === "part_no" ? self.partOptions : field === "vehicle_code" ? self.vehOptions : field === "customer_code" ? self.custOptions : field === "user_code" ? self.userOptions : field === "version_code" ? self.versionOptions : [];
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
    fPartNo: "", fEventType: "", fStatus: "", fPeriod: "",

    /* detail modal */
    modalX: { open: false, loading: false, d: null },

    /* close/cancel/subsided basis modal */
    closeForm: { open: false, busy: false, event_no: "", action: "", actionLabel: "", close_basis: "" },

    /* create forms */
    formSingle: { show: false, busy: false, event_type: "", part_no: "", period: "", event_qty: "",
      source_basis: "", oem_code: "", veh_model: "", source_ref: "", bp_batch: "", bp_date: "" },
    formBp: { show: false, busy: false, old_part_no: "", new_part_no: "", bp_date: "",
      old_qty: "", new_qty: "", oem_code: "", veh_model: "", period: "", source_basis: "设变通知", source_ref: "" },

    statusLabel(s) {
      return { "待确认": "待确认", "生效": "生效", "持续中": "持续中", "已回落": "已回落", "已关闭": "已关闭", "已取消": "已取消" }[s] || s || "—";
    },
    eventTypeLabel(t) {
      return { "水位脉冲": "水位脉冲", "断点旧件截断": "断点旧件截断", "断点新件启动": "断点新件启动", "其他": "其他" }[t] || t || "—";
    },

    async init() {
      self.list = pageable(async (q) => svc("independent_event", "list", {
        part_no: self.fPartNo, event_type: self.fEventType, status: self.fStatus, period: self.fPeriod, ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
      try { const r = await svc("md_part","list",{page_size:9999},{quiet:true}); self.partOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.part_no]=i.part_name||i.part_no}); } catch {}
      try { const r = await svc("md_vehicle","list",{page_size:9999},{quiet:true}); self.vehOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.vehicle_code]=i.vehicle_name||i.vehicle_code}); } catch {}
      try { const r = await svc("md_customer","list",{page_size:9999},{quiet:true}); self.custOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.customer_code]=i.customer_name||i.customer_code}); } catch {}
      try { const r = await svc("md_user","list",{page_size:9999},{quiet:true}); self.userOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.user_code]=i.user_name||i.user_code}); } catch {}
      try { const r = await svc("md_fcst_version","list",{page_size:9999},{quiet:true}); self.versionOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.version_code]=i.period||i.version_code}); } catch {}
    },

    search() { self.list.load(1); },

    /* ---- detail modal ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("independent_event", "get", { event_no: d.event_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- state machine actions ---- */
    async act(d, kind) {
      const no = d.event_no;
      try {
        if (kind === "confirm") {
          await svc("independent_event", "confirm", { event_no: no });
          toast("已确认 · " + no);
        } else if (kind === "mark_sustained") {
          await svc("independent_event", "mark_sustained", { event_no: no });
          toast("已标记持续中 · " + no);
        } else if (kind === "mark_subsided") {
          self.openClose(no, "mark_subsided", "标记回落");
          return;
        } else if (kind === "close") {
          self.openClose(no, "close", "关闭");
          return;
        } else if (kind === "cancel") {
          self.openClose(no, "cancel", "取消");
          return;
        } else return;
        if (self.modalX.open) self.modalX.d = await svc("independent_event", "get", { event_no: no }).catch(() => self.modalX.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    /* ---- close basis modal ---- */
    openClose(event_no, action, actionLabel) {
      self.closeForm = { open: true, busy: false, event_no, action, actionLabel, close_basis: "" };
    },
    closeCloseForm() { self.closeForm.open = false; },
    async submitClose() {
      const f = self.closeForm;
      if (!f.close_basis.trim()) return toast("请填写依据/原因", "warn");
      f.busy = true;
      try {
        if (f.action === "mark_subsided") {
          await svc("independent_event", "mark_subsided", { event_no: f.event_no, close_basis: f.close_basis.trim() });
          toast("已标记回落 · " + f.event_no);
        } else if (f.action === "close") {
          await svc("independent_event", "close", { event_no: f.event_no, close_basis: f.close_basis.trim() });
          toast("已关闭 · " + f.event_no);
        } else if (f.action === "cancel") {
          await svc("independent_event", "cancel", { event_no: f.event_no, close_basis: f.close_basis.trim() });
          toast("已取消 · " + f.event_no);
        }
        self.closeForm.open = false;
        if (self.modalX.open) self.modalX.d = await svc("independent_event", "get", { event_no: f.event_no }).catch(() => self.modalX.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },

    /* ---- create single event ---- */
    resetSingle() {
      const f = self.formSingle;
      f.event_type = ""; f.part_no = ""; f.period = ""; f.event_qty = "";
      f.source_basis = ""; f.oem_code = ""; f.veh_model = ""; f.source_ref = "";
      f.bp_batch = ""; f.bp_date = "";
    },
    async saveSingle() {
      const f = self.formSingle;
      if (!f.event_type) return toast("事件类型必选", "warn");
      if (!f.part_no) return toast("零件号必填", "warn");
      if (!f.period) return toast("归属期间必填", "warn");
      if (!f.event_qty) return toast("事件量必填", "warn");
      if (!f.source_basis) return toast("来源依据必选", "warn");
      if (!f.oem_code) return toast("OEM编码必填", "warn");
      if (!f.veh_model) return toast("车型必填", "warn");
      f.busy = true;
      try {
        const r = await svc("independent_event", "create", {
          event_type: f.event_type, part_no: f.part_no, period: f.period,
          event_qty: f.event_qty, source_basis: f.source_basis, oem_code: f.oem_code,
          veh_model: f.veh_model, source_ref: f.source_ref || undefined,
          bp_batch: f.bp_batch || undefined, bp_date: f.bp_date || undefined,
        });
        toast(`已创建 ${r.event_no}`);
        f.show = false; self.resetSingle();
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },

    /* ---- create BP pair ---- */
    resetBp() {
      const f = self.formBp;
      f.old_part_no = ""; f.new_part_no = ""; f.bp_date = "";
      f.old_qty = ""; f.new_qty = ""; f.oem_code = ""; f.veh_model = "";
      f.period = ""; f.source_basis = "设变通知"; f.source_ref = "";
    },
    async saveBp() {
      const f = self.formBp;
      if (!f.old_part_no) return toast("旧件号必填", "warn");
      if (!f.new_part_no) return toast("新件号必填", "warn");
      if (!f.bp_date) return toast("断点日期必填", "warn");
      if (!f.old_qty) return toast("旧件量必填", "warn");
      if (!f.new_qty) return toast("新件量必填", "warn");
      if (!f.oem_code) return toast("OEM编码必填", "warn");
      if (!f.veh_model) return toast("车型必填", "warn");
      if (!f.period) return toast("归属期间必填", "warn");
      f.busy = true;
      try {
        const r = await svc("independent_event", "create_bp_pair", {
          old_part_no: f.old_part_no, new_part_no: f.new_part_no, bp_date: f.bp_date,
          old_qty: f.old_qty, new_qty: f.new_qty, oem_code: f.oem_code,
          veh_model: f.veh_model, period: f.period,
          source_basis: f.source_basis || "设变通知",
          source_ref: f.source_ref || undefined,
        });
        toast(`已创建断点事件 ${r.event_no}`);
        f.show = false; self.resetBp();
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },

    /* helper to check if event type is bp-related */
    isBpType(t) { return t && (t.includes("断点") || t === "断点旧件截断" || t === "断点新件启动"); },
  });
  return self;
}
