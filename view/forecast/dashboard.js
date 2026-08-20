/* view/forecast/dashboard.js —— 销售预测首页看板 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "dashboard", name: "首页看板", ic: "📊",
  title: "销售预测 · 工作台", crumb: "KPI · 主链管道 · 待办",
  order: 10,
};

export default function pageDashboard() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    // KPI
    activeVersion: null,
    snapshotStatus: null,
    pendingReview: 0,
    // 管道
    recentSnapshot: [],
    recentBaseline: [],
    recentBatches: [],
    recentReleases: [],
    // 待办
    unfilledCount: 0,
    unconfirmedCount: 0,
    inProgressBatches: [],
    draftReleases: [],
    // 加载态
    loading: true,

    async init() {
      self.tpl = await fetch(new URL("dashboard.html", import.meta.url)).then(r => r.text());
      await self.loadAll();
    },

    async loadAll() {
      self.loading = true;
      try {
        // 取版本号: 优先活跃版本，否则取最新版本（含已锁定）
        let fv = "";
        try {
          const ver = await svc("md_fcst_version", "get_active", {}, { quiet: true });
          self.activeVersion = ver;
          fv = ver ? ver.fcst_version : "";
        } catch (e) {
          // 无活跃版本 → 取最新版本（含已锁定的历史版本）
          try {
            const all = await svc("md_fcst_version", "list", { page: 1, page_size: 1 }, { quiet: true });
            const latest = (all && all.items && all.items.length) ? all.items[0] : null;
            self.activeVersion = latest;
            fv = latest ? latest.fcst_version : "";
          } catch (e2) { /* 完全无版本数据 */ }
        }

        // 并行探测
        const results = await Promise.allSettled([
          // KPI
          fv ? svc("forecast_snapshot", "get_version_status", { fcst_version: fv }, { quiet: true }) : Promise.resolve(null),
          // 管道
          fv ? svc("forecast_snapshot", "list", { fcst_version: fv, page: 1, page_size: 5 }, { quiet: true }) : Promise.resolve(null),
          fv ? svc("forecast_baseline", "list", { fcst_version: fv, page: 1, page_size: 5 }, { quiet: true }) : Promise.resolve(null),
          fv ? svc("forecast_processing", "list_batches", { fcst_version: fv, page: 1, page_size: 5 }, { quiet: true }) : Promise.resolve(null),
          fv ? svc("demand_release", "list", { fcst_version: fv, page: 1, page_size: 5 }, { quiet: true }) : Promise.resolve(null),
          // 待办
          fv ? svc("forecast_snapshot", "list", { fcst_version: fv, data_flag: "OEM未提供", page: 1, page_size: 1 }, { quiet: true }) : Promise.resolve(null),
          fv ? svc("forecast_baseline", "list", { fcst_version: fv, status: "预计算", page: 1, page_size: 1 }, { quiet: true }) : Promise.resolve(null),
          svc("forecast_processing", "list_batches", { status: "进行中", page: 1, page_size: 5 }, { quiet: true }),
          svc("demand_release", "list", { status: "草稿", page: 1, page_size: 5 }, { quiet: true }),
        ]);

        const [snapStatus, snapList, baseList, batchList, relList, unfilled, unconfirmed, inProgBatches, draftRels] = results;

        // KPI
        if (snapStatus.status === "fulfilled" && snapStatus.value) {
          self.snapshotStatus = snapStatus.value;
        }
        // 管道
        if (snapList.status === "fulfilled" && snapList.value) self.recentSnapshot = snapList.value.items || [];
        if (baseList.status === "fulfilled" && baseList.value) self.recentBaseline = baseList.value.items || [];
        if (batchList.status === "fulfilled" && batchList.value) self.recentBatches = batchList.value.items || [];
        if (relList.status === "fulfilled" && relList.value) self.recentReleases = relList.value.items || [];
        // 待办
        if (unfilled.status === "fulfilled" && unfilled.value) self.unfilledCount = unfilled.value.total || 0;
        if (unconfirmed.status === "fulfilled" && unconfirmed.value) self.unconfirmedCount = unconfirmed.value.total || 0;
        if (inProgBatches.status === "fulfilled" && inProgBatches.value) self.inProgressBatches = inProgBatches.value.items || [];
        if (draftRels.status === "fulfilled" && draftRels.value) self.draftReleases = draftRels.value.items || [];
      } catch (e) { /* quiet */ }
      self.loading = false;
    },

    gotoPage(key) { window.location.hash = "#/" + key; },
    dash(v) { return (v == null || v === "") ? "—" : v; },
  });
  return self;
}
