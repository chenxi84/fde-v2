/* app/psc/process.js —— 产销协同「流程总览」（无后端应用的组级聚合页，key=process）
   数据驱动 SVG 流水线：月度版本 → 销售预测 → 库存策略 → 毛需求与净需求发布。
   节点状态/摘要由前端聚合现有服务推导（quiet 探测零值兜底）；SVG 以字符串生成、经 x-html 注入，
   点击经事件委托跳转对应页（带版本号）。「Agent 分析下一步」把进度快照发给右栏 Agent。 */
import { svc, fmt } from "/view/lib/api.js";

/* 页面自描述（平台扫描唯一入口）：组级页 key = 文件名 */
export const PAGE_META = {
  key: "process", name: "流程总览", ic: "🧭",
  title: "产销协同流程总览", crumb: "预测 → 库存策略 → 净需求发布",
  order: 15,
};

const NODE_W = 150, NODE_H = 52, GAP_X = 12;
const PILL_W = 220, PILL_H = 30, PILL_GAP = 14, STAGE_GAP = 34, PAD = 28;
const COL_GAP = 90;   // 并行分支（销售预测 / 库存策略）之间的水平间距

/* 正交连线（竖→横→竖，直角转角；末段带向下箭头）——用于阶段间拆分/汇聚（暗色） */
function elbow(x1, y1, x2, y2) {
  const yMid = (y1 + y2) / 2;
  const f = (n) => n.toFixed(1);
  const headH = 8, halfW = 4, shaftEnd = y2 - headH;
  const d = `M ${f(x1)} ${f(y1)} L ${f(x1)} ${f(yMid)} L ${f(x2)} ${f(yMid)} L ${f(x2)} ${f(shaftEnd)}`;
  const head = `<polygon points="${f(x2 - halfW)},${f(shaftEnd)} ${f(x2)},${f(y2)} ${f(x2 + halfW)},${f(shaftEnd)}" fill="#475569"></polygon>`;
  return `<path d="${d}" fill="none" stroke="#2c3a4d" stroke-width="1.5"></path>` + head;
}

/* 步骤间横向箭头（左→右），用于同一阶段内体现步骤前后顺序（暗色） */
function hArrow(x1, x2, y) {
  const f = (n) => n.toFixed(1);
  const headW = 7, headH = 3.5, shaftEnd = x2 - headW;
  return `<line x1="${f(x1)}" y1="${f(y)}" x2="${f(shaftEnd)}" y2="${f(y)}" stroke="#2c3a4d" stroke-width="1.5"></line>` +
    `<polygon points="${f(shaftEnd)},${f(y - headH)} ${f(x2)},${f(y)} ${f(shaftEnd)},${f(y + headH)}" fill="#475569"></polygon>`;
}

export default function pageProcess() {
  const self = Alpine.reactive({
    tpl: "",
    fmt,
    versions: [],        // md_monthly_version.list
    fv: "",              // 当前选中版本
    stages: [],          // 阶段+步骤（含状态/摘要，供 summaryText）
    layout: { w: 0, h: 0, stages: [], nodes: [], edges: [] },
    svgHtml: "",
    loading: true,

    async init() {
      self.tpl = await fetch(new URL("process.html", import.meta.url)).then((r) => r.text());
      await self.loadVersions();
      await self.refresh();
    },

    async loadVersions() {
      try {
        const r = await svc("md_monthly_version", "list", { page: 1, size: 200 }, { quiet: true });
        self.versions = Array.isArray(r) ? r : (r && r.items) || [];
      } catch { self.versions = []; }
      const draft = self.versions.find((v) => v && v.lock_status === "草稿");
      if (draft) self.fv = draft.version_no;
      else if (self.versions.length) self.fv = self.versions[0].version_no;
    },

    onVersionChange() { self.refresh(); },

    gotoPage(key) {
      if (self.fv) localStorage.setItem("fde.process.fv", self.fv);
      window.location.hash = "#/" + key;
    },

    /* 事件委托：点击 SVG 内带 data-page 的节点 → 跳转对应页 */
    onSvgClick(e) {
      const g = e.target && e.target.closest ? e.target.closest("[data-page]") : null;
      if (g && g.dataset.page) self.gotoPage(g.dataset.page);
    },

    /* 从各应用服务聚合当前版本的进度快照，推导每个动作节点状态 */
    async refresh() {
      self.loading = true;
      const v = self.fv;
      const qFc  = v ? svc("sales_forecast", "list", { version_no: v, page: 1, size: 200 }, { quiet: true }).catch(() => null) : Promise.resolve(null);
      const qSum = v ? svc("sales_forecast", "get_summary", { version_no: v }, { quiet: true }).catch(() => null) : Promise.resolve(null);
      const qIs  = v ? svc("inventory_strategy", "list", { version_no: v, page: 1, size: 200 }, { quiet: true }).catch(() => null) : Promise.resolve(null);
      const qDm  = v ? svc("demand", "list", { version_no: v, page: 1, size: 200 }, { quiet: true }).catch(() => null) : Promise.resolve(null);
      const qMp  = v ? svc("master_plan", "list", { version_no: v, page: 1, size: 1 }, { quiet: true }).catch(() => null) : Promise.resolve(null);
      const qIp  = svc("inventory_projection", "list", { page: 1, size: 1 }, { quiet: true }).catch(() => null);
      const qDp  = svc("demand_pool", "list", { page: 1, size: 1 }, { quiet: true }).catch(() => null);
      const qSw  = svc("md_breakpoint", "upcoming", { days: 60 }, { quiet: true }).catch(() => null);
      const [fc, sum, is, dm, mp, ip, dp, sw] = await Promise.all([qFc, qSum, qIs, qDm, qMp, qIp, qDp, qSw]);

      const fcItems = (fc && fc.items) || [];
      const fcTotal = (fc && fc.total) ?? fcItems.length;
      const sumRows = Array.isArray(sum) ? sum : (sum && sum.items) || [];
      const isItems = (is && is.items) || [];
      const isTotal = (is && is.total) ?? isItems.length;
      const dmItems = (dm && dm.items) || [];
      const dmTotal = (dm && dm.total) ?? dmItems.length;
      const mpTotal = (mp && mp.total) ?? 0;
      const ipTotal = (ip && ip.total) ?? 0;
      const dpTotal = (dp && dp.total) ?? 0;
      const swRows = Array.isArray(sw) ? sw : (sw && sw.items) || [];
      const swMats = new Set();
      for (const b of swRows) {
        if (b && b.old_material_no) swMats.add(b.old_material_no);
        if (b && b.new_material_no) swMats.add(b.new_material_no);
      }
      const switchCount = swMats.size;
      const switchNote = switchCount > 0 ? ` ⏳${switchCount}` : "";
      const ver = self.versions.find((x) => x && x.version_no === v) || {};
      const lock = ver.lock_status || "";

      const anyFc = (fn) => fcItems.some(fn);
      const anyDm = (fn) => dmItems.some(fn);
      const fcN = fcItems.length;
      const cntFc = (fn) => fcItems.filter(fn).length;

      self.stages = [
        { key: "md_monthly_version", name: "月度版本", page: "md_monthly_version",
          steps: [{ name: "创建草稿版本", done: !!v, summary: v ? `版本 ${v} · ${lock || "—"}` : "未创建" }] },
        { key: "sales_forecast", name: "销售预测", page: "sales_forecast", note: switchNote,
          steps: [
            { name: "开启预测", done: fcTotal > 0, summary: fcTotal > 0 ? `已生成 ${fcTotal} 行` : "未开启" },
            { name: "填客户预测", done: anyFc((d) => d.orig_qty != null), summary: fcN ? `已填 ${cntFc((d) => d.orig_qty != null)}/${fcN}` : "未填报" },
            { name: "算基线", done: anyFc((d) => d.base_qty != null), summary: fcN ? `已算 ${cntFc((d) => d.base_qty != null)}/${fcN}` : "未计算" },
            { name: "决策", done: anyFc((d) => d.final_qty != null || d.abnormal_flag), summary: fcN ? `已决策 ${cntFc((d) => d.final_qty != null || d.abnormal_flag)}/${fcN}` : "未决策" },
            { name: "汇总", done: sumRows.length > 0, summary: sumRows.length ? `已汇总 ${sumRows.length} 行` : "未汇总" },
          ] },
        { key: "inventory_strategy", name: "库存策略", page: "inventory_strategy", note: switchNote,
          steps: [{ name: "计算三层水位", done: isTotal > 0, summary: isTotal > 0 ? `已算 ${isTotal} 物料` : "未计算" }] },
        { key: "demand", name: "毛需求与净需求", page: "demand",
          steps: [
            { name: "合成毛需求", done: dmTotal > 0, summary: dmTotal > 0 ? `已合成 ${dmTotal} 行` : "未合成" },
            { name: "发布", done: lock === "发布（锁定）" || lock === "冻结", summary: lock || "未发布" },
            { name: "运算净需求", done: anyDm((d) => d.net_qty != null), summary: anyDm((d) => d.net_qty != null) ? "已运算" : "未运算" },
            { name: "导出净需求", done: false, summary: "手动导出" },
          ] },
        { key: "master_plan", name: "主计划", page: "master_plan",
          steps: [{ name: "导入净需求", done: mpTotal > 0, summary: mpTotal > 0 ? `已导入 ${mpTotal} 行` : "未导入" }] },
        { key: "inventory_projection", name: "库存推移表", page: "inventory_projection",
          steps: [
            { name: "逐日推演水位", done: ipTotal > 0, summary: ipTotal > 0 ? `主计划入库 + 出库计划出库 · 已推演` : "未推演" },
            { name: "击穿触发补库", done: dpTotal > 0, summary: dpTotal > 0 ? `已生成 ${dpTotal} 张补库单` : "未击穿" },
          ] },
        { key: "demand_pool", name: "需求池", page: "demand_pool",
          steps: [{ name: "补库单流转", done: dpTotal > 0, summary: dpTotal > 0 ? `共 ${dpTotal} 单` : "暂无补库单" }] },
      ];

      self.layout = self.computeLayout();
      self.svgHtml = self.buildSvg();
      self.loading = false;
    },

    /* 计算坐标：三行拓扑 —— 月度版本(居中) → [销售预测(左) ∥ 库存策略(右)] → 毛需求(居中)。
       阶段间用正交直角连线（拆分→并行→汇聚）；同一阶段内步骤之间用横向箭头体现前后顺序。 */
    computeLayout() {
      const byKey = {};
      self.stages.forEach((s) => { byKey[s.key] = s; });
      const rowW = (n) => n * NODE_W + (n - 1) * GAP_X;
      const sfW = rowW((byKey.sales_forecast || { steps: [] }).steps.length || 1);
      const isW = rowW((byKey.inventory_strategy || { steps: [] }).steps.length || 1);
      const dmW = rowW((byKey.demand || { steps: [] }).steps.length || 1);
      const mvW = rowW((byKey.md_monthly_version || { steps: [] }).steps.length || 1);
      const w = Math.max(PAD + sfW + COL_GAP + PILL_W + PAD, PAD + dmW + PAD, PAD + mvW + PAD);
      const centerCx = w / 2;
      const sfCx = PAD + sfW / 2;            // 左分支：节点行左对齐（sfW > PILL_W）
      const isCx = w - PAD - PILL_W / 2;     // 右分支：胶囊右对齐（PILL_W > isW，避免溢出）

      const rows = [
        [{ key: "md_monthly_version", cx: centerCx }],
        [{ key: "sales_forecast", cx: sfCx }, { key: "inventory_strategy", cx: isCx }],
        [{ key: "demand", cx: centerCx }],
        [{ key: "master_plan", cx: centerCx }],
        [{ key: "inventory_projection", cx: centerCx }],
        [{ key: "demand_pool", cx: centerCx }],
      ];

      let y = PAD;
      const stageMeta = [], nodes = [], edges = [], intraEdges = [];
      let prevBottoms = [];
      rows.forEach((row, ri) => {
        const bottoms = [];
        row.forEach(({ key, cx }) => {
          const st = byKey[key];
          if (!st) return;
          stageMeta.push({ key, name: st.name, page: st.page, note: st.note,
            pillX: cx - PILL_W / 2, pillY: y, pillW: PILL_W, pillH: PILL_H, cx });
          const nodeTop = y + PILL_H + PILL_GAP;
          const rw = rowW(st.steps.length);
          const x0 = cx - rw / 2;
          st.steps.forEach((step, pi) => {
            nodes.push({ k: key + "-" + pi, name: step.name, summary: step.summary, done: step.done,
              page: st.page, x: x0 + pi * (NODE_W + GAP_X), y: nodeTop, w: NODE_W, h: NODE_H });
          });
          // 步骤间横向箭头（体现先后顺序）
          for (let pi = 0; pi < st.steps.length - 1; pi++) {
            const ax = x0 + pi * (NODE_W + GAP_X) + NODE_W;
            intraEdges.push({ x1: ax + 2, x2: ax + GAP_X - 2, y: nodeTop + NODE_H / 2 });
          }
          bottoms.push({ cx, y: nodeTop + NODE_H });
        });
        if (ri > 0) {
          prevBottoms.forEach((p) => bottoms.forEach((c) => edges.push({ x1: p.cx, y1: p.y, x2: c.cx, y2: y })));
        }
        prevBottoms = bottoms;
        y += PILL_H + PILL_GAP + NODE_H + STAGE_GAP;
      });
      return { w, h: y - STAGE_GAP + PAD, stages: stageMeta, nodes, edges, intraEdges };
    },

    /* 生成 SVG 字符串（规避 Alpine 在 <svg> 内 x-for 的命名空间限制） */
    buildSvg() {
      const L = self.layout;
      if (!L.w || !L.nodes.length) return "";
      const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const NUM = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"];

      const bg = `<rect x="8" y="8" width="${L.w - 16}" height="${L.h - 16}" rx="16" fill="#0f1b2a" stroke="#1e2c3e" stroke-width="1"></rect>`;

      const stageEls = L.stages.map((s, si) =>
        `<g data-page="${esc(s.page)}" style="cursor:pointer">` +
        `<rect x="${s.pillX}" y="${s.pillY}" width="${s.pillW}" height="${s.pillH}" rx="${s.pillH / 2}" fill="url(#p-pill)"></rect>` +
        `<text x="${s.cx}" y="${s.pillY + s.pillH / 2 + 5}" text-anchor="middle" fill="#ffffff" font-size="14" font-weight="700" letter-spacing="1">${NUM[si] || ""} ${esc(s.name)}${esc(s.note)}</text></g>`
      ).join("");

      const nodeEls = L.nodes.map((n) => {
        const fill = n.done ? "#12271c" : "#182432";
        const stroke = n.done ? "#1e5a3c" : "#2c3a4d";
        const dot = n.done ? "#34d399" : "#475569";
        const nameColor = n.done ? "#86efac" : "#dbe4ee";
        return `<g data-page="${esc(n.page)}" style="cursor:pointer">` +
          `<rect x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="10" fill="${fill}" stroke="${stroke}" stroke-width="1.2"></rect>` +
          `<circle cx="${n.x + 16}" cy="${n.y + n.h / 2}" r="5" fill="${dot}"></circle>` +
          `<text x="${n.x + 28}" y="${n.y + 21}" fill="${nameColor}" font-size="13" font-weight="600">${esc(n.name)}</text>` +
          `<text x="${n.x + 28}" y="${n.y + 40}" fill="#7e90a8" font-size="11">${esc(n.summary)}</text></g>`;
      }).join("");

      const edgeEls = L.edges.map((e) => elbow(e.x1, e.y1, e.x2, e.y2)).join("");
      const intraEls = (L.intraEdges || []).map((e) => hArrow(e.x1, e.x2, e.y)).join("");

      return `<svg viewBox="0 0 ${L.w} ${L.h}" width="100%" style="min-width:720px;display:block">` +
        `<defs>` +
        `<linearGradient id="p-pill" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#1d2c3f"/><stop offset="1" stop-color="#175e54"/></linearGradient>` +
        `</defs>` +
        bg + edgeEls + stageEls + nodeEls + intraEls + `</svg>`;
    },

    /* 把阶段/步骤拼成给 Agent 的文本快照 */
    summaryText() {
      const lines = [`月度版本：${self.fv || "（未选）"}`];
      for (const st of self.stages) {
        const steps = st.steps.map((s) => `${s.name}${s.done ? "✓" : "✗"}`).join(" → ");
        lines.push(`${st.name}：${steps}`);
      }
      return lines.join("\n");
    },

    /* 触发右栏 Agent 分析下一步 */
    agentAnalyze() {
      const prompt = `请分析产销协同月度版本 ${self.fv || "（未选）"} 的执行进度，判断当前卡在哪一步、下一步应该执行什么操作（按流程顺序给建议）。\n\n当前状态快照：\n${self.summaryText()}`;
      window.dispatchEvent(new CustomEvent("fde:agent-open"));
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent("fde:agent-prompt", { detail: { message: prompt } }));
      }, 250);
    },
  });
  return self;
}
