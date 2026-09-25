/* app/nasa_pms/stakeholder/view.js —— 利益相关者台账（与后端 stakeholder.py 同文件夹）
 *
 * 数据来源类型：**外部同步（机构与人员）** —— 相关方本体由外部主数据同步进来，
 * 本系统只读引用、不维护源数据。UI 由此与同组其它页有三处**语义差**（照抄别的页会同时错）：
 *   · **没有「新建」按钮** —— 只有一个「同步相关方」入口（对应 `upsert`：编号由外部来源给定，
 *     存在即更新）。文案刻意叫「同步」而不是「新建」：本页新增的是"同步进来的一条主数据"，
 *     不是"本系统开的一张单"。
 *   · **没有「删除」** —— 同步源删掉一条，本页也不删（引用要留着）。列表里也没有行内删除。
 *   · **没有状态徽标** —— 主数据没有状态机（卡片 11）。页面上唯一的"状态感"是期望的
 *     **已承诺 / 未承诺**，那是期望这一行的属性（材料 §4.1.1.2.8），不是整条相关方的状态。
 *
 * 交互要点：
 *   · 期望是**聚合内子表**（无独立标识，`(sh_no, seq)`）—— 随详情模态一起取（`get` 带 `expectations`）；
 *     页面上**没有**"跨相关方的期望汇总"（卡片 11 无「并入说明」类要求，见应用详设 §1.3.2）。
 *   · **本页最关键的语义差**：期望一旦**已获相关方承诺**，其陈述 / 类别 / 来源 / 度量口径
 *     即冻结（BR-07）—— 但**冻结可解锁**（取消勾选「已获相关方承诺」即刻解锁），
 *     与同组 `technical_measure` 的"基线冻结 + rebaseline 解锁"同形。
 *     照抄别的页的"终态一律只读、无解锁入口"会漏掉解锁这一半。
 *   · 类别选「度量有效性（MOE）」时**度量口径变必填**（BR-06）—— 前端给提示并在未填时禁用提交，
 *     判定权威仍在后端。
 */
import { svc, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "stakeholder", name: "利益相关者", ic: "◉",
  title: "利益相关者台账", crumb: "主数据 · 外部同步 · 期望随相关方维护",
  order: 710,
  // 列表渲染**全字段列**（CONVENTION §7：list 返回全字段）；这三列非关键，默认隐藏，
  // 经平台「列设置」按需开启。
  // ⚠ 「所属机构」**不**藏：相关方来源是「机构与人员」，一条人员相关方靠它归口到机构，
  //    藏了就看不出"这是哪个单位的人"。
  col_default_hidden: "职责,联系方式,所属项目",
};

/* 字典：相关方类型 = 架构卡片 11 的「类型（客户/承包商/内部组织）」，
   业务名逐字取自《术语表.md》的「客户」「承包商」两行（见 新增术语.md §1） */
const SH_TYPES = [["customer", "客户"], ["contractor", "承包商"], ["internal_org", "内部组织"]];
/* 期望类别 = 材料 §4.1.1.2.3（Needs, Goals, Objectives）+ §4.1.1.2.6（MOEs）+ §4.1.1.2.2（constraints）
   —— 业务名见 新增术语.md §2 */
const KINDS = [["need", "需要（Need）"], ["goal", "目标（Goal）"], ["objective", "指标（Objective）"],
               ["moe", "度量有效性（MOE）"], ["constraint", "约束（Constraint）"]];

/* ⚠ 本页**没有状态字典** —— 主数据无状态机（卡片 11）。唯一的 0/1 标记是期望的「已获承诺」，
   用平台设计系统的 `.st` + `.st-<色>`（st-green = 已承诺终局态 / st-slate = 还没谈拢）。
   不要写 `var(--ok)` / `var(--red)` 之类的内联色 —— 设计令牌里**没有**这两个变量，
   浏览器会静默回落成继承色，页面不报错但颜色全错（同组 requirement 样板即踩此坑）。 */

export default function pageStakeholder() {
  const self = Alpine.reactive({
    tpl: "",
    list: null,
    // 筛选（与后端 list 的可过滤参数一一对应：sh_type 精确 / keyword 跨字段模糊）
    f_sh_type: "", f_keyword: "",
    // 详情 / 维护（同一模态，mode 切换）
    modal: { open: false, loading: false, mode: "view", d: null, saving: false },
    // 同步相关方（唯一写主档的入口，对应 upsert；editing = 从行内「维护」进来）
    form: { open: false, editing: false, saving: false, d: null },
    // 期望（新增 / 编辑，聚合内子表）
    em: { open: false, mode: "add", saving: false, sh_no: "", sh_name: "", d: null },

    shTypes: SH_TYPES, kinds: KINDS,

    typeName(v) { const t = SH_TYPES.find((x) => x[0] === v); return t ? t[1] : (v || "—"); },
    /** 列表里类型列用**码**（CUSTOMER）+ 中文别名两行；选择器里用中文（业务名唯一来源是术语表） */
    typeCode(v) { return v ? String(v).toUpperCase() : "—"; },
    kindName(v) { const k = KINDS.find((x) => x[0] === v); return k ? k[1] : (v || "—"); },
    kindCode(v) { return v ? String(v).toUpperCase() : "—"; },
    dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; },
    /** 「期望 已承诺/总」（派生计数，`get` 与 `list` 同口径 —— 后端 _counts 唯一实现） */
    expCount(d) { return ((d && d.committed_total) || 0) + "/" + ((d && d.expectation_total) || 0); },

    /* ── 期望的两种只读轴（本页语义差）────────────────────
       · committedFrozen：**该条期望**已获承诺 ⇒ 陈述 / 类别 / 来源 / 度量口径冻结（BR-07），
                          解锁入口就在同一个模态里（取消勾选「已获相关方承诺」）；
       · 相关方本体**没有**第二根轴 —— 它来自外部同步，本系统只读引用（没有状态、没有终态）。 */
    expFrozenRow(e) { return !!e && !!Number(e.committed); },
    /* ⚠ 模态里读 `em.d` 一律走下面这层**空安全** helper，模板里不写裸 `em.d.kind`：
       `x-if="em.d"` 的子绑定**可能**在 openEditExp 把 `em.d` 置 null 的那一拍被再求值一次
       （Alpine 的销毁与子效果执行顺序不保证）—— 同组 review 页实测抛 4 条
       "Cannot read properties of null (reading 'status')"。 */
    expFrozen() { return !!(self.em.d && self.em.d.committed); },
    expFrozenText() {
      return "该期望已获相关方承诺（材料 §4.1.1.2.8）—— 陈述 / 类别 / 来源 / 度量口径不可改写；"
        + "要改请先取消勾选「已获相关方承诺」（BR-07）";
    },
    /** BR-06 的前端镜像：类别选了 MOE 却没写度量口径 ⇒ 不能提交（判定权威仍在后端） */
    needMoe() {
      return !!(self.em.d && self.em.d.kind === "moe"
        && !String(self.em.d.moe === null || self.em.d.moe === undefined
          ? "" : self.em.d.moe).trim());
    },
    emTitle() { return self.em.mode === "edit" ? "编辑期望" : "登记期望"; },

    async init() {
      // ⚠ 先把会被模板引用的响应式状态建好，再挂模板（模板一旦注入就立刻求值 `list.items`，
      //   此刻 list 还是 null 会喷 "reading 'items' of null"；见 pitfalls #37）
      const tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("stakeholder", "list", {
        sh_type: self.f_sh_type || undefined,
        keyword: self.f_keyword.trim() || undefined,
        ...q,
      }));
      self.tpl = tpl;
      await self.list.load();
    },

    search() { self.list.load(1); },

    /* ── 详情 / 维护（同一模态）───────────────────────── */
    /** 取一条相关方的详情并**规整选填字段**（统一成空串，编辑表单才不会显示 "null"）—— 唯一取数入口 */
    async fetchDetail(sh_no) {
      const d = await svc("stakeholder", "get", { sh_no: sh_no });
      if (d) {
        d.duty = d.duty || "";
        d.org = d.org || "";
        d.contact = d.contact || "";
        d.project_no = d.project_no || "";
        d.expectations = (d.expectations || []).map((e) => ({
          ...e, moe: e.moe || "", note: e.note || "",
        }));
      }
      return d;
    },
    async openDetail(row, mode) {
      const m = mode || "view";
      self.modal = { open: true, loading: true, mode: m, d: null, saving: false };
      try {
        self.modal.d = await self.fetchDetail(row.sh_no);
      } catch { self.modal.open = false; } finally { self.modal.loading = false; }
    },
    closeModal() { self.modal.open = false; },
    /** 详情模态若正开着这条相关方，重取一次 —— 期望子表变了而详情不刷新会前后不一致 */
    async refreshDetail(sh_no) {
      if (!self.modal.open || !self.modal.d || self.modal.d.sh_no !== sh_no) return;
      try {
        self.modal.d = await self.fetchDetail(sh_no);
      } catch { /* api.js 已 toast */ }
    },
    expsOf(d) { return (d && d.expectations) || []; },

    async saveEdit() {
      const d = self.modal.d;
      self.modal.saving = true;
      try {
        // 载荷里**没有** expectation_total / committed_total：它们是派生计数，只能由子表推导
        await svc("stakeholder", "upsert", {
          sh_no: d.sh_no, name: d.name, sh_type: d.sh_type,
          duty: d.duty || "", org: d.org || "", contact: d.contact || "",
          project_no: d.project_no || "",
        });
        toast("已维护相关方 " + d.sh_no);
        self.modal.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.modal.saving = false; }
    },

    /* ── 同步相关方（唯一写主档的入口 = upsert）───────── */
    /** 从行内「维护」进来：editing = true（编号锁定——编号由外部来源给定，落库不可变，BR-01） */
    openSync(row) {
      self.form = !row
        ? { open: true, editing: false, saving: false,
            d: { sh_no: "", name: "", sh_type: "", duty: "", org: "", contact: "", project_no: "" } }
        : { open: true, editing: true, saving: false,
            d: { sh_no: row.sh_no, name: row.name || "", sh_type: row.sh_type || "",
                 duty: row.duty || "", org: row.org || "", contact: row.contact || "",
                 project_no: row.project_no || "" } };
    },
    closeForm() { self.form.open = false; },
    /** F-1：编号 / 名称 / 类型三项齐备才可提交（类型不给默认值，字典校验才落得实） */
    canSubmit() {
      const d = self.form.d;
      if (!d) return false;
      return !!(d.sh_no.trim() && d.name.trim() && d.sh_type);
    },
    async saveForm() {
      const d = self.form.d;
      self.form.saving = true;
      try {
        await svc("stakeholder", "upsert", {
          sh_no: d.sh_no.trim(), name: d.name.trim(), sh_type: d.sh_type,
          duty: d.duty || "", org: d.org || "", contact: d.contact || "",
          project_no: d.project_no || "",
        });
        toast(self.form.editing ? "已同步更新 " + d.sh_no : "已同步相关方 " + d.sh_no);
        self.form.open = false;
        // 详情模态若正开着这条，内容一起刷新（同一条 upsert 改的就是它）
        await self.refreshDetail(d.sh_no.trim());
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.form.saving = false; }
    },

    /* ── 期望（聚合内子表：随相关方一起维护，无独立标识 —— 卡片 I-1）── */
    openAddExp(sh_no, sh_name) {
      self.em = { open: true, mode: "add", saving: false, sh_no: sh_no, sh_name: sh_name || "",
                  d: { seq: null, statement: "", kind: "", source: "", moe: "",
                       committed: false, note: "" } };
    },
    openEditExp(sh_no, sh_name, e) {
      self.em = { open: true, mode: "edit", saving: false, sh_no: sh_no, sh_name: sh_name || "",
                  d: { seq: e.seq, statement: e.statement || "", kind: e.kind || "",
                       source: e.source || "", moe: e.moe || "",
                       committed: !!Number(e.committed), note: e.note || "" } };
    },
    closeExp() { self.em.open = false; },
    /** F-2 / F-3：陈述 + 类别 + 来源必填；类别为 MOE 时口径也必填（BR-05 / BR-06） */
    canExp() {
      const d = self.em.d;
      if (!d) return false;
      return !!(d.statement.trim() && d.kind && d.source.trim()) && !self.needMoe();
    },
    async saveExp() {
      const d = self.em.d;
      const frozen = self.expFrozen();
      self.em.saving = true;
      try {
        if (self.em.mode === "edit") {
          // ⚠ 已获承诺时**只发**承诺与备注（口径字段一发过去后端就按 BR-07 拒）；
          //   取消勾选后 expFrozen() 立刻为假，字段随即可改并一并发出去（撤回 + 改写同一次调用）
          const payload = { sh_no: self.em.sh_no, seq: d.seq,
                            committed: !!d.committed, note: d.note || "" };
          if (!frozen) {
            payload.statement = d.statement.trim();
            payload.kind = d.kind;
            payload.source = d.source.trim();
            payload.moe = d.moe || "";
          }
          await svc("stakeholder", "update_expectation", payload);
          toast("已保存期望");
        } else {
          await svc("stakeholder", "add_expectation", {
            sh_no: self.em.sh_no, statement: d.statement.trim(), kind: d.kind,
            source: d.source.trim(), moe: d.moe || "", committed: !!d.committed,
            note: d.note || "",
          });
          toast("已登记期望");
        }
        self.em.open = false;
        // 期望是聚合内子表：详情模态与列表的派生计数都要跟着变，两处一起刷
        await self.refreshDetail(self.em.sh_no);
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast */ } finally { self.em.saving = false; }
    },
  });
  return self;
}
