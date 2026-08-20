/* app/psc/demand/view.js —— 毛需求与净需求页面工厂（与 demand.py 同文件夹）
   手工参考创建：契约无 create / update / delete / import_batch，单据变更仅经版本级操作
   build_gross / publish / calc_net / export_net；状态机随 md_monthly_version.lock_status 流转
   （草稿 → 发布（锁定） → 冻结，单向不可逆），本聚合无独立状态列。 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名；order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "demand",
  name: "毛需求与净需求",
  ic: "🧮",
  title: "毛需求与净需求",
  crumb: "毛需求合成发布 · 净需求运算(毛需求+未发−库存−在途)",
  order: 120,
};

const ROLLING_MONTHS = ["N+1", "N+2", "N+3"];   // BR-03 枚举，与后端 ROLLING_MONTHS 一致

export default function pageDemand() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,                       // 展示工具（dash / fmtTime / tryParse 为 window 全局，模板直接用）

    /* ---- 列表 + 过滤（demand.list(version_no, material_no, rolling_month, page, size) 一一对应；
            契约无 keyword 参数 → 不设关键字搜索，禁止前端假过滤） ---- */
    list: null,
    fVersion: "",                   // version_no（兼作操作区版本选择，选中后列表按此过滤）
    hideAll: false,                 // 无草稿版本时默认不显示任何数据
    fMaterial: "",                  // material_no（物料 autocomplete 精确匹配）
    fRolling: "",                   // 全部 / N+1 / N+2 / N+3

    /* ---- 版本下拉（md_monthly_version.list quiet；lock_status 驱动操作区按钮） ---- */
    versionList: [],
    versionMap: {},                 // { version_no: lock_status }
    lockOf(no) { return (no && self.versionMap[no]) || ""; },
    get lockStatus() { return self.lockOf(self.fVersion); },

    /* ---- 物料 autocomplete（md_material.list quiet，扁平数组，禁止嵌套 autoOptions[field]） ---- */
    materialOptions: [],
    matQuery: "",
    matOpen: false,
    get filteredMaterials() {
      const q = (self.matQuery || "").trim().toLowerCase();
      if (!q) return self.materialOptions;
      return self.materialOptions.filter((p) =>
        (p.material_no || "").toLowerCase().includes(q) ||
        (p.material_name || "").toLowerCase().includes(q));
    },

    /* ---- 上游数据摘要（sales_forecast.get_summary quiet，手工参考创建确认） ---- */
    summary: { open: false, loading: false, rows: [] },

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      // list 实例须在 tpl 赋值前同步建好（items:[]）：tpl 一旦赋值 Alpine 即注入模板并求值 list.*
      self.list = pageable(async (q) => {
        // 无草稿且未手动选版本 → 暂不显示任何数据
        if (self.hideAll && !self.fVersion) return { items: [], total: 0 };
        return svc("demand", "list", {
          version_no: self.fVersion || undefined,
          material_no: self.fMaterial || undefined,
          rolling_month: self.fRolling || undefined,
          ...q,                     // page / size（契约 string 型，照传）
        });
      });
      await self.loadVersions();     // 备齐版本 lock_status 映射，再拉列表数据
      await self.loadMaterials();    // 物料 autocomplete 数据源
      // 默认只显示草稿版本；无草稿则暂不显示（hideAll）
      const draft = (self.versionList || []).find((v) => v && v.lock_status === "草稿");
      if (draft) { self.fVersion = draft.version_no; self.hideAll = false; }
      else { self.hideAll = true; }
      await self.list.load();
    },

    /* 版本下拉数据源：quiet 探测，失败不喷 toast，零值兜底（下拉仅「全部」、按钮禁用） */
    async loadVersions() {
      try {
        const r = await svc("md_monthly_version", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.versionList = rows;
        const map = {};
        for (const v of rows) if (v && v.version_no) map[v.version_no] = v.lock_status || "";
        self.versionMap = map;
      } catch { self.versionList = []; self.versionMap = {}; }
    },

    /* 物料 autocomplete 数据源：quiet 探测，失败零值兜底为空数组 */
    async loadMaterials() {
      try {
        const r = await svc("md_material", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.materialOptions = rows;
      } catch { self.materialOptions = []; }
    },

    /* ---- 过滤 / 分页 ---- */
    search() { self.list.load(1); },

    /* 远期（N+2/N+3）用简化列布局：隐藏 未发/库存/在途/净需求（远期按毛额，不扣减） */
    isFar() { return self.fRolling === "N+2" || self.fRolling === "N+3"; },
    onVersionChange() {
      self.hideAll = false;          // 手动选择版本后解除"暂不显示"
      self.summary.open = false;     // 版本切换折叠摘要，避免展示错版本数据
      self.summary.rows = [];
      self.list.load(1);
    },
    resetFilters() {
      self.fVersion = ""; self.fMaterial = ""; self.fRolling = ""; self.matQuery = "";
      self.matOpen = false;
      self.summary.open = false; self.summary.rows = [];
      self.list.load(1);
    },

    selectMaterial(p) {
      self.fMaterial = p.material_no;
      self.matQuery = p.material_no;   // 回填输入框显示所选物料号
      self.matOpen = false;
      self.search();
    },
    clearMaterial() {
      self.fMaterial = ""; self.matQuery = ""; self.matOpen = false;
      self.search();
    },

    /* ---- 上游数据摘要（折叠「上游数据摘要 ▾」） ---- */
    async toggleSummary() {
      self.summary.open = !self.summary.open;
      if (self.summary.open) await self.loadSummary();
    },
    async loadSummary() {
      if (!self.fVersion) { self.summary.rows = []; return; }
      self.summary.loading = true;
      try {
        const r = await svc("sales_forecast", "get_summary", { version_no: self.fVersion }, { quiet: true });
        self.summary.rows = Array.isArray(r) ? r : (r && r.items) || [];
      } catch { self.summary.rows = []; } finally { self.summary.loading = false; }
    },

    /* ---- 详情模态（demand.get 全字段，毛需求/净需求分层拆解） ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("demand", "get", {
          version_no: d.version_no, material_no: d.material_no, rolling_month: d.rolling_month,
        });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 版本级操作（操作区与模态页脚共用；字面量逐项书写，勿变量拼名）
           非法流转（未合成即发布 / 未发布即运算 / 未运算即导出 / 冻结后再合成）由后端
           FdeError 经 api.js 统一 toast，页面不硬编状态机校验 ---- */
    async act(kind, no) {
      const versionNo = no || self.fVersion || "";
      if (!versionNo) return toast("请先选择月度版本", "warn");
      if (kind === "publish" && !confirm("发布后毛需求冻结不可改，联动锁定月度版本，确认发布？")) return;
      try {
        if (kind === "build_gross") {
          const r = await svc("demand", "build_gross", { version_no: versionNo });
          toast(`毛需求合成成功，共 ${(r && r.material_count) || 0} 个物料`);
        } else if (kind === "publish") {
          await svc("demand", "publish", { version_no: versionNo });
          toast("毛需求发布成功");
        } else if (kind === "calc_net") {
          await svc("demand", "calc_net", { version_no: versionNo });
          toast("净需求运算成功");
        } else if (kind === "export_net") {
          const rows = await svc("demand", "export_net", { version_no: versionNo });
          self.exportCsv(rows || [], versionNo);
          toast(`已导出 ${(rows || []).length} 行净需求`);
        } else {
          return;
        }
        await self.loadVersions();                   // 刷新 lock_status，驱动操作区按钮切换
        if (self.modalX.open && self.modalX.d) {     // 已开模态原地刷新（合成/运算后字段变化）
          self.modalX.d = await svc("demand", "get", {
            version_no: self.modalX.d.version_no,
            material_no: self.modalX.d.material_no,
            rolling_month: self.modalX.d.rolling_month,
          });
        }
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    /* 导出净需求清单 → 前端拼 CSV 触发浏览器下载（US-06，供线下产能平衡） */
    exportCsv(rows, versionNo) {
      const head = ["version_no", "material_no", "rolling_month", "net_qty"];
      const lines = [head.join(",")];
      for (const r of rows) {
        lines.push([r.version_no || "", r.material_no || "", r.rolling_month || "", r.net_qty ?? ""].join(","));
      }
      const csv = "﻿" + lines.join("\r\n");
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `net_demand_${versionNo || ""}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    },
  });
  return self;
}
