/* app/psc/inventory_projection/view.js —— 库存推移表（与 inventory_projection.py 同文件夹）
   数据来源类型：自动参考创建——每日 0 点系统定时 refresh_batch 推演生成；契约无 create / update /
   delete → 无业务单据表单，仅「刷新 refresh / 批量刷新 refresh_batch」两个计算触发入口 + 列表 + 详情
   （只读展示，页面零鉴权，数据范围由后端闸门执法）；预警扫描（scan_alert）由 refresh_batch 内部联动，
   前端不单独提供入口。 */
import { svc, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 预警六态徽章配色（本页局部映射，不动公共 HUES）：缺货/击穿=红（击穿警示），
   呆滞/超储=橙（降储治理），无=中性 slate。 */
const ALERT_HUES = { 缺货: "red", 击穿最低: "red", 击穿安全: "red", 呆滞: "amber", 超储: "amber", 无: "slate" };
const alertHue = (t) => ALERT_HUES[t] || "slate";

/* 本地日期 YYYY-MM-DD（不用 toISOString 的 UTC，避免时差跨日） */
function localToday() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/* 月历网格：返回 42 格（6 周 × 7 天，周一为一周首）。本月外为 padding（d=null）。
   cell = { d: Date|null, ds: "YYYY-MM-DD"|"" } */
function buildMonthGrid(ym) {
  const [y, m] = ym.split("-").map(Number);
  const first = new Date(y, m - 1, 1);
  const lead = (first.getDay() + 6) % 7;             // 周一=0
  const start = new Date(y, m - 1, 1 - lead);
  const p = (n) => String(n).padStart(2, "0");
  const cells = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    const inMonth = d.getMonth() === m - 1;
    cells.push({
      d: inMonth ? d : null,
      ds: inMonth ? `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` : "",
    });
  }
  return cells;
}

/* 页面自描述（平台扫描唯一入口）：key = 应用文件夹名；order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "inventory_projection",
  name: "库存推移表",
  ic: "🌊",
  title: "库存推移表",
  crumb: "逐日推演库存水位 · 缺货/击穿/呆滞/超储预警",
  order: 140,
  bold: true,
};

export default function pageInventoryProjection() {
  const self = Alpine.reactive({
    tpl: "",
    fmt, alertHue,

    /* ---- 列表 + 过滤（与 list(material_no, biz_date, alert_type, page, size) 一一对应；契约无 keyword） ---- */
    list: null,
    fMaterial: "",       // material_no（autocomplete 精确匹配）
    fBizDate: "",        // biz_date（精确匹配）
    fAlert: "",          // alert_type 六态 chips（'' = 全部）

    /* ---- 物料主数据（过滤条 / 操作弹窗 / 日历共用一份 autocomplete 数据源） ---- */
    matOptions: [],      // 扁平 material_no 数组（禁止嵌套对象存储）
    matMap: {},          // { material_no: material_name }
    matFiltered: [],     // 过滤后的 material_no 数组（下拉渲染）
    acShow: "",          // "" / "filter" / "op" / "cal" —— 当前展开的 autocomplete

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 操作弹窗（刷新 / 批量刷新；非业务单据表单） ---- */
    op: { open: false, kind: "", busy: false, mat: "", bizDate: "", opening: "", matNos: "", version: "", summary: null },

    /* ---- 视图切换（列表 / 日历） ---- */
    viewMode: "cal",     // "list" | "cal"（默认日历）

    /* ---- 日历视图（单物料月历：余额 + 入/出小字，按预警上色；严格从今天起，历史不显示） ---- */
    cal: {
      material_no: "",
      month: "",         // "YYYY-MM" 月历游标
      loading: false,
      rows: [],          // 该物料全序列（list 无分页返回）
      map: {},           // { "YYYY-MM-DD": row }
      water: null,       // 三层水位 {min_level, safety_level, batch_level}（无策略则 null）
    },

    /* ---- 今日（BR-11：biz_date < 今日的历史快照前端视觉隐藏，数据不删） ---- */
    today: "",

    async init() {
      self.today = localToday();
      self.cal.month = self.today.slice(0, 7);   // 日历默认当月
      // list 实例须在 tpl 赋值前同步建好（items:[]），避免模板求值 list.* 为 null
      self.list = pageable(async (q) => svc("inventory_projection", "list", {
        material_no: self.fMaterial || undefined,
        biz_date: self.fBizDate || undefined,
        alert_type: self.fAlert || undefined,
        ...q,                        // page / size
      }));
      await self.loadMaterials();
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      await self.list.load();
    },

    /* 物料下拉数据源：quiet 探测，失败不喷 toast；零值兜底 → 过滤仅「全部」、弹窗显示空态 */
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

    matName(no) { return (no && self.matMap[no]) || ""; },

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
      const q = which === "op" ? self.op.mat : (which === "cal" ? self.cal.material_no : self.fMaterial);
      self.filterMat(q);
    },
    pickMat(no) {
      if (self.acShow === "op") { self.op.mat = no; }
      else if (self.acShow === "cal") { self.cal.material_no = no; self.loadCal(); }
      else { self.fMaterial = no; }
      self.acShow = "";
    },

    /* ---- 过滤 / 分页 ---- */
    search() { self.list.load(1); },
    resetFilters() {
      self.fMaterial = ""; self.fBizDate = ""; self.fAlert = "";
      self.list.load(1);
    },

    /* BR-11：历史快照隐藏已下沉到后端 list（未选日期时 biz_date>=今日）。
       前端不再二次过滤，保证选定具体历史日期时能正常回看。 */
    isPast(date) { return !!date && date < self.today; },
    get visibleItems() {
      return (self.list && self.list.items) || [];
    },

    /* ---- 日历视图（单物料月历） ---- */
    switchView(mode) {
      self.viewMode = mode;
      if (mode === "cal") {
        if (!self.cal.month) self.cal.month = localToday().slice(0, 7);
        if (self.cal.material_no) self.loadCal();
      }
    },
    async loadCal() {
      const no = self.cal.material_no;
      self.cal.loading = true;
      self.cal.water = null;
      try {
        if (!no) { self.cal.rows = []; self.cal.map = {}; return; }
        // list 不传 page/size → 返回该物料全序列（默认 biz_date 升序、从今天起，历史已隐藏）
        const r = await svc("inventory_projection", "list", { material_no: no });
        const items = Array.isArray(r) ? r : (r && r.items) || [];
        self.cal.rows = items;
        const map = {};
        for (const it of items) map[it.biz_date] = it;
        self.cal.map = map;
      } catch {
        self.cal.rows = [];
        self.cal.map = {};
      } finally {
        self.cal.loading = false;
      }
      // 三层水位单独取：无库存策略时不影响日历主体显示（水位行显示「暂无」）
      try {
        self.cal.water = await svc("inventory_strategy", "get_water_level", {
          version_no: localToday().slice(0, 7).replace("-", ""),
          material_no: no,
        }, { quiet: true });
      } catch {
        self.cal.water = null;
      }
    },
    calShift(delta) {
      const [y, m] = self.cal.month.split("-").map(Number);
      const d = new Date(y, m - 1 + delta, 1);
      self.cal.month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    },
    calThisMonth() { self.cal.month = localToday().slice(0, 7); },
    get calGrid() {
      const rows = self.cal.map;
      return buildMonthGrid(self.cal.month).map((c) =>
        c.d ? { ...c, row: rows[c.ds] || null } : { ...c, row: null }
      );
    },
    get calWeeks() {
      const g = self.calGrid;
      const weeks = [];
      for (let i = 0; i < g.length; i += 7) weeks.push(g.slice(i, i + 7));
      return weeks;
    },
    calBg(row) {
      if (!row) return "#fff";
      return { 缺货: "#fde8e8", 击穿最低: "#fde8e8", 击穿安全: "#fdf3e3", 超储: "#fdf3e3", 无: "#fff" }[row.alert_type] || "#fff";
    },
    calNeg(row) { return row && Number(row.balance) < 0 ? "cal-neg" : ""; },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("inventory_projection", "get", { material_no: d.material_no, biz_date: d.biz_date });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 操作弹窗（自动参考创建：无 create/update/delete 表单） ---- */
    openOp(kind) {
      self.op = {
        open: true, kind, busy: false,
        mat: "",
        bizDate: self.today || localToday(),
        opening: "", matNos: "", version: "", summary: null,
      };
      self.acShow = "";
    },
    closeOp() { self.op.open = false; self.acShow = ""; },

    /* 批量摘要派生：成功物料 / 失败明细 / 触发补库的物料（按物料聚合张数）。
       补库单为系统自动创建——refresh_batch 刷新成功后逐物料 scan_alert，击穿水位
       （缺货/击穿最低/击穿安全）即自动 demand_pool.create，无需人工确认。 */
    get batchSuccessMats() {
      return (self.op.summary && self.op.summary.success_materials) || [];
    },
    get batchReplenishMats() {
      const rs = (self.op.summary && self.op.summary.replenishments) || [];
      const byMat = {};
      for (const r of rs) {
        if (r && r.material_no) byMat[r.material_no] = (byMat[r.material_no] || 0) + 1;
      }
      return Object.keys(byMat).map((no) => ({ material_no: no, count: byMat[no] }));
    },

    async submitOp() {
      const o = self.op;
      if (o.kind === "refresh") {
        if (!o.mat) return toast("请选择物料", "warn");
        if (!o.bizDate) return toast("请选择推演起始日期", "warn");
      }
      o.busy = true;
      try {
        if (o.kind === "refresh") {
          const r = await svc("inventory_projection", "refresh", {
            material_no: o.mat,
            biz_date: o.bizDate,
            opening_stock: (o.opening !== "" && o.opening !== null && o.opening !== undefined) ? Number(o.opening) : undefined,
          });
          toast(`已推演 ${r.generated} 日 · ${r.material_no}`);
          self.closeOp();
          await self.list.load(self.list.page);
        } else if (o.kind === "batch") {
          // 自动口径：起始日期 = 当天，物料范围 = 全量「正常」状态物料（后端缺省值）
          const r = await svc("inventory_projection", "refresh_batch", {});
          o.summary = r;
          toast(`批量刷新完成 · 成功 ${r.success} / 失败 ${r.fail} · 自动补库 ${(r.replenishments || []).length} 张`);
          await self.list.load(self.list.page);
        }
      } catch { /* 物料不存在 / 日期非法 / 无策略记录等由 api.js 统一 toast */ } finally { o.busy = false; }
    },
  });
  return self;
}
