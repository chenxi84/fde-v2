/* app/forecast/md_fcst_version/view.js —— 月度版本 */
import { svc, hue, dash, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "md_fcst_version", name: "月度版本", ic: "\u{1F4C5}",
  title: "月度版本", crumb: "计划周期 · Opening · R版联动",
  order: 160,
};

export default function pageMdFcstVersion() {
  const self = Alpine.reactive({
    tpl: "", hue, dash, fmt: (v) => dash(v),
    list: null,
    modal: { open: false, loading: false, d: null },
    form: { open: false, fcst_version: "", base_period: "", opening_date: "" },
    computedPeriods: [],
    lockForm: { open: false, fcst_version: "", rel_no: "" },

    get computedPeriodsDisplay() {
      return self.computedPeriods;
    },

    recalcPeriods() {
      const bp = (self.form.base_period || "").trim();
      if (!bp || bp.length < 7) { self.computedPeriods = []; return; }
      try {
        const [y, m] = bp.split("-").map(Number);
        if (!y || !m || m < 1 || m > 12) { self.computedPeriods = []; return; }
        const periods = [];
        for (let i = 1; i <= 3; i++) {
          let mm = m + i, yy = y;
          if (mm > 12) { mm -= 12; yy += 1; }
          periods.push(`${yy}-${String(mm).padStart(2, "0")}`);
        }
        self.computedPeriods = periods;
      } catch { self.computedPeriods = []; }
    },

    async init() {
      self.list = pageable(async (q) => svc("md_fcst_version", "list", { ...q }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then(r => r.text());
      await self.list.load();
    },

    search() { self.list.load(1); },

    showCreate() {
      self.form = { open: true, fcst_version: "", base_period: "", opening_date: "" };
      self.computedPeriods = [];
    },

    async view(d) {
      self.modal = { open: true, loading: true, d: null };
      try { self.modal.d = await svc("md_fcst_version", "get", { fcst_version: d.fcst_version }); }
      catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    async save() {
      const f = self.form;
      if (!f.fcst_version || !f.base_period) { toast("版本号和锚定期间均必填"); return; }
      if (!self.computedPeriods.length) { toast("锚定期间格式不正确，无法推算预测期间"); return; }
      try {
        await svc("md_fcst_version", "create", {
          fcst_version: f.fcst_version,
          base_period: f.base_period,
          periods: self.computedPeriods,
          opening_date: f.opening_date || undefined,
        });
        toast(`月度版本创建成功 · ${f.fcst_version}`);
        self.form.open = false; self.computedPeriods = [];
        await self.list.load(1);
      } catch (e) { /* api.js */ }
    },

    showLock(d) {
      self.lockForm = { open: true, fcst_version: d.fcst_version, rel_no: "" };
    },
    async doLock() {
      const lf = self.lockForm;
      try {
        await svc("md_fcst_version", "set_linked", {
          fcst_version: lf.fcst_version,
          rel_no: lf.rel_no || undefined,
        });
        toast("版本已锁定");
        self.lockForm.open = false;
        if (self.modal.d && self.modal.d.fcst_version === lf.fcst_version) {
          self.modal.d = await svc("md_fcst_version", "get", { fcst_version: lf.fcst_version });
        }
        await self.list.load();
      } catch (e) { /* api.js */ }
    },
  });
  return self;
}
