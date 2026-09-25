/* app/nasa_pms/configuration_item/view.js —— 配置项台账（与后端 configuration_item.py 同文件夹）
 *
 * 数据来源类型：**独立创建** —— 保留「登记配置项」入口（对应 create）。
 * 交互要点：版本只读（只能经「版本变更」递增，BR-01/BR-03）；已发布时名称/类型/责任人置灰，
 * 须填变更号才解锁（BR-02）；归档需二次确认且文案说明"记录保留 + 终态不可再改"。
 * 动作按钮按状态显隐（状态机：draft → controlled → released → archived）。
 */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "configuration_item", name: "配置项", ic: "📦",
  title: "配置项台账", crumb: "受控 · 发版 · 基线 · 版本递增",
  order: 630,
};

/* 字典：后端约束见 CONVENTION，业务名取自《术语表.md》 */
const TYPES = [["hardware", "硬件"], ["software", "软件"], ["document", "文档"],
               ["model", "模型"], ["data", "数据"]];
/* 材料 §6.5.1.2.2 的四条基线（随阶段演进：功能 → 分配 → 产品 → 部署） */
const BASELINES = [["functional", "功能基线"], ["allocated", "分配基线"],
                   ["product", "产品基线"], ["as_deployed", "部署基线"]];
const STATUS = {
  draft: ["草稿", "var(--muted)"],
  controlled: ["受控", "var(--amber)"],
  released: ["已发布", "var(--ok)"],
  archived: ["已归档", "var(--line)"],
};

export default function pageConfigurationItem() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    // 筛选
    f_type: "", f_status: "", f_baseline: "",
    // 详情 / 编辑
    modal: { open: false, loading: false, mode: "view", d: null, changeNo: "", saving: false },
    // 登记
    form: { open: false, d: null, saving: false },
    // 候选集 —— 跨应用只读（**值仍是文本**，不动契约）：变更号 ← change_request、责任人 ← stakeholder
    changes: [],
    owners: [],
    // 版本变更 / 纳入基线（两个小动作模态，字段少，合一个状态对象）
    // cur = 打开模态那一刻的当前版本，用于 F-8 的「新版本必须 > 当前版本」判定
    act: { open: false, kind: "", ci_no: "", name: "", cur: 0, nv: "", changeNo: "",
           baseline: "product", baselineVer: "", saving: false },

    types: TYPES, baselines: BASELINES,

    typeName(v) { const t = TYPES.find((x) => x[0] === v); return t ? t[1] : (v || "—"); },
    baselineName(v) { const b = BASELINES.find((x) => x[0] === v); return b ? b[1] : (v || "—"); },
    statusName(v) { return (STATUS[v] || [v, ""])[0]; },
    statusColor(v) { return (STATUS[v] || ["", ""])[1]; },
    /** 已发布：内容冻结，须带变更号才解锁（BR-02）；已归档为终态，永不解锁 */
    locked(d) { return d && (d.status === "released" || d.status === "archived"); },
    dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; },
    vtag(v) { return (v === null || v === undefined || v === "") ? "—" : ("v" + v); },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("configuration_item", "list", {
        ci_type: self.f_type || undefined,
        status: self.f_status || undefined,
        baseline: self.f_baseline || undefined,
        ...q,
      }));
      await self.loadCandidates();
      await self.list.load();
    },

    /** 变更号候选（`change_request` 单据号）：**只做候选、值仍是文本**（后端只校验非空，BR-02/BR-03）。
     * 跨应用只读、失败静默兜底为空列表。 */
    async loadChanges() {
      try {
        const r = await svc("change_request", "list", {}, { quiet: true });
        self.changes = (r && r.items) || [];
      } catch { self.changes = []; }
    },

    /** 责任人候选（`stakeholder` 主数据）：**只做候选、值仍是文本姓名** ——
     * 不落 `sh_no` 是有意的：全组 `owner` 都是文本口径，单页上外键会造成"同一件事两种口径"。
     * 失败静默兜底为空列表（不喷 toast）。 */
    async loadOwners() {
      try {
        const r = await svc("stakeholder", "list", {}, { quiet: true });
        self.owners = (r && r.items) || [];
      } catch { self.owners = []; }
    },

    /** 两个候选集一起拉（互不依赖，并发） */
    async loadCandidates() {
      await Promise.all([self.loadChanges(), self.loadOwners()]);
    },

    search() { self.list.load(1); },

    /* 详情 / 编辑：同一个模态，mode 切换 */
    async openDetail(row, mode) {
      self.modal = { open: true, loading: true, mode: mode || "view", d: null, changeNo: "", saving: false };
      try {
        self.modal.d = await svc("configuration_item", "get", { ci_no: row.ci_no });
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    async saveEdit() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        // 已发布：必须带变更号（BR-02）；带了才允许改内容
        const payload = { ci_no: d.ci_no };
        if (!self.locked(d) || self.modal.changeNo) {
          payload.name = d.name;
          payload.ci_type = d.ci_type;
          payload.owner = d.owner;
        }
        if (self.modal.changeNo) payload.change_no = self.modal.changeNo;
        await svc("configuration_item", "update", payload);
        toast("已保存");
        self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /* 登记配置项 */
    openForm() {
      self.form = { open: true, saving: false, d: {
        name: "", ci_type: "", owner: "" } };
    },
    closeForm() { self.form.open = false; },
    /** F-1：提交按钮可用性 —— 名称与类型必填（类型不给默认值，须显式选择，BR-05 才落得实） */
    canSubmit() {
      const d = self.form.d;
      return !!(d.name.trim() && d.ci_type);
    },
    async saveForm() {
      const d = self.form.d;
      self.form.saving = true;
      try {
        await svc("configuration_item", "create", {
          name: d.name.trim(), ci_type: d.ci_type, owner: d.owner || undefined,
        });
        toast("已登记配置项（草稿 · v1）");
        self.form.open = false;
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.form.saving = false; }
    },

    /* ── 状态机动作（F-9：按钮按状态显隐）────────────────── */

    /** 提交受控：草稿 → 受控 */
    async control(row) {
      try {
        await svc("configuration_item", "control", { ci_no: row.ci_no });
        toast("已提交受控");
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    /** 发版：受控 → 已发布（非首次发版后端会要求变更号，BR-03） */
    async release(row) {
      const ref = row.released_ver ? `（已有发布版本 v${row.released_ver}，本次属于版本变更）` : "";
      if (!confirm(`确定把配置项 ${row.ci_no} 发版？当前版本 v${row.version} 将冻结为已发布版本${ref}。`)) return;
      try {
        await svc("configuration_item", "release", { ci_no: row.ci_no });
        toast("已发版");
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },

    /** 打开「版本变更」模态（F-8） */
    openBump(row) {
      self.act = { open: true, kind: "bump", ci_no: row.ci_no, name: row.name,
                   cur: Number(row.version || 0), nv: String(Number(row.version || 0) + 1),
                   changeNo: "", baseline: "product", baselineVer: "", saving: false };
    },
    /** 打开「纳入基线」模态（F-8 同构） */
    openBaseline(row) {
      self.act = { open: true, kind: "baseline", ci_no: row.ci_no, name: row.name,
                   cur: Number(row.version || 0), nv: "", changeNo: "",
                   baseline: row.baseline || "product",
                   baselineVer: row.baseline_ver || "", saving: false };
    },
    closeAct() { self.act.open = false; },
    /** F-8：版本变更须「新版本号大于当前版本」（BR-01）且变更号必填（BR-03）；
        「纳入基线」只要求基线类型已选（BR-03 的变更号只约束版本变更） */
    canAct() {
      const a = self.act;
      if (a.kind !== "bump") return !!a.baseline;
      if (!a.changeNo.trim()) return false;
      const nv = parseInt(a.nv, 10);
      return Number.isFinite(nv) && nv > Number(a.cur || 0);
    },
    async saveAct() {
      const a = self.act;
      a.saving = true;
      try {
        if (a.kind === "bump") {
          // 版本变更须带已批准的变更请求号（BR-03）；成功后状态回落「受控」
          await svc("configuration_item", "bump_version", {
            ci_no: a.ci_no, new_version: parseInt(a.nv, 10), change_no: a.changeNo.trim(),
          });
          toast("版本已变更（状态回落为受控，待重新发版）");
        } else {
          await svc("configuration_item", "assign_baseline", {
            ci_no: a.ci_no, baseline: a.baseline, baseline_ver: a.baselineVer || undefined,
          });
          toast("已纳入基线");
        }
        a.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { a.saving = false; }
    },

    /* 归档：二次确认，文案强调记录保留 + 终态不可再改 */
    async archive(row) {
      if (!confirm(`确定把配置项 ${row.ci_no}（v${row.version}）归档？\n\n`
        + `记录会保留 —— 归档后**不能**再修改、变更版本或纳入基线（终态）。`)) return;
      try {
        await svc("configuration_item", "archive", { ci_no: row.ci_no });
        toast("已归档（记录保留）");
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },
  });
  return self;
}
