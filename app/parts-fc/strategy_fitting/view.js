/* app/parts-fc/strategy_fitting/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "strategy_fitting", name: "策略拟合", ic: "🎯",
  title: "策略仿真拟合", crumb: "策略拟合 · 滚动回测 · 候选策略打分排名",
  order: 80,
};

export default function pageStrategyFitting() {
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
    fPartNo: "", fStatus: "",

    modal: { open: false, loading: false, d: null },
    selectForm: { show: false, busy: false, cand_no: "" },
    candidateForm: { show: false, busy: false, strategy: "", inv_policy: "" },

    form: { show: false, busy: false, part_no: "", veh_model: "", demand_shape: "", data_range: "" },

    statusLabel(s) { return { "拟合中": "拟合中", "已选定": "已选定", "生效中": "生效中" }[s] || s || "—"; },
    shapeLabel(s) { return { "稳定": "稳定", "波动": "波动", "季节": "季节", "短生命周期": "短生命周期", "断续": "断续" }[s] || s || "—"; },

    async init() {
      self.list = pageable(async (q) => svc("strategy_fitting", "list",
        { part_no: self.fPartNo, status: self.fStatus, ...q }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
      try { const r = await svc("md_part","list",{page_size:9999},{quiet:true}); self.partOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.part_no]=i.part_name||i.part_no}); } catch {}
      try { const r = await svc("md_vehicle","list",{page_size:9999},{quiet:true}); self.vehOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.vehicle_code]=i.vehicle_name||i.vehicle_code}); } catch {}
      try { const r = await svc("md_customer","list",{page_size:9999},{quiet:true}); self.custOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.customer_code]=i.customer_name||i.customer_code}); } catch {}
      try { const r = await svc("md_user","list",{page_size:9999},{quiet:true}); self.userOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.user_code]=i.user_name||i.user_code}); } catch {}
    },

    search() { self.list.load(1); },

    /* ---- detail modal ---- */
    async viewFit(doc) {
      self.modal = { open: true, loading: true, d: null };
      self.selectForm.show = false;
      self.candidateForm.show = false;
      try {
        self.modal.d = await svc("strategy_fitting", "get", { fit_no: doc.fit_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    /* ---- add candidate ---- */
    openAddCandidate() {
      self.candidateForm = { show: true, busy: false, strategy: "", inv_policy: "" };
    },
    async submitAddCandidate() {
      if (!self.candidateForm.strategy) return toast("策略必填", "warn");
      if (!self.candidateForm.inv_policy) return toast("库存策略必填", "warn");
      self.candidateForm.busy = true;
      try {
        await svc("strategy_fitting", "add_candidate", {
          fit_no: self.modal.d.header.fit_no,
          strategy: self.candidateForm.strategy,
          inv_policy: self.candidateForm.inv_policy,
        });
        toast("已添加候选策略");
        self.candidateForm.show = false;
        self.modal.d = await svc("strategy_fitting", "get", { fit_no: self.modal.d.header.fit_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.candidateForm.busy = false; }
    },

    /* ---- run backtest ---- */
    async runBacktest() {
      try {
        const r = await svc("strategy_fitting", "run_backtest", { fit_no: self.modal.d.header.fit_no });
        toast(`回测完成 · ${r.fit_no} · ${r.rankings ? r.rankings.length + " 候选" : ""}`);
        self.modal.d = await svc("strategy_fitting", "get", { fit_no: self.modal.d.header.fit_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    /* ---- select strategy ---- */
    openSelect() {
      self.selectForm = { show: true, busy: false, cand_no: "" };
    },
    async submitSelect() {
      if (!self.selectForm.cand_no) return toast("请选择候选编号", "warn");
      const cand = (self.modal.d.candidates || []).find(c => c.cand_no === Number(self.selectForm.cand_no));
      if (cand && cand.score != null && cand.score < 60) {
        if (!confirm(`候选综合分 ${cand.score.toFixed(1)} 低于可接受线(60)，建议转借用基线。仍要选定？`)) return;
      }
      self.selectForm.busy = true;
      try {
        const r = await svc("strategy_fitting", "select_strategy", {
          fit_no: self.modal.d.header.fit_no, cand_no: Number(self.selectForm.cand_no),
        });
        toast(`已选定策略 ${r.selected_cand}（${r.strategy}）`);
        self.selectForm.show = false;
        self.modal.d = await svc("strategy_fitting", "get", { fit_no: self.modal.d.header.fit_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.selectForm.busy = false; }
    },

    /* ---- create ---- */
    resetForm() {
      const f = self.form;
      f.part_no = ""; f.veh_model = ""; f.demand_shape = ""; f.data_range = "";
    },
    async saveForm() {
      const f = self.form;
      if (!f.part_no) return toast("零件号必填", "warn");
      if (!f.veh_model) return toast("适用车型必填", "warn");
      if (!f.demand_shape) return toast("需求形态必选", "warn");
      f.busy = true;
      try {
        const r = await svc("strategy_fitting", "create", {
          part_no: f.part_no, veh_model: f.veh_model,
          demand_shape: f.demand_shape, data_range: f.data_range || undefined,
        });
        toast(`已创建拟合单 ${r.fit_no}（请添加候选策略并执行回测）`);
        f.show = false; self.resetForm();
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },
  });
  return self;
}
