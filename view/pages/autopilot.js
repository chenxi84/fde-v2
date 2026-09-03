/* 自主运行：定时任务配置（agent_service schedule，唤醒 leader 按 description / 已沉淀 skill 自主执行）。
   数据来自 /api/agent-schedules（FDE 封装 agent_service /schedule/，隐藏 agent_id/credential 细节）。 */
import { get, post, del, toast } from "../lib/api.js";

export function pageAutopilot() {
  const self = Alpine.reactive({
    tpl: "",
    schedules: [],
    loading: false,
    form: { name: "", cron: "", description: "", permission_mode: "dont_ask" },

    async init() {
      self.tpl = await fetch(new URL("autopilot.html", import.meta.url)).then((r) => r.text());
      await self.load();
    },

    async load() {
      self.loading = true;
      try {
        self.schedules = (await get("/api/agent-schedules", { quiet: true }).catch(() => [])) || [];
      } finally {
        self.loading = false;
      }
    },

    async create() {
      if (!self.form.name.trim() || !self.form.cron.trim()) {
        toast("请填写任务名和 cron 表达式", "warn");
        return;
      }
      await post("/api/agent-schedules", self.form);
      self.form = { name: "", cron: "", description: "", permission_mode: "dont_ask" };
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
