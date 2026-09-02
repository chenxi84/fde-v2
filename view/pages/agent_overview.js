/* 平台智能体总览：展示平台设计的智能体角色（只读）+ 运行时团队状态。
   数据来自 /api/agent-overview（角色定义读 agent_roles，运行时读 agent_service）。 */
import { get } from "../lib/api.js";

export function pageAgentOverview() {
  const self = Alpine.reactive({
    tpl: "",
    roles: [],        // [{type, label, kind, apps|tools, description, system_prompt}]
    runtime: { teams: [], session_count: 0, agent_count: 0 },

    async init() {
      self.tpl = await fetch(new URL("agent_overview.html", import.meta.url)).then((r) => r.text());
      await self.load();
    },

    async load() {
      const d = await get("/api/agent-overview", { quiet: true }).catch(() => null);
      if (d) {
        self.roles = d.roles || [];
        self.runtime = d.runtime || { teams: [], session_count: 0, agent_count: 0 };
      }
    },

    /* 应用短名：psc/md_customer → md_customer */
    appShort(app) { return String(app).split("/").pop(); },

    /* 刷新运行时状态 */
    async refresh() { await self.load(); },
  });
  return self;
}
