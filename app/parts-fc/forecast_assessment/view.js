/* app/parts-fc/forecast_assessment/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "forecast_assessment", name: "预测考核", ic: "📝",
  title: "预测转单率考核", crumb: "事后闭环 · 转单率/FVA/达成率 · 归因反哺",
  order: 120,
};

const ATTRIBUTION_TYPES = [
  "销售多报", "OEM需求塌方", "事件影响", "基线方法失准",
];

export default function pageForecastAssessment() {
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
    fResult: "", fPartNo: "", fPeriod: "",

    modal: { open: false, loading: false, d: null },
    fvaData: [],
    fvaLoading: false,

    attrForm: { show: false, busy: false, fa_no: "", part_no: "", period: "",
      attribution: "", result: "计入考核", evidence: "" },

    recordForm: { show: false, busy: false, fa_no: "", part_no: "", veh_model: "", period: "",
      fcst_qty: "", actual_qty: "", settle_qty: "", base_qty: "", adj_qty: "" },

    calcForm: { show: false, busy: false, calcPeriod: "" },

    createForm: { show: false, busy: false, period: "" },

    resultLabel(r) { return { "计入考核": "计入考核", "免责剔除": "免责剔除", "归因流程·策略": "归因流程·策略" }[r] || r || "—"; },

    async init() {
      self.list = pageable(async (q) => svc("forecast_assessment", "list",
        { part_no: self.fPartNo, period: self.fPeriod, result: self.fResult, ...q }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
      try { const r = await svc("md_part","list",{page_size:9999},{quiet:true}); self.partOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.part_no]=i.part_name||i.part_no}); } catch {}
      try { const r = await svc("md_vehicle","list",{page_size:9999},{quiet:true}); self.vehOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.vehicle_code]=i.vehicle_name||i.vehicle_code}); } catch {}
      try { const r = await svc("md_customer","list",{page_size:9999},{quiet:true}); self.custOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.customer_code]=i.customer_name||i.customer_code}); } catch {}
      try { const r = await svc("md_user","list",{page_size:9999},{quiet:true}); self.userOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.user_code]=i.user_name||i.user_code}); } catch {}
    },

    search() { self.list.load(1); },

    /* ---- 详情模态 ---- */
    async viewFa(doc) {
      self.modal = { open: true, loading: true, d: null };
      self.attrForm.show = false;
      self.recordForm.show = false;
      self.fvaData = [];
      try {
        self.modal.d = await svc("forecast_assessment", "get", { fa_no: doc.fa_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; self.attrForm.show = false; self.recordForm.show = false; },

    /* ---- FVA 视图（静默加载） ---- */
    async loadFva() {
      self.fvaLoading = true;
      try {
        const r = await svc("forecast_assessment", "get_fva_view", {
          part_no: self.modal.d.part_no, period: self.modal.d.period,
        }, { quiet: true });
        self.fvaData = Array.isArray(r) ? r : [];
      } catch { /* 静默 */ } finally { self.fvaLoading = false; }
    },

    /* ---- 创建考核期批次 ---- */
    openCreate() {
      self.createForm = { show: true, busy: false, period: "" };
    },
    async submitCreate() {
      if (!self.createForm.period) return toast("考核期必填", "warn");
      self.createForm.busy = true;
      try {
        const r = await svc("forecast_assessment", "create", { period: self.createForm.period });
        toast(`已创建考核批次 ${r.fa_no}`);
        self.createForm.show = false;
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.createForm.busy = false; }
    },

    /* ---- 添加考核记录 ---- */
    openRecordForm() {
      self.recordForm = {
        show: true, busy: false,
        fa_no: self.modal.d.fa_no,
        part_no: "", veh_model: "", period: "",
        fcst_qty: "", actual_qty: "", settle_qty: "", base_qty: "", adj_qty: "",
      };
    },
    async submitRecord() {
      const f = self.recordForm;
      if (!f.part_no) return toast("零件号必填", "warn");
      if (!f.veh_model) return toast("车型必填", "warn");
      if (!f.period) return toast("期间必填", "warn");
      if (!f.fcst_qty || Number(f.fcst_qty) <= 0) return toast("预测值须大于0", "warn");
      if (!f.actual_qty && f.actual_qty !== 0) return toast("实际转单量必填", "warn");
      if (!f.settle_qty && f.settle_qty !== 0) return toast("结算量必填", "warn");
      if (!f.base_qty && f.base_qty !== 0) return toast("基线值必填", "warn");
      if (!f.adj_qty && f.adj_qty !== 0) return toast("修正值必填", "warn");
      f.busy = true;
      try {
        await svc("forecast_assessment", "add_record", {
          fa_no: f.fa_no, part_no: f.part_no, veh_model: f.veh_model, period: f.period,
          fcst_qty: Number(f.fcst_qty), actual_qty: Number(f.actual_qty),
          settle_qty: Number(f.settle_qty), base_qty: Number(f.base_qty), adj_qty: Number(f.adj_qty),
        });
        toast("考核记录已添加");
        f.show = false;
        self.modal.d = await svc("forecast_assessment", "get", { fa_no: f.fa_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },

    /* ---- 归因认定 ---- */
    openAttr() {
      self.attrForm = {
        show: true, busy: false,
        fa_no: self.modal.d.fa_no, part_no: self.modal.d.part_no, period: self.modal.d.period,
        attribution: "", result: "计入考核", evidence: "",
      };
    },
    async submitAttr() {
      if (!self.attrForm.attribution) return toast("请选择归因类别", "warn");
      if (!self.attrForm.result) return toast("请选择考核结论", "warn");
      if (self.attrForm.result === "免责剔除" && !self.attrForm.evidence)
        return toast("免责剔除须附举证（BR-03）", "warn");
      self.attrForm.busy = true;
      try {
        await svc("forecast_assessment", "attribute", {
          fa_no: self.attrForm.fa_no, part_no: self.attrForm.part_no, period: self.attrForm.period,
          attribution: self.attrForm.attribution, result: self.attrForm.result,
          evidence: self.attrForm.evidence || undefined,
        });
        toast(`${self.attrForm.fa_no} 归因完成`);
        self.attrForm.show = false;
        self.modal.d = await svc("forecast_assessment", "get", { fa_no: self.attrForm.fa_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.attrForm.busy = false; }
    },

    /* ---- 批量计算 ---- */
    openCalc() {
      self.calcForm = { show: true, busy: false, calcPeriod: self.fPeriod || "" };
    },
    async submitCalc() {
      if (!self.calcForm.calcPeriod) return toast("考核期间必填", "warn");
      self.calcForm.busy = true;
      try {
        const r = await svc("forecast_assessment", "calculate", { period: self.calcForm.calcPeriod });
        toast(`计算完成 · ${r.records} 条记录`);
        self.calcForm.show = false;
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.calcForm.busy = false; }
    },
  });
  return self;
}
