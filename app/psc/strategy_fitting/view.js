/* app/psc/strategy_fitting/view.js —— 策略拟合页面工厂（与后端 strategy_fitting.py 同文件夹）

   数据来源类型：手工参考创建（上游结果来自 ERP 历史干净需求 + md_material 当前参数），
   由用户手工决定何时基于哪些上游数据发起拟合。契约无 update / set_* / import_batch / delete
   → 无编辑入口、无删除按钮；单据变更仅经状态机动作（待复核 → approve 已生效 / reject 已否决；
   已生效 → rollback 已否决）与创建（run / run_batch）。 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名；order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "strategy_fitting",
  name: "策略拟合",
  ic: "🎯",
  title: "策略拟合",
  crumb: "滚动回测拟合最优方法参数 · 待复核→已生效/已否决",
  order: 160,
  bold: true,
};

export default function pageStrategyFitting() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,                        // 展示工具（dash / fmtTime / tryParse 为 window 全局，模板直接用）

    /* ---- 列表 + 过滤（与 strategy_fitting.list(material_no, fit_version, status, abnormal_flag, page, size)
            一一对应；material_no 为 LIKE 模糊、fit_version 精确、status / abnormal_flag 枚举） ---- */
    list: null,
    fStatus: "",                     // 全部 / 待复核 / 已生效 / 已否决（chips）
    fMaterial: "",                   // material_no 模糊关键字（LIKE，自由文本，非主数据选择）
    fVersion: "",                    // fit_version 精确匹配（YYYYMM）
    fAbnormal: "",                   // '' 全部 / 'true' 异常 / 'false' 正常

    /* ---- 物料主数据（发起拟合 autocomplete 选项 + 列表/详情名称回显） ---- */
    matOptions: [],                  // md_material.list 返回项（扁平数组，铁律：禁止嵌套 autoOptions[field]）
    matMap: {},                      // { material_no: material_name }
    matQuery: "",                    // autocomplete 输入态
    matOpen: false,                  // autocomplete 展开态

    /* ---- 详情模态 ---- */
    modalX: { open: false, loading: false, d: null },

    /* ---- 发起拟合表单（run） ---- */
    form: { open: false, busy: false, material_no: "", fit_version: "" },

    /* ---- 批量拟合表单（run_batch） ---- */
    batch: { open: false, busy: false, fit_version: "" },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      // list 实例须在 tpl 赋值后的首个 await 之前同步建好（items:[]）：tpl 一旦赋值 Alpine
      // 即注入模板并求值 list.*，若此时 list 仍为 null 会喷「reading 'items' of null」。
      self.list = pageable(async (q) => svc("strategy_fitting", "list", {
        material_no: self.fMaterial.trim() || undefined,
        fit_version: self.fVersion.trim() || undefined,
        status: self.fStatus || undefined,
        abnormal_flag: self.fAbnormal === "" ? undefined : (self.fAbnormal === "true"),
        ...q,                        // page / size
      }));
      await self.loadMasters();      // 备齐物料名称映射 + autocomplete 选项，再拉列表
      await self.list.load();
    },

    /* 物料主数据：quiet 探测，失败不喷 toast，零值兜底（autocomplete 显示「暂无可选物料」） */
    async loadMasters() {
      try {
        const r = await svc("md_material", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        self.matOptions = rows;
        const map = {};
        for (const m of rows) if (m && m.material_no) map[m.material_no] = m.material_name || m.material_no;
        self.matMap = map;
      } catch { /* 兜底：名称回显原样展示 material_no */ }
    },

    matName(no) { return (no && self.matMap[no]) || ""; },

    /* autocomplete 过滤：同时匹配代号与名称（主数据引用铁律：内联 autocomplete，非 <select>） */
    onMatInput() { self.matOpen = true; self.form.material_no = ""; },

    matFiltered() {
      const q = String(self.matQuery || "").trim().toLowerCase();
      if (!q) return self.matOptions;
      return self.matOptions.filter((o) =>
        String(o.material_no || "").toLowerCase().includes(q) ||
        String(o.material_name || "").toLowerCase().includes(q));
    },
    pickMat(o) {
      self.form.material_no = o.material_no;
      self.matQuery = o.material_no;
      self.matOpen = false;
    },

    /* ---- 展示工具 ---- */
    /* 小数 → 百分比（smape / fulfill_rate）：0.152 → 15.2%、0.95 → 95% */
    pct(v) {
      if (v === null || v === undefined || v === "") return "—";
      return (Number(v) * 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 }) + "%";
    },
    /* 异常标记徽章（boolean）：true=⚠ 异常 / false=正常 */
    abnHue(flag) { return flag === true ? "amber" : flag === false ? "green" : "slate"; },
    abnText(flag) { return flag === true ? "⚠ 异常" : flag === false ? "正常" : "—"; },

    /* ---- 过滤 / 分页 ---- */
    search() { self.list.load(1); },
    resetFilters() {
      self.fStatus = ""; self.fMaterial = ""; self.fVersion = ""; self.fAbnormal = "";
      self.list.load(1);
    },

    /* ---- 详情模态：点 material_no → get 全量字段（复合主键 fit_version + material_no） ---- */
    async viewX(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("strategy_fitting", "get",
          { fit_version: d.fit_version, material_no: d.material_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },

    /* ---- 状态机动作：行内操作列与模态页脚共用判定（待复核→approve/reject；已生效→rollback；已否决终态无按钮）
            字面量逐项书写，勿变量拼名；非法流转由后端 FdeError 经 api.js 统一 toast ---- */
    async act(d, kind) {
      const key = { fit_version: d.fit_version, material_no: d.material_no };
      try {
        let r = null;
        if (kind === "approve") {
          const abnormal = !!d.abnormal_flag;
          if (abnormal && !confirm("参数跳变过大，确认生效？")) return;   // BR-14 二次确认
          r = await svc("strategy_fitting", "approve", { ...key, confirm: abnormal });
        } else if (kind === "reject") {
          r = await svc("strategy_fitting", "reject", { ...key });
        } else if (kind === "rollback") {
          r = await svc("strategy_fitting", "rollback", { ...key });
        } else return;
        toast(`${kind === "approve" ? "已复核通过" : kind === "reject" ? "已否决" : "已回滚"} · ${d.material_no} · ${d.fit_version}`);
        if (self.modalX.open && r) self.modalX.d = r;    // 已开模态原地刷新
        await self.list.load(self.list.page);            // 列表刷新当前页
      } catch { /* api.js 已 toast */ }
    },

    /* ---- 发起拟合（run）：单物料，接受 material_no / fit_version 两个可写业务参数 ---- */
    openRun() {
      // 预填当前年月（YYYYMM）：发起拟合默认对当月拟合，用户通常无需改动
      const now = new Date();
      const ym = now.getFullYear() + String(now.getMonth() + 1).padStart(2, "0");
      self.form = { open: true, busy: false, material_no: "", fit_version: ym };
      self.matQuery = ""; self.matOpen = false;
    },
    closeRun() { self.form.open = false; self.matOpen = false; },

    async saveRun() {
      const f = self.form;
      if (!f.material_no || !f.material_no.trim()) return toast("请选择物料号", "warn");
      if (!f.fit_version || !f.fit_version.trim()) return toast("请填写拟合版本（YYYYMM）", "warn");
      if (!/^\d{6}$/.test(f.fit_version.trim())) return toast("拟合版本格式必须为 YYYYMM", "warn");
      f.busy = true;
      try {
        const r = await svc("strategy_fitting", "run",
          { material_no: f.material_no.trim(), fit_version: f.fit_version.trim() });
        toast(`已发起拟合 · ${(r && r.material_no) || f.material_no} · ${(r && r.fit_version) || f.fit_version}`);
        self.closeRun();
        self.resetFilters();         // 新记录恒「待复核」，重置过滤确保可见
        await self.list.load(1);
      } catch { /* 物料不存在 / 版本非法等由 api.js 统一 toast */ } finally { f.busy = false; }
    },

    /* ---- 批量拟合（run_batch）：整批，仅接受 fit_version；对全部正常状态物料逐物料拟合 ---- */
    openBatch() {
      // 预填当前年月（YYYYMM）：批量拟合默认对当月拟合，用户通常无需改动
      const now = new Date();
      const ym = now.getFullYear() + String(now.getMonth() + 1).padStart(2, "0");
      self.batch = { open: true, busy: false, fit_version: ym };
    },
    closeBatch() { self.batch.open = false; },

    async saveBatch() {
      const b = self.batch;
      if (!b.fit_version || !b.fit_version.trim()) return toast("请填写拟合版本（YYYYMM）", "warn");
      if (!/^\d{6}$/.test(b.fit_version.trim())) return toast("拟合版本格式必须为 YYYYMM", "warn");
      b.busy = true;
      try {
        const r = await svc("strategy_fitting", "run_batch", { fit_version: b.fit_version.trim() });
        toast(`批量拟合完成 · 共 ${r.total} · 成功 ${r.success} · 失败 ${r.failed}`);
        self.closeBatch();
        await self.list.load(1);     // 拟合结果陆续落表（均「待复核」）
      } catch { /* api.js 已 toast */ } finally { b.busy = false; }
    },
  });
  return self;
}
