/* app/parts-fc/md_calendar/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "md_calendar", name: "工作日历", ic: "📅",
  title: "工作日历", crumb: "主数据 · 工作日/节假日",
  order: 19,
};

export default function pageMdCalendar() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    list: null,
    keyword: "",
    modalX: { open: false, loading: false, d: null },
    form: { open: false, busy: false, date: "", holiday_name: "", status: "active" },

    statusLabel(s) { return { active: "启用", inactive: "停用" }[s] || s || "—"; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("md_calendar", "list",
        { keyword: self.keyword, ...q }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    async viewX(doc) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("md_calendar", "get", { date: doc.date });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeModal() { self.modalX.open = false; },

    openCreate() {
      self.form = { open: true, busy: false, date: "", holiday_name: "", status: "active" };
    },
    closeCreate() { self.form.open = false; },
    resetForm() {
      self.form.date = ""; self.form.holiday_name = ""; self.form.status = "active";
    },

    async saveForm() {
      const f = self.form;
      if (!f.date || !f.holiday_name) return toast("必填字段缺失", "warn");
      f.busy = true;
      try {
        await svc("md_calendar", "create", {
          date: f.date, holiday_name: f.holiday_name, status: f.status,
        });
        const code = f.date;
        f.open = false; self.resetForm();
        toast(`日历 ${code} 创建成功`);
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },
  });
  return self;
}
