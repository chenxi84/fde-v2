/* app/psc/inventory_strategy/view.js —— 库存策略（与后端 inventory_strategy.py 同文件夹）
   自动参考创建：三层水位 / 对冲工具均为系统计算派生值，禁止手工录入 →
   无 create / update 表单，仅「计算 calc / 批量计算 calc_batch」入口 + 列表 + 详情。 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名；order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "inventory_strategy",
  name: "库存策略",
  ic: "🎚",
  title: "库存策略",
  crumb: "三层水位(最低/安全/组批) · 品种分层(库存/速度对冲)",
  order: 110,
  bold: true,
};

export default function pageInventoryStrategy() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,                       // 展示工具（dash / fmtTime / tryParse 为 window 全局，模板直接用）

    /* ---- 列表 + 过滤（与 inventory_strategy.list(version_no, material_no, hedge_tool, page, size)
            一一对应；契约无 keyword 参数 → 不设独立关键字搜索框） ---- */
    list: null,
    fVersion: "",                   // 月度版本（md_monthly_version.list）
    fMaterial: "",                  // 物料号（md_material.list，后端 LIKE 模糊）
    fHedge: "",                     // 全部 / 库存 / 速度（BR-14 枚举）

    /* ---- 主数据选项（过滤条与计算入口共用一份；quiet 探测零值兜底） ---- */
    versionOptions: [],             // md_monthly_version.list items
    materialOptions: [],            // md_material.list items（独立扁平数组，禁止嵌套对象存储）
    materialNames: {},              // { material_no: material_name }
    materialFiltered: [],           // 当前 autocomplete 过滤结果
    matOpen: "",                    // 'f' 过滤条 / 'c' 计算入口 / '' 关闭

    /* 即将切换的断点物料（md_breakpoint.upcoming quiet） */
    switchMap: {},

    /* ---- 计算入口（自动参考创建豁免；仅 calc / calc_batch） ---- */
    calc: { version_no: "", material_no: "", busy: false, batchBusy: false },

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      // list 实例须在后续任何 await 之前同步建好（items:[]）：tpl 一旦赋值 Alpine 即注入
      // 模板并求值 list.*，若此时 list 仍为 null 会喷「reading 'items' of null」。
      self.list = pageable(async (q) => svc("inventory_strategy", "list", {
        version_no: self.fVersion || undefined,
        material_no: self.fMaterial || undefined,
        hedge_tool: self.fHedge || undefined,
        ...q,                        // page / size（契约 integer 型，照传）
      }));
      await self.loadOptions();      // 备齐版本/物料选项，再拉列表数据
      await self.list.load();
    },

    /* 主数据下拉数据源：quiet 探测，失败不喷 toast，零值兜底 */
    async loadOptions() {
      try {
        const r = await svc("md_monthly_version", "list", { page: 1, size: 200 }, { quiet: true });
        self.versionOptions = (r && r.items) || [];
      } catch { self.versionOptions = []; }
      try {
        const r = await svc("md_material", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = (r && r.items) || [];
        self.materialOptions = rows;
        const names = {};
        for (const m of rows) if (m && m.material_no) names[m.material_no] = m.material_name || "";
        self.materialNames = names;
      } catch { self.materialOptions = []; }
      // 断点「即将切换」物料（60 天内 switch_time，quiet；旧件/新件都纳入）
      try {
        const r = await svc("md_breakpoint", "upcoming", { days: 60 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        const map = {};
        for (const b of rows) {
          if (!b) continue;
          const st = b.switch_time || "";
          if (b.old_material_no) { map[b.old_material_no] = map[b.old_material_no] || {}; map[b.old_material_no].old = true; if (st) map[b.old_material_no].switch_time = st; }
          if (b.new_material_no) { map[b.new_material_no] = map[b.new_material_no] || {}; map[b.new_material_no].new = true; if (st) map[b.new_material_no].switch_time = st; }
        }
        self.switchMap = map;
      } catch { self.switchMap = {}; }
    },

    materialName(no) { return (no && self.materialNames[no]) || ""; },
    batchDays(v) { return (v === null || v === undefined || v === "") ? "—" : v + " 天"; },
    /* 断点「即将切换」标记：旧件待替换(amber) / 新件待上线(blue) */
    switchInfo(no) {
      const s = no && self.switchMap[no];
      if (!s) return null;
      return s.old
        ? { label: "旧件待替换", cls: "st-amber", time: s.switch_time }
        : { label: "新件待上线", cls: "st-blue", time: s.switch_time };
    },

    /* ---- 物料 autocomplete（内联下拉；@click.stop 切换 + @input 过滤 + @click.away 关闭；
            同时匹配 material_no 与 material_name；选中后存 material_no） ---- */
    filterMaterial(q) {
      const kw = (q || "").toLowerCase();
      self.materialFiltered = self.materialOptions.filter((m) => {
        const no = (m.material_no || "").toLowerCase();
        const name = (m.material_name || "").toLowerCase();
        return no.includes(kw) || name.includes(kw);
      }).slice(0, 50);
    },
    openMaterial(which) {
      self.matOpen = which;
      self.filterMaterial(which === "f" ? self.fMaterial : self.calc.material_no);
    },
    pickMaterial(m, which) {
      if (which === "f") self.fMaterial = m.material_no;
      else self.calc.material_no = m.material_no;
      self.matOpen = "";
    },

    /* ---- 过滤 / 分页 ---- */
    search() { self.list.load(1); },
    resetFilters() {
      self.fVersion = ""; self.fMaterial = ""; self.fHedge = "";
      self.list.load(1);
    },

    /* ---- 计算入口：单物料计算（version_no + material_no 必填；不传 customer_no） ---- */
    async calcOne() {
      const c = self.calc;
      if (!c.version_no) return toast("请选择月度版本", "warn");
      if (!c.material_no) return toast("请选择物料", "warn");
      c.busy = true;
      try {
        const r = await svc("inventory_strategy", "calc", { version_no: c.version_no, material_no: c.material_no });
        toast(`已计算 · ${c.material_no}`);
        if (self.modalX.open && r && r.version_no === c.version_no && r.material_no === c.material_no) {
          self.modalX.d = r;         // 已开模态原地刷新
        }
        await self.list.load(self.list.page);
      } catch { /* 物料不存在 / 版本非法 / 满足率不支持等由 api.js 统一 toast */ } finally { c.busy = false; }
    },

    /* ---- 批量计算：仅需 version_no，逐物料计算，单个失败不中断 ---- */
    async calcBatch() {
      const c = self.calc;
      if (!c.version_no) return toast("请选择月度版本", "warn");
      c.batchBusy = true;
      try {
        const r = await svc("inventory_strategy", "calc_batch", { version_no: c.version_no });
        toast(`批量计算完成：成功 ${r.success} / 失败 ${r.fail}`);
        if (r.fail > 0 && r.errors && r.errors.length) {
          const msgs = r.errors.slice(0, 5).map((e) => `${e.material_no || "?"}：${e.message}`);
          toast("失败明细：" + msgs.join("；") + (r.errors.length > 5 ? "…" : ""), "warn");
        }
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { c.batchBusy = false; }
    },

    /* ---- 行内 / 模态页脚重算（重复计算覆盖更新，BR-01） ---- */
    async recalc(d) {
      try {
        const r = await svc("inventory_strategy", "calc", { version_no: d.version_no, material_no: d.material_no });
        toast(`已重算 · ${d.material_no}`);
        if (self.modalX.open && r && r.version_no === d.version_no && r.material_no === d.material_no) {
          self.modalX.d = r;
        }
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    /* ---- 详情模态 ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("inventory_strategy", "get", { version_no: d.version_no, material_no: d.material_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },
  });
  return self;
}
