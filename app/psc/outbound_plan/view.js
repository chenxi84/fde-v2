/* app/psc/outbound_plan/view.js —— 出库计划（与 outbound_plan.py 同文件夹）
   手工参考创建：业务人员手工登记出库计划（客户/物料/数量/计划出库日期/实际出库单号）。
   到期自动关闭（后端惰性关闭：list/get 读取时结算，前端无需轮询）；已关闭仍可编辑延期，
   延期到今日及以后自动恢复「待出库」。库存推移表预计出库量只取「待出库」计划。 */
import { svc, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 状态徽章（本页局部映射）：待出库=绿（在途执行），已关闭=中性 slate（历史留痕） */
const STATUS_HUES = { 待出库: "green", 已关闭: "slate" };
const statusHue = (s) => STATUS_HUES[s] || "slate";

/* 本地日期 YYYY-MM-DD（不用 toISOString 的 UTC，避免时差跨日） */
function localToday() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/* 页面自描述（平台扫描唯一入口）：key = 应用文件夹名；order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "outbound_plan",
  name: "出库计划",
  ic: "📤",
  title: "出库计划",
  crumb: "手工登记出库计划 · 到期自动关闭 · 可延期恢复",
  order: 135,
};

export default function pageOutboundPlan() {
  const self = Alpine.reactive({
    tpl: "",
    fmt, statusHue,

    /* ---- 列表 + 过滤（与 list(material_no, customer_no, status, page, size) 一一对应） ---- */
    list: null,
    fMaterial: "",        // material_no（autocomplete 精确匹配）
    fCustomer: "",        // customer_no（下拉精确匹配）
    fStatus: "",          // 状态 chips（'' = 全部）

    /* ---- 主数据下拉（物料 autocomplete + 客户 select；过滤条与表单共用一份数据源） ---- */
    matOptions: [],       // 扁平 material_no 数组
    matMap: {},           // { material_no: material_name }
    matFiltered: [],      // 过滤后的 material_no 数组（下拉渲染）
    acShow: "",           // "" / "filter" / "form" —— 当前展开的 autocomplete
    custOptions: [],      // [{customer_no, customer_name}]
    custMap: {},          // { customer_no: customer_name }

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 新建 / 编辑共用表单（mode: create | edit） ---- */
    form: {
      open: false, busy: false, mode: "create",
      plan_no: "", customer_no: "", material_no: "", qty: "", out_date: "", actual_out_no: "",
    },

    today: "",

    async init() {
      self.today = localToday();
      // list 实例须在 tpl 赋值前同步建好（items:[]），避免模板求值 list.* 为 null
      self.list = pageable(async (q) => svc("outbound_plan", "list", {
        material_no: self.fMaterial || undefined,
        customer_no: self.fCustomer || undefined,
        status: self.fStatus || undefined,
        ...q,                        // page / size
      }));
      await Promise.all([self.loadMaterials(), self.loadCustomers()]);
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      await self.list.load();
    },

    /* 物料下拉数据源：quiet 探测，失败零值兜底 */
    async loadMaterials() {
      try {
        const r = await svc("md_material", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        const opts = [];
        const map = {};
        for (const m of rows) {
          if (m && m.material_no) {
            opts.push(m.material_no);
            map[m.material_no] = m.material_name || m.material_no;
          }
        }
        self.matOptions = opts;
        self.matMap = map;
        self.matFiltered = opts.slice(0, 50);
      } catch {
        self.matOptions = [];
        self.matMap = {};
        self.matFiltered = [];
      }
    },

    /* 客户下拉数据源：quiet 探测，失败零值兜底 */
    async loadCustomers() {
      try {
        const r = await svc("md_customer", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.custOptions = rows.filter((c) => c && c.customer_no);
        const map = {};
        for (const c of self.custOptions) map[c.customer_no] = c.customer_name || c.customer_no;
        self.custMap = map;
      } catch {
        self.custOptions = [];
        self.custMap = {};
      }
    },

    matName(no) { return (no && self.matMap[no]) || ""; },
    custName(no) { return (no && self.custMap[no]) || ""; },

    /* autocomplete：@input 实时过滤（同时匹配代号与名称），@click.stop 展开 */
    filterMat(q) {
      const query = (q || "").toLowerCase();
      self.matFiltered = self.matOptions
        .filter((no) => {
          if (!query) return true;
          const code = (no || "").toLowerCase();
          const name = (self.matMap[no] || "").toLowerCase();
          return code.includes(query) || name.includes(query);
        })
        .slice(0, 50);
    },
    openAc(which) {
      self.acShow = which;
      self.filterMat(which === "form" ? self.form.material_no : self.fMaterial);
    },
    pickMat(no) {
      if (self.acShow === "form") self.form.material_no = no;
      else self.fMaterial = no;
      self.acShow = "";
    },

    /* ---- 过滤 / 分页 ---- */
    search() { self.list.load(1); },
    resetFilters() {
      self.fMaterial = ""; self.fCustomer = ""; self.fStatus = "";
      self.list.load(1);
    },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("outbound_plan", "get", { plan_no: d.plan_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 新建 / 编辑 ---- */
    openCreate() {
      self.form = {
        open: true, busy: false, mode: "create",
        plan_no: "", customer_no: "", material_no: "", qty: "", out_date: self.today, actual_out_no: "",
      };
      self.acShow = "";
    },
    openEdit(d) {
      self.form = {
        open: true, busy: false, mode: "edit",
        plan_no: d.plan_no, customer_no: d.customer_no || "", material_no: d.material_no || "",
        qty: (d.qty === null || d.qty === undefined) ? "" : String(d.qty),
        out_date: d.out_date || "", actual_out_no: d.actual_out_no || "",
      };
      self.acShow = "";
    },
    /* 详情页脚 → 编辑（先关详情再开表单，避免双模态叠层） */
    editFromDetail() {
      const d = self.modalX.d;
      self.modalX.open = false;
      if (d) self.openEdit(d);
    },
    closeForm() { self.form.open = false; self.acShow = ""; },

    formTitle() {
      return self.form.mode === "create" ? "新建出库计划" : `编辑出库计划 · ${self.form.plan_no}`;
    },

    async save() {
      const f = self.form;
      if (!f.customer_no) return toast("请选择客户", "warn");
      if (!f.material_no) return toast("请选择物料", "warn");
      if (!f.out_date) return toast("请选择计划出库日期", "warn");
      if (f.qty === "" || Number(f.qty) <= 0) return toast("出库数量必须大于 0", "warn");
      f.busy = true;
      try {
        if (f.mode === "create") {
          await svc("outbound_plan", "create", {
            customer_no: f.customer_no,
            material_no: f.material_no,
            qty: Number(f.qty),
            out_date: f.out_date,
            actual_out_no: f.actual_out_no || undefined,
          });
          toast("出库计划创建成功");
          f.open = false;
          await self.list.load(1);
        } else {
          await svc("outbound_plan", "update", {
            plan_no: f.plan_no,
            customer_no: f.customer_no,
            material_no: f.material_no,
            qty: Number(f.qty),
            out_date: f.out_date,
            actual_out_no: f.actual_out_no,
          });
          toast("出库计划已更新（延期到今日及以后将恢复待出库）");
          f.open = false;
          await self.list.load(self.list.page);
        }
      } catch { /* 主数据不存在 / 日期非法等由 api.js 统一 toast */ } finally { f.busy = false; }
    },

    /* 删除：仅待出库可删（后端拦截已关闭），confirm 二次确认 */
    async removeX(d) {
      if (!confirm(`确认删除出库计划 ${d.plan_no}？`)) return;
      try {
        await svc("outbound_plan", "delete", { plan_no: d.plan_no });
        toast("出库计划已删除");
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },
  });
  return self;
}
