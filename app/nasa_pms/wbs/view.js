/* 工作分解结构台账 · 独立创建（顶层元素自带编号）· 草稿 / 已基线 / 变更中 / 已关闭
   元素树是本聚合内结构（父子同一张表）；控制账户 / 工作包 / 规划包是元素的 `kind` 属性。
   依据：NASA/SP-20250006071《NASA WBS Handbook》(2025-06) §3.3.4 / §3.4.2 / §3.4.4 / §3.5.2 */
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

export default function pageWbs() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    view: "list",                       // list | tree
    // 筛选（与后端 list 的可过滤参数一一对应）
    f_status: "", f_kind: "", f_keyword: "",
    tree: [],
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
      await self.list.load();
      await self.loadTree();
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
    },

    search() { self.list.load(1); },
    async reload() { await self.list.load(self.list.page); await self.loadTree(); },
    switchView(v) { self.view = v; if (v === "tree") self.loadTree(); },

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
