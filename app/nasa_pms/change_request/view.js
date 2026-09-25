/* app/nasa_pms/change_request/view.js —— 变更请求台账（与后端 change_request.py 同文件夹）
 *
 * 数据来源类型：**独立创建** —— 保留「提出变更」入口（对应 create）。
 * 交互要点：影响范围（配置项 / 需求）用**多选下拉**，选项来自跨应用 `configuration_item.list`
 * 与 `requirement.list`（失败静默兜底为空，不喷 toast）；内容只在「已提交」可编辑（BR-06）；
 * 审批模态里批准 / 拒绝两个按钮共用一份「审批意见」，未填都禁用（BR-02）；
 * 已拒绝 / 已实施是硬终态 —— 行上不再出现任何动作按钮（BR-04）。
 * 动作按钮按状态显隐（状态机：submitted → analyzing → reviewing → approved / rejected → implemented）。
 */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "change_request", name: "变更请求", ic: "🔁",
  title: "变更请求台账", crumb: "提出 · 影响分析 · 审批 · 实施",
  order: 640,
};

/* 状态徽章用平台设计系统的 `.st` + `.st-<色>`（`design-plus/view-convention/design-system.md`：
   blue=流程中态 / amber=进行中待办 / green=完成 / red=失败退回）。
   ⚠ 不要写 `var(--ok)` / `var(--red)` 之类的内联色 —— 设计令牌里**没有**这两个变量，
   浏览器会静默回落成继承色，页面不报错但颜色全错（同组样板踩过此坑）。 */
const STATUS = {
  submitted: ["已提交", "st-blue"],
  analyzing: ["影响分析", "st-blue"],
  reviewing: ["审批中", "st-amber"],
  approved: ["已批准", "st-green"],
  rejected: ["已拒绝", "st-red"],
  implemented: ["已实施", "st-green"],
};
/* 硬终态：已拒绝 / 已实施（BR-04）——到达后任何动作都不再提供 */
const TERMINAL = ["rejected", "implemented"];
const MODE_TITLE = { view: "变更请求详情", edit: "编辑变更请求", analyze: "提交影响分析",
                     disposition: "变更审批", implement: "实施变更" };

export default function pageChangeRequest() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    // 筛选（与后端 list 的可过滤参数一一对应：status / requester / ci_no / req_no）
    f_status: "", f_requester: "", f_ci: "", f_req: "",
    // 详情 / 编辑 / 影响分析 / 审批 / 实施 —— 同一个模态，mode 切换
    // dec = 审批输入（批准与拒绝共用一份意见）；imp = 实施说明
    modal: { open: false, loading: false, mode: "view", d: null, saving: false,
             dec: { comment: "", approver: "" }, imp: { note: "" } },
    // 提出变更
    form: { open: false, saving: false, d: null },
    // 「申请方」候选 —— 跨应用 stakeholder.list（**值仍是文本**，不落 sh_no）
    owners: [],
    // 跨应用选项：影响范围的配置项与需求（也是筛选下拉的选项源）
    cis: [], reqs: [],

    statusName(v) { return (STATUS[v] || [v, ""])[0]; },
    statusCls(v) { return (STATUS[v] || ["", "st-slate"])[1]; },
    /** 硬终态（已拒绝 / 已实施）：BR-04 —— 行上不再出现动作按钮 */
    terminal(d) { return !!d && TERMINAL.indexOf(d.status) >= 0; },
    modalTitle() { return MODE_TITLE[self.modal.mode] || "变更请求"; },
    dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; },
    /** 影响范围的两侧都以列表返回（后端已解析），视图直接 join 展示 */
    join(v) { return (v && v.length) ? v.join("、") : "—"; },
    ciLabel(no) { const c = self.cis.find((x) => x.ci_no === no);
                  return c ? (c.ci_no + " · " + c.name) : no; },
    reqLabel(no) { const r = self.reqs.find((x) => x.req_no === no);
                   return r ? (r.req_no + " · " + r.title) : no; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("change_request", "list", {
        status: self.f_status || undefined,
        requester: self.f_requester || undefined,
        ci_no: self.f_ci || undefined,
        req_no: self.f_req || undefined,
        ...q,
      }));
      await self.loadOptions();
      await self.loadOwners();
      await self.list.load();
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

    /** 影响范围下拉（也是筛选下拉）的选项源：跨应用只读调用，失败静默兜底为空列表 */
    async loadOptions() {
      try {
        const r = await svc("configuration_item", "list", {}, { quiet: true });
        self.cis = (r && r.items) || [];
      } catch { self.cis = []; }
      try {
        const r = await svc("requirement", "list", {}, { quiet: true });
        self.reqs = (r && r.items) || [];
      } catch { self.reqs = []; }
    },

    search() { self.list.load(1); },

    /* 详情 / 编辑 / 影响分析 / 审批 / 实施：同一个模态，mode 切换 */
    async openDetail(row, mode) {
      const m = mode || "view";
      self.modal = { open: true, loading: true, mode: m, d: null, saving: false,
                     dec: { comment: "", approver: "" }, imp: { note: "" } };
      try {
        const d = await svc("change_request", "get", { cr_no: row.cr_no });
        if (d) {
          // 影响范围两侧必为数组（多选下拉绑定要求）
          d.ci_nos = d.ci_nos || [];
          d.req_nos = d.req_nos || [];
          // ⚠ 可空文本字段归一为 '' —— 模板绑定里对它们调 .trim()（如 canAnalyze），
          //   拿到 null 会抛 "Cannot read properties of null" 一片 pageerror（实测踩过：
          //   已提交的变更请求 impact_analysis 本就是 NULL）
          d.description = d.description || "";
          d.impact_analysis = d.impact_analysis || "";
        }
        self.modal.d = d;
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },

    /** F-4：内容只在「已提交」可编辑 —— 其余状态标题/申请方/说明/影响范围一律只读 */
    editable() { return !!self.modal.d && self.modal.mode === "edit"; },
    /** 保存可用性：标题 / 申请方非空，且影响范围**改完之后**不能为空（BR-01） */
    canSaveEdit() {
      const d = self.modal.d;
      return !!d && !!d.title.trim() && !!d.requester.trim()
        && ((d.ci_nos && d.ci_nos.length) + (d.req_nos && d.req_nos.length) > 0);
    },
    async saveEdit() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        // ⚠ 载荷里**没有** cr_no 之外的键字段与状态 —— 编号不可变（BR-03），状态只走动作服务
        await svc("change_request", "update", {
          cr_no: d.cr_no, title: d.title, requester: d.requester,
          ci_nos: d.ci_nos, req_nos: d.req_nos, description: d.description || "",
        });
        toast("已保存");
        self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /** F-7：影响分析非空才能提交（BR-02）
        ⚠ `|| ""` 是第二道防线：openDetail 已归一，但模板绑定会被并发/局部刷新重算，
           任何路径下 `d.impact_analysis` 为 null 都不能让这里抛错（抛了就整片 pageerror） */
    canAnalyze() {
      const d = self.modal.d;
      return !!d && !!(d.impact_analysis || "").trim();
    },
    async saveAnalyze() {
      self.modal.saving = true;
      try {
        await svc("change_request", "analyze", {
          cr_no: self.modal.d.cr_no,
          impact_analysis: self.modal.d.impact_analysis.trim(),
        });
        toast("已提交影响分析");
        self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /** F-8：审批意见非空才能批准 / 拒绝（批准与拒绝共用一个输入，故同一守卫） */
    canDispose() { return !!self.modal.dec.comment.trim(); },
    async saveDispose(kind) {
      self.modal.saving = true;
      try {
        // ⚠ 两个字面量分开写（不能变量拼服务名）—— 平台靠源码字面量派生「页→服务」隐式放行边
        if (kind === "approve") {
          await svc("change_request", "approve", {
            cr_no: self.modal.d.cr_no, comment: self.modal.dec.comment.trim(),
            approver: self.modal.dec.approver || undefined,
          });
        } else {
          await svc("change_request", "reject", {
            cr_no: self.modal.d.cr_no, comment: self.modal.dec.comment.trim(),
            approver: self.modal.dec.approver || undefined,
          });
        }
        toast(kind === "approve" ? "已批准" : "已拒绝");
        self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    async saveImplement() {
      self.modal.saving = true;
      try {
        await svc("change_request", "implement", {
          cr_no: self.modal.d.cr_no, note: self.modal.imp.note || undefined,
        });
        toast("已实施（记录保留）");
        self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /* 提出变更 */
    openForm() {
      self.form = { open: true, saving: false, d: {
        title: "", requester: "", description: "", project_no: "",
        ci_nos: [], req_nos: [] } };
    },
    closeForm() { self.form.open = false; },
    /** F-1：标题 / 申请方必填，且影响范围至少选一个配置项或一条需求（BR-01） */
    canSubmit() {
      const d = self.form.d;
      return !!d && !!d.title.trim() && !!d.requester.trim()
        && (d.ci_nos.length + d.req_nos.length > 0);
    },
    async saveForm() {
      const d = self.form.d;
      self.form.saving = true;
      try {
        await svc("change_request", "create", {
          title: d.title.trim(), requester: d.requester.trim(),
          ci_nos: d.ci_nos, req_nos: d.req_nos,
          description: d.description || undefined,
          project_no: d.project_no || undefined,
        });
        toast("已提交变更请求");
        self.form.open = false;
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.form.saving = false; }
    },

    /** 提交审批：影响分析 → 审批中（单键动作，故用二次确认） */
    async submitReview(row) {
      if (!confirm(`确定把变更请求 ${row.cr_no} 提交审批？\n\n`
        + `提交后内容即定型，不能再修改影响范围（BR-06）。`)) return;
      try {
        await svc("change_request", "submit_review", { cr_no: row.cr_no });
        toast("已提交审批");
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ }
    },
  });
  return self;
}
