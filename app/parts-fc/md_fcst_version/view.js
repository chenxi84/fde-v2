/* app/parts-fc/md_fcst_version/view.js */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "md_fcst_version", name: "预测版本", ic: "📆",
  title: "预测版本主数据", crumb: "主数据 · 预测版本",
  order: 20,
};

export default function pageMdFcstVersion() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    list: null,
    keyword: "",
    modalX: { open: false, loading: false, d: null },
    form: { open: false, busy: false, version_code: "", period: "", status: "活跃" },

    statusLabel(s) { return { "活跃": "活跃", "已关闭": "已关闭" }[s] || s || "—"; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("md_fcst_version", "list",
        { keyword: self.keyword, ...q }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    async viewX(doc) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("md_fcst_version", "get", { version_code: doc.version_code });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeModal() { self.modalX.open = false; },

    openCreate() {
      self.form = { open: true, busy: false, version_code: "", period: "", status: "活跃" };
    },
    closeCreate() { self.form.open = false; },

    /* V202601 → 2026-01 自动推导 */
    derivePeriod(v) {
      const m = (v || "").match(/^V(\d{4})(\d{2})$/);
      if (m) { self.form.period = m[1] + "-" + m[2]; }
    },

    async saveForm() {
      const f = self.form;
      if (!f.version_code || !f.period) return toast("版本号和期间必填", "warn");
      if (!/^V\d{6}$/.test(f.version_code)) return toast("版本号格式须为 V+YYYYMM，如 V202601", "warn");
      f.busy = true;
      try {
        await svc("md_fcst_version", "create", {
          version_code: f.version_code, period: f.period, status: f.status,
        });
        toast(`版本 ${f.version_code} 创建成功`);
        f.open = false;
        await self.list.load(1);
      } catch { } finally { f.busy = false; }
    },
  });
  return self;
}
