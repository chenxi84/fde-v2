/* app/psc/material360.js —— psc 组级聚合页「物料 360 视图」（无后端应用 · key=material_360）
   选中一个物料，一屏呈现其基础数据 / 销售历史 / 预测与库存策略 / 毛净需求 / 入库出库计划 / 库存推移。
   编排方式：前端 Promise.allSettled 扇出 ~15 个 quiet svc 字面量，每个分区独立零值回落
   （任一应用无数据/失败只空该区，不坏整页；照抄 app/psc/dashboard.js 模式）。
   图表：手写 SVG 模板字符串 + x-html 注入（照抄 app/psc/process.js buildSvg 模式）。
   月度版本：自动取当前活跃版本（get_active），非用户可选——360 视图与版本无关，仅作只读标注。 */
import { svc, hue, fmt, dash } from "/view/lib/api.js";

/* 页面自描述（平台扫描的唯一入口）：组级页 key = material_360；order 在 dashboard(10)/process(15) 之后、应用页(100) 之前 */
export const PAGE_META = {
  key: "material_360", name: "物料 360 视图", ic: "🧭",
  title: "物料 360 视图", crumb: "单物料全景 · 基础数据 / 历史 / 预测 / 需求 / 计划 / 推移",
  order: 20,
};

/* 预警色（库存推移分区 · 与 inventory_projection/view.js 同映射，本地复制避免跨页共享） */
const ALERT_HUES = { 缺货: "red", 击穿最低: "red", 击穿安全: "red", 呆滞: "amber", 超储: "amber", 无: "slate" };
const alertHue = (t) => ALERT_HUES[t] || "slate";

/* ── 浅色主题 SVG 色板（对齐平台设计系统 fde.css）──
   prime #175e54 松绿（主折线）、amber #d97706 熔琥珀（预警）、prime-soft #e3eee9（水位带）、
   line #dde2d9（网格）、muted #69758a（轴标签）。 */

/* 默认零值回落：list 类返回 {items, total}，其余返回 null */
function pick(s, def = { items: [], total: 0 }) {
  return (s.status === "fulfilled" && s.value != null) ? s.value : def;
}

export default function pageMaterial360() {
  const self = Alpine.reactive({
    tpl: "",
    fmt, dash, hue, alertHue,
    loading: true,

    /* ── 物料选择器（flat 数组 · 照抄 inventory_projection/view.js 模式） ── */
    matOptions: [], matMap: {}, matFiltered: [],
    acShow: "",              // "" / "filter" —— 当前展开的 autocomplete
    fMaterial: "",           // 搜索框输入（与选中不同步，选定才写入 material_no）
    material: null,          // 选中的物料号（null = 未选）
    materialInfo: null,      // md_material.get 结果

    /* ── 月度版本（自动取活跃版本，非用户可选） ── */
    fv: "",                  // 当前活跃 version_no
    anchorPeriod: "",        // 活跃版本锚定月 YYYY-MM（N+1 → 实际月换算用）
    versionInfo: null,       // 活跃版本 {version_no, anchor_period, lock_status}

    /* ── 分区数据（每区独立；未选物料时全部空） ── */
    /* ① 基础数据 */
    projects: [],            // [{project_no, usage, project_name, stage, sop_date, eop_date, veh_model, share}]
    replacements: [],        // [{rel_no, old_material_no, new_material_no, status}]
    breakpoints: [],         // [{bp_id, old_material_no, new_material_no, switch_time, customer_no}]
    bpChain: [],             // trace 链

    /* ② 销售历史 */
    histPoints: [],          // [{period, qty}] 按期聚合升序（图表 + 实际月份）
    attainment: [],          // 客户 MAPE/bias

    /* ③ 预测与库存策略 */
    fcSummary: [],           // [{rolling_month, final_qty_sum}]
    fcDetail: [],            // [{customer_no, rolling_month, final_qty, base_method, abnormal_flag}]
    waterStrategy: null,     // {min_level, safety_level, batch_level, lower, upper, hedge_tool, basis, ...}
    fittingHist: [],         // [{fit_version, pred_method, smape, status, abnormal_flag}]
    fitLatest: null,         // get_latest 结果（含 mase/sigma_l/pred_qty/detail_json）
    fitCandidates: [],       // 候选排名（解析 detail_json.candidates）
    fitSteps: [],            // winner 逐月拟合 steps（供曲线）

    /* ④ 毛需求/净需求 */
    demandRows: [],          // [{rolling_month, forecast_qty, inventory_qty, gross_qty, open_order_qty, onhand_qty, in_transit_qty, net_qty}]

    /* ⑤ 入库计划 */
    masterLatest: [],        // [{rolling_month, plan_version, plan_qty, latest_inbound_date}]
    replenishPool: [],       // [{replenish_no, replenish_type, replenish_qty, required_inbound, promised_inbound, status}]

    /* ⑥ 出库计划 */
    outbound: [],            // [{plan_no, customer_no, qty, out_date, status}]

    /* ⑦ 库存推移 */
    projRows: [],           // 逐日 rows
    projWater: null,         // water level 参考

    async init() {
      self.tpl = await fetch(new URL("material360.html", import.meta.url)).then((r) => r.text());
      await Promise.all([
        self.loadMaterials(),
        self.loadVersion(),
      ]);
      self.loading = false;
      window.addEventListener("resize", () => {
        const E = window.echarts;
        if (!E) return;
        ["m360HistoryChart", "m360ProjChart"].forEach(id => {
          const el = document.getElementById(id);
          if (el) { const c = E.getInstanceByDom(el); if (c) c.resize(); }
        });
      });
    },

    gotoPage(key) { window.location.hash = "#/" + key; },

    /* ── 物料选择器 ── */
    async loadMaterials() {
      try {
        const r = await svc("md_material", "list", { page: 1, size: 200 }, { quiet: true });
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        const opts = [], map = {};
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
        self.matOptions = []; self.matMap = {}; self.matFiltered = [];
      }
    },
    matName(no) { return (no && self.matMap[no]) || ""; },
    openAc(which) { self.acShow = which; self.filterMat(self.fMaterial); },
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
    pickMat(no) {
      self.material = no;
      self.fMaterial = no;
      self.acShow = "";
      self.loadAll();
    },
    clearMat() {
      self.material = null; self.fMaterial = ""; self.materialInfo = null;
      self.resetSections();
    },

    /* ── 月度版本（自动取活跃版本） ── */
    async loadVersion() {
      try {
        const active = await svc("md_monthly_version", "get_active", {}, { quiet: true });
        if (active && active.version_no) {
          self.fv = active.version_no;
          self.anchorPeriod = active.anchor_period || "";
          self.versionInfo = active;
        } else {
          const latest = await svc("md_monthly_version", "list", { page: 1, size: 1 }, { quiet: true });
          const items = (latest && latest.items) || [];
          if (items.length) {
            self.fv = items[0].version_no;
            self.anchorPeriod = items[0].anchor_period || "";
            self.versionInfo = items[0];
          }
        }
      } catch {
        self.fv = ""; self.anchorPeriod = ""; self.versionInfo = null;
      }
    },

    /* N+1/N+2/N+3 → 实际月份（anchor_period + 偏移） */
    actualMonth(rm) {
      const off = parseInt((rm || "").replace(/[^\d]/g, ""), 10);
      if (!self.anchorPeriod || !off) return rm || "—";
      const [y, m] = self.anchorPeriod.split("-").map(Number);
      const d = new Date(y, m - 1 + off, 1);
      const p = (n) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}`;
    },

    /* ── 大模型分析：把已加载的 360 数据快照拼成结构化提示词，交右栏 Agent 分析 ── */
    buildAnalysisPrompt() {
      const m = self.material;
      const i = self.materialInfo || {};
      const L = [];
      L.push(`你是资深产销协同（S&OP）计划专家。请对物料 ${m} 做一次全景体检分析。`);
      L.push("以下是我已采集的该物料数据快照，请**直接基于这些数据分析，不要调用任何工具或再查数据**。");

      /* ① 基础数据与生命周期 */
      L.push("\n## 一、基础数据与生命周期");
      L.push(`- 物料 ${m}「${i.material_name || "—"}」；状态 ${i.status || "—"}；价值等级 ${i.value_class || "—"}；单位价值 ${i.unit_value ?? "—"}`);
      L.push(`- 生产天数 ${i.prod_days ?? "—"}；物流天数 ${i.logistics_days ?? "—"}；切换成本 ${i.change_cost ?? "—"}；切换风险 ${i.change_risk || "—"}`);
      L.push(`- 服务水平目标 ${i.service_level != null ? (i.service_level * 100).toFixed(1) + "%" : "—"}；批次窗口 ${i.batch_window ?? "—"} 天`);
      if (self.projects.length) {
        L.push(`- 所属项目：${self.projects.map((p) => `${p.project_no}「${p.project_name}」阶段 ${p.stage}，SOP ${p.sop_date || "—"}，EOP ${p.eop_date || "—"}，车型 ${p.veh_model || "—"}，份额 ${p.share ?? "—"}`).join("；")}`);
      } else L.push("- 所属项目：无");
      if (self.bpChain.length > 1) L.push(`- 断点链：${self.bpChain.join(" → ")}`);
      if (self.replacements.length) {
        L.push(`- 替换关系：${self.replacements.map((r) => `${r.old_material_no}→${r.new_material_no}（${r.status}）`).join("；")}`);
      }

      /* ② 销售历史与需求特征 */
      L.push("\n## 二、销售历史与需求特征");
      if (self.histPoints.length) {
        const vals = self.histPoints.map((p) => p.qty);
        const total = vals.reduce((a, b) => a + b, 0);
        const avg = total / vals.length;
        const maxV = Math.max(...vals), minV = Math.min(...vals);
        const sd = Math.sqrt(vals.reduce((a, b) => a + (b - avg) ** 2, 0) / vals.length);
        const cv = avg > 0 ? ((sd / avg) * 100).toFixed(1) : "0";
        L.push(`- 近 ${self.histPoints.length} 期销量：均值 ${avg.toFixed(0)}，最高 ${maxV}，最低 ${minV}，标准差 ${sd.toFixed(0)}，变异系数 CV ${cv}%`);
        L.push(`- 近 12 期序列：${vals.slice(-12).join("、")}`);
      } else L.push("- 暂无销售历史");
      if (self.attainment.length) {
        L.push(`- 客户达成率：${self.attainment.map((a) => `${a.customer_no}（MAPE ${(a.mape * 100).toFixed(1)}%，bias ${(a.bias * 100).toFixed(1)}%）`).join("；")}`);
      } else L.push("- 客户达成率：暂无");

      /* ③ 预测方法与库存策略 */
      L.push("\n## 三、预测方法与库存策略");
      L.push(`- 当前预测方法 ${i.base_method || "—"}；参数 ${i.base_params || "—"}；拟合版本 ${i.fit_version || "—"}`);
      if (self.fittingHist.length) {
        L.push(`- 拟合历史：${self.fittingHist.slice(0, 4).map((f) => `${f.fit_version}（${f.pred_method}，SMAPE ${(f.smape * 100).toFixed(1)}%，${f.status}${f.abnormal_flag ? "·异常" : ""}）`).join("；")}`);
      } else L.push("- 拟合历史：暂无");
      if (self.waterStrategy) {
        const w = self.waterStrategy;
        L.push(`- 库存策略：对冲工具「${w.hedge_tool || "—"}」；最低水位 A=${w.min_level}；安全水位 C=${w.safety_level}；批次水位 B=${w.batch_level}；下界(A+C)=${w.lower}；上界(A+C+B)=${w.upper}`);
        L.push(`- 服务系数 ${w.service_factor != null ? (w.service_factor * 100).toFixed(1) + "%" : "—"}；需求波动 ${w.resp_volatility ?? "—"}`);
      } else L.push("- 库存策略：暂无");

      /* ④ 供需平衡 */
      L.push("\n## 四、供需平衡（毛需求/净需求）");
      if (self.demandRows.length) {
        for (const d of self.demandRows) {
          L.push(`- ${self.actualMonth(d.rolling_month)}：销售预测 ${d.forecast_qty ?? "—"}，库存策略 ${d.inventory_qty ?? "—"}，毛需求 ${d.gross_qty ?? "—"}，未发订单 ${d.open_order_qty ?? "—"}，当前库存 ${d.onhand_qty ?? "—"}，在途工单 ${d.in_transit_qty ?? "—"}，净需求 ${d.net_qty ?? "—"}`);
        }
      } else L.push("- 暂无毛/净需求（版本未发布或未计算净需求）");

      /* ⑤ 计划与执行 */
      L.push("\n## 五、计划与执行");
      if (self.masterLatest.length) {
        L.push(`- 主计划（最新版）：${self.masterLatest.map((x) => `${self.actualMonth(x.rolling_month)} 入库 ${x.plan_qty}（v${x.plan_version}，最迟 ${x.latest_inbound_date || "—"}）`).join("；")}`);
      } else L.push("- 主计划：暂无");
      if (self.replenishPool.length) {
        L.push(`- 补库单：${self.replenishPool.map((p) => `${p.replenish_no}（${p.replenish_type}，${p.replenish_qty}，${p.status}，要求入库 ${p.required_inbound || "—"}）`).join("；")}`);
      } else L.push("- 补库单：暂无");
      if (self.outbound.length) {
        L.push(`- 出库计划：${self.outbound.map((o) => `${o.customer_no} ${o.qty}（${o.out_date || "—"}，${o.status}）`).join("；")}`);
      } else L.push("- 出库计划：暂无");

      /* ⑥ 库存推移与风险 */
      L.push("\n## 六、库存推移与风险");
      if (self.projRows.length) {
        const endBal = self.projRows[self.projRows.length - 1].balance;
        const alerts = self.projRows.filter((r) => r.alert_type && r.alert_type !== "无");
        const alertTypes = [...new Set(alerts.map((a) => a.alert_type))];
        L.push(`- 未来 ${self.projRows.length} 天推演：期末结存 ${endBal}；预警 ${alerts.length} 天${alertTypes.length ? `（${alertTypes.join("/")}）` : ""}`);
        if (self.waterStrategy) L.push(`- 水位参考：下界 ${self.waterStrategy.lower}，上界 ${self.waterStrategy.upper}`);
      } else L.push("- 库存推移：暂无推演数据");

      /* 分析指令 */
      L.push("\n## 请按以下 6 个维度输出分析结论：");
      L.push("1. **需求特征**：销量趋势（升/降/稳）、波动性（CV 高/低）、客户集中度、达成率健康度；");
      L.push("2. **预测质量**：当前预测方法是否匹配需求特征，拟合 SMAPE 是否可接受，异常信号；");
      L.push("3. **库存策略**：A/C/B 三层水位与服务水平目标是否自洽，对冲工具（库存 vs 速度）选择是否恰当；");
      L.push("4. **供需平衡**：未来 3 个月净需求是缺口还是富余，缺货/积压风险各几何；");
      L.push("5. **执行风险**：主计划/补库单/出库与需求是否匹配，库存推移是否穿越水位线；");
      L.push("6. **综合建议**：按优先级给出 3~5 条可操作建议，每条一句话点明「问题 + 动作」。");
      L.push("\n要求：结论精炼、只说判断和建议、不重复罗列数据；用中文；若某维度缺数据，明确写「该维度数据不足，无法判断」。");

      return L.join("\n");
    },

    /* 触发右栏 Agent 分析（process.js 同款事件流：先开栏，再注入 prompt） */
    analyze() {
      if (!self.material) return;
      const prompt = self.buildAnalysisPrompt();
      window.dispatchEvent(new CustomEvent("fde:agent-open"));
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent("fde:agent-prompt", { detail: { message: prompt } }));
      }, 250);
    },

    /* ── 全量加载（选物料后触发） ── */
    async loadAll() {
      if (!self.material) return;
      self.loading = true;
      self.resetSections();
      const m = self.material;
      const fv = self.fv;

      const calls = [
        /* ① 基础数据 */
        svc("md_material", "get", { material_no: m }, { quiet: true }).catch(() => null),
        svc("md_project_part", "list_by_material", { material_no: m }, { quiet: true }).catch(() => []),
        svc("md_part_replace", "list", { old_material_no: m, page: 1, size: 50 }, { quiet: true }).catch(() => ({ items: [] })),
        svc("md_part_replace", "list", { new_material_no: m, page: 1, size: 50 }, { quiet: true }).catch(() => ({ items: [] })),
        svc("md_breakpoint", "list", { old_material_no: m, page: 1, size: 50 }, { quiet: true }).catch(() => ({ items: [] })),
        svc("md_breakpoint", "list", { new_material_no: m, page: 1, size: 50 }, { quiet: true }).catch(() => ({ items: [] })),
        svc("md_breakpoint", "trace", { new_material_no: m }, { quiet: true }).catch(() => []),
        /* ② 销售历史（全量列表 → 按期聚合；达成率按物料） */
        svc("sales_history", "list", { material_no: m }, { quiet: true }).catch(() => ({ items: [] })),
        svc("attainment", "list", { material_no: m, page: 1, size: 50 }, { quiet: true }).catch(() => ({ items: [] })),
      ];
      const settled = await Promise.allSettled(calls);
      const [matInfo, projParts, rpOld, rpNew, bpOld, bpNew, bpChain,
        histList, attainment] = settled.map((s) => pick(s, null));

      self.materialInfo = matInfo;
      self.bpChain = Array.isArray(bpChain) ? bpChain : [];

      /* 合并替换/断点双向（精确过滤 material_no，因为后端 list 是 LIKE 模糊） */
      const rpOldItems = ((rpOld && rpOld.items) || []).filter((x) => x.old_material_no === m);
      const rpNewItems = ((rpNew && rpNew.items) || []).filter((x) => x.new_material_no === m);
      self.replacements = [...rpOldItems, ...rpNewItems];
      const bpOldItems = ((bpOld && bpOld.items) || []).filter((x) => x.old_material_no === m);
      const bpNewItems = ((bpNew && bpNew.items) || []).filter((x) => x.new_material_no === m);
      self.breakpoints = [...bpOldItems, ...bpNewItems];

      /* 历史：按期聚合（period 升序），得出图表点集 */
      const histRows = (histList && histList.items) || [];
      const byPeriod = {};
      for (const r of histRows) {
        if (!r || !r.period) continue;
        byPeriod[r.period] = (byPeriod[r.period] || 0) + (Number(r.qty) || 0);
      }
      self.histPoints = Object.keys(byPeriod).sort().map((period) => ({ period, qty: byPeriod[period] }));
      self.attainment = (attainment && attainment.items) || [];

      /* 补项目详情（list_by_material 只给 project_no/usage，需再 get 拿阶段/车型/份额） */
      const projNos = (Array.isArray(projParts) ? projParts : []).map((p) => p.project_no).filter(Boolean);
      const projPartsMap = {};
      for (const p of (Array.isArray(projParts) ? projParts : [])) projPartsMap[p.project_no] = p;
      const projDetails = await Promise.all(
        projNos.map((pn) => svc("md_project", "get", { project_no: pn }, { quiet: true }).catch(() => null))
      );
      self.projects = projDetails.map((d, i) => ({
        project_no: projNos[i],
        usage: (projPartsMap[projNos[i]] || {}).usage || "",
        project_name: (d && d.project_name) || "",
        stage: (d && d.stage) || "",
        sop_date: (d && d.sop_date) || "",
        eop_date: (d && d.eop_date) || "",
        veh_model: (d && d.veh_model) || "",
        share: d && d.share != null ? d.share : "",
      }));

      /* ③ ④ ⑤ ⑥ ⑦ 其余分区 */
      await self.loadRest();

      self.loading = false;
      Alpine.nextTick(() => self.renderCharts());
    },

    /* 版本相关 + 其余分区（③ 预测/策略、④ 毛净需求、⑤ 入库计划、⑥ 出库、⑦ 库存推移） */
    async loadRest() {
      if (!self.material) return;
      const m = self.material;
      const fv = self.fv;

      const settled = await Promise.allSettled([
        /* ③ 预测与库存策略 */
        fv ? svc("sales_forecast", "get_summary", { version_no: fv, material_no: m }, { quiet: true }).catch(() => []) : Promise.resolve([]),
        fv ? svc("sales_forecast", "list", { version_no: fv, material_no: m, page: 1, size: 200 }, { quiet: true }).catch(() => ({ items: [] })) : Promise.resolve({ items: [] }),
        fv ? svc("inventory_strategy", "get", { version_no: fv, material_no: m }, { quiet: true }).catch(() => null) : Promise.resolve(null),
        svc("strategy_fitting", "list", { material_no: m, page: 1, size: 20 }, { quiet: true }).catch(() => ({ items: [] })),
        svc("strategy_fitting", "get_latest", { material_no: m }, { quiet: true }).catch(() => null),
        /* ④ 毛/净需求 */
        fv ? svc("demand", "list", { version_no: fv, material_no: m, page: 1, size: 50 }, { quiet: true }).catch(() => ({ items: [] })) : Promise.resolve({ items: [] }),
        /* ⑤ 入库计划 */
        fv ? svc("master_plan", "get_latest", { version_no: fv, material_no: m }, { quiet: true }).catch(() => []) : Promise.resolve([]),
        svc("demand_pool", "list", { material_no: m, page: 1, size: 50 }, { quiet: true }).catch(() => ({ items: [] })),
        /* ⑥ 出库计划 */
        svc("outbound_plan", "list", { material_no: m, page: 1, size: 50 }, { quiet: true }).catch(() => ({ items: [] })),
        /* ⑦ 库存推移 */
        svc("inventory_projection", "list", { material_no: m, page: 1, size: 200 }, { quiet: true }).catch(() => ({ items: [] })),
        fv ? svc("inventory_strategy", "get_water_level", { version_no: fv, material_no: m }, { quiet: true }).catch(() => null) : Promise.resolve(null),
      ]);
      const [fcSummary, fcDetail, waterStrategy, fittingHist, fitLatest,
        demandRows, masterLatest, replenishPool, outbound, projRows, projWater] = settled.map((s) => pick(s, null));

      self.fcSummary = Array.isArray(fcSummary) ? fcSummary : [];
      self.fcDetail = (fcDetail && fcDetail.items) || [];
      self.waterStrategy = waterStrategy;
      self.fittingHist = ((fittingHist && fittingHist.items) || [])
        .filter((x) => x.material_no === m);
      self.fitLatest = fitLatest;
      if (fitLatest && fitLatest.detail_json) {
        try {
          const det = typeof fitLatest.detail_json === "string" ? JSON.parse(fitLatest.detail_json) : fitLatest.detail_json;
          self.fitCandidates = (det && det.candidates) || [];
          const win = self.fitCandidates[0];
          self.fitSteps = (win && win.steps) || [];
        } catch {
          self.fitCandidates = []; self.fitSteps = [];
        }
      } else {
        self.fitCandidates = []; self.fitSteps = [];
      }
      self.demandRows = (demandRows && demandRows.items) || [];
      self.masterLatest = Array.isArray(masterLatest) ? masterLatest : [];
      self.replenishPool = (replenishPool && replenishPool.items) || [];
      self.outbound = (outbound && outbound.items) || [];
      self.projRows = (projRows && projRows.items) || [];
      self.projWater = projWater;
    },

    resetSections() {
      self.projects = []; self.replacements = []; self.breakpoints = []; self.bpChain = [];
      self.histPoints = []; self.attainment = [];
      self.fcSummary = []; self.fcDetail = []; self.waterStrategy = null; self.fittingHist = [];
      self.fitLatest = null; self.fitCandidates = []; self.fitSteps = [];
      self.demandRows = [];
      self.masterLatest = []; self.replenishPool = [];
      self.outbound = [];
      self.projRows = []; self.projWater = null;
    },

    /* ── ECharts 渲染（销售历史 + 库存推移，复用 histPoints / projRows / projWater，零新增后端） ── */
    renderCharts() {
      this.renderHistoryChart();
      this.renderProjChart();
      this.renderFitChart();
    },
    renderHistoryChart() {
      const el = document.getElementById("m360HistoryChart");
      const E = window.echarts;
      if (!el || !E) return;
      if (E.getInstanceByDom(el)) E.getInstanceByDom(el).dispose();
      const pts = self.histPoints || [];
      if (!pts.length) return;
      const chart = E.init(el);
      chart.setOption({
        grid: { top: 30, left: 56, right: 24, bottom: 40 },
        tooltip: { trigger: "axis" },
        xAxis: { type: "category", data: pts.map(p => p.period), boundaryGap: false },
        yAxis: { type: "value", name: "销量" },
        series: [{ type: "line", smooth: true, data: pts.map(p => p.qty),
          areaStyle: { opacity: .08 }, lineStyle: { color: "#175e54", width: 2 },
          itemStyle: { color: "#175e54" } }],
      });
    },
    renderProjChart() {
      const el = document.getElementById("m360ProjChart");
      const E = window.echarts;
      if (!el || !E) return;
      if (E.getInstanceByDom(el)) E.getInstanceByDom(el).dispose();
      const rows = self.projRows || [];
      if (!rows.length) return;
      const chart = E.init(el);
      const w = self.projWater || self.waterStrategy;
      const breach = ["缺货", "击穿最低", "击穿安全"];
      chart.setOption({
        grid: { top: 44, left: 60, right: 24, bottom: 44 },
        tooltip: { trigger: "axis" },
        legend: { top: 8 },
        xAxis: { type: "category", data: rows.map(r => r.biz_date), boundaryGap: false,
          axisLabel: { rotate: 45, fontSize: 10 } },
        yAxis: { type: "value", name: "库存水位", scale: true },
        series: [
          { name: "库存水位", type: "line", smooth: true, showSymbol: false,
            data: rows.map(r => Number(r.balance)),
            areaStyle: { opacity: .08 }, lineStyle: { color: "#d97706", width: 2 },
            itemStyle: { color: "#d97706" },
            markLine: { symbol: "none", silent: true,
              data: w ? [
                { yAxis: w.min_level, name: "最低 A", lineStyle: { color: "#ef4444", type: "dashed" } },
                { yAxis: w.lower, name: "下界 A+C", lineStyle: { color: "#d97706", type: "dashed" } },
                { yAxis: w.upper, name: "上界 A+C+B", lineStyle: { color: "#0ea5e9", type: "dashed" } },
              ] : [],
              label: { position: "insideEndTop", formatter: "{b}" } } },
          { name: "击穿点", type: "scatter", symbolSize: 9,
            data: rows.filter(r => breach.includes(r.alert_type))
                      .map(r => [r.biz_date, Number(r.balance)]),
            itemStyle: { color: "#dc2626" } },
        ],
      });
    },

    /* 拟合过程曲线（winner 逐月 实际 vs 预测，浅色主题 · 复用 hist 图色板） */
    renderFitChart() {
      const el = document.getElementById("m360FitChart");
      const E = window.echarts;
      if (!el || !E) return;
      if (E.getInstanceByDom(el)) E.getInstanceByDom(el).dispose();
      const steps = self.fitSteps || [];
      if (!steps.length) return;
      const chart = E.init(el);
      chart.setOption({
        grid: { top: 30, left: 56, right: 24, bottom: 40 },
        tooltip: { trigger: "axis" },
        legend: { top: 4 },
        xAxis: { type: "category", data: steps.map(s => s.period), boundaryGap: false,
          axisLabel: { rotate: 45, fontSize: 10 } },
        yAxis: { type: "value", name: "需求", scale: true },
        series: [
          { name: "实际", type: "line", smooth: true, showSymbol: true,
            data: steps.map(s => Number(s.actual)),
            lineStyle: { color: "#175e54", width: 2 } },
          { name: "预测", type: "line", smooth: true, showSymbol: true,
            data: steps.map(s => Number(s.pred)),
            lineStyle: { color: "#d97706", width: 2, type: "dashed" } },
        ],
      });
    },

    /* ── 工具 ── */
    pct(v) {
      if (v == null || v === "") return "—";
      const p = Number(v) * 100;
      return (Number.isInteger(p) ? String(p) : p.toFixed(1)) + "%";
    },
  });
  return self;
}
