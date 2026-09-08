/* 自主运行：定时任务配置（agent_service schedule，唤醒 leader 按 mode 执行）。
   数据来自 /api/agent-schedules（FDE 封装 agent_service /schedule/，隐藏 agent_id/credential 细节）。

   mode 三模式：
   - agent：leader + 任务描述自由执行（开放式）
   - flow ：leader 只调 platform_run_flow 触发确定性 DAG
   - skill：leader 按已沉淀 skill 的固定步骤执行 */
import { get, post, del, toast } from "../lib/api.js";

export function pageAutopilot() {
  const self = Alpine.reactive({
    tpl: "",
    schedules: [],
    flows: [],
    skills: [],
    loading: false,
    form: { name: "", cron: "", mode: "agent", description: "", flow_name: "", skill_name: "", permission_mode: "dont_ask" },

    async init() {
      self.tpl = await fetch(new URL("autopilot.html", import.meta.url)).then((r) => r.text());
      await Promise.all([self.load(), self.loadOptions()]);
    },

    async load() {
      self.loading = true;
      try {
        self.schedules = (await get("/api/agent-schedules", { quiet: true }).catch(() => [])) || [];
      } finally {
        self.loading = false;
      }
    },

    async loadOptions() {
      self.flows = (await get("/api/flows", { quiet: true }).catch(() => [])) || [];
      self.skills = (await get("/api/skills", { quiet: true }).catch(() => [])) || [];
    },

    async create() {
      if (!self.form.name.trim() || !self.form.cron.trim()) {
        toast("请填写任务名和 cron 表达式", "warn");
        return;
      }
      if (self.form.mode === "flow" && !self.form.flow_name) {
        toast("请选择工作流", "warn");
        return;
      }
      if (self.form.mode === "skill" && !self.form.skill_name) {
        toast("请选择技能", "warn");
        return;
      }
      await post("/api/agent-schedules", self.form);
      self.form = { name: "", cron: "", mode: "agent", description: "", flow_name: "", skill_name: "", permission_mode: "dont_ask" };
      await self.load();
    },

    async toggle(s) {
      await post(`/api/agent-schedules/${s.schedule_id}/toggle`, { enabled: !s.enabled });
      await self.load();
    },

    async remove(s) {
      if (!confirm(`删除定时任务「${s.name}」？`)) return;
      await del(`/api/agent-schedules/${s.schedule_id}`);
      await self.load();
    },

    modeLabel(m) { return m === "bypass" ? "完全信任" : "安全模式"; },
  });
  return self;
}
