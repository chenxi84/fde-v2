/* e2e 组级看板（无后端应用的聚合页 · 默认落地页）：
   KPI 指标带（成员 / 任务 / 进行中 / 已完成）+ 任务状态分布。
   对标 view/crm/dashboard.*；svc 一律字面量 + quiet 探测（失败零值兜底，不喷 toast）。 */
import { svc, hue, fmt } from "/view/lib/api.js";

export const PAGE_META = {
  key: "dashboard", name: "首页看板", ic: "▦",
  title: "首页看板", crumb: "成员 · 任务全景 · KPI · 状态分布",
  order: 1,
};

export default function pageDashboard() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    kpi: { members: "…", tasks: "…", doing: "…", done: "…" },
    taskBy: {},                       // { 待办:n, 进行中:n, 已完成:n }
    taskByOrder: ["待办", "进行中", "已完成"],

    async init() {
      self.tpl = await fetch(new URL("dashboard.html", import.meta.url)).then((r) => r.text());
      await self.loadAll();
    },

    async loadAll() {
      // page/size 缺省 → 服务端返回全量 `{total, items}`（**两个应用都必须**，CONVENTION §7）。
      // ⚠ 这两行依赖的是**契约形状**，不是"顺手写写的兜底"：2026-09-18 之前 `task.list` 无参时
      // 返回**裸数组**，`t.items` 取不到 ⇒ 任务类 KPI 与状态分布**恒 0**（且被 0==0 的断言放行）。
      // 所以这里**故意不做裸数组兜底** —— 兜底会让下一个违约者继续蒙混；形状不对就该红。
      const [m, t] = await Promise.all([
        svc("member", "list", {}, { quiet: true }).catch(() => ({ total: 0, items: [] })),
        svc("task", "list", {}, { quiet: true }).catch(() => ({ total: 0, items: [] })),
      ]);
      const tasks = (t && t.items) || [];
      const by = { 待办: 0, 进行中: 0, 已完成: 0 };
      for (const it of tasks) { const s = it.status; by[s] = (by[s] || 0) + 1; }
      self.kpi = {
        members: (m && m.total) ?? 0,
        tasks: (t && t.total) ?? tasks.length,
        doing: by["进行中"] || 0,
        done: by["已完成"] || 0,
      };
      self.taskBy = by;
    },
  });
  return self;
}
