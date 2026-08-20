/* app/parts-fc/demand_collection/view.js —— 主机厂原始需求收集表（D03），加工链入口 */
import { svc, hue, fmt, dash, fmtTime, tryParse, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "demand_collection",
  name: "毛需求收集",
  ic: "📥",
  title: "主机厂原始需求收集",
  crumb: "流程入口 · OEM滚动预测收集 · 信号拆解",
  order: 40,
};

export default function pageDemandCollection() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,

    /* ---- 主数据 autocomplete ---- */
    partOptions: [], vehOptions: [], custOptions: [], userOptions: [], versionOptions: [], autoFiltered: [], autoShow: "", autoDisplay: {},

    async loadAutoOptions(source, field, nameField) {
      try {
        const r = await svc(source, "list", {page_size: 9999}, {quiet:true});
        const items = r.items || [];
        self.autoOptions = items;
        items.forEach(item => {
          self.autoDisplay[item[field]] = item[nameField] || item[field];
        });
      } catch { self.autoOptions = []; }
    },

    filterAuto(field, query) {
      const q = (query || "").toLowerCase();
      const src = field === "part_no" ? self.partOptions : field === "vehicle_code" ? self.vehOptions : field === "customer_code" ? self.custOptions : field === "user_code" ? self.userOptions : field === "version_code" ? self.versionOptions : [];
      self.autoFiltered = src.filter(item => {
        const code = (item[field] || "").toLowerCase();
        const name = (self.autoDisplay[item[field]] || "").toLowerCase();
        return code.includes(q) || name.includes(q);
      }).slice(0, 50);
    },


    toggleAuto(showKey, dataField) {
      if (self.autoShow === showKey) { self.autoShow = ""; return; }
      self.autoShow = showKey;
      self.filterAuto(dataField || showKey, "");
    },

    selectAuto(item, formObj, field, dataField) {
      formObj[field] = item[dataField || field];
      self.autoShow = "";
    },

    openAuto(showKey, dataField) {
      self.autoShow = showKey;
      self.filterAuto(dataField || showKey, "");
    },

    /* ---- 工厂 autocomplete ---- */
    plantOptions: [],
    async loadPlants(customerCode) {
      if (!customerCode) { self.plantOptions = []; return; }
      try {
        const r = await svc("md_customer", "get_plants", {customer_code: customerCode}, {quiet:true});
        self.plantOptions = Array.isArray(r) ? r : [];
      } catch { self.plantOptions = []; }
    },

    /* ---- 列表 + 过滤 ---- */
    list: null,
    fStatus: "",
    fOemCode: "",
    fFcstVersion: "",
    oemOptions: [],
    fcstVersionOptions: [],

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 新建表单 ---- */
    get currentVersion() {
      const now = new Date();
      return "V" + now.getFullYear() + String(now.getMonth() + 1).padStart(2, "0");
    },
    form: { show: false, busy: false, oem_code: "", plant_code: "", fcst_version: "",
            base_period: "", demand_type: "月度滚动预测", source_channel: "", recv_date: "", remark: "" },

    /* ---- 刷新明细（从进行中项目同步新增零件） ---- */
    async syncFromProjects(d) {
      const no = d.collect_no || (d.header && d.header.collect_no);
      try {
        const r = await svc("demand_collection", "sync_from_projects", { collect_no: no });
        toast(r.message || "同步完成");
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await self._fetchDetail(no);
        }
        await self.list.load(self.list.page);
      } catch {}
    },

    /* ---- 录入明细子表单（保留用于特殊场景） ---- */
    linesForm: { open: false, busy: false, collect_no: "", lines: [], oem_code: "", plant_code: "" },
    historyCache: {},

    async loadHistory(part_no, project_no) {
      if (!part_no) return [];
      const cacheKey = part_no + "|" + (project_no || "");
      if (self.historyCache[cacheKey]) return self.historyCache[cacheKey];
      try {
        // 查该零件自身的历史
        const r = await svc("md_material_history", "get_recent", {
          part_no, oem_code: self.linesForm.oem_code, plant_code: self.linesForm.plant_code,
          project_no: project_no || "", months: 6,
        }, { quiet: true });
        let hist = Array.isArray(r) ? [...r] : [];

        // 继承替换物料的历史
        try {
          const replaced = await svc("project_ledger", "get_replacement_for", { part_no }, { quiet: true });
          if (replaced && replaced.replacement_for) {
            const r2 = await svc("md_material_history", "get_recent", {
              part_no: replaced.replacement_for, oem_code: self.linesForm.oem_code,
              plant_code: self.linesForm.plant_code, project_no: project_no || "", months: 6,
            }, { quiet: true });
            if (Array.isArray(r2) && r2.length) {
              hist = [...r2, ...hist];  // 被替换物料的历史排在前面
            }
          }
        } catch {}
        self.historyCache[cacheKey] = hist;
        return hist;
      } catch { return []; }
    },

    /* ---- 逐行拆解子表单 ---- */
    decompForm: { open: false, busy: false, collect_no: "", line_no: "", period: "",
                  noise_adj: 0, pulse_qty: 0, method: "", basis: "" },

    /* ---- 作废弹窗 ---- */
    cancelForm: { open: false, busy: false, collect_no: "", reason: "" },

    /* ---- 替代弹窗 ---- */
    supersedeForm: { open: false, busy: false, collect_no: "", new_collect_no: "" },

    async init() {
      self.list = pageable(async (q) => svc("demand_collection", "list", {
        oem_code: self.fOemCode || undefined,
        fcst_version: self.fFcstVersion || undefined,
        status: self.fStatus || undefined,
        ...q,
      }));
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      await self.list.load();
      try {
        const all = await svc("demand_collection", "list", { all: 1 });
        self.oemOptions = [...new Set((all.items || []).map((d) => d.oem_code).filter(Boolean))];
        self.fcstVersionOptions = [...new Set((all.items || []).map((d) => d.fcst_version).filter(Boolean))];
      } catch { /* 去重加载非关键 */ }
      try { const r = await svc("md_part","list",{page_size:9999},{quiet:true}); self.partOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.part_no]=i.part_name||i.part_no}); } catch {}
      try { const r = await svc("md_vehicle","list",{page_size:9999},{quiet:true}); self.vehOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.vehicle_code]=i.vehicle_name||i.vehicle_code}); } catch {}
      try { const r = await svc("md_customer","list",{page_size:9999},{quiet:true}); self.custOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.customer_code]=i.customer_name||i.customer_code}); } catch {}
      try { const r = await svc("md_user","list",{page_size:9999},{quiet:true}); self.userOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.user_code]=i.user_name||i.user_code}); } catch {}
      try { const r = await svc("md_fcst_version","list",{page_size:9999},{quiet:true}); self.versionOptions = (r.items||[]); (r.items||[]).forEach(i=>{self.autoDisplay[i.version_code]=i.period||i.version_code}); } catch {}
    },

    search() { self.list.load(1); },

    /* ---- 详情模态 ---- */
    /** 获取详情并预建快照映射 */
    async _fetchDetail(collect_no) {
      const data = await svc("demand_collection", "get", { collect_no });
      data._snapMap = {};
      (data.snapshots || []).forEach(s => { data._snapMap[s.line_no] = s; });
      return data;
    },

    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await self._fetchDetail(d.collect_no);
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 预测版本(V202601) → 基准期间(2026-01)自动推导 ---- */
    deriveBasePeriod(v) {
      const m = (v || "").match(/^V(\d{4})(\d{2})$/);
      if (m) { self.form.base_period = m[1] + "-" + m[2]; }
    },

    /* ---- 新建收集单 ---- */
    resetForm() {
      const f = self.form;
      f.oem_code = ""; f.plant_code = ""; f.fcst_version = self.currentVersion; f.base_period = "";
      f.demand_type = "月度滚动预测"; f.source_channel = ""; f.recv_date = ""; f.remark = "";
      self.deriveBasePeriod(f.fcst_version);
    },
    async saveForm() {
      const f = self.form;
      if (!f.oem_code) return toast("客户编码必填", "warn");
      if (!f.plant_code) return toast("工厂编码必填", "warn");
      if (!f.fcst_version) return toast("预测版本必填（请从主数据中选择）", "warn");
      if (!/^V\d{6}$/.test(f.fcst_version)) return toast("预测版本格式须为 V+YYYYMM，如 V202601", "warn");
      if (!f.base_period) return toast("基准期间必填", "warn");
      f.busy = true;
      try {
        const r = await svc("demand_collection", "create", {
          oem_code: f.oem_code, plant_code: f.plant_code, fcst_version: f.fcst_version,
          base_period: f.base_period, demand_type: f.demand_type,
          source_channel: f.source_channel, recv_date: f.recv_date, remark: f.remark,
        });
        if (r.existing) {
          toast("该客户+工厂+版本已存在收集单 " + r.collect_no + "，请直接在已有单据中新增零件", "info");
          f.show = false; self.resetForm();
          // 打开已有收集单详情
          await self.viewX({ collect_no: r.collect_no });
        } else {
          const auto = r.auto_lines || 0;
          toast("已创建收集单 · " + r.collect_no + (auto ? " · 自动填充 " + auto + " 行明细（N+1/+2/+3）" : ""));
          f.show = false; self.resetForm();
        }
        await self.list.load(1);
      } catch { } finally { f.busy = false; }
    },

    /* ---- 录入明细（多行动态） ---- */
    openLines(d) {
      const no = d.collect_no || (d.header && d.header.collect_no);
      const oem = (d.header && d.header.oem_code) || self.linesForm.oem_code || "";
      const plant = (d.header && d.header.plant_code) || self.linesForm.plant_code || "";
      self.historyCache = {};
      self.linesForm = {
        open: true, busy: false, collect_no: no, oem_code: oem, plant_code: plant,
        lines: [{ part_no: "", project_no: "", veh_model: "", period: "", orig_qty: 0, uom: "件", data_flag: "正常", forecast_source: "主机厂预告" }],
      };
    },
    closeLines() { self.linesForm.open = false; },
    addLineRow() {
      self.linesForm.lines.push({ part_no: "", project_no: "", veh_model: "", period: "", orig_qty: 0, uom: "件", data_flag: "正常", forecast_source: "主机厂预告" });
    },
    removeLineRow(i) { if (self.linesForm.lines.length > 1) self.linesForm.lines.splice(i, 1); },
    async submitLines() {
      const f = self.linesForm;
      const invalid = f.lines.some((l) =>
        !l.part_no.trim() || !l.project_no.trim() || !l.veh_model.trim() || !l.period.trim() || !l.orig_qty);
      if (invalid) return toast("每行必填：零件号 / 项目号 / 车型 / 期间 / 原始量", "warn");
      f.busy = true;
      try {
        await svc("demand_collection", "add_lines", {
          collect_no: f.collect_no,
          lines: f.lines.map((l) => ({ ...l, orig_qty: parseFloat(l.orig_qty) || 0, project_no: l.project_no || "" })),
        });
        toast("明细录入完成 · " + f.lines.length + " 行");
        self.closeLines();
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await self._fetchDetail(f.collect_no);
        }
      } catch { } finally { f.busy = false; }
    },

    /* ---- 自动预拆解 ---- */
    decompMethod: "移动平均",
    autoDecompForm: { open: false, busy: false, loading: true, collect_no: "", groups: [], result: null },

    methodInfo: {
      "移动平均":     { desc: "3 期居中移动平均平滑波动", suit: "需求平稳、常规月度滚动预测", tip: "最通用，默认首选" },
      "指数平滑":     { desc: "α=0.3 指数加权，近期数据权重更高", suit: "车型退市衰减、趋势变化明显", tip: "越近的月份影响越大" },
      "阶跃检测":     { desc: "相邻期间差值检测永久性跳变", suit: "新车型投产、产能切换、年款升级", tip: "跳上去就不再回来的变化" },
      "发运结算倒推": { desc: "依赖外部结算数据，当前不可用", suit: "—", tip: "将回退为免拆解" },
      "免拆解":       { desc: "全部归零，不进行自动拆解", suit: "新项目首月、数据不足、不确定时", tip: "保守策略，等人工逐行判断" },
    },

    async openAutoDecomp(d) {
      const no = d.collect_no || (d.header && d.header.collect_no);
      self.autoDecompForm = { open: true, busy: false, loading: true, collect_no: no, groups: [], result: null };
      try {
        const r = await svc("demand_collection", "analyze_groups", { collect_no: no });
        self.autoDecompForm.groups = (r.groups || []).map(g => ({ ...g, selected: g.recommend }));
        self.autoDecompForm.loading = false;
      } catch { self.autoDecompForm.open = false; }
    },
    closeAutoDecomp() { self.autoDecompForm.open = false; },

    /** 一键采纳全部推荐 */
    acceptAllRecommends() {
      self.autoDecompForm.groups.forEach(g => { g.selected = g.recommend; });
    },

    async runAutoDecomp() {
      const f = self.autoDecompForm;
      // 构建 group_methods
      const gm = {};
      f.groups.forEach(g => { gm[g.part_no + '|' + g.veh_model] = g.selected; });
      f.busy = true; f.result = null;
      try {
        const r = await svc("demand_collection", "auto_decompose", {
          collect_no: f.collect_no, method: "移动平均", group_methods: gm,
        });
        f.result = r;
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await self._fetchDetail(f.collect_no);
        }
        await self.list.load(self.list.page);
      } catch { } finally { f.busy = false; }
    },

    /* ---- 逐行拆解（人工覆核） ---- */
    openDecomp(d, snap) {
      const no = d.collect_no || (d.header && d.header.collect_no);
      // 如果传了快照行，预填已有值供覆核
      self.decompForm = {
        open: true, busy: false, collect_no: no,
        line_no: snap ? String(snap.line_no) : "",
        period: snap ? snap.period : "",
        noise_adj: snap ? snap.noise_adj : 0,
        pulse_qty: snap ? snap.pulse_qty : 0,
        method: snap ? snap.method : "",
        basis: snap ? snap.basis : "",
      };
    },
    closeDecomp() { self.decompForm.open = false; },
    get trueQty() {
      const f = self.decompForm;
      return (parseFloat(f.noise_adj) || 0) + (parseFloat(f.pulse_qty) || 0);
    },
    async submitDecomp() {
      const f = self.decompForm;
      if (!f.line_no.trim()) return toast("行号必填", "warn");
      if (!f.period.trim()) return toast("期间必填", "warn");
      if (!f.method.trim()) return toast("拆解方法必填", "warn");
      f.busy = true;
      try {
        await svc("demand_collection", "decompose", {
          collect_no: f.collect_no,
          line_no: f.line_no.trim(),
          period: f.period.trim(),
          noise_adj: parseFloat(f.noise_adj) || 0,
          pulse_qty: parseFloat(f.pulse_qty) || 0,
          method: f.method.trim(),
          basis: f.basis.trim() || undefined,
        });
        toast("拆解完成");
        self.closeDecomp();
        if (self.modalX.open && self.modalX.d) {
          self.modalX.d = await self._fetchDetail(f.collect_no);
        }
      } catch { } finally { f.busy = false; }
    },

    /* ---- 拆解确认 ---- */
    async confirmDecomp(d) {
      const no = d.collect_no || (d.header && d.header.collect_no);
      if (!confirm("确认拆解后将冻结版本并生成脉冲事件，确定继续？")) return;
      try {
        const r = await svc("demand_collection", "confirm_decompose", { collect_no: no });
        const batch = r.proc_batch || "";
        let msg = "拆解已确认 · " + no;
        if (batch) msg += " · 加工批次 " + batch + " 已自动创建";
        if (r.warning) msg += " · " + r.warning;
        toast(msg);
        if (self.modalX.open && self.modalX.d) self.modalX.d.header.status = "已拆解";
        await self.list.load(self.list.page);
      } catch { }
    },

    /* ---- 锁定 ---- */
    /* ---- 版本比对 ---- */
    diffResult: { open: false, loading: false, collect_no: "", prev_version: "", diffs: [] },
    async versionDiff(d) {
      const no = d.collect_no || (d.header && d.header.collect_no);
      self.diffResult = { open: true, loading: true, collect_no: no, prev_version: "", diffs: [] };
      try {
        const r = await svc("demand_collection", "version_diff", { collect_no: no });
        self.diffResult = { open: true, loading: false, collect_no: no, prev_version: r.prev_version || "", diffs: r.diffs || [] };
        if (!r.diffs || !r.diffs.length) toast("无差异或无可比对的上期版本");
      } catch { self.diffResult.open = false; }
    },
    closeDiff() { self.diffResult.open = false; },

    /* ---- 替代 ---- */
    openSupersede(d) {
      const no = d.collect_no || (d.header && d.header.collect_no);
      self.supersedeForm = { open: true, busy: false, collect_no: no };
    },
    closeSupersede() { self.supersedeForm.open = false; },
    async submitSupersede() {
      const f = self.supersedeForm;
      f.busy = true;
      try {
        const r = await svc("demand_collection", "supersede", { collect_no: f.collect_no });
        toast(r.message || "替代完成");
        self.closeSupersede();
        if (self.modalX.open) self.modalX.open = false;
        await self.list.load(1);
        // 打开新单详情供编辑
        await self.viewX({ collect_no: r.collect_no });
      } catch { } finally { f.busy = false; }
    },

    /* ---- 作废 ---- */
    openCancel(d) {
      const no = d.collect_no || (d.header && d.header.collect_no);
      self.cancelForm = { open: true, busy: false, collect_no: no, reason: "" };
    },
    closeCancel() { self.cancelForm.open = false; },
    async submitCancel() {
      const f = self.cancelForm;
      if (!f.reason.trim()) return toast("请填写作废原因", "warn");
      f.busy = true;
      try {
        await svc("demand_collection", "cancel", { collect_no: f.collect_no, reason: f.reason.trim() });
        toast("已作废 · " + f.collect_no);
        self.cancelForm.open = false;
        if (self.modalX.open && self.modalX.d) self.modalX.d.header.status = "已作废";
        await self.list.load(self.list.page);
      } catch { } finally { f.busy = false; }
    },

    statusLabel(s) {
      return { "草稿": "草稿", "已拆解": "已拆解", "已锁定": "已锁定", "已替代": "已替代", "已作废": "已作废" }[s] || s || "—";
    },
  });
  return self;
}
