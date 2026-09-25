/* app/nasa_pms/process.js —— 系统工程「流程总览」（无后端应用的组级聚合页，key=process）
 *
 * 与 PSC 那份（`app/psc/process.js`）同一套机制：**数据驱动 SVG** + 事件委托跳转 + 委托右栏 Agent。
 * 差别在**拓扑**：PSC 是单条产销链，nasa_pms 的 11 个聚合根是**四个职能域**（与 `_roles.py`
 * 声明的四个角色一一对应），每域内是一条小链：
 *
 *   ① 需求与验证域：利益相关者 → 需求 → 验证项
 *   ② 风险与度量域：风险 → 技术度量 → 决策
 *   ③ 配置与变更域：配置项 → 变更请求 → 接口
 *   ④ 计划与评审域：技术计划 → 评审
 *
 * 每个节点的读数都来自**该应用自己的服务**（`list` / `list_alerts`，quiet 探测 + 零值兜底），
 * 所以图上是实时状态而非硬编码；节点灰/绿 = **该应用的关键闭环有没有发生过**（见 doneOf）。
 * 「让 AI 管家跑」按声明制委派：平台没有 HTTP 的"运行流程"端点，Agent 有 `platform_run_flow` 工具。
 */
import { svc } from "/view/lib/api.js";

/* 页面自描述（平台扫描唯一入口）：组级页 key = 文件名 */
export const PAGE_META = {
  key: "process", name: "流程总览", ic: "🧭",
  title: "系统工程流程总览", crumb: "需求与验证 · 风险与度量 · 配置与变更 · 计划与评审",
  order: 5,          // dashboard(1) 之后、业务页(610+) 之前
};

// 尺寸按「两列**自然放得下**常见内容区」定（≈1080 宽）—— 画布过宽会出横向滚动条（用户反馈）。
const NODE_W = 152, NODE_H = 56, GAP_X = 22;      // 152 与 PSC 同量级（它也是 150）
const PILL_W = 214, PILL_H = 30, PILL_GAP = 14, PAD = 24;
const COL_GAP = 40, ROW_GAP = 26;                 // 域按 2 列 × 2 行摆
const SUM_FS = 10;                                // 摘要字号（比节点名小一号）
const SUM_CH = 12;                                // 每行约 12 个中文字宽（10px 字号，中文≈10px/字）
const SUM_LINES = 2;                              // 摘要最多两行（超出才截断）

/* 把摘要按 " · " 边界折成 1–2 行（SVG 没有 ellipsis、也不会自动换行，必须自己折） */
function wrapSummary(s) {
  const segs = String(s || "").split(" · ").map((x) => x.trim()).filter(Boolean);
  const lines = [];
  for (const seg of segs) {
    const cur = lines[lines.length - 1];
    if (cur === undefined || (cur + " · " + seg).length > SUM_CH) lines.push(seg);
    else lines[lines.length - 1] = cur + " · " + seg;
  }
  if (lines.length > SUM_LINES) {
    const rest = lines.splice(SUM_LINES - 1).join(" · ");
    lines.push(rest.length > SUM_CH ? rest.slice(0, SUM_CH - 1) + "…" : rest);
  }
  return lines;
}

/* 本组四个职能域（与 `_roles.py` 的四个角色同构）· 每域是一串有先后依赖的应用 */
const DOMAINS = [
  { role: "nasa_requirements", name: "需求与验证域", apps: ["stakeholder", "requirement", "verification"] },
  { role: "nasa_risk_tpm", name: "风险与度量域", apps: ["risk", "technical_measure", "decision"] },
  { role: "nasa_cm", name: "配置与变更域", apps: ["configuration_item", "change_request", "interface"] },
  { role: "nasa_planner", name: "计划与评审域", apps: ["tech_plan", "wbs", "review"] },
];
const APP_LABEL = {
  stakeholder: "利益相关者", requirement: "需求", verification: "验证项",
  risk: "风险", technical_measure: "技术度量", decision: "决策",
  configuration_item: "配置项", change_request: "变更请求", interface: "接口",
  tech_plan: "技术计划", wbs: "WBS 元素", review: "评审",
};

/* 步骤间横向箭头（左→右）：域内应用有先后依赖，用它体现顺序（与 PSC 同款，暗色） */
function hArrow(x1, x2, y) {
  const f = (n) => n.toFixed(1);
  const headW = 8, headH = 4, shaftEnd = x2 - headW;
  return `<line x1="${f(x1)}" y1="${f(y)}" x2="${f(shaftEnd)}" y2="${f(y)}" stroke="#2c3a4d" stroke-width="1.5"></line>` +
    `<polygon points="${f(shaftEnd)},${f(y - headH)} ${f(x2)},${f(y)} ${f(shaftEnd)},${f(y + headH)}" fill="#475569"></polygon>`;
}

export default function pageProcess() {
  const self = Alpine.reactive({
    tpl: "",
    stages: [],          // 四个域（供 summaryText / 布局）
    flows: [],           // 本组声明的 flow（/api/flows?group=）
    layout: { w: 0, h: 0, stages: [], nodes: [], intraEdges: [] },
    svgHtml: "",
    loading: true,

    async init() {
      self.tpl = await fetch(new URL("process.html", import.meta.url)).then((r) => r.text());
      await Promise.all([self.refresh(), self.loadFlows()]);
    },

    async loadFlows() {
      try {
        const r = await fetch(`/api/flows?group=nasa_pms`, { credentials: "same-origin" });
        const j = await r.json();
        const items = (j && (j.data || j.items)) || [];
        self.flows = items.map((f) => {
          const nodes = f.nodes || [];
          const byType = {};
          for (const n of nodes) byType[n.type || "agent"] = (byType[n.type || "agent"] || 0) + 1;
          return { key: f.key, name: f.name, description: (f.description || "").replace(/\s+/g, " "),
                   nodes: nodes.length, byType };
        });
      } catch { self.flows = []; }
    },

    gotoPage(key) { window.location.hash = "#/" + key; },

    /* 事件委托：点击 SVG 内带 data-page 的节点/域名 → 跳转对应页 */
    onSvgClick(e) {
      const g = e.target && e.target.closest ? e.target.closest("[data-page]") : null;
      if (g && g.dataset.page) self.gotoPage(g.dataset.page);
    },

    /* 拉各应用台账的实时读数 → 每个节点一行摘要 + 一个 done 判定 */
    async refresh() {
      self.loading = true;

      const call = (app, s, kw) => svc(app, s, kw || {}, { quiet: true }).catch(() => null);
      const [req, ver, sh, risk, tpm, dec, ci, cr, itf, tp, rv, wb, alerts] = await Promise.all([
        call("requirement", "list", { page: 1, size: 1 }),
        call("verification", "list", { page: 1, size: 1 }),
        call("stakeholder", "list", { page: 1, size: 1 }),
        call("risk", "list", { page: 1, size: 1 }),
        call("technical_measure", "list", { page: 1, size: 1 }),
        call("decision", "list", { page: 1, size: 1 }),
        call("configuration_item", "list", { page: 1, size: 1 }),
        call("change_request", "list", { page: 1, size: 1 }),
        call("interface", "list", { page: 1, size: 1 }),
        call("tech_plan", "list", { page: 1, size: 1 }),
        call("review", "list", { page: 1, size: 1 }),
        call("wbs", "list", { page: 1, size: 1 }),
        call("technical_measure", "list_alerts", { status: "open", page: 1, size: 1 }),
      ]);
      const n = (r) => (r && r.total) ?? 0;

      /* 关键闭环计数：用 filtered list 拿总数（各应用 list 都支持按状态筛） */
      const cnt = async (app, kw) => n(await call(app, "list", { ...kw, page: 1, size: 1 }));
      const [reqBase, reqPend, verPass, verFail, verClosed, riskClosed, ciRel, crReview,
             itfFrozen, tpApproved, tpRevised, rvTrack, rvClosed, decDone,
             wbsBase] = await Promise.all([
        cnt("requirement", { status: "baselined" }), cnt("requirement", { status: "pending_review" }),
        cnt("verification", { status: "passed" }), cnt("verification", { status: "failed" }),
        cnt("verification", { status: "closed" }), cnt("risk", {}),
        cnt("configuration_item", { status: "released" }), cnt("change_request", { status: "reviewing" }),
        cnt("interface", { status: "frozen" }), cnt("tech_plan", { status: "approved" }),
        cnt("tech_plan", { status: "revised" }), cnt("review", { status: "tracking" }),
        cnt("review", { status: "closed" }), cnt("decision", { status: "implemented" }),
        cnt("wbs", { status: "baselined" }),
      ]);
      const riskTerminal = n(risk) - (await cnt("risk", { status: "identified" }))
        - (await cnt("risk", { status: "analyzing" })) - (await cnt("risk", { status: "mitigating" }));
      const openAlerts = n(alerts);

      const meta = {
        stakeholder:  { sum: `${n(sh)} 条 · 期望随方维护`,              done: n(sh) > 0 },
        requirement:  { sum: `${n(req)} 条 · 已基线 ${reqBase} / 待评审 ${reqPend}`, done: reqBase > 0 },
        verification: { sum: `${n(ver)} 行 · 通过 ${verPass} / 未过 ${verFail}`,
                        done: verPass + verFail > 0 },
        risk:         { sum: `${n(risk)} 条 · 已了结 ${riskTerminal}`,   done: riskTerminal > 0 },
        technical_measure: { sum: `${n(tpm)} 条 · 未了结告警 ${openAlerts}`,
                             done: n(tpm) > 0 && openAlerts === 0 },
        decision:     { sum: `${n(dec)} 条 · 已实施 ${decDone}`,         done: decDone > 0 },
        configuration_item: { sum: `${n(ci)} 条 · 已发布 ${ciRel}`,      done: ciRel > 0 },
        change_request: { sum: `${n(cr)} 条 · 审批中 ${crReview}`,       done: n(cr) > 0 && crReview === 0 },
        interface:    { sum: `${n(itf)} 条 · 已冻结 ${itfFrozen}`,       done: itfFrozen > 0 },
        tech_plan:    { sum: `${n(tp)} 份 · 已批准 ${tpApproved}`,
                        done: tpApproved > 0 },
        review:       { sum: `${n(rv)} 场 · 跟踪 ${rvTrack} / 已关 ${rvClosed}`, done: rvClosed > 0 },
        wbs:          { sum: `${n(wb)} 个元素 · 已基线 ${wbsBase}`,   done: wbsBase > 0 },
      };

      self.stages = DOMAINS.map((d) => ({
        key: d.role, name: d.name,
        steps: d.apps.map((a) => ({ app: a, name: APP_LABEL[a] || a,
                                    summary: (meta[a] || {}).sum || "—",
                                    done: !!(meta[a] || {}).done, page: a })),
      }));
      self.layout = self.computeLayout();
      self.svgHtml = self.buildSvg();
      self.loading = false;
    },

    /* 坐标：**一域一行**（四个域自上而下），域内应用横向排列（左→右即依赖方向）。
       ⚠ 为什么不是 2 列 × 2 行（2026-09-25 两次实测后定）：
       平台的**内容区宽度取决于右栏是否展开** —— 右栏开着约 638px、收起约 1000px。
       2 列摆法画布 ~1088 ⇒ 右栏开着时**出横向滚动条**；早先的 4 行摆法（画布 612）在右栏收起时
       被 `width:100%` **放大 1.6 倍 ⇒ 字看着太大**。**一域一行 + 节点收窄（画布 ≈548）**两头都满足：
       638 装得下（不滚动）、1000 也不放大（`max-width` 封顶，居中显示）。
       域之间**不连线**：它们是并列的职能域，不是一条流水线（PSC 是单链，故它有正交连线）。 */
    computeLayout() {
      const rowW = (k) => k * NODE_W + (k - 1) * GAP_X;
      const maxRow = Math.max(...self.stages.map((s) => rowW(s.steps.length)));
      const w = PAD * 2 + Math.max(maxRow, PILL_W);
      const cellH = PILL_H + PILL_GAP + NODE_H;
      const h = PAD * 2 + self.stages.length * cellH + (self.stages.length - 1) * ROW_GAP;
      const cx = w / 2;

      const stageMeta = [], nodes = [], intraEdges = [];
      let y = PAD;
      self.stages.forEach((st) => {
        const rw = rowW(st.steps.length);
        const x0 = cx - rw / 2;
        const nodeTop = y + PILL_H + PILL_GAP;
        stageMeta.push({ key: st.key, name: st.name, page: st.steps[0].page,
                         pillX: cx - PILL_W / 2, pillY: y, pillW: PILL_W, pillH: PILL_H, cx });
        st.steps.forEach((step, i) => {
          nodes.push({ k: st.key + "-" + i, name: step.name, lines: wrapSummary(step.summary),
                       done: step.done, page: step.page,
                       x: x0 + i * (NODE_W + GAP_X), y: nodeTop, w: NODE_W, h: NODE_H });
        });
        for (let i = 0; i < st.steps.length - 1; i++) {
          const ax = x0 + i * (NODE_W + GAP_X) + NODE_W;
          intraEdges.push({ x1: ax + 3, x2: ax + GAP_X - 3, y: nodeTop + NODE_H / 2 });
        }
        y += cellH + ROW_GAP;
      });
      return { w, h, stages: stageMeta, nodes, intraEdges };
    },

    /* 生成 SVG 字符串（规避 Alpine 在 <svg> 内 x-for 的命名空间限制）—— 与 PSC 同款渲染 */
    buildSvg() {
      const L = self.layout;
      if (!L.w || !L.nodes.length) return "";
      const esc = (s) => String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const NUM = ["①", "②", "③", "④", "⑤", "⑥"];
      const bg = `<rect x="8" y="8" width="${L.w - 16}" height="${L.h - 16}" rx="16" fill="#0f1b2a" stroke="#1e2c3e" stroke-width="1"></rect>`;
      const stageEls = L.stages.map((s, si) =>
        `<g data-page="${esc(s.page)}" style="cursor:pointer">` +
        `<rect x="${s.pillX}" y="${s.pillY}" width="${s.pillW}" height="${s.pillH}" rx="${s.pillH / 2}" fill="url(#p-pill)"></rect>` +
        `<text x="${s.cx}" y="${s.pillY + s.pillH / 2 + 5}" text-anchor="middle" fill="#ffffff" font-size="14" font-weight="700" letter-spacing="1">${NUM[si] || ""} ${esc(s.name)}</text></g>`
      ).join("");
      const nodeEls = L.nodes.map((nd) => {
        const fill = nd.done ? "#12271c" : "#182432";
        const stroke = nd.done ? "#1e5a3c" : "#2c3a4d";
        const dot = nd.done ? "#34d399" : "#475569";
        const nameColor = nd.done ? "#86efac" : "#dbe4ee";
        return `<g data-page="${esc(nd.page)}" style="cursor:pointer">` +
          `<rect x="${nd.x}" y="${nd.y}" width="${nd.w}" height="${nd.h}" rx="10" fill="${fill}" stroke="${stroke}" stroke-width="1.2"></rect>` +
          `<circle cx="${nd.x + 16}" cy="${nd.y + nd.h / 2}" r="5" fill="${dot}"></circle>` +
          `<text x="${nd.x + 28}" y="${nd.y + 22}" fill="${nameColor}" font-size="13" font-weight="600">${esc(nd.name)}</text>` +
          (nd.lines || []).map((ln, li) =>
            `<text x="${nd.x + 28}" y="${nd.y + 36 + li * 12}" fill="#7e90a8" font-size="${SUM_FS}">${esc(ln)}</text>`
          ).join("") + `</g>`;
      }).join("");
      const intraEls = (L.intraEdges || []).map((e) => hArrow(e.x1, e.x2, e.y)).join("");
      // ⚠ `max-width:${L.w}px`：**不许放大**（画布比容器小时按自然尺寸渲染，字号才等于设计值；
      //   容器更窄则由外层 .scroll-x 横向滚动）—— 少了它，窄画布会被 width:100% 放大、字看着超大。
      return `<svg viewBox="0 0 ${L.w} ${L.h}" width="100%" style="min-width:520px;max-width:${L.w}px;display:block">` +
        `<defs><linearGradient id="p-pill" x1="0" y1="0" x2="1" y2="0">` +
        `<stop offset="0" stop-color="#1d2c3f"></stop><stop offset="1" stop-color="#175e54"></stop>` +
        `</linearGradient></defs>` + bg + stageEls + intraEls + nodeEls + `</svg>`;
    },

    /* 给 Agent 的文本快照（图上有什么，就发什么） */
    summaryText() {
      const lines = ["系统工程流程总览（按职能域）"];
      for (const st of self.stages) {
        lines.push(`${st.name}：` + st.steps
          .map((s) => `${s.name}(${s.summary})${s.done ? "✓" : "✗"}`).join(" → "));
      }
      return lines.join("\n");
    },

    /* 委托右栏 Agent 分析（平台无 HTTP 的运行端点，跑流程也走它） */
    agentAnalyze() {
      const prompt = "请按系统工程流程总览判断：四个职能域里当前**卡在哪一环**、下一步该做什么"
        + "（按流程顺序给建议，可点名具体应用与服务）。\n\n当前状态快照：\n" + self.summaryText();
      self.askAgent(prompt);
    },

    runFlow(f) {
      self.askAgent(`请用 platform_run_flow 运行流程「${f.name}」，跑完后汇报：每个节点做了什么、`
        + `哪些节点被条件跳过、以及最终落库的业务影响。`);
    },

    askAgent(message) {
      window.dispatchEvent(new CustomEvent("fde:agent-open"));
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent("fde:agent-prompt", { detail: { message } }));
      }, 250);
    },

    openFlowEditor() { window.location.hash = "#/flow_editor"; },
  });
  return self;
}
