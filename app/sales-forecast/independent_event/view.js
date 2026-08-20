/* app/sales-forecast/independent_event/view.js —— 独立事件登记表（D06），叠加结构独立加项唯一载体 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "independent_event",
  name: "独立事件",
  ic: "⚡",
  title: "独立事件",
  crumb: "独立事件登记 · 水位脉冲 / 断点 / 其他事件 · 叠加结构加项载体",
  order: 50,
};

export default function pageIndependentEvent() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,

    /* ---- 列表 + 过滤 ---- */
    list: null,
    fStatus: "",
    fEventType: "",

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 关闭/取消弹窗 ---- */
    closeForm: { open: false, busy: false, event_no: "", action: "", actionLabel: "", close_basis: "" },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("independent_event", "list", {
        status: self.fStatus || undefined,
        event_type: self.fEventType || undefined,
        ...q,
      }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("independent_event", "get", { event_no: d.event_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 状态机动作 ---- */
    async act(d, kind) {
      const no = d.event_no;
      try {
        let r = null;
        if (kind === "confirm") {
          r = await svc("independent_event", "confirm", { event_no: no });
        } else if (kind === "mark_sustained") {
          r = await svc("independent_event", "mark_sustained", { event_no: no });
        } else if (kind === "mark_subsided") {
          self.openClose(no, "mark_subsided", "标记回落");
          return;
        } else if (kind === "close") {
          self.openClose(no, "close", "关闭");
          return;
        } else if (kind === "cancel") {
          self.openClose(no, "cancel", "取消");
          return;
        } else return;
        if (r) {
          toast(kind === "confirm" ? "已确认 · " + no : "已标记持续中 · " + no);
          if (self.modalX.open) self.modalX.d = r;
          await self.list.load(self.list.page);
        }
      } catch { /* api.js 已 toast */ }
    },

    openClose(event_no, action, actionLabel) {
      self.closeForm = { open: true, busy: false, event_no, action, actionLabel, close_basis: "" };
    },
    closeCloseForm() { self.closeForm.open = false; },
    async submitClose() {
      const f = self.closeForm;
      if (!f.close_basis.trim()) return toast("请填写依据/原因", "warn");
      f.busy = true;
      try {
        let r = null;
        if (f.action === "mark_subsided") {
          r = await svc("independent_event", "mark_subsided", { event_no: f.event_no, close_basis: f.close_basis.trim() });
          toast("已标记回落 · " + f.event_no);
        } else if (f.action === "close") {
          r = await svc("independent_event", "close", { event_no: f.event_no, close_basis: f.close_basis.trim() });
          toast("已关闭 · " + f.event_no);
        } else if (f.action === "cancel") {
          r = await svc("independent_event", "cancel", { event_no: f.event_no, close_basis: f.close_basis.trim() });
          toast("已取消 · " + f.event_no);
        }
        self.closeForm.open = false;
        if (self.modalX.open && r) self.modalX.d = r;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { f.busy = false; }
    },

    statusLabel(s) {
      return { "待确认": "待确认", "生效": "生效", "持续中": "持续中", "已回落": "已回落", "已关闭": "已关闭", "已取消": "已取消" }[s] || s || "—";
    },

    eventTypeLabel(t) {
      return { "水位脉冲": "水位脉冲", "断点·旧件截断": "断点·旧件截断", "断点·新件启动": "断点·新件启动", "其他": "其他" }[t] || t || "—";
    },
  });
  return self;
}
