/* 工作分解结构台账 · 独立创建（顶层元素自带编号）· 草稿 / 已基线 / 变更中 / 已关闭
   元素树是本聚合内结构（父子同一张表）；控制账户 / 工作包 / 规划包是元素的 `kind` 属性。
   三种视图：台账（字典表）/ 树（缩进索引）/ 甘特（**WBS 级汇总条**，进度数据只读派生）。
   依据：NASA/SP-20250006071《NASA WBS Handbook》(2025-06) §3.3.4 / §3.4.2 / §3.4.4 / §3.5.2
        NASA/SP-2010-3403《Schedule Management Handbook》(2010-11) §5.5（IMS 按 WBS 层级呈现） */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "wbs", name: "WBS", ic: "🧱",
  title: "工作分解结构台账", crumb: "元素 · 编号 · 基线 · 变更",
  order: 720,
  /* ⚠ 15 列**同时铺开**时，表格的最小内容宽（1380px）超过卡片宽（1238px），浏览器只能把最后
     一列「操作」压到 48px —— 五个按钮因此竖排，行高从 39px 涨到 223px，整页看着像散架。
     修法与同组 decision / interface / review 一致：把四个**字典 / 长文本**列交给平台
     「列设置」（`colctl`，per-user 服务端持久化）默认隐藏 —— 信息不丢，按需勾回来。
     判据已固化成断言 VT-LAYOUT-01/02/03（表格不溢出 · 按钮不换行 · 隐藏列就这四列）。 */
  col_default_hidden: "内容描述,规范号,预算与报告号,修订授权",
};

/* 元素类型（§3.3.4）。本版不建 OBS —— CA/WP/PP 收成元素属性（术语表附「本版口径」#1） */
const KINDS = [
  ["product", "产品"],
  ["enabling", "使能性工作"],
  ["ca", "控制账户"],
  ["wp", "工作包"],
  ["pp", "规划包"],
];

const STATUS = {
  draft: ["草稿", "st-slate"],
  baselined: ["已基线", "st-blue"],
  in_change: ["变更中", "st-amber"],
  closed: ["已关闭", "st-green"],
};

/* ── ECharts 甘特：option 构造（纯函数，只吃行模型，不碰 Alpine/网络）────────────────
   放在模块级是刻意的：渲染逻辑与页面状态解耦，读代码时"长什么样"与"取什么数"一眼分开。 */

const ROW_H = 26;                  // 一行的高度（px）—— 与网格上下边距**成对**：见 ganttOption
const BAR_H = 9;                   // 活动条高度
const SUM_H = 8;                   // 汇总条高度（比活动条**细**：层级越高越"虚"，这是甘特惯例）
const MS_R = 6;                    // 里程碑菱形半对角

/** `"2026-09-28"` → 本地午夜毫秒。**不要用 `new Date("2026-09-28")`** —— 那按 UTC 解析，
 *  在西半球（UTC-x）会显示成前一天；本地午夜构造则与刻度标签永远同日。 */
function _dayMs(s) {
  const p = String(s || "").split("-").map(Number);
  return new Date(p[0], (p[1] || 1) - 1, p[2] || 1).getTime();
}

/** tooltip 里要拼 HTML ⇒ 名称、描述这些**用户输入**必须转义（否则是注入面） */
function _esc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** `"2026-09-28"` → `"09-28"`：条右侧的读数用短日期 —— 年份由时间轴给，不必每行重复
 *  （首版带年份 + 条数，实测被卡片右缘截断成「…（」）。 */
function _md(s) { return String(s || "").slice(5); }

const _KIND_CN = { summary: "汇总", activity: "活动", milestone: "里程碑" };

/** y 轴标签：**两列对齐**（编号定宽 monospace + 名称定宽截断），缩进用全角空格。
 *  ⚠ ECharts 的富文本 `padding` 是**按 style 名固定**的，做不了"每行不同缩进" ——
 *    所以缩进走全角空格（`　`，中文页里 1 个字宽，稳定）。 */
function _catLabel(r) {
  if (r.is_act) {
    return "{m|" + _esc(r.a.act_no) + "}{m|" + "　".repeat(r.depth) + _esc(r.a.name) + "}";
  }
  return "{n|" + _esc(r.d.wbs_no) + "}{t|" + "　".repeat(r.depth)
       + (r.depth ? "└ " : "") + _esc(r.d.title) + "}";
}

/** 行模型 → ECharts option。
 *  坐标系：x = **时间轴**（`type:"time"`，ECharts 自己算刻度与网格线，不再手搓百分比），
 *          y = **类目轴**（一行一个元素/活动，`inverse` 让树顶在上）。 */
function ganttOption(rows, narrow) {
  /* 左侧两列的宽度是**唯一来源**：富文本的 `width` 与 `grid.left` 都从这两个常量算出来 ——
     分开写就会出现"标签宽度与绘图区起点对不上"（差几十像素、还不报错）。
     窄画布（1280 视口 + Agent 右栏展开时卡片只有 ~640px）下把名称列收窄，先把绘图区保住。 */
  const NO_W = 104;                       // 编号列（等宽）
  const NM_W = narrow ? 104 : 186;        // 名称列（截断）
  const PAD_R = narrow ? 132 : 104;      // 右侧 gutter：装条右边的读数（窄画布下读数也短一点）
  const grid = { left: NO_W + NM_W + 22, right: PAD_R, top: 34, bottom: 12 };
  /* ⚠ 横轴**不用 `type:"time"`，用「天偏移」的 value 轴**（0 = 项目最早开始日）——
     时间轴那条路实测三处坑，且都是**静默**的：
       ① 轴范围必须**先滤掉没有日期的行**（「无活动」的元素没有 from/to）：首版把 reduce 初值
          写成 `rows[0].from`，撞上无日期的行就把累加器污染成 `undefined` ⇒ `_dayMs(undefined)`
          = NaN ⇒ ECharts 把轴缩到 epoch 附近，**刻度全变成"1-1"、一根条都不画**；
       ② `interval` 对时间轴**被忽略**（写了 7 天仍按 auto 排）；
       ③ auto 在窄画布上排出 2 天步长，标签叠成「9-2910-1」，而它那条轴**不遵守 `hideOverlap`**。
     换成 value 轴后：步长是**整数天**、`interval` 说话管用、标签由我按 `base + v 天` 反算 ——
     不依赖时区，也不会在两端冒出半天的怪刻度。 */
  const starts = rows.filter((r) => r.from).map((r) => _dayMs(r.from));
  const base = Math.min(...starts);                 // 横轴 0 点 = 最早开始日
  const dayOf = (iso) => Math.round((_dayMs(iso) - base) / 86400000);
  const dayEnd = (iso) => dayOf(iso) + 1;           // `to` 是**含当天**：右端 +1 天
  const spanD = Math.max(...rows.filter((r) => r.to).map((r) => dayEnd(r.to)));
  const stepD = spanD <= 45 ? 7 : (spanD <= 100 ? 14 : (spanD <= 220 ? 28 : 56));
  /* 偏移天数 → "MM-DD"：用 `setDate` 按**日历天**推进（`base + n*86400000` 在夏令时切换那天会
     差一小时、进而把日期推走一天；`setDate` 不会）。 */
  const mdOf = (off) => {
    const d = new Date(base);
    d.setDate(d.getDate() + off);
    return String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  };

  return {
    animation: false,
    grid: grid,
    tooltip: {
      trigger: "item", confine: true, borderWidth: 0,
      backgroundColor: "rgba(15,27,42,.92)", textStyle: { color: "#fff", fontSize: 12 },
      padding: [8, 10],
    },
    xAxis: {
      type: "value", position: "top", min: 0, max: spanD, interval: stepD,
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { show: true, lineStyle: { color: "#eef2f7" } },   // 竖向网格线：条不再悬空
      axisLabel: { fontSize: 10.5, color: "#8a97a6",
                   formatter: (v) => (v % 1 === 0 && v >= 0 && v <= spanD) ? mdOf(v) : "" },
    },
    yAxis: {
      type: "category", inverse: true, data: rows.map(_catLabel),
      triggerEvent: true,                            // 点**标签**也要能开详情（默认不派发）
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { show: true, lineStyle: { color: "#f1f5f9" } },
      axisLabel: {
        interval: 0, hideOverlap: false,             // ⚠ 默认 auto 会**隔行隐藏**标签，必须钉住
        margin: 14,
        rich: {
          n: { width: NO_W, fontFamily: "ui-monospace,Consolas,monospace",
               fontSize: 11.5, color: "#64748b", align: "left" },
          t: { width: NM_W, fontSize: 12, color: "#1f2937", align: "left",
               overflow: "truncate" },
          m: { width: NO_W, fontFamily: "ui-monospace,Consolas,monospace",
               fontSize: 11, color: "#94a3b8", align: "left" },
        },
      },
    },
    series: [{
      type: "custom",
      data: rows.map((r) => ({ row: r, value: [dayOf(r.from), dayEnd(r.to)] })),
      renderItem: (params, api) => {
        const r = rows[params.dataIndex];
        const idx = params.dataIndex;
        const cs = params.coordSys;
        const band = api.size([0, 1])[1];
        const cy = api.coord([dayOf(r.from), idx])[1];
        const kids = [];

        // 行底纹：隔行浅色（长表里不串行）
        if (idx % 2 === 1) {
          kids.push({ type: "rect", silent: true, z2: -1,
                      shape: { x: cs.x, y: cy - band / 2, width: cs.width, height: band },
                      style: { fill: "#fafbfc" } });
        }

        if (r.is_act && r.is_ms) {                     // 里程碑：菱形
          const x = api.coord([dayOf(r.from), idx])[0];
          kids.push({ type: "polygon",
                      shape: { points: [[x, cy - MS_R], [x + MS_R, cy],
                                        [x, cy + MS_R], [x - MS_R, cy]] },
                      style: { fill: "#0ea5e9" } });
        } else if (r.is_act) {                         // 活动条（+ 完成度 + 基线）
          const a = api.coord([dayOf(r.from), idx])[0];
          const b = api.coord([dayEnd(r.to), idx])[0];
          const w = Math.max(b - a, 3);
          const crit = !!r.a.critical;
          const bs = r.a.baseline_start ? api.coord([dayOf(r.a.baseline_start), idx])[0] : null;
          const be = r.a.baseline_finish
            ? api.coord([dayEnd(r.a.baseline_finish), idx])[0] : null;
          if (bs !== null && be !== null) {            // 基线条（灰细条，压在活动条下面）
            kids.push({ type: "rect", silent: true,
                        shape: { x: bs, y: cy + 6, width: Math.max(be - bs, 3),
                                 height: 3, r: 1.5 },
                        style: { fill: "#94a3b8" } });
          }
          kids.push({ type: "rect",
                      shape: { x: a, y: cy - BAR_H / 2, width: w, height: BAR_H, r: 3 },
                      style: { fill: crit ? "#f59e0b" : "#38bdf8" } });
          const pc = Math.max(0, Math.min(100, Number(r.a.percent_complete) || 0));
          if (pc > 0) {                                // 完成度叠在条内（深一档同色）
            kids.push({ type: "rect", silent: true,
                        shape: { x: a, y: cy - BAR_H / 2, width: Math.max(w * pc / 100, 2),
                                 height: BAR_H, r: 3 },
                        style: { fill: crit ? "#b45309" : "#0284c7" } });
          }
        } else if (r.acts) {                           // 汇总条：细深条 + 两端向下的小三角
          const a = api.coord([dayOf(r.from), idx])[0];
          const b = api.coord([dayEnd(r.to), idx])[0];
          const w = Math.max(b - a, 4);
          kids.push({ type: "rect",
                      shape: { x: a, y: cy - SUM_H / 2, width: w, height: SUM_H, r: 1 },
                      style: { fill: "#475569",
                               // 子树含关键活动 → **琥珀描边**（不整条染色：演示数据里整棵树
                               // 都含关键路径，整条染会糊成一片橙，看不出层级）
                               stroke: r.crit ? "#f59e0b" : "transparent",
                               lineWidth: r.crit ? 1.2 : 0 } });
          const cap = (x, sgn) => ({ type: "polygon", silent: true,
            shape: { points: [[x, cy + SUM_H / 2 - 1], [x + sgn * 5, cy + SUM_H / 2 - 1],
                              [x, cy + SUM_H / 2 + 4]] },
            style: { fill: "#475569" } });
          kids.push(cap(a, 1), cap(b, -1));
        } else {                                       // 无活动：不画条，只给一句读数
          kids.push({ type: "text", silent: true,
                      style: { x: cs.x + 8, y: cy, text: "无活动", fill: "#a8b3c0",
                               fontSize: 11, textVerticalAlign: "middle" } });
        }

        // 条右侧的读数（**短日期**：年份交给时间轴，条数只给汇总行）
        const spanTxt = narrow ? ("→ " + _md(r.to)) : (_md(r.from) + " → " + _md(r.to));
        const label = r.is_act
          ? (r.is_ms ? _md(r.from) : _md(r.from) + " → " + _md(r.to))
          : (r.acts ? spanTxt + "（" + r.acts + "）" : "");
        if (label) {
          const x0 = r.is_act && r.is_ms
            ? api.coord([dayOf(r.from), idx])[0] + MS_R + 6
            : api.coord([dayEnd(r.to), idx])[0] + 6;
          // ⚠ 收在绘图区右缘（`grid.right` 留的那条 gutter）：条跑到最右时读数会溢出画布被裁掉
          const x = Math.min(x0, cs.x + cs.width + 4);
          kids.push({ type: "text", silent: true,
                      style: { x: x, y: cy, text: label, fill: "#94a3b8", fontSize: 10.5,
                               textVerticalAlign: "middle" } });
        }
        return { type: "group", children: kids };
      },
      tooltip: {
        formatter: (p) => {
          const r = p.data && p.data.row;
          if (!r) return "";
          if (r.is_act) {
            const a = r.a;
            return "<b>" + _esc(a.act_no) + "</b> " + _esc(a.name)
              + "<br/>" + (_KIND_CN[a.kind] || a.kind) + "　挂靠 " + _esc(a.wbs_no)
              + "<br/>工期 " + a.duration_days + " 天　"
              + (a.critical ? "<b style='color:#f5b04c'>关键路径</b>" : "浮时 " + a.float_days + " 天")
              + "<br/>最早 " + r.from + " → " + r.to
              + (a.baseline_start ? "<br/>基线 " + a.baseline_start + " → " + a.baseline_finish : "")
              + (a.percent_complete ? "<br/>完成 " + a.percent_complete + "%" : "");
          }
          return "<b>" + _esc(r.d.wbs_no) + "</b> " + _esc(r.d.title)
            + "<br/>子树活动 " + r.acts + " 条"
            + (r.crit ? "（<b style='color:#f5b04c'>含关键活动</b>）" : "")
            + "<br/>包络 " + r.from + " → " + r.to
            + "<br/><span style='opacity:.7'>点此开元素详情</span>";
        },
      },
    }],
    /* 不放 `dataZoom`：横轴是**天偏移的 value 轴**、步长按跨度分档定死（7/14/28/56 天），
       缩放会让刻度落到非整数天 —— 而标签格式器只给整数天出字，一缩放刻度就整片消失。
       长周期项目由 stepD 的分档兜住（这也是活动页甘特没有的"自主决定步长"）。 */
  };
}

export default function pageWbs() {
  let chartInstance = null;   // ECharts 实例（闭包持有，**不进 Alpine 响应式** —— 被 Proxy 包住会坏）
  let chartNarrow = null;     // 上一次渲染用的是宽/窄哪套布局（决定 resize 时要不要重画）

  const self = Alpine.reactive({
    tpl: "",
    list: null,
    view: "list",                       // list | tree | gantt
    // 筛选（与后端 list 的可过滤参数一一对应）
    f_status: "", f_kind: "", f_keyword: "",
    tree: [],
    // 甘特视图的**进度数据**：来自 `activity.schedule_view`（跨应用只读派生，本应用不落日期）
    schedule: null,
    schErr: false,
    // 详情 / 编辑模态（同一模态，mode 切换；字典全字段）
    modal: { open: false, d: null, mode: "view", busy: false },
    // 新建根元素 / 加子元素（同一表单，`parent` 为空即顶层）
    form: { open: false, saving: false, parent: null, no: "", title: "", kind: "product",
            scope_ref: "", owner: "", req_nos: "" },
    // 发起变更
    fm: { open: false, d: null, change_no: "", note: "", saving: false },
    // 关闭
    cm: { open: false, d: null, note: "", saving: false },
    // 候选集 —— 跨应用只读（**值仍是文本**）：责任人 ← stakeholder、变更号 ← change_request
    owners: [],
    crs: [],
    // 每个叶子元素下的活动数（跨应用只读 `activity.list`，**只读不写**；见 architecture.md 方向表）
    acts: {},
    // ⚠ 是**父号集合**（谁当过父），不是"子号集合" —— 判叶子要问「我自己有孩子吗」。
    //   写成"把每个 child 塞进去"会把**叶子本身**也收进来（它也是别人的孩子），实测当场判错。
    parentSet: new Set(),

    kinds: KINDS,
    kindName(v) { const k = KINDS.find((x) => x[0] === v); return k ? k[1] : (v || "—"); },
    statusName(v) { return (STATUS[v] || [v, ""])[0]; },
    statusCls(v) { return (STATUS[v] || ["", "st-slate"])[1]; },
    dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; },
    stName(d) { return self.statusName(d && d.status); },
    stCls(d) { return self.statusCls(d && d.status); },
    kindOf(d) { return self.kindName(d && d.kind); },

    /* ⚠ 模态里读 `modal.d` 一律走空安全 helper，模板里不写裸 `modal.d.status` ——
       `x-if` 的销毁与子效果执行顺序不保证，写裸取值会抛 "Cannot read properties of null"
       （同组 review 页实测抛过 4 条，见 decision/view.js 的同类注释）。 */
    isStatus(d, s) { return !!d && d.status === s; },
    inStatus(d, list) { return !!d && list.indexOf(d.status) >= 0; },
    parentText(d) { return (d && d.parent_no) ? d.parent_no : "（顶层）"; },
    revText(d) { return "v" + ((d && d.rev_no) || 0); },
    /** 允许的动作 —— 与后端闸门同口径（前端只做显隐，判定以后端为准） */
    canAddChild(d) { return !!d && d.status !== "closed"; },
    canBaseline(d) { return self.inStatus(d, ["draft", "in_change"]); },
    canChange(d) { return self.isStatus(d, "baselined"); },
    canClose(d) { return self.isStatus(d, "baselined"); },
    /** 起草稿时提示：没有范围出处就不能基线（BR-03 的前端镜像，不是判据） */
    needScope(d) { return self.isStatus(d, "draft") && !(d && d.scope_ref); },
    /** 落实变更：`in_change` 回 `baselined`，此时版次会 +1 */
    baselineLabel(d) { return self.isStatus(d, "in_change") ? "落实变更" : "纳入基线"; },

    async init() {
      // ⚠ 先把会被模板引用的响应式状态建好，再挂模板（模板注入即求值 `list.items`，
      //   此刻 list 还是 null 会喷 "reading 'items' of null"；见 pitfalls #37）
      const tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("wbs", "list", {
        status: self.f_status || undefined,
        kind: self.f_kind || undefined,
        keyword: self.f_keyword || undefined,
        ...q,
      }));
      self.tpl = tpl;
      await self.loadOwners();
      await self.loadCrs();
      await self.loadTree();
      await self.loadActCounts();
      await self.list.load();
      // 图随窗口/右栏收放伸缩：跨过宽/窄分界时 renderChart 自己会重画（见那里的注释）
      window.addEventListener("resize", () => { if (chartInstance) self.renderChart(); });
    },

    /** 责任人候选（`stakeholder` 主数据）：只做候选、值仍是**文本姓名**
     *（全组 `owner` 都是文本口径）。跨应用只读，失败静默兜底。 */
    async loadOwners() {
      try {
        const r = await svc("stakeholder", "list", {}, { quiet: true });
        self.owners = (r && r.items) || [];
      } catch { self.owners = []; }
    },

    /** 变更号候选：**只列已批准的**（`change_request`）—— 值仍是文本 `cr_no`，
     *  后端 `change` 会再校验一次"是否已批准"（BR-05，跨应用）。失败静默兜底。 */
    async loadCrs() {
      try {
        const r = await svc("change_request", "list", { status: "approved" }, { quiet: true });
        self.crs = (r && r.items) || [];
      } catch { self.crs = []; }
    },

    async loadTree() {
      try {
        self.tree = await svc("wbs", "tree", {}, { quiet: true }) || [];
      } catch { self.tree = []; }
      const parents = new Set();
      const walk = (rows) => (rows || []).forEach((r) => {
        if ((r.children || []).length) parents.add(r.wbs_no);
        walk(r.children);
      });
      walk(self.tree);
      self.parentSet = parents;
    },

    /** 每个叶子元素下的活动数（跨应用**只读**一次取全表，在内存里归并 —— 不按行发 N 次请求）。
     *  取不到就退化成 0 条（只是读数缺失，页面照常用；不喷 toast）。 */
    async loadActCounts() {
      try {
        const r = await svc("activity", "list", { size: 9999 }, { quiet: true });
        const m = {};
        for (const a of ((r && r.items) || [])) m[a.wbs_no] = (m[a.wbs_no] || 0) + 1;
        self.acts = m;
      } catch { self.acts = {}; }
    },

    search() { self.list.load(1); },
    async reload() {
      await self.list.load(self.list.page);
      await Promise.all([self.loadTree(), self.loadActCounts()]);
      if (self.view === "gantt") {
        await self.loadSchedule();
        Alpine.nextTick(() => self.renderChart(true));   // 数据变了，图跟着重画
      }
    },
    async switchView(v) {
      self.view = v;
      if (v === "tree") await self.loadTree();
      if (v === "gantt") {
        await self.loadSchedule();
        // ⚠ 必须等 `x-show` 那一帧过去再 init：容器还是 `display:none` 时宽度为 0，
        //   ECharts 会建出一张 **0 宽的 canvas —— 什么都不画且不报错**（平台内踩过）。
        Alpine.nextTick(() => self.renderChart());
      } else if (chartInstance) {
        chartInstance.dispose();                     // 切走就释放，别占着 canvas 与监听
        chartInstance = null;
      }
    },

    /** 进度数据（**跨应用只读**）：一次取全表的派生排程，本页只做汇总呈现。
     *  ⚠ 本页对 `activity` 一律只读（同 `loadActCounts`）—— 视图层跨应用调用不开写边；
     *     日期也**不落 wbs 库**（`wbs_element` 至今没有日期列，应用详设 §1.3.2 的边界）。
     *  取不到就退化成一句提示，**不喷 toast**：甘特只是本页第三种看法，台账/树不受影响。 */
    async loadSchedule() {
      try {
        self.schedule = await svc("activity", "schedule_view", {}, { quiet: true });
        self.schErr = false;
      } catch { self.schedule = null; self.schErr = true; }
    },

    /** 树视图的**缩进索引**（材料 §3.4.4 图 3-12：缩进列出以体现层级） */
    flat(rows, depth) {
      const out = [];
      for (const r of (rows || [])) {
        out.push({ d: r, depth: depth || 0 });
        out.push(...self.flat(r.children || [], (depth || 0) + 1));
      }
      return out;
    },
    treeRows() { return self.flat(self.tree, 0); },

    /* ── 甘特视图：**WBS 级汇总条**（跨应用只读的派生呈现，本应用不存日期）─────────────
       材料依据：IMS 的甘特是**按 WBS 层级呈现**的（NASA/SP-2010-3403 §5.5）——每个元素的条
       由**其子树全部活动**包络而成（min 最早开始 → max 最早完成），不是元素自己存的日期
       （元素根本没有日期列）。汇总条是"分配责任、看整体"的层级，活动条是"干活"的层级。
       口径与活动页甘特一致：横轴 = **日历天**，日期来自 `activity.schedule_view`。

       ⚠ 2026-09-27 改为 **ECharts 画**（此前是手搓 div 条）——手搓那版实测两个硬伤：
         ① 180px 的日期列装不下「2026-09-28 → 2026-10-23（5 条）」，文字**溢出压在条形上**；
         ② 没有网格线，条悬在半空，读不出"到哪天"。
       平台**已经内置 echarts**（`view/lib/echarts.min.js`，经 `view_shell.html` 全局加载，
       psc 的 inventory_projection / material360 / strategy_fitting 三个页在用）——时间轴、
       网格线、tooltip、滚轮缩放、resize 全是白送的，且与那三个页图表观感统一。零新增依赖。
       ⚠ `view/lib/` 只 import 不修改 ⇒ 渲染代码在本页自己写一份（同组活动页那份仍是手搓的，
         两页不共享代码是平台约定：每个 view.js 自包含）。 */

    /** 子树索引：`wbs_no` → 落在这棵子树里的活动（含自身与全部后代）。
     *  一次归并、O(树 + 活动数)，**不按行发 N 次请求**、也不按行重扫活动表。 */
    subtreeActs() {
      const own = {};
      for (const a of ((self.schedule && self.schedule.items) || [])) {
        const k = String(a.wbs_no || "");
        (own[k] = own[k] || []).push(a);
      }
      const out = {};
      const walk = (rows) => {                       // 返回本层各子树活动的**并集**
        const acc = [];
        for (const r of (rows || [])) {
          const sub = (own[r.wbs_no] || []).concat(walk(r.children || []));
          out[r.wbs_no] = sub;
          acc.push(...sub);
        }
        return acc;
      };
      walk(self.tree);
      return out;
    },

    /** 甘特行模型 = **元素行**（每条一个汇总条）+ 叶子元素下面的**活动行**（叶子才有活动）。
     *  行顺序与树视图一致（`treeRows()`），缩进深度沿用 `depth`；`from`/`to` 是 **ISO 日期串**
     *  （不折算百分比 —— 换算交给 ECharts 的时间轴）。
     *  ⚠ 这个模型同时是 **e2e 的断言面**：图是 canvas，DOM 里没有"条"可量（见 `脚本 §8`），
     *     所以它随 option 一起挂进 `series.data`，测试用 `getOption()` 读回来对账。 */
    ganttRows() {
      const s = self.schedule;
      if (!s || !(s.items || []).length) return [];
      const sub = self.subtreeActs();
      const out = [];
      for (const r of self.treeRows()) {
        const acts = sub[r.d.wbs_no] || [];
        const row = { is_act: false, key: "w:" + r.d.wbs_no, d: r.d, depth: r.depth,
                      acts: acts.length, crit: acts.some((a) => a.critical) };
        if (acts.length) {
          const ss = acts.map((a) => a.early_start).sort();
          const ff = acts.map((a) => a.early_finish).sort();
          Object.assign(row, { from: ss[0], to: ff[ff.length - 1] });
        }
        out.push(row);
        // 叶子元素把挂着的活动逐条列出来（活动只能挂最底层元素 —— WBS 手册 §4 / BR-05）
        if (!self.isLeaf(r.d)) continue;
        for (const a of acts) {
          out.push({ is_act: true, key: "a:" + a.act_no, a, depth: (r.depth || 0) + 1,
                     is_ms: a.kind === "milestone",
                     from: a.early_start, to: a.early_finish });
        }
      }
      return out;
    },

    /** 图表容器高度：**一行 26px**（与 `ROW_H` 同口径）+ 顶部刻度带 + 底部留白。
     *  行高与 `ganttOption` 的 `grid` 上下边距是**一对**，改一个必须改另一个。 */
    ganttHeight() {
      return Math.max(160, self.ganttRows().length * ROW_H + 62);
    },

    /* ── ECharts 渲染（平台已内置 echarts：view/lib/echarts.min.js，view_shell 全局加载）──
       `force` = 数据变了要**重画**；不带 force 时，同一档宽度下只 `resize()`（省一次重建）。
       ⚠ 宽/窄是**两套布局**（标签列宽 + 右侧 gutter 都不同），所以跨过分界时必须重画 ——
         只 `resize()` 会让选项停在旧布局里：窄画布配宽标签列 ⇒ 时间轴刻度挤成一坨
         （实测「9-281-1 10-5 10-9 10-1310-1710-21」）。 */
    renderChart(force) {
      const el = document.getElementById("wbsGantt");
      if (!el || !window.echarts) return;
      const narrow = (el.clientWidth || 0) < 820;
      if (chartInstance && !force && narrow === chartNarrow) { chartInstance.resize(); return; }
      if (chartInstance) { chartInstance.dispose(); chartInstance = null; }
      const rows = self.ganttRows();
      if (!rows.length) return;                      // 无数据：由模板空态提示
      const ch = window.echarts.init(el);
      chartInstance = ch;
      chartNarrow = narrow;
      ch.setOption(ganttOption(rows, narrow));
      ch.on("click", (p) => {
        // 条（custom series）与 **y 轴标签**（`yAxis.triggerEvent`）都能点开详情。
        // ⚠ 轴标签事件里的 `p.value` 是**类目名（那串富文本标签）**、不是行号 —— 得回表查
        //   （实测：按行号取会静默取到 undefined，点上去毫无反应、控制台也不报错）。
        let i = p.dataIndex;
        if (p.componentType === "yAxis") {
          const cats = (ch.getOption().yAxis[0] || {}).data || [];
          i = (typeof p.value === "number") ? p.value : cats.indexOf(String(p.value));
        }
        const row = (i >= 0 && i < rows.length) ? rows[i] : null;
        if (!row) return;
        if (row.is_act) self.jumpActivity({ wbs_no: row.a.wbs_no }, "filter");
        else self.openDetail(row.d, "view");
      });
      /* ⚠ 这一帧 resize 别删：容器是在 `x-show` 切过来的那一帧才从 `display:none` 变成有宽度，
         小概率仍读到 0 宽 —— 而 **canvas 宽 0 就是整张图什么都不画，且不报任何错**
         （平台内已经踩过：material360 的「逐月拟合」图因此从来没显示过）。 */
      requestAnimationFrame(() => { if (chartInstance) chartInstance.resize(); });
    },

    /** 甘特区里"当前口径"那行字（日历 / 项目区间） */
    schHead() {
      const s = self.schedule;
      if (!s) return "";
      return s.unit_cn + "　·　" + s.project_start + " → " + s.project_finish;
    },

    /* ── 元素与活动的关系（材料 WBS 手册 §4：每个最底层元素至少一条活动/里程碑）──
       读数与入口都做成**跨应用只读**：本页看得到、点得动，但**不写** `activity` 的聚合
       —— 全仓的视图层跨应用调用一律只读，第一条写边不从这里开。 */
    isLeaf(d) { return !!d && !self.parentSet.has(d.wbs_no); },
    actCount(d) { return (d && self.acts[d.wbs_no]) || 0; },
    /** 叶子且一条活动都没有 —— 对应材料 §4 那条，标出来（前端只做提示，判据在后端体检） */
    noActivity(d) { return self.isLeaf(d) && self.actCount(d) === 0 && d.status !== "closed"; },
    canAddActivity(d) { return self.isLeaf(d) && !!d && d.status !== "closed"; },
    /** 跳到进度活动台账去建/看（**只读跳转**：写活动仍由 `activity` 页自己做） */
    jumpActivity(d, mode) {
      try {
        sessionStorage.setItem("fde.activity_preset",
                               JSON.stringify({ wbs_no: d.wbs_no, mode: mode || "filter" }));
      } catch { /* 存不进就退化成普通跳转 */ }
      location.hash = "#/activity";
    },

    /* ── 详情 / 编辑 ──────────────────────────────────── */
    async openDetail(row, mode) {
      self.modal.open = true;
      self.modal.mode = mode || "view";
      self.modal.d = row;                       // 先用列表项渲染，随后取全字段
      try {
        const d = await svc("wbs", "get", { wbs_no: row.wbs_no });
        if (d) self.modal.d = d;
      } catch (e) { toast(String(e.message || e)); }
    },
    closeModal() { self.modal.open = false; self.modal.d = null; },
    /** 已基线 / 已关闭的元素不可直接改（BR-05 / BR-06 的前端镜像：只做只读，判定在后端） */
    ro(d) { return self.modal.mode === "view" || self.inStatus(d, ["baselined", "closed"]); },
    /** 只有 `draft` 与 `in_change` 能直接改 —— 已基线要给「发起变更」，所以**编辑按钮也不给**，
     *  否则点进去字段全是灰的，是个死胡同（同组 decision 页对 frozen 状态就是这么处理的） */
    canEdit(d) { return self.inStatus(d, ["draft", "in_change"]); },
    /** 修改字典字段（**编号不在可改字段里** —— BR-07，界面上也没有这个输入框） */
    async saveEdit() {
      const d = self.modal.d;
      if (!d || self.modal.busy) return;
      self.modal.busy = true;
      try {
        const r = await svc("wbs", "update", {
          wbs_no: d.wbs_no, title: d.title || undefined, description: d.description || undefined,
          scope_ref: d.scope_ref || undefined, spec_no: d.spec_no || undefined,
          spec_title: d.spec_title || undefined, charge_code: d.charge_code || undefined,
          owner: d.owner || undefined, req_nos: d.req_nos || undefined,
        });
        toast(`已保存 ${r.wbs_no} 的字典字段`);
        self.modal.mode = "view";
        self.modal.d = r;
        await self.reload();
      } catch (e) { toast(String(e.message || e)); }
      finally { self.modal.busy = false; }
    },

    /* ── 新建（顶层或子元素）───────────────────────────── */
    openForm(parent) {
      self.form = { open: true, saving: false, parent: parent || null,
                    no: "", title: "", kind: "product", scope_ref: "",
                    owner: (self.owners[0] && self.owners[0].name) || "",
                    req_nos: "" };
    },
    async submitForm() {
      const f = self.form;
      if (f.saving) return;
      if (!f.title.trim()) { toast("元素名称不能为空"); return; }
      f.saving = true;
      try {
        if (f.parent) {
          await svc("wbs", "add_child", { parent_no: f.parent.wbs_no, title: f.title.trim(),
                                          kind: f.kind, scope_ref: f.scope_ref || undefined,
                                          owner: f.owner || undefined,
                                          req_nos: f.req_nos || undefined });
          toast("已在该元素下新增子元素（子号由系统按规则分配）");
        } else {
          if (!f.no.trim()) { toast("顶层元素必须给出编号（6 位数字，如 123456）"); f.saving = false; return; }
          await svc("wbs", "create", { wbs_no: f.no.trim(), title: f.title.trim(), kind: f.kind,
                                       scope_ref: f.scope_ref || undefined,
                                       owner: f.owner || undefined,
                                       req_nos: f.req_nos || undefined });
          toast("已建立顶层元素 " + f.no.trim());
        }
        f.open = false;
        await self.reload();
      } catch (e) { toast(String(e.message || e)); }
      finally { f.saving = false; }
    },

    /* ── 三个状态动作 ─────────────────────────────────── */
    async baseline(d) {
      if (self.modal.busy) return;
      self.modal.busy = true;
      try {
        const r = await svc("wbs", "baseline", { wbs_no: d.wbs_no });
        toast(self.isStatus(d, "in_change")
          ? `变更已落实：版次 → ${self.revText(r)}`
          : `已纳入基线：${r.wbs_no}`);
        self.modal.d = r;
        await self.reload();
      } catch (e) { toast(String(e.message || e)); }
      finally { self.modal.busy = false; }
    },
    openChange(d) {
      self.fm = { open: true, d, change_no: (self.crs[0] && self.crs[0].cr_no) || "",
                  note: "", saving: false };
    },
    async submitChange() {
      const f = self.fm;
      if (f.saving) return;
      if (!f.change_no) { toast("请选择一个已批准的变更请求"); return; }
      f.saving = true;
      try {
        const r = await svc("wbs", "change", { wbs_no: f.d.wbs_no,
                                               change_no: f.change_no,
                                               note: f.note || undefined });
        toast(`已发起修订，元素进入「变更中」（${f.change_no}）`);
        f.open = false;
        self.modal.d = r;
        await self.reload();
      } catch (e) { toast(String(e.message || e)); }
      finally { f.saving = false; }
    },
    openClose(d) { self.cm = { open: true, d, note: "", saving: false }; },
    async submitClose() {
      const f = self.cm;
      if (f.saving) return;
      f.saving = true;
      try {
        const r = await svc("wbs", "close", { wbs_no: f.d.wbs_no, note: f.note || undefined });
        toast(`已关闭 ${r.wbs_no}`);
        f.open = false;
        self.modal.d = r;
        await self.reload();
      } catch (e) { toast(String(e.message || e)); }
      finally { f.saving = false; }
    },
  });
  return self;
}
