/* app/nasa_pms/risk/view.js —— 风险台账（与后端 risk.py 同文件夹）
 *
 * 数据来源类型：**独立创建** —— 保留「新建风险」入口（对应 create）。
 * 交互要点：风险等级**恒为推导只读值**（可能性 × 后果，BR-01）——新建/编辑表单里都没有等级控件，
 * 等级只能经「评估」动作改变；关闭必须给处置结论（BR-02），等级为高/严重的不可选「接受」（BR-03）；
 * 终态（已关闭 / 已接受）不再显示任何动作按钮（BR-06）。
 */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "risk", name: "风险", ic: "⚠",
  title: "风险台账", crumb: "识别 · 评估 · 缓解 · 关闭",
  order: 620,
};

/* 字典：业务名取自《术语表.md》；类别词源为材料 §6.4「Key Concepts in Risk Management」 */
const CATEGORIES = [["technical", "技术风险"], ["cost", "成本风险"], ["schedule", "进度风险"],
                    ["programmatic", "程序性风险"], ["safety", "安全风险"]];
const LEVELS = [["low", "低"], ["medium", "中"], ["high", "高"], ["critical", "严重"]];
const DIMS = [[1, "1 · 极低"], [2, "2 · 低"], [3, "3 · 中"], [4, "4 · 高"], [5, "5 · 极高"]];
const DISPOSITIONS = [["mitigated", "缓解完成"], ["transferred", "转移"], ["accepted", "接受"]];
/* 状态徽章用平台设计系统的 `.st` + `.st-<色>`（`design-plus/view-convention/design-system.md`：
   green=完成 / amber=进行中 / red=失败退回 / blue=流程中 / slate=中性）。
   ⚠ 不要写 `var(--ok)` / `var(--red)` 之类的内联色 —— 设计令牌里**没有**这两个变量，
   浏览器会静默回落成继承色，页面不报错但颜色全错（requirement 样板即踩此坑）。 */
const STATUS = {
  identified: ["识别", "st-slate"],
  analyzing: ["分析中", "st-amber"],
  mitigating: ["缓解中", "st-amber"],
  closed: ["已关闭", "st-green"],
  accepted: ["已接受", "st-slate"],
};
const LEVEL_CLS = { low: "st-green", medium: "st-amber", high: "st-red", critical: "st-red" };
const TERMINAL = ["closed", "accepted"];      // 终态：BR-06 之后一律不得再改
const HIGH_LEVELS = ["high", "critical"];     // BR-03：不得以「接受」收尾

const MODE_TITLE = { view: "风险详情", edit: "编辑风险", assess: "重评风险等级",
                     mitigate: "登记缓解措施", close: "关闭风险" };

export default function pageRisk() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    // 筛选（与后端 list 的可过滤参数一一对应）
    f_category: "", f_status: "", f_level: "",
    // 详情 / 编辑 / 评估 / 缓解 / 关闭 —— 同一个模态，mode 切换
    modal: { open: false, loading: false, mode: "view", d: null, saving: false,
             assess: { likelihood: "", consequence: "" },
             mit: { text: "" },
             close: { disposition: "", note: "" } },
    // 新建
    form: { open: false, saving: false, d: null },
    // 「受影响需求」下拉 —— 跨应用 requirement.list（架构：risk → requirement.list）
    reqs: [],
    // 「责任人」候选 —— 跨应用 stakeholder.list（**值仍是文本姓名**，不落 sh_no；见应用详设 §6.3）
    owners: [],

    categories: CATEGORIES, levels: LEVELS, dims: DIMS, dispositions: DISPOSITIONS,

    categoryName(v) { const c = CATEGORIES.find((x) => x[0] === v); return c ? c[1] : (v || "—"); },
    levelName(v) { const l = LEVELS.find((x) => x[0] === v); return l ? l[1] : "—"; },
    levelCls(v) { return LEVEL_CLS[v] || "st-slate"; },
    dimName(v) { const d = DIMS.find((x) => x[0] === Number(v)); return d ? d[1] : "—"; },
    dispositionName(v) { const d = DISPOSITIONS.find((x) => x[0] === v); return d ? d[1] : (v || "—"); },
    /** 终态（已关闭 / 已接受）—— 与服务端 `_check_mutable`（BR-06）同口径。
     *  ⚠ 前端必须据此**隐藏「编辑」入口**：服务端会拒，UI 却给按钮，用户会撞一个永远存不下的保存。 */
    frozen(d) { return !!d && (d.status === "closed" || d.status === "accepted"); },
    statusName(v) { return (STATUS[v] || [v, ""])[0]; },
    statusCls(v) { return (STATUS[v] || ["", "st-slate"])[1]; },
    dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; },
    /** 终态（已关闭 / 已接受）：BR-06 */
    terminal(d) { return !!d && TERMINAL.indexOf(d.status) >= 0; },
    /** 等级为「高」/「严重」：BR-03 */
    highOrAbove(d) { return !!d && HIGH_LEVELS.indexOf(d.risk_level) >= 0; },
    /** 关闭时哪些处置结论不可选 —— BR-02（缓解完成须已登记缓解措施）/ BR-03（高等级不得接受） */
    optDisabled(code) {
      const d = self.modal.d;
      if (!d) return false;
      if (code === "accepted" && self.highOrAbove(d)) return true;
      if (code === "mitigated" && !d.mitigation) return true;
      return false;
    },
    modalTitle() { return MODE_TITLE[self.modal.mode] || "风险"; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("risk", "list", {
        category: self.f_category || undefined,
        status: self.f_status || undefined,
        risk_level: self.f_level || undefined,
        ...q,
      }));
      await self.loadReqs();
      await self.loadOwners();
      await self.list.load();
    },

    /** 「受影响需求」下拉：跨应用只读调用 —— 失败静默兜底为空列表（不喷 toast） */
    async loadReqs() {
      try {
        const r = await svc("requirement", "list", {}, { quiet: true });
        self.reqs = (r && r.items) || [];
      } catch { self.reqs = []; }
    },

    /** 「责任人」候选：同 `requirement` —— 只做候选、值仍是文本（全组一致口径） */
    async loadOwners() {
      try {
        const r = await svc("stakeholder", "list", {}, { quiet: true });
        self.owners = (r && r.items) || [];
      } catch { self.owners = []; }
    },

    search() { self.list.load(1); },

    /* 详情 / 编辑 / 评估 / 缓解 / 关闭：同一个模态，mode 切换 */
    async openDetail(row, mode) {
      const m = mode || "view";
      self.modal = { open: true, loading: true, mode: m, d: null, saving: false,
                     assess: { likelihood: "", consequence: "" },
                     mit: { text: "" }, close: { disposition: "", note: "" } };
      try {
        const d = await svc("risk", "get", { risk_no: row.risk_no });
        if (d) d.req_no = d.req_no || "";             // 弱引用可空 → 下拉用空串表示「不关联」
        self.modal.assess = { likelihood: (d && d.likelihood) || "", consequence: (d && d.consequence) || "" };
        self.modal.mit = { text: (d && d.mitigation) || "" };
        self.modal.d = d;
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    async saveEdit() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        // ⚠ 载荷里**没有**风险等级 / 可能性 / 后果 —— 本应用没有直接写等级的入口（BR-01）
        await svc("risk", "update", {
          risk_no: d.risk_no, title: d.title, statement: d.statement,
          category: d.category, owner: d.owner, req_no: d.req_no || "",
        });
        toast("已保存");
        self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /** F-3：可能性与后果都要选才可提交（等级必须成对推导） */
    canAssess() {
      const a = self.modal.assess;
      return a.likelihood !== "" && a.consequence !== "";
    },
    async saveAssess() {
      self.modal.saving = true;
      try {
        await svc("risk", "assess", {
          risk_no: self.modal.d.risk_no,
          likelihood: Number(self.modal.assess.likelihood),
          consequence: Number(self.modal.assess.consequence),
        });
        toast("已重评等级");
        self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    canMitigate() { return !!self.modal.mit.text.trim(); },
    async saveMitigate() {
      self.modal.saving = true;
      try {
        await svc("risk", "mitigate", { risk_no: self.modal.d.risk_no,
                                        mitigation: self.modal.mit.text.trim() });
        toast("已登记缓解措施");
        self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /** F-2：必须选中一个**可选**的处置结论才能关闭 */
    canClose() {
      const code = self.modal.close.disposition;
      return !!code && !self.optDisabled(code);
    },
    async saveClose() {
      self.modal.saving = true;
      try {
        await svc("risk", "close", { risk_no: self.modal.d.risk_no,
                                     disposition: self.modal.close.disposition,
                                     note: self.modal.close.note || undefined });
        toast("已关闭风险");
        self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /* 新建 */
    openForm() {
      self.form = { open: true, saving: false, d: {
        title: "", statement: "", category: "technical",
        likelihood: "", consequence: "", req_no: "", owner: "" } };
    },
    closeForm() { self.form.open = false; },
    /** 标题 / 风险情景 / 类别 三者齐备才可提交 */
    canSubmit() {
      const d = self.form.d;
      return !!d && !!d.title.trim() && !!d.statement.trim() && !!d.category;
    },
    async saveForm() {
      const d = self.form.d;
      self.form.saving = true;
      try {
        await svc("risk", "create", {
          title: d.title.trim(), statement: d.statement.trim(), category: d.category,
          likelihood: d.likelihood === "" ? undefined : Number(d.likelihood),
          consequence: d.consequence === "" ? undefined : Number(d.consequence),
          req_no: d.req_no || undefined,
          owner: d.owner || undefined,
        });
        toast("已识别新风险");
        self.form.open = false;
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.form.saving = false; }
    },
  });
  return self;
}
