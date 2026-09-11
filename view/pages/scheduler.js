/* 定时任务（scheduler）：定时调用应用服务/API。组级平台页——只显示/配置当前应用组的任务。
   数据 /api/scheduler-jobs（组过滤）+ /api/flow-service-options（服务下拉）。 */
import { get, post, del, toast } from "../lib/api.js";

export const PAGE_META = {
  key: "scheduler",
  name: "定时任务",
  ic: "🔌",
  title: "定时任务",
  crumb: "定时调用应用服务 · 当前组",
  order: 60,
};

export function pageScheduler() {
  const self = Alpine.reactive({
    tpl: "",
    group: window.__fdeModule || "",
    jobs: [],
    services: [],   // [{service: "app.svc", description}]
    form: { app: "", service: "", cron: "", description: "" },
    openCreate: false,

    async init() {
      self.tpl = await fetch(new URL("scheduler.html", import.meta.url)).then((r) => r.text());
      await Promise.all([self.load(), self.loadServices()]);
    },

    async load() {
      const qs = "?group=" + encodeURIComponent(self.group);
      const d = await get("/api/scheduler-jobs" + qs, { quiet: true }).catch(() => []);
      self.jobs = d || [];
    },

    async loadServices() {
      const d = await get("/api/flow-service-options", { quiet: true }).catch(() => []);
      self.services = d || [];
    },

    /* 应用短名列表（去重） */
    get apps() {
      const s = new Set();
      for (const x of self.services) s.add(x.service.split(".")[0]);
      return [...s];
    },

    /* 某应用的可用服务 */
    servicesOf(app) {
      return self.services.filter((x) => x.service.startsWith(app + "."));
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

    openForm() { self.openCreate = true; },
    closeForm() {
      self.openCreate = false;
      self.form = { app: "", service: "", cron: "", description: "" };
    },

    async save() {
      const f = self.form;
      if (!f.app) return toast("请选择应用", "warn");
      if (!f.service) return toast("请选择服务", "warn");
      if (!f.cron.trim()) return toast("请填写 cron", "warn");
      try {
        await post("/api/scheduler-jobs", {
          group: self.group,
          app_name: self.group + "/" + f.app,
          service: f.service,
          cron: f.cron.trim(),
          description: f.description.trim(),
          enabled: true,
        });
        toast("已创建定时任务");
        self.closeForm();
        await self.load();
      } catch { /* api.js 统一 toast */ }
    },

    async toggle(j) {
      try {
        await post("/api/scheduler-jobs/" + j.id + "/toggle", { group: self.group, enabled: !j.enabled });
        await self.load();
      } catch { /* api.js 统一 toast */ }
    },
    async run(j) {
      try {
        await post("/api/scheduler-jobs/" + j.id + "/run", { group: self.group });
        toast("已触发运行");
        await self.load();
      } catch { /* api.js 统一 toast */ }
    },
    async remove(j) {
      if (!confirm(`删除定时任务「${self.apiJobName(j)}」？`)) return;
      try {
        await del("/api/scheduler-jobs/" + j.id + "?group=" + encodeURIComponent(self.group));
        await self.load();
      } catch { /* api.js 统一 toast */ }
    },
  });
  return self;
}
