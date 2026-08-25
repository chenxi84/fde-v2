/* app/e2e/process.js —— 组级「流程总览」参考实现（数据驱动 SVG 流程图，最小自足样例）
   不聚合后端服务，硬编码一条 3 阶段链路，演示核心范式（照抄结构、换业务数据即可）：
   ① SVG 不在模板里用 x-for，改在 JS 拼 SVG 字符串 → x-html 注入；点击用 data-page 事件委托；
   ② 坐标在 computeLayout() 里算；③ 正交直角连线 elbow + 步骤间横向箭头 hArrow；④ 暗色主题。
   范式正本见 design-plus/view-convention/patterns.md §8。 */

export const PAGE_META = {
  key: "process", name: "流程总览", ic: "🧭",
  title: "流程总览", crumb: "数据驱动 SVG 流程图",
  order: 15,
};

const NODE_W = 150, NODE_H = 52, GAP_X = 12;
const PILL_W = 200, PILL_H = 30, PILL_GAP = 14, STAGE_GAP = 34, PAD = 28;

function elbow(x1, y1, x2, y2) {
  const yMid = (y1 + y2) / 2, f = (n) => n.toFixed(1);
  const headH = 8, halfW = 4, shaftEnd = y2 - headH;
  const d = `M ${f(x1)} ${f(y1)} L ${f(x1)} ${f(yMid)} L ${f(x2)} ${f(yMid)} L ${f(x2)} ${f(shaftEnd)}`;
  return `<path d="${d}" fill="none" stroke="#2c3a4d" stroke-width="1.5"></path>` +
    `<polygon points="${f(x2 - halfW)},${f(shaftEnd)} ${f(x2)},${f(y2)} ${f(x2 + halfW)},${f(shaftEnd)}" fill="#475569"></polygon>`;
}

function hArrow(x1, x2, y) {
  const f = (n) => n.toFixed(1), headW = 7, headH = 3.5, shaftEnd = x2 - headW;
  return `<line x1="${f(x1)}" y1="${f(y)}" x2="${f(shaftEnd)}" y2="${f(y)}" stroke="#2c3a4d" stroke-width="1.5"></line>` +
    `<polygon points="${f(shaftEnd)},${f(y - headH)} ${f(x2)},${f(y)} ${f(shaftEnd)},${f(y + headH)}" fill="#475569"></polygon>`;
}

export default function pageProcess() {
  const self = Alpine.reactive({
    tpl: "",
    svgHtml: "",

    async init() {
      self.tpl = await fetch(new URL("process.html", import.meta.url)).then((r) => r.text());
      self.svgHtml = self.build();
    },

    goto(key) { location.hash = "#/" + key; },
    onSvgClick(e) {
      const g = e.target && e.target.closest ? e.target.closest("[data-page]") : null;
      if (g && g.dataset.page) self.goto(g.dataset.page);
    },

    /* 硬编码演示数据：3 阶段线性流（真实页可换成前端 quiet 聚合后端服务的推导结果） */
    stages() {
      return [
        { key: "member", name: "① 录入客户", page: "member", steps: [
          { name: "录入", done: true, summary: "已完成" },
          { name: "审核", done: false, summary: "待处理" },
        ] },
        { key: "task", name: "② 建立任务", page: "task", steps: [
          { name: "创建", done: false, summary: "未开始" },
        ] },
        { key: "task", name: "③ 任务闭环", page: "task", steps: [
          { name: "执行", done: false, summary: "未开始" },
          { name: "归档", done: false, summary: "未开始" },
        ] },
      ];
    },

    build() {
      const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const NUM = ["①", "②", "③", "④", "⑤", "⑥"];
      const stages = self.stages();
      const maxSteps = Math.max(...stages.map((s) => s.steps.length), 1);
      const w = maxSteps * NODE_W + (maxSteps - 1) * GAP_X + PAD * 2;
      const cx = w / 2;
      let y = PAD;
      const stageEls = [], nodeEls = [], edgeEls = [], intraEls = [];
      stages.forEach((st, si) => {
        stageEls.push(`<g data-page="${esc(st.page)}" style="cursor:pointer">` +
          `<rect x="${cx - PILL_W / 2}" y="${y}" width="${PILL_W}" height="${PILL_H}" rx="${PILL_H / 2}" fill="url(#p-pill)"></rect>` +
          `<text x="${cx}" y="${y + PILL_H / 2 + 5}" text-anchor="middle" fill="#fff" font-size="14" font-weight="700">${esc(st.name)}</text></g>`);
        const nodeTop = y + PILL_H + PILL_GAP;
        const rw = st.steps.length * NODE_W + (st.steps.length - 1) * GAP_X;
        const x0 = cx - rw / 2;
        st.steps.forEach((step, pi) => {
          const fill = step.done ? "#12271c" : "#182432";
          const stroke = step.done ? "#1e5a3c" : "#2c3a4d";
          const dot = step.done ? "#34d399" : "#475569";
          const nameColor = step.done ? "#86efac" : "#dbe4ee";
          const nx = x0 + pi * (NODE_W + GAP_X);
          nodeEls.push(`<g data-page="${esc(st.page)}" style="cursor:pointer">` +
            `<rect x="${nx}" y="${nodeTop}" width="${NODE_W}" height="${NODE_H}" rx="10" fill="${fill}" stroke="${stroke}" stroke-width="1.2"></rect>` +
            `<circle cx="${nx + 16}" cy="${nodeTop + NODE_H / 2}" r="5" fill="${dot}"></circle>` +
            `<text x="${nx + 28}" y="${nodeTop + 21}" fill="${nameColor}" font-size="13" font-weight="600">${esc(step.name)}</text>` +
            `<text x="${nx + 28}" y="${nodeTop + 40}" fill="#7e90a8" font-size="11">${esc(step.summary)}</text></g>`);
        });
        for (let pi = 0; pi < st.steps.length - 1; pi++) {
          const ax = x0 + pi * (NODE_W + GAP_X) + NODE_W;
          intraEls.push(hArrow(ax + 2, ax + GAP_X - 2, nodeTop + NODE_H / 2));
        }
        const nodeBottom = nodeTop + NODE_H;
        if (si > 0) edgeEls.push(elbow(cx, y - STAGE_GAP, cx, y));
        y = nodeBottom + STAGE_GAP;
      });
      const h = y - STAGE_GAP + PAD;
      const bg = `<rect x="8" y="8" width="${w - 16}" height="${h - 16}" rx="16" fill="#0f1b2a" stroke="#1e2c3e" stroke-width="1"></rect>`;
      return `<svg viewBox="0 0 ${w} ${h}" width="100%" style="min-width:480px;display:block">` +
        `<defs><linearGradient id="p-pill" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#1d2c3f"/><stop offset="1" stop-color="#175e54"/></linearGradient></defs>` +
        bg + edgeEls.join("") + stageEls.join("") + nodeEls.join("") + intraEls.join("") + `</svg>`;
    },
  });
  return self;
}
