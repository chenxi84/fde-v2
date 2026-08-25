/* app/psc/master_plan/view.js —— 主计划页面工厂（与后端 master_plan.py 同文件夹）
   线下产能平衡结果导回 · 按计划版本号版本化（每次导入 +1）；契约无 update / set_* / delete /
   create，唯一写入口 = import_plan（批量行录入）；无状态机，无行内动作与页脚流转按钮。 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名；order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "master_plan",
  name: "主计划",
  ic: "🗓",
  title: "主计划",
  crumb: "线下产能平衡结果导回 · 计划版本号版本化",
  order: 130,
  bold: true,
};

export default function pageMasterPlan() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,                        // 展示工具（dash / fmtTime / tryParse 为 window 全局，模板直接用）

    /* ---- 列表 + 过滤（与 master_plan.list(version_no, material_no, page, size) 一一对应；
            契约无 keyword 参数 → 不设关键字搜索框，禁止前端假过滤） ---- */
    list: null,
    fVersion: "",                    // version_no（来自 md_monthly_version.list）
    fMaterial: "",                   // material_no（来自 md_material.list）

    /* ---- 主数据下拉（过滤条与导入表单共用；quiet 探测，失败零值兜底） ---- */
    versionOptions: [],              // md_monthly_version.list 返回项（version_no / lock_status）
    versionMap: {},                  // { version_no: lock_status }
    materialOptions: [],             // 扁平数组（主数据引用铁律：禁止嵌套对象 autoOptions[field]）
    materialMap: {},                 // { material_no: material_name }
    materialFiltered: [],            // autocomplete 实时过滤结果
    materialAutoShow: "",            // "filter" | "row<idx>"（哪个 autocomplete 展开）

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 导入表单（import_plan：version_no 顶部一次指定 + 批量行录入） ---- */
    importForm: {
      open: false, busy: false,
      version_no: "",
      rows: [],                      // [{ material_no, rolling_month, plan_qty, latest_inbound_date }]
      errors: [],                    // 后端逐行校验失败明细 { row, field, message }
    },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      // list 实例须在后续 await 之前同步建好（items:[]）：tpl 一旦赋值 Alpine 即注入
      // 模板并求值 list.*，若此时 list 仍为 null 会喷「reading 'items' of null」。
      self.list = pageable(async (q) => svc("master_plan", "list", {
        version_no: self.fVersion || undefined,
        material_no: self.fMaterial || undefined,
        ...q,                        // page / size
      }));
      await self.loadOptions();      // 备齐月度版本 + 物料下拉，再拉列表数据
      await self.list.load();
    },

    /* 下拉数据源：quiet 探测，失败不喷 toast，零值兜底 */
    async loadOptions() {
      try {
        const r = await svc("md_monthly_version", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.versionOptions = rows;
        const map = {};
        for (const v of rows) if (v && v.version_no) map[v.version_no] = v.lock_status || "";
        self.versionMap = map;
      } catch { self.versionOptions = []; }
      try {
        const r = await svc("md_material", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.materialOptions = rows;
        const map = {};
        for (const m of rows) if (m && m.material_no) map[m.material_no] = m.material_name || m.material_no;
        self.materialMap = map;
      } catch { self.materialOptions = []; }
    },

    materialName(no) { return (no && self.materialMap[no]) || ""; },
    /* rolling_month 三色徽章（N+1/N+2/N+3），未知回落 slate */
    rmHue(rm) { return ({ "N+1": "teal", "N+2": "blue", "N+3": "amber" })[rm] || "slate"; },

    /* ---- 物料号 autocomplete（过滤条 + 导入行共用一份 materialOptions / materialFiltered） ---- */
    filterMaterial(q) {
      const query = (q || "").trim().toLowerCase();
      self.materialFiltered = self.materialOptions.filter((m) => {
        const no = (m.material_no || "").toLowerCase();
        const name = (m.material_name || "").toLowerCase();
        return no.includes(query) || name.includes(query);
      }).slice(0, 50);
    },
    toggleMaterialAuto(key, query) {
      if (self.materialAutoShow === key) { self.materialAutoShow = ""; return; }
      self.materialAutoShow = key;
      self.filterMaterial(query);
    },
    closeMaterial() { self.materialAutoShow = ""; },
    selectMaterialFilter(item) {
      self.fMaterial = item.material_no;
      self.materialAutoShow = "";
      self.search();
    },
    selectMaterialRow(item, idx) {
      const row = self.importForm.rows[idx];
      if (row) row.material_no = item.material_no;
      self.materialAutoShow = "";
    },

    /* ---- 过滤 / 分页 ---- */
    search() { self.list.load(1); },
    resetFilters() {
      self.fVersion = ""; self.fMaterial = "";
      self.list.load(1);
    },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("master_plan", "get", {
          plan_version: d.plan_version,
          material_no: d.material_no,
          rolling_month: d.rolling_month,
        });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 导入表单（唯一写入口：import_plan 批量行录入） ---- */
    openImport() {
      self.importForm = {
        open: true, busy: false, version_no: "",
        rows: [{ material_no: "", rolling_month: "", plan_qty: "", latest_inbound_date: "" }],
        errors: [],
      };
    },
    closeImport() { self.importForm.open = false; },
    addRow() {
      self.importForm.rows.push({ material_no: "", rolling_month: "", plan_qty: "", latest_inbound_date: "" });
    },
    removeRow(idx) {
      if (self.importForm.rows.length <= 1) return;   // 至少保留 1 行
      self.importForm.rows.splice(idx, 1);
    },

    async saveImport() {
      const f = self.importForm;
      if (!f.version_no) return toast("请选择月度版本", "warn");
      for (let i = 0; i < f.rows.length; i++) {
        const r = f.rows[i];
        if (!r.material_no) return toast(`第 ${i + 1} 行物料号不能为空`, "warn");
        if (!r.rolling_month) return toast(`第 ${i + 1} 行滚动月度不能为空`, "warn");
        if (r.plan_qty === "" || r.plan_qty === null || r.plan_qty === undefined)
          return toast(`第 ${i + 1} 行需求量不能为空`, "warn");
        if (!r.latest_inbound_date) return toast(`第 ${i + 1} 行最迟入库日期不能为空`, "warn");
      }
      f.busy = true;
      try {
        const res = await svc("master_plan", "import_plan", {
          version_no: f.version_no,
          rows: f.rows.map((r) => ({
            material_no: r.material_no,
            rolling_month: r.rolling_month,
            plan_qty: r.plan_qty,
            latest_inbound_date: r.latest_inbound_date,
          })),
        });
        if (res && res.fail > 0) {
          // 部分失败：成功行已落库，失败明细在模态内回显，不关模态
          f.errors = res.errors || [];
          toast(`导入完成 · 成功 ${res.success} 行 / 失败 ${res.fail} 行`, "warn");
        } else {
          toast(`已导入 · 新版本 v${(res && res.plan_version != null) ? res.plan_version : ""}`);
          self.closeImport();
        }
        if (res && res.success > 0) {
          self.fVersion = ""; self.fMaterial = "";   // 重置过滤，新版本自然置顶
          await self.list.load(1);
        }
      } catch { /* 版本不存在 / 非法枚举等由 api.js 统一 toast，页面不硬编校验 */ } finally { f.busy = false; }
    },
  });
  return self;
}
