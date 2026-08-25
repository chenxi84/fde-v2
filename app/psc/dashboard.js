/* app/psc/dashboard.js —— psc 组级看板（无后端应用的聚合页 · 默认落地页 key=dashboard）
   区块：KPI 指标带（demand_pool 三态 / strategy_fitting 待复核 / 月度版本草稿 / 推移表缺货预警）
        + 主链管道 7 段（销售预测→库存策略→毛净需求→主计划→推移表→需求池→策略拟合，各 list 最近 5 行）
        + 待办队列 3 行（需求池待下达 / 拟合待复核 / 版本草稿）。
   全部 15 处 svc 字面量 + {quiet:true} 探测（失败零值兜底，不喷 toast）；跳转目标字面量 key。
   对标 app/e2e/dashboard.*。 */
import { svc, hue, fmt } from "/view/lib/api.js";

/* 页面自描述（平台扫描的唯一入口）：组级页 key 固定 dashboard；order 最小居首 */
export const PAGE_META = {
  key: "dashboard", name: "产销协同看板", ic: "🏭",
  title: "产销协同看板", crumb: "KPI · 主链管道 · 待办队列",
  order: 10,
};

export default function pageDashboard() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    loading: true,

    /* KPI 数字（数量型指标，零值兜底 0） */
    kpi: { pending: 0, released: 0, producing: 0, review: 0, draft: 0, shortage: 0 },

    /* 待办队列（total 计数 + 最近 items） */
    todo: {
      replenish: { total: 0, items: [] },   // 需求池「待下达」补库单
      fitting: { total: 0, items: [] },     // 策略拟合「待复核」
      version: { total: 0, items: [] },     // 月度版本「草稿」
    },

    /* 主链管道 7 段（最近 5 行） */
    pipe: {
      forecast: { items: [] },     // ① 销售预测
      strategy: { items: [] },     // ② 库存策略
      demand: { items: [] },       // ③ 毛需求/净需求
      master: { items: [] },       // ④ 主计划
      projection: { items: [] },   // ⑤ 库存推移表
      pool: { items: [] },         // ⑥ 需求池
      fitting: { items: [] },      // ⑦ 策略拟合
    },

    async init() {
      self.tpl = await fetch(new URL("dashboard.html", import.meta.url)).then((r) => r.text());
      await self.loadAll();
    },

    gotoPage(key) { window.location.hash = "#/" + key; },

    async loadAll() {
      /* ── 版本探测：get_active → 回退 list 取最新；皆空则 fv=""，管道①~④ 短路 ── */
      let fv = "";
      const active = await svc("md_monthly_version", "get_active", {}, { quiet: true }).catch(() => null);
      if (active && active.version_no) {
        fv = active.version_no;
      } else {
        const latest = await svc("md_monthly_version", "list", { page: 1, size: 1 }, { quiet: true })
          .catch(() => ({ items: [] }));
        fv = ((latest && latest.items) || [])[0]?.version_no || "";
      }

      /* ── KPI / 待办 / 管道 并行探测（全部 quiet + 零值兜底；fv 为空时管道①~④ 短路）── */
      const qPending   = svc("demand_pool", "list", { status: "待下达", page: 1, size: 5 }, { quiet: true }).catch(() => null);
      const qReleased  = svc("demand_pool", "list", { status: "已下达", page: 1, size: 1 }, { quiet: true }).catch(() => null);
      const qProducing = svc("demand_pool", "list", { status: "生产中", page: 1, size: 1 }, { quiet: true }).catch(() => null);
      const qReview    = svc("strategy_fitting", "list", { status: "待复核", page: 1, size: 5 }, { quiet: true }).catch(() => null);
      const qDraft     = svc("md_monthly_version", "list", { lock_status: "草稿", page: 1, size: 5 }, { quiet: true }).catch(() => null);
      const qShortage  = svc("inventory_projection", "list", { alert_type: "缺货", page: 1, size: 1 }, { quiet: true }).catch(() => null);
      const qForecast  = fv ? svc("sales_forecast", "list", { version_no: fv, page: 1, size: 5 }, { quiet: true }).catch(() => null) : Promise.resolve(null);
      const qStrategy  = fv ? svc("inventory_strategy", "list", { version_no: fv, page: 1, size: 5 }, { quiet: true }).catch(() => null) : Promise.resolve(null);
      const qDemand    = fv ? svc("demand", "list", { version_no: fv, page: 1, size: 5 }, { quiet: true }).catch(() => null) : Promise.resolve(null);
      const qMaster    = fv ? svc("master_plan", "list", { version_no: fv, page: 1, size: 5 }, { quiet: true }).catch(() => null) : Promise.resolve(null);
      const qProj      = svc("inventory_projection", "list", { page: 1, size: 5 }, { quiet: true }).catch(() => null);
      const qPool      = svc("demand_pool", "list", { page: 1, size: 5 }, { quiet: true }).catch(() => null);
      const qFitting   = svc("strategy_fitting", "list", { page: 1, size: 5 }, { quiet: true }).catch(() => null);

      const settled = await Promise.allSettled([
        qPending, qReleased, qProducing, qReview, qDraft, qShortage,
        qForecast, qStrategy, qDemand, qMaster, qProj, qPool, qFitting,
      ]);
      const pick = (s) => ((s.status === "fulfilled" && s.value) ? s.value : { total: 0, items: [] });
      const [
        dpPending, dpReleased, dpProducing, sfReview, mvDraft, ipShortage,
        fc, is, dm, mp, ip, dpPool, sfFitting,
      ] = settled.map(pick);

      /* KPI（全部取 list.total，零值兜底） */
      self.kpi = {
        pending: dpPending.total ?? 0,
        released: dpReleased.total ?? 0,
        producing: dpProducing.total ?? 0,
        review: sfReview.total ?? 0,
        draft: mvDraft.total ?? 0,
        shortage: ipShortage.total ?? 0,
      };
      /* 待办队列（与 KPI 共用同一次返回） */
      self.todo.replenish = { total: dpPending.total ?? 0, items: dpPending.items || [] };
      self.todo.fitting   = { total: sfReview.total ?? 0, items: sfReview.items || [] };
      self.todo.version   = { total: mvDraft.total ?? 0, items: mvDraft.items || [] };
      /* 主链管道（最近 5 行） */
      self.pipe.forecast.items   = fc.items || [];
      self.pipe.strategy.items   = is.items || [];
      self.pipe.demand.items     = dm.items || [];
      self.pipe.master.items     = mp.items || [];
      self.pipe.projection.items = ip.items || [];
      self.pipe.pool.items       = dpPool.items || [];
      self.pipe.fitting.items    = sfFitting.items || [];

      self.loading = false;
    },
  });
  return self;
}
