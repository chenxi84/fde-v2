/* 平台告警页：通用告警（库存预警 / 定时任务失败 / 集成接口失败）。
   数据来自 /api/alerts，统一结构 {source, level, title, detail, time}。 */
import { get } from "../lib/api.js";

export function pageAlerts() {
  const self = Alpine.reactive({
    tpl: "",
    alerts: [],
    loading: false,
    sourceFilter: "",  // '' = 全部来源

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

    get sources() {
      return [...new Set(self.alerts.map((a) => a.source))];
    },

    get filtered() {
      if (!self.sourceFilter) return self.alerts;
      return self.alerts.filter((a) => a.source === self.sourceFilter);
    },
  });
  return self;
}
