/* 协同总览（组级运转仪表盘）：员工（智能体）+ 工具（skill）+ 工作流 + 定时任务 + 运转时间线。
   数据聚合 /api/agent-overview + /api/flows + /api/flow-runs。图标网格 + 点击钻取详情模态。 */
import { get, post } from "../lib/api.js";

export const PAGE_META = {
  key: "workbench",
  name: "AI管家",
  ic: "🧭",
  title: "AI管家",
  crumb: "智能体 · 技能 · 工作流 · 运转全貌",
  order: 1,
};

export function pageWorkbench() {
  const self = Alpine.reactive({
    tpl: "",
    roles: [],        // 智能体角色（员工）
    skills: [],       // 已沉淀技能（工具）
    schedules: [],    // 定时任务（自主运行：唤醒智能体）
    apiJobs: [],      // API 任务（scheduler：定时调用服务）
    integrations: [], // 集成端点（外部系统 API）
    knowledge: { files: [], index: {} },  // 知识库（平台级共享）
    runtime: { teams: [], session_count: 0, agent_count: 0 },
    flows: [],        // 工作流
    runs: [],         // 运转时间线
    alerts: [],       // 告警（库存预警/定时任务失败/集成失败/Agent 上报）
    leader: null,
    modal: null,      // 详情模态 {kind, data}
    openSchedule: "", // 展开的定时任务 schedule_id

    async init() {
      self.tpl = await fetch(new URL("workbench.html", import.meta.url)).then((r) => r.text());
      await self.load();
    },

    async load() {
      const group = window.__fdeModule || "";
      const qs = group ? "?group=" + encodeURIComponent(group) : "";
      const [ov, fl, runs, alerts, skills, apiJobs, integrations, knowledge] = await Promise.all([
        get("/api/agent-overview" + qs, { quiet: true }).catch(() => null),
        get("/api/flows" + qs, { quiet: true }).catch(() => []),
        get("/api/flow-runs?limit=20", { quiet: true }).catch(() => []),
        get("/api/alerts", { quiet: true }).catch(() => []),
        get("/api/skills?all=1", { quiet: true }).catch(() => []),
        get("/api/scheduler-jobs?group=" + encodeURIComponent(window.__fdeModule || ""), { quiet: true }).catch(() => []),
        get("/api/integration/endpoints?group=" + encodeURIComponent(window.__fdeModule || ""), { quiet: true }).catch(() => []),
        get("/api/knowledge", { quiet: true }).catch(() => ({ files: [], index: {} })),
      ]);
      if (ov) {
        self.roles = ov.roles || [];
        self.schedules = ov.schedules || [];
        self.runtime = ov.runtime || { teams: [], session_count: 0, agent_count: 0 };
        self.leader = ov.leader || null;
      }
      self.skills = skills || [];
      self.flows = fl || [];
      self.runs = runs || [];
      self.alerts = alerts || [];
      self.apiJobs = apiJobs || [];
      self.integrations = integrations || [];
      self.knowledge = knowledge || { files: [], index: {} };
    },

    /* —— 图标 / 标签 —— */
    appShort(app) { return String(app).split("/").pop(); },
    toolShort(tool) { return String(tool).replace(/^platform_/, ""); },
    stepShort(tool) { const p = String(tool).split("__"); return p.length >= 3 ? p.slice(-2).join(".") : tool; },
    employeeIcon(kind) { return kind === "平台" ? "👔" : "👤"; },
    /* 该角色当前是否在活跃团队里（按 label 或 type 匹配运行时成员名） */
    isActive(role) {
      const names = [];
      for (const t of self.runtime.teams || []) {
        for (const m of t.members || []) {
          if (m.name) names.push(m.name);
        }
      }
      return names.includes(role.label) || names.includes(role.type);
    },
    nodeIcon(type) { return type === "call" ? "⚙️" : type === "skill" ? "🔧" : "🧠"; },
    nodeTypeLabel(type) { return type === "call" ? "调服务" : type === "skill" ? "技能" : "智能体"; },
    modeLabel(m) { return m === "bypass" ? "完全信任" : "安全模式"; },
    scheduleModeLabel(m) { return m === "flow" ? "工作流" : m === "skill" ? "技能" : "智能体"; },
    scheduleTargetText(s) {
      if (s.mode === "flow") return "工作流「" + s.target + "」";
      if (s.mode === "skill") return "技能「" + s.target + "」";
      return "leader 自由执行";
    },
    apiJobName(j) {
      const app = String(j.app_name || "").split("/").pop();
      return app + "." + j.service;
    },
    apiJobStatus(j) {
      const s = j.last_run && j.last_run.status;
      return s === "ok" ? "成功" : s === "error" ? "失败" : s === "running" ? "运行中" : "未运行";
    },
    apiJobStatusClass(j) {
      const s = j.last_run && j.last_run.status;
      return s === "ok" ? "t-teal" : s === "error" ? "t-red" : s === "running" ? "t-amber" : "t-slate";
    },

    /* —— 详情模态 —— */
    openModal(kind, data) { self.modal = { kind, data }; },
    closeModal() { self.modal = null; },
    modalTitle(m) {
      if (!m) return "";
      return m.data ? (m.data.label || m.data.name || "") : "";
    },
    toggleSchedule(id) { self.openSchedule = self.openSchedule === id ? "" : id; },

    runStatus(s) { return s === "done" ? "成功" : s === "error" ? "失败" : "执行中"; },
    runStatusClass(s) { return s === "done" ? "t-teal" : s === "error" ? "t-red" : "t-amber"; },
    alertIcon(level) { return level === "red" ? "🚨" : "⚠️"; },
    alertClass(level) { return level === "red" ? "t-red" : "t-amber"; },
    skillStatusLabel(s) { return s === "approved" ? "已发布" : s === "deprecated" ? "已弃用" : "草稿"; },
    skillStatusClass(s) { return s === "approved" ? "t-teal" : s === "deprecated" ? "t-slate" : "t-amber"; },
    async skillAction(id, action, score) {
      const url = "/api/skills/" + id + "/" + action;
      try {
        if (action === "rate") {
          await post(url, { score: score || 0 });
        } else {
          await post(url, {});
        }
        await self.load();
      } catch { /* api.js 统一 toast */ }
    },
    lastRunStatus(name) {
      const r = self.runs.find((x) => x.flow_name === name);
      return r ? r.status : null;
    },

    gotoFlow() { location.hash = "#/flow_editor"; },
    gotoAutopilot() { location.hash = "#/autopilot"; },
    gotoAlerts() { location.hash = "#/alerts"; },
    gotoScheduler() { location.hash = "#/scheduler"; },
    gotoIntegration() { location.hash = "#/integration"; },
    gotoKnowledge() { location.hash = "#/knowledge"; },

    async refresh() { await self.load(); },
  });
  return self;
}
