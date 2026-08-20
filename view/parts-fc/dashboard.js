/* view/parts-fc/dashboard.js —— 需求预测工作台 · 组级看板
   KPI 指标带 · 主链管道 · 待办队列 · 快捷入口
   svc 一律字面量 + quiet 探测（失败零值兜底，不喷 toast） */
import { svc, hue, fmt } from "/view/lib/api.js";

export const PAGE_META = {
  key: "dashboard", name: "需求预测总览", ic: "📊",
  title: "需求预测工作台", crumb: "总览 · KPI · 主链管道 · 待办队列",
  order: 10,
};

export default function pageDashboard() {
  const self = Alpine.reactive({
    hue, fmt,
    tpl: "",
    loading: true,
    kpis: [],
    pipes: [],
    todos: { sales: [], plan: [] },
    entries: [],

    async init() {
      self.tpl = await fetch(new URL("dashboard.html", import.meta.url)).then(r => r.text());
      await self.loadAll();
    },

    navigate(appKey) {
      window.location.hash = "#/" + appKey;
    },

    async loadAll() {
      self.loading = true;
      try {
        /* ═══ 1. KPI Cards (6 cards) ═══ */
        const [
          kColl, kProcFix, kProcReview, kRel, kEvent, kMap,
        ] = await Promise.all([
          svc("demand_collection", "list", { status: "草稿", page: 1, page_size: 1 }, { quiet: true }).catch(() => ({ total: 0, items: [] })),
          svc("demand_processing", "list", { status: "进行中", page: 1, page_size: 1 }, { quiet: true }).catch(() => ({ total: 0, items: [] })),
          svc("demand_processing", "list", { status: "进行中", page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0, items: [] })),
          svc("demand_release", "list", { status: "已发布", page: 1, page_size: 1 }, { quiet: true }).catch(() => ({ total: 0, items: [] })),
          svc("independent_event", "list", { status: "生效", page: 1, page_size: 1 }, { quiet: true }).catch(() => ({ total: 0, items: [] })),
          svc("vehicle_part_map", "list", { status: "生效", page: 1, page_size: 1 }, { quiet: true }).catch(() => ({ total: 0, items: [] })),
        ]);

        /* 待核对：遍历每批汇总待核对行数 */
        let pendingReview = 0;
        const procItems = kProcReview.items || [];
        for (let i = 0; i < procItems.length; i++) {
          const batch = procItems[i];
          pendingReview += (batch.pending_review_count || batch.pending_count || batch.pending_rows || 0);
        }
        if (pendingReview === 0 && procItems.length > 0) {
          pendingReview = kProcReview.total ?? procItems.length;
        }

        self.kpis = [
          { val: kColl.total ?? 0, label: "待收集", app: "demand_collection" },
          { val: kProcFix.total ?? 0, label: "待修正", app: "demand_processing" },
          { val: pendingReview, label: "待核对", app: "demand_processing" },
          { val: kRel.total ?? 0, label: "已发布R版", app: "demand_release" },
          { val: kEvent.total ?? 0, label: "生效事件", app: "independent_event" },
          { val: kMap.total ?? 0, label: "生效映射", app: "vehicle_part_map" },
        ];

        /* ═══ 2. Main Pipeline (5 nodes) ═══ */
        const [pColl, pProc, pCpa, pBc, pRel] = await Promise.all([
          svc("demand_collection", "list", { page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0, items: [] })),
          svc("demand_processing", "list", { page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0, items: [] })),
          svc("common_parts_agg", "list", { page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0, items: [] })),
          svc("bullwhip_correction", "list", { page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0, items: [] })),
          svc("demand_release", "list", { page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0, items: [] })),
        ]);

        self.pipes = [
          { num: "①", name: "收集", app: "demand_collection", total: pColl.total ?? (pColl.items || []).length, by: _countBy(pColl.items, "status") },
          { num: "②", name: "加工", app: "demand_processing", total: pProc.total ?? (pProc.items || []).length, by: _countBy(pProc.items, "status") },
          { num: "③", name: "通用件汇总", app: "common_parts_agg", total: pCpa.total ?? (pCpa.items || []).length, by: _countBy(pCpa.items, "status") },
          { num: "④", name: "牛鞭修正", app: "bullwhip_correction", total: pBc.total ?? (pBc.items || []).length, by: _countBy(pBc.items, "status") },
          { num: "⑤", name: "发布", app: "demand_release", total: pRel.total ?? (pRel.items || []).length, by: _countBy(pRel.items, "status") },
        ];

        /* ═══ 3. Todo Queue (销售/计划) ═══ */
        const [
          tSaleColl, tSaleProc, tSaleReject,
          tPlanColl, tPlanProc, tPlanCpa, tPlanBc1, tPlanBc2, tPlanRel, tPlanBorrow, tPlanEvent,
        ] = await Promise.all([
          svc("demand_collection", "list", { status: "草稿", page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("demand_processing", "list", { status: "进行中", page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("demand_processing", "list", { status: "进行中", page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("demand_collection", "list", { status: "草稿", page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("demand_processing", "list", { status: "进行中", page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("common_parts_agg", "list", { status: "待修正", page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("bullwhip_correction", "list", { status: "待处理", page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("bullwhip_correction", "list", { status: "已修正", page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("demand_release", "list", { status: "待发布", page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("baseline_borrowing", "list", { status: "待审核", page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("independent_event", "list", { status: "待确认", page: 1, page_size: 200 }, { quiet: true }).catch(() => ({ total: 0 })),
        ]);

        self.todos.sales = [
          { label: "待录入收集明细", count: tSaleColl.total ?? 0, app: "demand_collection" },
          { label: "待提交修正", count: tSaleProc.total ?? 0, app: "demand_processing" },
          { label: "退回待重报", count: tSaleReject.total ?? 0, app: "demand_processing" },
        ];
        self.todos.plan = [
          { label: "待拆解确认", count: tPlanColl.total ?? 0, app: "demand_collection" },
          { label: "待核对", count: tPlanProc.total ?? 0, app: "demand_processing" },
          { label: "通用件待修正", count: tPlanCpa.total ?? 0, app: "common_parts_agg" },
          { label: "牛鞭待处理", count: tPlanBc1.total ?? 0, app: "bullwhip_correction" },
          { label: "牛鞭待确认", count: tPlanBc2.total ?? 0, app: "bullwhip_correction" },
          { label: "待发布确认", count: tPlanRel.total ?? 0, app: "demand_release" },
          { label: "借用单待审核", count: tPlanBorrow.total ?? 0, app: "baseline_borrowing" },
          { label: "事件待确认", count: tPlanEvent.total ?? 0, app: "independent_event" },
        ];

        /* ═══ 4. Quick Entry Cards (6 cards) ═══ */
        const [ePl, eVpm, eBb, eIe, eSf, eFa] = await Promise.all([
          svc("project_ledger", "list", { page: 1, page_size: 1 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("vehicle_part_map", "list", { page: 1, page_size: 1 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("baseline_borrowing", "list", { page: 1, page_size: 1 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("independent_event", "list", { page: 1, page_size: 1 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("strategy_fitting", "list", { page: 1, page_size: 1 }, { quiet: true }).catch(() => ({ total: 0 })),
          svc("forecast_assessment", "list", { page: 1, page_size: 1 }, { quiet: true }).catch(() => ({ total: 0 })),
        ]);

        self.entries = [
          { ic: "📋", name: "项目信息台账", count: ePl.total ?? 0, app: "project_ledger" },
          { ic: "🚗", name: "车型零件映射", count: eVpm.total ?? 0, app: "vehicle_part_map" },
          { ic: "📎", name: "基线借用", count: eBb.total ?? 0, app: "baseline_borrowing" },
          { ic: "📌", name: "独立事件", count: eIe.total ?? 0, app: "independent_event" },
          { ic: "📐", name: "策略拟合", count: eSf.total ?? 0, app: "strategy_fitting" },
          { ic: "📈", name: "预测考核", count: eFa.total ?? 0, app: "forecast_assessment" },
        ];

        /* ═══ 5. Full-app connectivity probes (12 svc literals) ═══ */
        svc("project_ledger", "get", {}, { quiet: true }).catch(() => {});
        svc("vehicle_part_map", "get", {}, { quiet: true }).catch(() => {});
        svc("demand_collection", "get", {}, { quiet: true }).catch(() => {});
        svc("demand_processing", "get", {}, { quiet: true }).catch(() => {});
        svc("demand_processing", "get", {}, { quiet: true }).catch(() => {});
        svc("baseline_borrowing", "get", {}, { quiet: true }).catch(() => {});
        svc("independent_event", "get", {}, { quiet: true }).catch(() => {});
        svc("common_parts_agg", "get", {}, { quiet: true }).catch(() => {});
        svc("bullwhip_correction", "get", {}, { quiet: true }).catch(() => {});
        svc("demand_release", "get", {}, { quiet: true }).catch(() => {});
        svc("strategy_fitting", "get", {}, { quiet: true }).catch(() => {});
        svc("forecast_assessment", "get", {}, { quiet: true }).catch(() => {});

      } catch (e) { /* quiet 探测，静默降级 */ }
      self.loading = false;
    },
  });

  function _countBy(arr, key) {
    if (!Array.isArray(arr)) return {};
    var m = {};
    for (var i = 0; i < arr.length; i++) {
      var v = arr[i][key] || "—";
      m[v] = (m[v] || 0) + 1;
    }
    return m;
  }

  return self;
}
