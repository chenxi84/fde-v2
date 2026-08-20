/* app/sales-forecast/forecast_assessment/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "forecast_assessment", name: "预测考核", ic: "⊡",
  title: "预测转单率考核", crumb: "事后闭环 · 双口径 · FVA 视图",
  order: 140,
};

export default function pageForecastAssessment() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    list: null,
    fResult: "", fPartNo: "", fPeriod: "",

    modal: { open: false, loading: false, d: null },
    fvaData: [],
    fvaLoading: false,

    attrForm: { show: false, busy: false, fa_no: "", part_no: "", period: "",
      attribution: "", result: "计入考核", evidence: "" },

    calcForm: { show: false, busy: false, calcPeriod: "" },

    resultLabel(r) { return { "计入考核": "计入考核", "免责剔除": "免责剔除", "归因流程·策略": "归因流程·策略" }[r] || r || "—"; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      self.list = pageable(async (q) => svc("forecast_assessment", "list",
        { part_no: self.fPartNo, period: self.fPeriod, result: self.fResult, ...q }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    async viewFa(doc) {
      self.modal = { open: true, loading: true, d: null };
      self.attrForm.show = false;
      self.fvaData = [];
      try {
        self.modal.d = await svc("forecast_assessment", "get", { fa_no: doc.fa_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; self.attrForm.show = false; },

    async loadFva() {
      self.fvaLoading = true;
      try {
        const r = await svc("forecast_assessment", "get_fva_view", {
          part_no: self.modal.d.part_no, period: self.modal.d.period,
        });
        self.fvaData = r || [];
      } catch { /* api.js 已 toast */ } finally { self.fvaLoading = false; }
    },

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
          evidence: self.attrForm.evidence,
        });
        toast(`${self.attrForm.fa_no} 归因完成`);
        self.attrForm.show = false;
        self.modal.d = await svc("forecast_assessment", "get", { fa_no: self.attrForm.fa_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.attrForm.busy = false; }
    },

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
