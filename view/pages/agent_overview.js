/* 平台智能体总览：展示角色（含功能概述）+ 已沉淀 skill + 定时任务 + 运行时团队。
   数据来自 /api/agent-overview。 */
import { get } from "../lib/api.js";

export function pageAgentOverview() {
  const self = Alpine.reactive({
    tpl: "",
    roles: [],        // [{type, label, kind, group, apps|tools, description, system_prompt}]
    runtime: { teams: [], session_count: 0, agent_count: 0 },
    skills: [],       // [{name, trigger, description, steps:[{tool, note}]}]
    schedules: [],    // [{schedule_id, name, cron, enabled, permission_mode}]
    leader: null,     // 编排器 leader 摘要 {label, description, capabilities}
    flowRun: null,    // 最近一次编排执行进度 {flow_name, status, step_index, step_total, current_role}
    openRole: "",     // 展开查看功能概述（system_prompt）的角色 type

    async init() {
      self.tpl = await fetch(new URL("agent_overview.html", import.meta.url)).then((r) => r.text());
      await self.load();
    },

    async load() {
      const group = window.__fdeModule || "";
      const qs = group ? "?group=" + encodeURIComponent(group) : "";
      const d = await get("/api/agent-overview" + qs, { quiet: true }).catch(() => null);
      if (d) {
        self.roles = d.roles || [];
        self.runtime = d.runtime || { teams: [], session_count: 0, agent_count: 0 };
        self.skills = d.skills || [];
        self.schedules = d.schedules || [];
        self.leader = d.leader || null;
        self.flowRun = d.flow_run || null;
      }
    },

    appShort(app) { return String(app).split("/").pop(); },
    toolShort(tool) { return String(tool).replace(/^platform_/, ""); },
    stepShort(tool) { const p = String(tool).split("__"); return p.length >= 3 ? p.slice(-2).join(".") : tool; },
    toggleRole(type) { self.openRole = self.openRole === type ? "" : type; },
    modeLabel(m) { return m === "bypass" ? "完全信任" : "安全模式"; },
    async refresh() { await self.load(); },
  });
  return self;
}
