/* app/psc/attainment/view.js —— 达成率与置信度（与后端 attainment.py 同文件夹）
 *
 * 数据来源：唯一来源为「历史台账单表计算」——点击【运算达成率】触发 attainment.compute，
 * 读 sales_history 行内 forecast_qty(F)/qty(A) 计算 MAPE/bias 并回写，列表随即刷新。不再来自 ERP。
 * 前端无 create / update / delete / upsert 手工入口。
 */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名（与后端应用名对齐） */
export const PAGE_META = {
  key: "attainment", name: "达成率与置信度", ic: "📊",
  title: "达成率与置信度", crumb: "派生指标 · 客户×物料 MAPE/bias",
  order: 535,
};

export default function pageAttainment() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,                       // pageable 实例
    customer_no: "",                  // 客户过滤（autocomplete 精确匹配）
    material_no: "",                  // 物料过滤（autocomplete 精确匹配）
    custMap: {}, matMap: {},          // 主数据名称映射：{no: name}（列表/详情名称回显）
    custOptions: [], matOptions: [],  // 主数据 autocomplete 选项（扁平数组，铁律）
    custQuery: "", custOpen: false,   // 客户 autocomplete 输入态 / 展开态
    matQuery: "", matOpen: false,     // 物料 autocomplete 输入态 / 展开态
    modalX: { open: false, loading: false, d: null },
    computing: false,

    /* 百分比展示：小数 → 百分比（mape 非负、无符号） */
    pct(v) {
      if (v === null || v === undefined || v === "") return "—";
      return (Number(v) * 100).toLocaleString("zh-CN", { maximumFractionDigits: 1 }) + "%";
    },
    /* 带符号百分比（bias：多报为正） */
    spct(v) {
      if (v === null || v === undefined || v === "") return "—";
      const p = Number(v) * 100;
      return (p > 0 ? "+" : "") + p.toLocaleString("zh-CN", { maximumFractionDigits: 1 }) + "%";
    },
    /* bias 方向着色：正（多报）暖色 / 负（少报）冷色 / 0 中性 */
    biasStyle(v) {
      if (v === null || v === undefined || v === "") return "";
      if (v > 0) return "color:var(--amber);font-weight:600";
      if (v < 0) return "color:var(--prime);font-weight:600";
      return "color:var(--muted)";
    },

    /* autocomplete 过滤：同时匹配代号与名称 */
    custFiltered() {
      const q = String(self.custQuery || "").trim().toLowerCase();
      if (!q) return self.custOptions;
      return self.custOptions.filter((o) =>
        String(o.customer_no || "").toLowerCase().includes(q) ||
        String(o.customer_name || "").toLowerCase().includes(q));
    },
    matFiltered() {
      const q = String(self.matQuery || "").trim().toLowerCase();
      if (!q) return self.matOptions;
      return self.matOptions.filter((o) =>
        String(o.material_no || "").toLowerCase().includes(q) ||
        String(o.material_name || "").toLowerCase().includes(q));
    },

    pickCust(o) {
      self.customer_no = o.customer_no;
      self.custQuery = o.customer_no;
      self.custOpen = false;
      self.search();
    },
    pickMat(o) {
      self.material_no = o.material_no;
      self.matQuery = o.material_no;
      self.matOpen = false;
      self.search();
    },
    clearCust() {
      self.customer_no = ""; self.custQuery = ""; self.custOpen = false;
      self.search();
    },
    clearMat() {
      self.material_no = ""; self.matQuery = ""; self.matOpen = false;
      self.search();
    },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("attainment", "list",
        { customer_no: self.customer_no || undefined, material_no: self.material_no || undefined, ...q }));
      await self.list.load();
      self.loadMasters();
    },

    /* 主数据名称映射 + autocomplete 选项（quiet 探测：失败不喷 toast、零值兜底） */
    loadMasters() {
      svc("md_customer", "list", { page: 1, size: 200 }, { quiet: true })
        .then((r) => {
          const items = (r && r.items) || [];
          const map = {};
          items.forEach((c) => { map[c.customer_no] = c.customer_name; });
          self.custMap = map;
          self.custOptions = items;
        })
        .catch(() => {});
      svc("md_material", "list", { page: 1, size: 200 }, { quiet: true })
        .then((r) => {
          const items = (r && r.items) || [];
          const map = {};
          items.forEach((m) => { map[m.material_no] = m.material_name; });
          self.matMap = map;
          self.matOptions = items;
        })
        .catch(() => {});
    },

    search() { self.list.load(1); },

    /* 统一运算：一次性计算历史台账中所有 物料+客户 的 MAPE/bias 并回写，随后刷新列表 */
    async runCompute() {
      if (self.computing) return;
      self.computing = true;
      try {
        const r = await svc("attainment", "compute", {});
        toast(`运算完成 · 更新 ${r.computed} 条 / 跳过 ${r.skipped} 条`);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.computing = false; }
    },

    custName(no) { return self.custMap[no] || ""; },
    matName(no) { return self.matMap[no] || ""; },

    /* 详情模态：点 customer_no → get 全量字段（未命中返回 None → 空态） */
    async viewAtt(doc) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("attainment", "get",
          { customer_no: doc.customer_no, material_no: doc.material_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeModal() { self.modalX.open = false; },
  });
  return self;
}
