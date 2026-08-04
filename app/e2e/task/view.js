/* app/e2e/task/view.js —— 任务管理页面工厂（与后端 task.py 同文件夹）
   事务单据：创建 / 指派 / 启动 / 完成 / 退回；契约无 update / delete，单据变更仅经状态机动作。 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名；order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "task",
  name: "任务管理",
  ic: "☑",
  title: "任务管理",
  crumb: "事务单据 · 创建 / 指派 / 启动 / 完成 / 退回",
  order: 20,
};

export default function pageTask() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,                        // 展示工具（dash / fmtTime / tryParse 为 window 全局，模板直接用）

    /* ---- 列表 + 过滤（与 task.list(status, assignee_member_no, priority, page, page_size) 一一对应；
            契约无 keyword 参数 → 不设关键字搜索，禁止前端假过滤） ---- */
    list: null,
    fStatus: "",                     // 全部 / 待办 / 进行中 / 已完成
    fAssignee: "",                   // member_no（来自 member.list）
    fPriority: "",                   // 全部 / low / high

    /* ---- 负责人主数据（过滤条与创建表单共用一份） ---- */
    memberList: [],
    memberMap: {},                   // { member_no: name }，供列表列与详情姓名回显

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 创建表单（模态表单；契约无 update → 仅 create） ---- */
    form: { open: false, busy: false, more: false, title: "", assignee_member_no: "", priority: "low", description: "" },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      // list 实例须在任何后续 await 之前同步建好（items:[]）：tpl 一旦赋值 Alpine 即注入
      // 模板并求值 list.*，若此时 list 仍为 null 会喷「reading 'items' of null」（对标 crm 范式）。
      self.list = pageable(async (q) => svc("task", "list", {
        status: self.fStatus || undefined,
        assignee_member_no: self.fAssignee || undefined,
        priority: self.fPriority || undefined,
        ...q,                        // page / page_size（契约 string 型，照传）
      }));
      await self.loadMembers();      // 备齐姓名映射，再拉列表数据
      await self.list.load();
    },

    /* 负责人下拉数据源：quiet 探测，失败不喷 toast，零值兜底 */
    async loadMembers() {
      try {
        const r = await svc("member", "list", { page: 1, page_size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.memberList = rows;
        const map = {};
        for (const m of rows) if (m && m.member_no) map[m.member_no] = m.name || m.member_no;
        self.memberMap = map;
      } catch { /* 失败兜底：过滤下拉仅「全部」、表单下拉显示「暂无可指派成员」 */ }
    },

    memberName(no) { return (no && self.memberMap[no]) || ""; },

    /* ---- 过滤 / 分页 ---- */
    search() { self.list.load(1); },
    resetFilters() {
      self.fStatus = ""; self.fAssignee = ""; self.fPriority = "";
      self.list.load(1);
    },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("task", "get", { task_no: d.task_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 状态机动作：行内操作列与模态页脚共用（待办→启动；进行中→完成/退回；已完成终态无按钮）
            字面量逐项书写，勿变量拼名 ---- */
    async act(d, kind) {
      const no = d.task_no;
      try {
        let r = null;
        if (kind === "start") r = await svc("task", "start", { task_no: no });
        else if (kind === "complete") r = await svc("task", "complete", { task_no: no });
        else if (kind === "reopen") r = await svc("task", "reopen", { task_no: no });
        else return;
        toast(`${kind === "start" ? "已启动" : kind === "complete" ? "已完成" : "已退回"} · ${no}`);
        if (self.modalX.open && r) self.modalX.d = r;   // 已开模态原地刷新
        await self.list.load(self.list.page);           // 列表刷新当前页
      } catch { /* 非法流转等由 api.js 统一 toast，页面不硬编状态机校验 */ }
    },

    /* ---- 创建表单 ---- */
    openCreate() {
      self.form = { open: true, busy: false, more: false, title: "", assignee_member_no: "", priority: "low", description: "" };
    },
    closeCreate() { self.form.open = false; },

    async save() {
      const f = self.form;
      if (!f.title || !f.title.trim()) return toast("请填写任务标题", "warn");
      if (!f.assignee_member_no) return toast("请选择负责人", "warn");
      if (!f.priority) return toast("请选择优先级", "warn");
      f.busy = true;
      try {
        const r = await svc("task", "create", {
          title: f.title.trim(),
          description: f.description && f.description.trim() ? f.description.trim() : undefined,
          assignee_member_no: f.assignee_member_no,
          priority: f.priority,
        });
        toast(`已创建任务 · ${(r && r.task_no) || ""}`);
        self.closeCreate();
        self.fStatus = ""; self.fAssignee = ""; self.fPriority = "";  // 新任务恒「待办」，重置过滤确保可见
        await self.list.load(1);
      } catch { /* 成员不存在（BR-6）等由 api.js 统一 toast */ } finally { f.busy = false; }
    },
  });
  return self;
}