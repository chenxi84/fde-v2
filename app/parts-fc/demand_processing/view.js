/* app/parts-fc/demand_processing/view.js —— 毛需求加工表（D04），加工链总账 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "demand_processing",
  name: "毛需求加工",
  ic: "⚙",
  title: "毛需求加工",
  crumb: "核心加工 · 统计基线→销售修正→修正核对 · 核定毛需求",
  order: 50,
};

export default function pageDemandProcessing() {
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

    /* ---- 列表 + 过滤 ---- */
    list: null,
    fStatus: "",
    fOemCode: "",
    oemOptions: [],


    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 基线确认（批量列表模式）---- */
    baselineForm: { open: false, busy: false, proc_batch: "", rows: [] },

    /* ---- 销售修正 —— 批量列表模式 ---- */
    adjForm: { open: false, busy: false, proc_batch: "", rows: [] },

    reasonOptions: ["客户预告修正", "自行预估修正", "促销活动", "车型减产", "车型增产", "季节性调整", "其他"],

    /* ---- 核对（批量列表模式）---- */
    chkForm: { open: false, busy: false, proc_batch: "", rows: [] },

    async init() {
      self.list = pageable(async (q) => svc("demand_processing", "list", {
        oem_code: self.fOemCode || undefined,
        status: self.fStatus || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      await self.list.load();
      try {
        const all = await svc("demand_processing", "list", { all: 1 });
        self.oemOptions = [...new Set((all.items || []).map((d) => d.oem_code).filter(Boolean))];
      } catch { /* 去重加载非关键 */ }
      try { const r = await svc("md_part","list",{page_size:9999},{quiet:true}); self.partOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.part_no]=i.part_name||i.part_no}); } catch {}
      try { const r = await svc("md_vehicle","list",{page_size:9999},{quiet:true}); self.vehOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.vehicle_code]=i.vehicle_name||i.vehicle_code}); } catch {}
      try { const r = await svc("md_customer","list",{page_size:9999},{quiet:true}); self.custOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.customer_code]=i.customer_name||i.customer_code}); } catch {}
      try { const r = await svc("md_user","list",{page_size:9999},{quiet:true}); self.userOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.user_code]=i.user_name||i.user_code}); } catch {}
    },

    search() { self.list.load(1); },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        const data = await svc("demand_processing", "get", { proc_batch: d.proc_batch });
        // 合并三表：baseline + adjustment + check → 按 (part_no, veh_model, period) 合并
        const adjMap = {}; (data.adjustments || []).forEach(a => { adjMap[a.part_no + '|' + a.veh_model + '|' + a.period] = a; });
        const chkMap = {}; (data.checks || []).forEach(c => { chkMap[c.part_no + '|' + c.veh_model + '|' + c.period] = c; });
        data._merged = (data.baselines || []).map(b => {
          const key = b.part_no + '|' + b.veh_model + '|' + b.period;
          return { ...b, _adj: adjMap[key] || null, _chk: chkMap[key] || null };
        });
        self.modalX.d = data;
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 生成基线 ---- */
    baselineGenForm: { open: false, busy: false, loading: true, proc_batch: "", groups: [], summary: "", result: null },

    methodInfo: {
      "移动平均": { desc: "最近 N 期简单平均", suit: "平稳需求" },
      "指数平滑": { desc: "α=0.3 指数加权，近期权重高", suit: "趋势衰减、近期更关键" },
      "阶跃外推": { desc: "检测永久性跳变，用最新值", suit: "产能切换、新车型爬坡" },
    },

    async openGenBaseline(d) {
      const no = d.proc_batch || (d.header && d.header.proc_batch);
      self.baselineGenForm = { open: true, busy: false, loading: true, proc_batch: no, groups: [], summary: "", result: null };
      try {
        const r = await svc("demand_processing", "analyze_baseline_methods", { proc_batch: no });
        self.baselineGenForm.groups = (r.groups || []).map(g => ({ ...g, selected: g.recommend }));
        self.baselineGenForm.summary = r.summary || "";
        self.baselineGenForm.loading = false;
      } catch { self.baselineGenForm.open = false; }
    },
    closeGenBaseline() { self.baselineGenForm.open = false; },

    acceptAllBaselineRecommends() {
      self.baselineGenForm.groups.forEach(g => { g.selected = g.recommend; });
    },

    async runGenBaseline() {
      const f = self.baselineGenForm;
      // 用统计最多的方法作为统一参数（简化，也可后续支持分组方法）
      const counts = {};
      f.groups.forEach(g => { counts[g.selected] = (counts[g.selected] || 0) + 1; });
      const topMethod = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || "移动平均";
      f.busy = true; f.result = null;
      try {
        const r = await svc("demand_processing", "generate_baseline", { proc_batch: f.proc_batch, method: topMethod });
        f.result = r;
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await svc("demand_processing", "get", { proc_batch: f.proc_batch });
        }
        self.fStatus = ""; await self.list.load(1);
      } catch { } finally { f.busy = false; }
    },

    /* ---- 基线确认（批量列表模式）---- */
    async openBaseline(d) {
      const no = d.proc_batch || (d.header && d.header.proc_batch);
      self.baselineForm = { open: true, busy: true, proc_batch: no, rows: [] };
      try {
        const data = await svc("demand_processing", "get", { proc_batch: no });
        if (data.header && data.header.status !== '进行中') {
          toast("批次状态为「" + data.header.status + "」，仅进行中批次可确认基线", "warn");
          self.baselineForm.open = false;
          self.fStatus = ""; await self.list.load(1);
          return;
        }
        const baselines = data.baselines || [];
        self.baselineForm.rows = baselines.map(b => ({
          part_no: b.part_no, veh_model: b.veh_model, period: b.period,
          base_qty: b.base_qty, causal_qty: b.causal_qty || 0,
          deviation: b.deviation || 0,
          base_path: b.base_path, base_method: b.base_method,
          deviation_reason: b.deviation_reason || '',
          override_qty: '',  // 覆盖基线量
        }));
        if (!self.baselineForm.rows.length) {
          toast("暂无基线数据，请先生成基线", "warn");
          self.baselineForm.open = false;
        }
      } catch { self.baselineForm.open = false; } finally { self.baselineForm.busy = false; }
    },
    closeBaseline() { self.baselineForm.open = false; },

    async submitBaseline() {
      const f = self.baselineForm;
      const toSubmit = f.rows.filter(r => r.deviation_reason || r.override_qty);
      if (!toSubmit.length) return toast("无变更，无需提交", "warn");
      f.busy = true;
      try {
        await svc("demand_processing", "batch_confirm_baseline", {
          proc_batch: f.proc_batch,
          confirmations: toSubmit.map(r => ({
            part_no: r.part_no, veh_model: r.veh_model, period: r.period,
            base_qty: r.override_qty ? parseFloat(r.override_qty) : undefined,
            deviation_reason: (r.deviation_reason || '').trim() || undefined,
          })),
        });
        toast(`已确认 ${toSubmit.length} 行基线`);
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await svc("demand_processing", "get", { proc_batch: f.proc_batch });
        }
        await self.openBaseline({ proc_batch: f.proc_batch });
      } catch { } finally { f.busy = false; }
    },

    /* ---- 销售修正（批量列表模式）---- */
    async openAdj(d) {
      const no = d.proc_batch || (d.header && d.header.proc_batch);
      self.adjForm = { open: true, busy: true, proc_batch: no, rows: [] };
      try {
        const data = await svc("demand_processing", "get", { proc_batch: no });
        if (data.header && data.header.status !== '进行中') {
          toast("批次状态为「" + data.header.status + "」，仅进行中批次可修正", "warn");
          self.adjForm.open = false;
          self.fStatus = ""; await self.list.load(1);
          return;
        }
        const baselines = data.baselines || [];
        const adjMap = {};
        (data.adjustments || []).forEach(a => { adjMap[a.part_no + '|' + a.veh_model + '|' + a.period] = a; });

        self.adjForm.rows = baselines.map(b => {
          const key = b.part_no + '|' + b.veh_model + '|' + b.period;
          const adj = adjMap[key] || {};
          const baseQty = b.base_qty || 0;
          return {
            part_no: b.part_no, veh_model: b.veh_model, period: b.period,
            base_qty: baseQty, causal_qty: b.causal_qty || 0,
            adj_qty: adj.adj_qty !== undefined ? adj.adj_qty : baseQty,
            adj_delta: adj.adj_delta || 0, adj_pct: adj.adj_pct || 0,
            adj_reason_cat: adj.adj_reason_cat || '',
            adj_evidence: adj.adj_evidence || '',
            submit_status: (adj.submit_status === '已提交' || adj.submit_status === '待提交') ? '已修正' : (adj.submit_status || '未修正'),
          };
        });
        if (!self.adjForm.rows.length) {
          toast("暂无基线数据，请先生成基线", "warn");
          self.adjForm.open = false;
        }
      } catch { self.adjForm.open = false; } finally { self.adjForm.busy = false; }
    },
    closeAdj() { self.adjForm.open = false; },

    onAdjQtyChange(row) {
      const bq = parseFloat(row.base_qty) || 1;
      const aq = parseFloat(row.adj_qty) || 0;
      row.adj_delta = Math.round((aq - bq) * 100) / 100;
      row.adj_pct = Math.round((Math.abs(aq - bq) / Math.max(Math.abs(bq), 0.01)) * 10000) / 100;
    },

    async submitAdj() {
      const f = self.adjForm;
      if (!f.rows.length) return toast("无数据", "warn");
      // 超20%偏离须举证校验
      const missing = f.rows.filter(r => r.adj_pct > 20 && !(r.adj_evidence || '').trim());
      if (missing.length) return toast(`${missing.length} 行修正幅度超20%但缺少举证`, "warn");
      f.busy = true;
      try {
        await svc("demand_processing", "batch_adjust", {
          proc_batch: f.proc_batch,
          adjustments: f.rows.map(r => ({
            part_no: r.part_no, veh_model: r.veh_model, period: r.period,
            adj_qty: parseFloat(r.adj_qty) || 0,
            adj_reason_cat: r.adj_reason_cat || '自行预估修正',
            adj_evidence: (r.adj_evidence || '').trim() || undefined,
          })),
        });
        toast(`已提交 ${f.rows.length} 条修正，可供核对`);
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await svc("demand_processing", "get", { proc_batch: f.proc_batch });
        }
        await self.openAdj({ proc_batch: f.proc_batch });
        await self.list.load(1);
      } catch { } finally { f.busy = false; }
    },

    /* ---- 核对（批量列表模式）---- */
    async openChk(d) {
      const no = d.proc_batch || (d.header && d.header.proc_batch);
      self.chkForm = { open: true, busy: true, proc_batch: no, rows: [] };
      try {
        const data = await svc("demand_processing", "get", { proc_batch: no });
        if (data.header && data.header.status !== '进行中') {
          toast("批次状态为「" + data.header.status + "」，仅进行中批次可核对", "warn");
          self.chkForm.open = false;
          self.fStatus = ""; await self.list.load(1);
          return;
        }
        const adjustments = data.adjustments || [];
        const existingChk = data.checks || [];
        const chkMap = {};
        existingChk.forEach(c => { chkMap[c.part_no + '|' + c.veh_model + '|' + c.period] = c; });

        self.chkForm.rows = adjustments.map(a => {
          const key = a.part_no + '|' + a.veh_model + '|' + a.period;
          const chk = chkMap[key] || {};
          return {
            part_no: a.part_no, veh_model: a.veh_model, period: a.period,
            base_qty: a.base_qty, adj_qty: a.adj_qty, adj_delta: a.adj_delta,
            adj_pct: a.adj_pct, adj_reason_cat: a.adj_reason_cat,
            chk_result: chk.chk_result || '',
            chk_reason: chk.chk_reason || '',
            chk_adj_qty: chk.chk_adj_qty != null ? chk.chk_adj_qty : '',
            approved_qty: chk.approved_qty || '',
          };
        });
        if (!self.chkForm.rows.length) {
          toast("暂无修正数据，请先完成销售修正", "warn");
          self.chkForm.open = false;
        }
      } catch { self.chkForm.open = false; } finally { self.chkForm.busy = false; }
    },
    closeChk() { self.chkForm.open = false; },

    async submitChk() {
      const f = self.chkForm;
      const reviewed = f.rows.filter(r => r.chk_result);
      if (!reviewed.length) return toast("无核对结果，请至少审核一行", "warn");
      const rejectNoReason = reviewed.filter(r => r.chk_result === '退回' && !(r.chk_reason || '').trim());
      if (rejectNoReason.length) return toast(`${rejectNoReason.length} 行退回但缺少书面理由`, "warn");
      self.chkForm.open = false;  // 先关弹窗防重复点击
      f.busy = true;
      try {
        const r = await svc("demand_processing", "batch_review", {
          proc_batch: f.proc_batch,
          reviews: reviewed.map(r => ({
            part_no: r.part_no, veh_model: r.veh_model, period: r.period,
            chk_result: r.chk_result,
            chk_reason: (r.chk_reason || '').trim() || undefined,
            chk_adj_qty: r.chk_adj_qty != null && r.chk_adj_qty !== '' ? parseFloat(r.chk_adj_qty) : undefined,
          })),
        });
        const msg = r.all_reviewed
          ? `全部核定完成！${r.approved}/${r.total_adjustments} 行通过，批次已可锁定`
          : `已审核 ${reviewed.length} 行（${r.approved}/${r.total_adjustments} 通过）`;
        toast(msg);
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await svc("demand_processing", "get", { proc_batch: f.proc_batch });
        }
        // 清除状态筛选，确保全部核定的批次可见
        if (r.all_reviewed) self.fStatus = "";
        await self.list.load(1);
      } catch { } finally { f.busy = false; }
    },

    /* ---- 锁定 ---- */
    async lockBatch(d) {
      const no = d.proc_batch || (d.header && d.header.proc_batch);
      if (!confirm("锁定后批次数据不可再修改，确定继续？")) return;
      try {
        await svc("demand_processing", "lock", { proc_batch: no });
        toast("已锁定 · " + no);
        if (self.modalX.open && self.modalX.d) self.modalX.d.header.status = "已锁定";
        self.fStatus = ""; await self.list.load(1);
      } catch { }
    },

    statusLabel(s) {
      return { "进行中": "进行中", "全部核定": "全部核定", "已锁定": "已锁定", "已提交": "已修正", "待提交": "已修正" }[s] || s || "—";
    },
  });
  return self;
}
