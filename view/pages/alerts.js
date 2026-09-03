/* 平台告警页：展示巡检发现的库存预警（主动上报的替代——页面拉取而非飞书推送）。
   数据来自 /api/alerts（inventory_projection 的 alert_type 非「无」记录）。 */
import { get } from "../lib/api.js";

const ALERT_HUES = { 缺货: "red", 击穿最低: "red", 击穿安全: "red", 呆滞: "amber", 超储: "amber" };

export function pageAlerts() {
  const self = Alpine.reactive({
    tpl: "",
    alerts: [],
    loading: false,
    typeFilter: "",  // '' = 全部

    async init() {
      self.tpl = await fetch(new URL("alerts.html", import.meta.url)).then((r) => r.text());
      await self.load();
    },

    async load() {
      self.loading = true;
      try {
        self.alerts = (await get("/api/alerts", { quiet: true }).catch(() => [])) || [];
      } finally {
        self.loading = false;
      }
    },

    hue(t) { return ALERT_HUES[t] || "slate"; },

    get types() {
      return [...new Set(self.alerts.map((a) => a.alert_type))].sort();
    },

    get filtered() {
      if (!self.typeFilter) return self.alerts;
      return self.alerts.filter((a) => a.alert_type === self.typeFilter);
    },
  });
  return self;
}
