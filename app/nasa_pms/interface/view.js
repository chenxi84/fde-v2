/* app/nasa_pms/interface/view.js —— 接口台账（与后端 interface.py 同文件夹）
 *
 * ⚠ 这里的「接口」是**系统/分系统之间的接口约定（ICD）**（材料 §6.3 Interface Management
 *   + 附录 L Interface Requirements），不是代码里的 API 接口。
 *
 * 数据来源类型：**独立创建** —— 保留「定义接口」入口（对应 create）。
 * 交互要点：
 *   · **两端（提供方 / 使用方）是接口的身份**（材料 §6.3.1.2.2 的 origin / destination）：
 *     创建时两项必填且**不能相同**；**一旦发布就不可再改**（改端等于换一条接口，BR-05）——
 *     与「配置项页填变更号解锁」「评审页一律只读」都不同，这是本页自己的锁定条件；
 *   · **约定内容（ICD）** 同样只在「定义中」可改：已定版后要改内容属于接口变更，
 *     必须走「版本变更」（revise，带新版本 + 原因），这正是「版本变更必须通知两端」的入口；
 *   · 「版本变更」是**唯一**改版本的入口，也是**唯一**产生通知记录的地方 ——
 *     通知与版本号同事务落库，前端不做二次拼装（卡片 I-2）；
 *   · 「变更通知台账」是**查询视图**（list_changes），不是第二个聚合。
 */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "interface",
  name: "接口",
  ic: "⇄",
  title: "接口台账",
  crumb: "定义中 · 已发布 · 变更中 · 已冻结",
  order: 690,
  // 列表渲染**全字段列**（CONVENTION §7：list 返回全字段）；这三列非关键，默认隐藏，
  // 经平台「列设置」按需开启（与同组 review 页同口径）
  col_default_hidden: "约定内容,冻结说明,所属项目",
};

/* 字典：业务名逐字取自《术语表.md》（已收「接口控制文档（ICD）」），
   IRD / IDD / ICP 取自材料 §6.3.1.3「Outputs」（本步回填，见 新增术语.md）。
   ⚠ 枚举下拉一律用**静态 `<option>`**：`x-model` + `x-for` 生成选项会在回填时静默停在第一项
   （同组实测踩过）—— 只有「关联配置项」这种**数据驱动**的选项才用 x-for。 */
const IF_TYPES = [
  ["icd", "接口控制文档（ICD）"],
  ["ird", "接口需求文档（IRD）"],
  ["idd", "接口定义文档（IDD）"],
  ["icp", "接口控制计划（ICP）"],
];
const STATUS = {
  defined: ["定义中", "st-slate"],
  released: ["已发布", "st-blue"],
  changing: ["变更中", "st-amber"],
  frozen: ["已冻结", "st-green"],
};
const PARTY = { provider: ["提供方", "st-blue"], consumer: ["使用方", "st-teal"] };
const ACTION = { release: "首次发布", revise: "版本变更" };
/* BR-07：已冻结是**硬终态**（改 / 发布 / 变更 / 再冻结全拒）——
   前端表现是所有写入口消失；已定版（非「定义中」）则是**部分冻结**（两端与 ICD 内容锁）。 */
const TERMINAL = "frozen";

export default function pageInterface() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    cis: [],                                   // 关联配置项选项（跨应用只读调用，失败静默兜底）
    // 筛选（与后端 list 的可过滤参数一一对应）
    f_type: "", f_status: "", f_provider: "", f_consumer: "",
    // 详情 / 编辑（同一模态，mode 切换）
    modal: { open: false, loading: false, mode: "view", d: null, saving: false },
    // 定义接口
    form: { open: false, d: null, saving: false },
    // 「责任人」候选 —— 跨应用 stakeholder.list（**值仍是文本**，不落 sh_no）
    owners: [],
    // 版本变更（改版本号 + 原因 + 选填的约定内容）
    rm: { open: false, if_no: "", name: "", cur: "", new_version: "", reason: "",
          icd_content: "", saving: false },
    // 变更通知台账（跨接口查询视图 list_changes）
    sum: { party: "", items: [], total: 0, loading: false },

    types: IF_TYPES,

    /* ── 展示助手 ──────────────────────────────────── */
    typeName(v) { const t = IF_TYPES.find((x) => x[0] === v); return t ? t[1] : (v || "—"); },
    /** 台账列里类型用**码**（ICD）+ 中文全名两行；选择器里用全名（业务名唯一来源是术语表） */
    typeCode(v) { return v ? String(v).toUpperCase() : "—"; },
    statusName(v) { return (STATUS[v] || [v, ""])[0]; },
    statusCls(v) { return (STATUS[v] || ["", "st-slate"])[1]; },
    partyName(v) { return (PARTY[v] || [v, ""])[0]; },
    partyCls(v) { return (PARTY[v] || ["", "st-slate"])[1]; },
    actionName(v) { return ACTION[v] || (v || "—"); },
    /** 版本：未定版时显示「未定版」而不是空白（定义中的接口本就还没有版本） */
    versionText(d) { return self.dash(d && d.version) === "—" ? "未定版" : d.version; },
    dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; },
    /** 版本变更历史行里的「版本」：A→B（首次发布没有旧版本，只显示新版本） */
    versionPair(c) {
      return c && c.old_version ? (c.old_version + " → " + c.new_version) : ("定版 " + (c.new_version || "—"));
    },

    /* ── 状态判定（模态里读 modal.d 一律走空安全 helper，模板不写裸取值）── */
    isStatus(d, s) { return !!d && d.status === s; },
    inStatus(d, list) { return !!d && list.indexOf(d.status) >= 0; },
    /** BR-05：只有「定义中」可以改两端与约定内容（已定版后要改须走版本变更） */
    canEditEnds(d) { return self.isStatus(d, "defined"); },
    /** BR-07：已冻结是硬终态 —— 没有任何写入口 */
    isFrozen(d) { return self.isStatus(d, TERMINAL); },
    frozenText() { return "已冻结（终态）—— 不能再修改、发布或变更版本（BR-07）"; },
    /** BR-09：只有已发布的接口能冻结（变更中要先完成变更） */
    canFreeze(d) { return self.isStatus(d, "released"); },
    /** 变更中 / 已发布都能「完成变更 / 发布」——但两种起因的语义不同，按钮文案分开 */
    releaseLabel(d) { return self.isStatus(d, "changing") ? "完成变更" : "发布"; },
    changesOf(d) { return (d && d.changes) || []; },

    async init() {
      // ⚠ 先把会被模板引用的响应式状态建好，再挂模板（模板一旦注入就立刻求值 `list.items`，
      //   此刻 list 还是 null 会喷 "reading 'items' of null"；见 pitfalls #37）
      const tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("interface", "list", {
        if_type: self.f_type || undefined,
        status: self.f_status || undefined,
        provider: self.f_provider || undefined,
        consumer: self.f_consumer || undefined,
        ...q,
      }));
      self.tpl = tpl;
      await self.loadOwners();
      await self.loadCis();
      await self.list.load();
      await self.loadChanges();
    },


    /** 责任人候选（`stakeholder` 主数据）：**只做候选、值仍是文本姓名**（不落 sh_no ——
     * 全组 `owner` 都是文本口径）；失败静默兜底为空列表。 */
    async loadOwners() {
      try {
        const r = await svc("stakeholder", "list", {}, { quiet: true });
        self.owners = (r && r.items) || [];
      } catch { self.owners = []; }
    },

    search() { self.list.load(1); },
    /** 主列表 + 通知台账一起刷新（任一动作都会影响两处：改版本会新增通知记录） */
    async reload() {
      await self.list.load(self.list.page);
      await self.loadChanges();
    },

    /** 关联配置项下拉的选项源：跨应用只读调用，失败静默兜底为空列表（同上组 change_request 页） */
    async loadCis() {
      try {
        const r = await svc("configuration_item", "list", {}, { quiet: true });
        self.cis = (r && r.items) || [];
      } catch { self.cis = []; }
    },

    /* ── 详情 / 编辑（同一模态）───────────────────────── */
    async openDetail(row, mode) {
      const m = mode || "view";
      self.modal = { open: true, loading: true, mode: m, d: null, saving: false };
      try {
        const d = await svc("interface", "get", { if_no: row.if_no });
        if (d) {
          // 可空文本字段统一成空串，编辑表单才不会显示 "null"（模板里对它们调 .trim()）
          d.icd_content = d.icd_content || "";
          d.ci_no = d.ci_no || "";
          d.owner = d.owner || "";
          d.project_no = d.project_no || "";
        }
        self.modal.d = d;
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    canSaveEdit() {
      const d = self.modal.d;
      if (!d) return false;
      if (!String(d.if_name || "").trim()) return false;
      // 两端只在定义中可写；可写时也不能为空、不能相同（BR-01 的前端镜像，后端仍是权威）
      if (self.canEditEnds(d)) {
        const p = String(d.provider || "").trim();
        const c = String(d.consumer || "").trim();
        if (!p || !c || p === c) return false;
      }
      return true;
    },

    async saveEdit() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        // 载荷里**没有** version / status：版本只能经「发布」与「版本变更」两步走（BR-03）
        const payload = {
          if_no: d.if_no,
          if_name: String(d.if_name).trim(),
          if_type: d.if_type,
          ci_no: d.ci_no || "",
          owner: d.owner || "",
          project_no: d.project_no || "",
        };
        /* ⚠ BR-05：两端与约定内容**只在「定义中」可写** —— 已定版后这三个参数**一个都不能发**
           （它们此刻是置灰的，把界面上的旧值一起发出去，后端会正确地拒掉整次保存 ——
            前端不该发一个自己知道会被拒的载荷。这是"只读字段不进写载荷"的硬规矩） */
        if (self.canEditEnds(d)) {
          payload.provider = String(d.provider || "").trim();
          payload.consumer = String(d.consumer || "").trim();
          payload.icd_content = d.icd_content || "";
        }
        await svc("interface", "update", payload);
        toast("已保存");
        self.modal.open = false;
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /* ── 状态机动作（F-3：按钮按状态显隐）────────────── */

    /** 发布：定义中 → 已发布（定版 A + 通知两端）；变更中 → 已发布（变更落实完成） */
    async release(row) {
      const label = self.releaseLabel(row);
      if (!confirm(`确认对接口 ${row.if_no} 执行「${label}」？\n\n首次发布会定版为 A，并把版本变更通知到两端。`)) return;
      try {
        await svc("interface", "release", { if_no: row.if_no });
        toast(self.isStatus(row, "changing") ? "变更已完成（接口回到已发布）" : "接口已发布（定版 A）");
        if (self.modal.open) self.modal.d = await svc("interface", "get", { if_no: row.if_no });
        await self.reload();
      } catch { /* api.js 已 toast */ }
    },

    /** 冻结：已发布 → 已冻结（硬终态，BR-09 要求先处于已发布） */
    async freeze(row) {
      if (!confirm(`确定冻结接口 ${row.if_no}？\n\n冻结后为终态：不能再修改、发布或变更版本。`)) return;
      try {
        await svc("interface", "freeze", { if_no: row.if_no });
        toast("接口已冻结");
        self.modal.open = false;
        await self.reload();
      } catch { /* api.js 已 toast */ }
    },

    /* ── 版本变更（唯一改版本的入口；也是唯一产生通知的地方）── */
    openRevise(row) {
      self.rm = { open: true, if_no: row.if_no, name: row.if_name || "",
                  cur: row.version || "", new_version: "", reason: "",
                  icd_content: "", saving: false };
    },
    closeRevise() { self.rm.open = false; },
    /** 下一个合法版本号（当前 A → B），只是给个便捷值，用户仍可自己改（后端才是权威） */
    nextVersion() {
      const cur = self.rm.cur || "";
      if (!/^[A-Z]$/.test(cur)) return "A";
      return cur === "Z" ? "" : String.fromCharCode(cur.charCodeAt(0) + 1);
    },
    /** F-4：新版本号必须是**单个大写字母**且**严格大于当前版本**；变更原因必填（BR-03 / BR-04） */
    canRevise() {
      const r = self.rm;
      const nv = String(r.new_version || "").trim();
      if (!/^[A-Z]$/.test(nv)) return false;
      if (!(nv > (r.cur || ""))) return false;
      return !!String(r.reason || "").trim();
    },
    reviseHint() {
      const r = self.rm;
      const nv = String(r.new_version || "").trim();
      if (!nv) return "新版本号必填：单个大写字母，且须大于当前版本";
      if (!/^[A-Z]$/.test(nv)) return "新版本号必须是单个大写字母（如 B / C）";
      if (!(nv > (r.cur || ""))) return `新版本号必须大于当前版本 ${r.cur || "未定版"}`;
      if (!String(r.reason || "").trim()) return "版本变更必须说明变更原因（BR-04）";
      return "";
    },
    async saveRevise() {
      const r = self.rm;
      r.saving = true;
      try {
        await svc("interface", "revise", {
          if_no: r.if_no, new_version: String(r.new_version).trim(),
          reason: String(r.reason).trim(),
          icd_content: r.icd_content || undefined,
        });
        toast("已发起版本变更并通知两端");
        r.open = false;
        await self.reload();
      } catch { /* api.js 已 toast */ } finally { r.saving = false; }
    },

    /* ── 变更通知台账（查询视图 list_changes）────────── */
    async loadChanges() {
      self.sum.loading = true;
      try {
        const r = await svc("interface", "list_changes", {
          party: self.sum.party || undefined, page: 1, size: 20,
        });
        self.sum.items = (r && r.items) || [];
        self.sum.total = (r && r.total) || 0;
      } catch { self.sum.items = []; self.sum.total = 0; } finally { self.sum.loading = false; }
    },
    setSumParty(p) { self.sum.party = p; return self.loadChanges(); },

    /* ── 定义接口 ──────────────────────────────────── */
    openForm() {
      self.form = { open: true, saving: false, d: {
        if_name: "", if_type: "", provider: "", consumer: "",
        icd_content: "", ci_no: "", owner: "", project_no: "" } };
    },
    closeForm() { self.form.open = false; },
    /** F-1：接口名称 / 类型 / 提供方 / 使用方 四项齐备**且两端不同**才可提交（类型不给默认值） */
    canSubmit() {
      const d = self.form.d;
      if (!d) return false;
      const p = String(d.provider || "").trim();
      const c = String(d.consumer || "").trim();
      return !!(String(d.if_name || "").trim() && d.if_type && p && c && p !== c);
    },
    submitHint() {
      const d = self.form.d;
      if (!d) return "";
      const p = String(d.provider || "").trim();
      const c = String(d.consumer || "").trim();
      if (p && c && p === c) return "接口的两端不能是同一个系统（BR-01）";
      return "接口名称 / 类型 / 提供方 / 使用方 四项必填（BR-01 / BR-02）";
    },
    async saveForm() {
      const d = self.form.d;
      self.form.saving = true;
      try {
        await svc("interface", "create", {
          if_name: String(d.if_name).trim(), if_type: d.if_type,
          provider: String(d.provider).trim(), consumer: String(d.consumer).trim(),
          icd_content: d.icd_content || undefined,
          ci_no: d.ci_no || undefined,
          owner: d.owner || undefined, project_no: d.project_no || undefined,
        });
        toast("已定义接口（定义中，尚未定版）");
        self.form.open = false;
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.form.saving = false; }
    },
  });
  return self;
}
