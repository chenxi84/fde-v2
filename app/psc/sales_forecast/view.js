/* app/psc/sales_forecast/view.js —— 销售预测（第⑦步：最复杂业务页）
   处理表复合键 version_no + material_no + customer_no + rolling_month；
   无独立 create / update / delete / import_batch：唯一"创建"入口 = open_version（手工参考创建），
   行级变更仅经加工动作 fill_customer / calc_baseline / adjust_event / decide / set_final，
   版本级输出经 summarize / get_summary。写操作随 md_monthly_version.lock_status 流转
   （草稿才可写，发布（锁定）/冻结只读），页面零鉴权（数据范围由后端闸门执法）。 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名；order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "sales_forecast",
  name: "销售预测",
  ic: "📈",
  title: "销售预测",
  crumb: "预测清单→处理→汇总 · 四种方法/异常决策/断点追溯",
  order: 100,
  bold: true,
};

export default function pageSalesForecast() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,                        // 展示工具（dash / fmtTime / tryParse 为 window 全局，模板直接用）

    /* ---- 列表 + 过滤（与 sales_forecast.list(version_no, material_no, customer_no,
            rolling_month, abnormal_flag, page, size) 一一对应；契约无 keyword → 不设关键字搜索） ---- */
    list: null,
    fVersion: "",                    // version_no（来自 md_monthly_version.list）
    fMaterial: "",                   // material_no（autocomplete）
    fCustomer: "",                   // customer_no（autocomplete）
    fRolling: "",                    // 全部 / N+1 / N+2 / N+3
    fAbnormal: "",                   // 全部 / "true"（异常）/ "false"（正常）

    /* ---- 主数据（三份，init 一次性 quiet 加载，失败静默降级为空数组） ---- */
    materialOptions: [],             // md_material.list 扁平项（{material_no, material_name, ...}）
    materialMap: {},                 // { material_no: material_name }
    custOptions: [],                 // md_customer.list 扁平项（{customer_no, customer_name, ...}）
    custMap: {},                     // { customer_no: customer_name }
    versionOptions: [],              // md_monthly_version.list 扁平项（含 lock_status）
    versionMap: {},                  // { version_no: {lock_status, anchor_period, opening_date} }

    /* ---- autocomplete 共享态 ---- */
    autoFiltered: [], autoShow: "",

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 开启版本（open_version 批量生成入口，数据来源类型 = 手工参考创建） ---- */
    openVersionForm: { open: false, busy: false, version_no: "", materialCount: 0 },

    /* ---- 手工新建组合（物料×客户，客户可空）—— 覆盖 open_version 未生成的组合 ---- */
    createForm: { open: false, busy: false, version_no: "", material_no: "", customer_no: "" },

    /* ---- 默认只显示草稿版本（无草稿则不显示任何数据，hideAll） ---- */
    hideAll: false,

    /* ---- 行级加工小模态（填预测 / 事件调整 / 填最终 复用） ---- */
    editForm: { open: false, busy: false, kind: "", row: null, more: false,
      orig_qty: "", adj_qty: "", event_analysis: "", event_adj: "", final_qty: "" },

    /* ---- 版本级汇总 ---- */
    summarizeForm: { open: false, busy: false, version_no: "" },
    summaryQuery: { open: false, busy: false, version_no: "", material_no: "", rows: [] },
    batchBusy: false,
    decideBusy: false,
    importOrigForm: { open: false, busy: false, text: "", result: null },

    /* 即将切换的断点物料（md_breakpoint.upcoming quiet；{material_no: {old,new,switch_time}}） */
    switchMap: {},

    async init() {
      // list 实例须在第一个 await 之前同步建好（items:[]）：tpl 一旦赋值 Alpine 即注入
      // 模板并求值 list.*，若此时 list 仍为 null 会喷「reading 'items' of null」。
      self.list = pageable(async (q) => {
        // 默认只显示草稿版本；无草稿且未手动选版本 → 暂不显示任何数据
        if (self.hideAll && !self.fVersion) return { items: [], total: 0 };
        return svc("sales_forecast", "list", {
          version_no: self.fVersion || undefined,
          material_no: self.fMaterial || undefined,
          customer_no: self.fCustomer || undefined,
          rolling_month: self.fRolling || undefined,
          abnormal_flag: self.fAbnormal || undefined,
          ...q,                        // page / size
        });
      });
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      await self.loadMasters();      // 备齐三份主数据（versionMap 判行编辑态），再拉列表
      // 默认只显示草稿版本；无草稿则暂不显示（hideAll），用户可手动选版本解除
      const draft = (self.versionOptions || []).find((v) => v && v.lock_status === "草稿");
      if (draft) { self.fVersion = draft.version_no; self.hideAll = false; }
      else { self.hideAll = true; }
      await self.list.load();
    },

    /* 批量算基线：对当前版本（可按物料/客户过滤）全部行一次性 calc_baseline */
    async batchBaseline() {
      if (self.batchBusy) return;
      if (!self.fVersion) return toast("请先选择版本", "warn");
      self.batchBusy = true;
      try {
        const r = await svc("sales_forecast", "calc_baseline_batch", {
          version_no: self.fVersion,
          material_no: self.fMaterial || undefined,
          customer_no: self.fCustomer || undefined,
        });
        toast(`批量算基线完成 · 成功 ${r.computed} 行 / 跳过 ${r.failed} 行`);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.batchBusy = false; }
    },

    /* 批量决策：对当前版本（可按物料/客户过滤）全部行一次性 decide */
    async batchDecide() {
      if (self.decideBusy) return;
      if (!self.fVersion) return toast("请先选择版本", "warn");
      self.decideBusy = true;
      try {
        const r = await svc("sales_forecast", "decide_batch", {
          version_no: self.fVersion,
          material_no: self.fMaterial || undefined,
          customer_no: self.fCustomer || undefined,
        });
        toast(`批量决策完成 · 决策 ${r.computed} 行 / 异常 ${r.abnormal} 行 / 跳过 ${r.failed} 行`);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.decideBusy = false; }
    },

    /* ---- 批量导入客户原始预测 ---- */
    openImportOrig() {
      if (!self.fVersion) return toast("请先选择版本", "warn");
      self.importOrigForm = { open: true, busy: false, text: "", result: null };
    },
    closeImportOrig() {
      const done = !!self.importOrigForm.result;
      self.importOrigForm.open = false; self.importOrigForm.result = null;
      if (done) self.list.load(self.list.page);
    },
    onImportOrigFile(evt) {
      const file = evt.target.files && evt.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => { self.importOrigForm.text = String(reader.result || ""); };
      reader.readAsText(file, "utf-8");
    },
    downloadOrigTemplate() {
      const csv = "material_no,customer_no,rolling_month,orig_qty\nM1,C001,N+1,1000\n";
      const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "客户原始预测导入模板.csv";
      a.click();
      URL.revokeObjectURL(a.href);
    },
    parseImportOrigRows() {
      const text = (self.importOrigForm.text || "").replace(/^﻿/, "");
      const rows = [];
      for (const line of text.split(/\r?\n/)) {
        const s = line.trim();
        if (!s) continue;
        if (/^material_no\s*[,，\t]/.test(s)) continue;   // 跳过表头
        const parts = s.split(/[,，\t]/).map((x) => x.trim());
        if (parts.length < 4) continue;
        const [material_no, customer_no, rolling_month, oq] = parts;
        rows.push({ material_no, customer_no, rolling_month, orig_qty: oq });
      }
      return rows;
    },
    async runImportOrig() {
      const rows = self.parseImportOrigRows();
      if (!rows.length) return toast("请粘贴或上传至少一行数据", "warn");
      self.importOrigForm.busy = true; self.importOrigForm.result = null;
      try {
        const r = await svc("sales_forecast", "import_orig_qty",
          { version_no: self.fVersion, rows });
        self.importOrigForm.result = r;
        toast(`导入完成 · 成功 ${r.success} 条 / 失败 ${r.fail} 条`);
      } catch { /* api.js 已 toast */ } finally { self.importOrigForm.busy = false; }
    },

    /* 三份主数据下拉：quiet 探测，失败不喷 toast，零值兜底 */
    async loadMasters() {
      try {
        const r = await svc("md_material", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.materialOptions = rows;
        const map = {};
        for (const m of rows) if (m && m.material_no) map[m.material_no] = m.material_name || m.material_no;
        self.materialMap = map;
      } catch { self.materialOptions = []; self.materialMap = {}; }
      try {
        const r = await svc("md_customer", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.custOptions = rows;
        const map = {};
        for (const c of rows) if (c && c.customer_no) map[c.customer_no] = c.customer_name || c.customer_no;
        self.custMap = map;
      } catch { self.custOptions = []; self.custMap = {}; }
      try {
        const r = await svc("md_monthly_version", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.versionOptions = rows;
        const map = {};
        for (const v of rows) if (v && v.version_no) map[v.version_no] = v;
        self.versionMap = map;
      } catch { self.versionOptions = []; self.versionMap = {}; }
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

    materialName(no) { return (no && self.materialMap[no]) || ""; },
    customerName(no) { return (no && self.custMap[no]) || ""; },
    /* 断点「即将切换」标记：旧件待替换(amber) / 新件待上线(blue) */
    switchInfo(no) {
      const s = no && self.switchMap[no];
      if (!s) return null;
      return s.old
        ? { label: "旧件待替换", cls: "st-amber", time: s.switch_time }
        : { label: "新件待上线", cls: "st-blue", time: s.switch_time };
    },

    /* ---- 过滤 / 分页 ---- */
    search() { self.list.load(1); },
    onVersionChange() {
      self.hideAll = false;          // 手动选择版本后解除"暂不显示"
      self.list.load(1);
    },
    resetFilters() {
      self.fVersion = ""; self.fMaterial = ""; self.fCustomer = "";
      self.fRolling = ""; self.fAbnormal = "";
      self.list.load(1);
    },

    /* ---- autocomplete（每主数据源独立扁平数组；@click.stop 展开 + @input 过滤 + @click.away 关闭） ---- */
    filterAuto(field, nameKey, query) {
      const q = String(query || "").toLowerCase();
      const src = field === "material_no" ? self.materialOptions : self.custOptions;
      self.autoFiltered = src.filter((item) => {
        const code = String(item[field] || "").toLowerCase();
        const name = String(item[nameKey] || "").toLowerCase();
        return code.includes(q) || name.includes(q);
      }).slice(0, 50);
    },
    toggleAuto(showKey, field, nameKey) {
      if (self.autoShow === showKey) { self.autoShow = ""; return; }
      self.autoShow = showKey;
      self.filterAuto(field, nameKey, "");
    },
    pickMaterial(item) { self.fMaterial = item.material_no; self.autoShow = ""; self.search(); },
    pickCustomer(item) { self.fCustomer = item.customer_no; self.autoShow = ""; self.search(); },
    pickSumMaterial(item) { self.summaryQuery.material_no = item.material_no; self.autoShow = ""; },

    /* ---- 版本状态判定（草稿才可写；发布（锁定）/冻结只读） ---- */
    isDraft(row) {
      const v = row && self.versionMap[row.version_no];
      return !!v && v.lock_status === "草稿";
    },
    draftVersions() { return self.versionOptions.filter((v) => v.lock_status === "草稿"); },

    /* ---- 异常标记展示（abnormal_flag 为 0/1 整数，映射后展示） ---- */
    abnormalText(v) { return v ? "异常" : "正常"; },
    abnormalHue(v) { return v ? "red" : "slate"; },
    /* 该品种调整后需求合计：同 版本+物料+滚动月度 全部客户 adj_qty 之和（物料级，行内重复显示） */
    adjSum(d) {
      let s = 0, any = false;
      for (const it of self.list.items || []) {
        if (it && it.version_no === d.version_no && it.material_no === d.material_no
            && it.rolling_month === d.rolling_month && it.adj_qty != null) {
          s += Number(it.adj_qty); any = true;
        }
      }
      return any ? s : null;
    },
    signed(v) {
      if (v === null || v === undefined || v === "") return "—";
      const n = Number(v);
      return (n >= 0 ? "+" : "") + fmt(n);
    },

    /* ---- 详情模态（查全：sales_forecast.get 全字段） ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("sales_forecast", "get", {
          version_no: d.version_no, material_no: d.material_no,
          customer_no: d.customer_no, rolling_month: d.rolling_month,
        });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* 跳转策略拟合页：把物料号写入 sessionStorage 供目标页预填过滤（纯前端、零后端） */
    goFit(d) {
      const no = d && d.material_no;
      if (!no) return toast("该行缺少物料号", "warn");
      try { sessionStorage.setItem("fde.fit.material", no); } catch { /* 隐私模式等忽略 */ }
      location.hash = "#/strategy_fitting";
    },

    /* ---- 行级加工：算基线 / 决策 为按钮直发（无表单）；填预测 / 事件调整 / 填最终 走小模态 ---- */
    async act(d, kind) {
      const key = { version_no: d.version_no, material_no: d.material_no,
        customer_no: d.customer_no, rolling_month: d.rolling_month };
      try {
        let r = null;
        if (kind === "calc_baseline") {
          if (!confirm("确认对该行执行基线计算？（断点追溯 + 四种方法基线计算）")) return;
          r = await svc("sales_forecast", "calc_baseline", key);
          toast(`已算基线 · base_qty=${r.base_qty ?? "—"}`);
        } else if (kind === "decide") {
          if (!confirm("确认执行异常决策？（按 MAPE 与偏离率自动标记并给出最终预测建议）")) return;
          r = await svc("sales_forecast", "decide", key);
          toast(r.abnormal_flag ? "已决策 · 标记异常，待人工填最终预测" : "已决策 · 最终预测已自动给出");
        } else return;
        if (self.modalX.open) self.modalX.d = r;    // 已开模态原地刷新
        await self.list.load(self.list.page);       // 列表刷新当前页
      } catch { /* 非法流转（锁定版本写操作等）由 api.js 统一 toast */ }
    },

    openFill(d) {
      self.editForm = { open: true, busy: false, kind: "fill", row: d, more: false,
        orig_qty: d.orig_qty != null ? d.orig_qty : "", adj_qty: d.adj_qty != null ? d.adj_qty : "",
        event_analysis: "", event_adj: "", final_qty: "" };
    },
    openEvent(d) {
      self.editForm = { open: true, busy: false, kind: "event", row: d, more: false,
        orig_qty: "", adj_qty: "", event_analysis: d.event_analysis || "",
        event_adj: d.event_adj != null ? d.event_adj : "", final_qty: "" };
    },
    openFinal(d) {
      self.editForm = { open: true, busy: false, kind: "final", row: d, more: false,
        orig_qty: "", adj_qty: "", event_analysis: "", event_adj: "",
        final_qty: d.final_qty != null ? d.final_qty : "" };
    },
    closeEdit() { self.editForm.open = false; },
    editTitle() {
      return self.editForm.kind === "fill" ? "填客户预测"
        : self.editForm.kind === "event" ? "事件调整" : "人工填最终预测";
    },
    async submitEdit() {
      const f = self.editForm;
      const d = f.row;
      if (!d) return;
      const key = { version_no: d.version_no, material_no: d.material_no,
        customer_no: d.customer_no, rolling_month: d.rolling_month };
      if (f.kind === "final" && (f.final_qty === "" || f.final_qty == null))
        return toast("请填写最终预测量", "warn");
      f.busy = true;
      try {
        let r = null;
        if (f.kind === "fill") {
          r = await svc("sales_forecast", "fill_customer", {
            ...key,
            orig_qty: f.orig_qty === "" || f.orig_qty == null ? undefined : Number(f.orig_qty),
            adj_qty: f.adj_qty === "" || f.adj_qty == null ? undefined : Number(f.adj_qty),
          });
          toast("已填客户预测");
        } else if (f.kind === "event") {
          r = await svc("sales_forecast", "adjust_event", {
            ...key,
            event_analysis: f.event_analysis && f.event_analysis.trim() ? f.event_analysis.trim() : undefined,
            event_adj: f.event_adj === "" || f.event_adj == null ? 0 : Number(f.event_adj),
          });
          toast("已事件调整");
        } else if (f.kind === "final") {
          r = await svc("sales_forecast", "set_final", { ...key, final_qty: Number(f.final_qty) });
          toast("已人工填最终预测");
        } else return;
        f.open = false;
        if (self.modalX.open) self.modalX.d = r;
        await self.list.load(self.list.page);
      } catch { /* 必填 / 非法值 / 非异常行填最终 由 api.js 统一 toast */ } finally { f.busy = false; }
    },

    /* ---- 开启版本（open_version：正常状态物料 × 历史采购客户 → 清单 + 处理表） ---- */
    async openOpenVersion() {
      self.openVersionForm = { open: true, busy: false, version_no: "", materialCount: 0 };
      try {
        const r = await svc("md_material", "list", { page: 1, size: 1, status: "正常" }, { quiet: true });
        self.openVersionForm.materialCount = (r && r.total != null) ? r.total : (r && r.items ? r.items.length : 0);
      } catch { self.openVersionForm.materialCount = 0; }
    },
    closeOpenVersion() { self.openVersionForm.open = false; },
    async submitOpenVersion() {
      const f = self.openVersionForm;
      if (!f.version_no) return toast("请选择版本", "warn");
      f.busy = true;
      try {
        const r = await svc("sales_forecast", "open_version", { version_no: f.version_no });
        toast(`已开启版本 · 清单 ${r.list_rows} 行 · 处理表 ${r.line_rows} 行`);
        f.open = false;
        self.fVersion = ""; self.fMaterial = ""; self.fCustomer = ""; self.fRolling = ""; self.fAbnormal = "";
        await self.list.load(1);
      } catch { /* 版本不存在 / 已锁定 / 已开启 由 api.js 统一 toast */ } finally { f.busy = false; }
    },

    /* ---- 手工新建组合（物料×客户，客户可空）—— 覆盖 open_version 未生成的组合 ---- */
    openCreate() {
      self.createForm = {
        open: true, busy: false,
        version_no: self.fVersion || "", material_no: "", customer_no: "",
      };
      self.autoShow = "";
    },
    closeCreate() { self.createForm.open = false; self.autoShow = ""; },
    pickCreateMaterial(item) { self.createForm.material_no = item.material_no; self.autoShow = ""; },
    pickCreateCustomer(item) { self.createForm.customer_no = item.customer_no; self.autoShow = ""; },
    async submitCreate() {
      const f = self.createForm;
      if (!f.version_no) return toast("请选择版本", "warn");
      if (!f.material_no) return toast("请选择物料", "warn");
      f.busy = true;
      try {
        await svc("sales_forecast", "create", {
          version_no: f.version_no,
          material_no: f.material_no,
          customer_no: f.customer_no || undefined,
        });
        toast(`已新建组合 · ${f.material_no} × ${f.customer_no || '（空客户）'}`);
        f.open = false;
        self.autoShow = "";
        await self.list.load(self.list.page);
      } catch { /* 物料/客户不存在 / 组合已存在 / 版本已锁定 由 api.js 统一 toast */ } finally { f.busy = false; }
    },

    /* ---- 版本级汇总 ---- */
    openSummarize() { self.summarizeForm = { open: true, busy: false, version_no: "" }; },
    closeSummarize() { self.summarizeForm.open = false; },
    async submitSummarize() {
      const f = self.summarizeForm;
      if (!f.version_no) return toast("请选择版本", "warn");
      f.busy = true;
      try {
        const r = await svc("sales_forecast", "summarize", { version_no: f.version_no });
        toast(`已汇总 ${r.summary_rows} 行`);
        f.open = false;
      } catch { /* 锁定版本 / 无最终预测等 由 api.js 统一 toast */ } finally { f.busy = false; }
    },

    openSummaryQuery() { self.summaryQuery = { open: true, busy: false, version_no: "", material_no: "", rows: [] }; },
    closeSummaryQuery() { self.summaryQuery.open = false; },
    async runSummaryQuery() {
      const f = self.summaryQuery;
      if (!f.version_no) return toast("请选择版本", "warn");
      f.busy = true;
      try {
        f.rows = await svc("sales_forecast", "get_summary", {
          version_no: f.version_no,
          material_no: f.material_no || undefined,
        });
      } catch { f.rows = []; } finally { f.busy = false; }
    },
  });
  return self;
}
