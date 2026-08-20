/* view/sales-forecast/dashboard.js —— 毛需求管理工作台 */
import { svc, hue, fmt, dash } from "/view/lib/api.js";

export const PAGE_META = {
  key: "dashboard", name: "工作台", ic: "📊",
  title: "毛需求管理 · 工作台", crumb: "Gross Demand Management Dashboard",
  order: 10,
};

export default function pageDashboard() {
  const self = Alpine.reactive({
    hue, fmt, dash,
    tpl: "",
    kpis: [],
    pipes: [],
    todos: { sales: [], plan: [] },
    loading: true,

    async init() {
      self.tpl = await fetch(new URL("dashboard.html", import.meta.url)).then(r => r.text());
      await self.loadAll();
    },

    async loadAll() {
      self.loading = true;
      try {
        const [dcList, dpList, drList, ieList, cpaList, bcList] = await Promise.all([
          svc("demand_collection", "list", {}, { quiet: true }),
          svc("demand_processing", "list", {}, { quiet: true }),
          svc("demand_release", "list", {}, { quiet: true }),
          svc("independent_event", "list", {}, { quiet: true }),
          svc("common_part_aggregation", "list", {}, { quiet: true }),
          svc("bullwhip_correction", "list", {}, { quiet: true }),
        ]);

        self.kpis = [
          { label: "收集单", val: Array.isArray(dcList) ? dcList.length : 0, link: "demand_collection" },
          { label: "加工批次", val: Array.isArray(dpList) ? dpList.length : 0, link: "demand_processing" },
          { label: "已发布R版", val: Array.isArray(drList) ? drList.filter(d => d.status === "已发布").length : 0, link: "demand_release" },
          { label: "生效事件", val: Array.isArray(ieList) ? ieList.filter(d => d.status === "生效").length : 0, link: "independent_event" },
          { label: "待确认事件", val: Array.isArray(ieList) ? ieList.filter(d => d.status === "待确认").length : 0, link: "independent_event" },
          { label: "待汇总", val: Array.isArray(cpaList) ? cpaList.filter(d => d.status === "待汇总").length : 0, link: "common_part_aggregation" },
        ];

        self.pipes = [
          { label: "收集", app: "demand_collection", items: _countBy(dcList, "status") },
          { label: "加工", app: "demand_processing", items: _countBy(dpList, "status") },
          { label: "通用件汇总", app: "common_part_aggregation", items: _countBy(cpaList, "status") },
          { label: "牛鞭修正", app: "bullwhip_correction", items: _countBy(bcList, "status") },
          { label: "发布", app: "demand_release", items: _countBy(drList, "status") },
        ];
      } catch (e) { /* quiet探测，静默降级 */ }
      self.loading = false;
    },

    go(app) { shell.nav(app); },
  });

  function _countBy(arr, key) {
    if (!Array.isArray(arr)) return {};
    const m = {};
    arr.forEach(d => { const v = d[key] || "—"; m[v] = (m[v] || 0) + 1; });
    return m;
  }

  return self;
}
