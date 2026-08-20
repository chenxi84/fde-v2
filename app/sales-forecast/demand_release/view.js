/* app/sales-forecast/demand_release/view.js —— 毛需求发布单（D09），加工链终点 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "demand_release",
  name: "需求发布",
  ic: "📤",
  title: "需求发布",
  crumb: "毛需求发布 · 冻结口径R版下达 · 净需求唯一输入 · 加工链终点",
  order: 40,
};

export default function pageDemandRelease() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,

    /* ---- 列表 + 过滤 ---- */
    list: null,
    fStatus: "",

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("demand_release", "list", {
        status: self.fStatus || undefined,
        ...q,
      }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("demand_release", "get", { rel_no: d.rel_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- Checklist 校验 ---- */
    async checklistVerify(d) {
      const no = d.rel_no || (d.header && d.header.rel_no);
      try {
        const r = await svc("demand_release", "checklist_verify", { rel_no: no });
        const allPass = r.all_pass;
        toast(allPass ? "Checklist 全部通过，状态已切换至「待发布」" : "Checklist 存在不通过项，请检查");
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await svc("demand_release", "get", { rel_no: no });
        }
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    /* ---- 发布 ---- */
    async publish(d) {
      const no = d.rel_no || (d.header && d.header.rel_no);
      if (!confirm("发布后将联动锁定 D04 批次与 D03 版本，确定发布？")) return;
      try {
        const r = await svc("demand_release", "publish", { rel_no: no });
        toast("已发布 · " + no);
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await svc("demand_release", "get", { rel_no: no });
        }
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    statusLabel(s) {
      return { "草稿": "草稿", "待发布": "待发布", "已发布": "已发布", "已替代": "已替代" }[s] || s || "—";
    },
  });
  return self;
}
