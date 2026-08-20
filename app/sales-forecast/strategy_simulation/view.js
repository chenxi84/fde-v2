/* app/sales-forecast/strategy_simulation/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "strategy_simulation", name: "策略仿真", ic: "⊿",
  title: "策略仿真拟合", crumb: "回测选优 · 基线方法军火库",
  order: 130,
};

export default function pageStrategySimulation() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    list: null,
    fStatus: "", fShape: "", fPartNo: "",

    modal: { open: false, loading: false, d: null },
    selectForm: { show: false, busy: false, cand_no: "" },

    form: { show: false, busy: false, part_no: "", veh_model: "", demand_shape: "", data_range: "" },

    statusLabel(s) { return { "拟合中": "拟合中", "已选定": "已选定", "生效中": "生效中", "已替代": "已替代" }[s] || s || "—"; },
    shapeLabel(s) { return { "稳定": "稳定", "波动": "波动", "季节": "季节", "短生命周期": "短生命周期", "断续": "断续" }[s] || s || "—"; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      self.list = pageable(async (q) => svc("strategy_simulation", "list",
        { part_no: self.fPartNo, status: self.fStatus, ...q }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    async viewFit(doc) {
      self.modal = { open: true, loading: true, d: null };
      self.selectForm.show = false;
      try {
        self.modal.d = await svc("strategy_simulation", "get", { fit_no: doc.fit_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    async runBacktest() {
      try {
        const r = await svc("strategy_simulation", "run_backtest", { fit_no: self.modal.d.header.fit_no });
        toast(`回测完成 · ${r.fit_no} · ${r.rankings ? r.rankings.length + " 候选" : ""}`);
        self.modal.d = await svc("strategy_simulation", "get", { fit_no: self.modal.d.header.fit_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    openSelect() {
      self.selectForm = { show: true, busy: false, cand_no: "" };
    },
    async submitSelect() {
      if (!self.selectForm.cand_no) return toast("请选择候选编号", "warn");
      const cand = (self.modal.d.candidates || []).find(c => c.cand_no === Number(self.selectForm.cand_no));
      if (cand && cand.score != null && cand.score < 60) {
        if (!confirm(`候选综合分 ${cand.score.toFixed(1)} 低于可接受线(60)，建议转借用基线 D05（BR-03）。仍要选定？`)) return;
      }
      self.selectForm.busy = true;
      try {
        const r = await svc("strategy_simulation", "select_strategy", {
          fit_no: self.modal.d.header.fit_no, cand_no: Number(self.selectForm.cand_no),
        });
        toast(`已选定策略 ${r.selected_cand}（${r.strategy}）`);
        self.selectForm.show = false;
        self.modal.d = await svc("strategy_simulation", "get", { fit_no: self.modal.d.header.fit_no }).catch(() => self.modal.d);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.selectForm.busy = false; }
    },

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
        const r = await svc("strategy_simulation", "create", {
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
