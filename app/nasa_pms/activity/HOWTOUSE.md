# activity 使用要点

**管什么**：IMS 里的一个**离散可度量工作单元** —— 活动（tasks，有工期）与里程碑（events，工期 0），带逻辑链、基线日期与实绩；不含 WBS 结构（属 `wbs`）、不含变更审批（属 `change_request`）。依据 `NASA/SP-2010-3403`《Schedule Management Handbook》Rev 1。

## 标准工作流（按此顺序）

1. `add_milestone(name, wbs_no, phase="start")` — 建**起始边界里程碑**（它可以没有前置）
2. `create(name, wbs_no, duration_days, predecessors=…, owner=…)` — 建活动，`wbs_no` 必须是**叶子**元素
3. `link(act_no, predecessor_no)` — 连逻辑链（完成→开始）
4. `check_network()` — 体检：开口端 / 冗余 / 环 / 工期 / 挂靠非叶子
5. `schedule_view(project_start="YYYY-MM-DD")` — 看**派生**日期（正推）+ 浮时 + 关键路径
6. `baseline(act_nos=[…], project_start=…)` — 建立进度基线（把派生日期冻住）
7. `record_progress(act_no, percent_complete, actual_start, actual_finish)` — 回填实绩
8. 基线后要改工期 / 逻辑链 → 先 `change(act_no, change_no)`（须**已批准**）再 `update`

查询用 `list`（按状态/类型/挂靠元素/责任方/是否已基线/关键词筛，分页 `{items,total}`）、`get`、`critical_path()`。

## 前置条件与禁忌

- **日期是派生量，不是填出来的**：表里只有 `duration_days` 与前置链，计划日期由 `schedule_view` 正推
  （材料 §5.5.9.3：日期由**逻辑与工期**决定，而不是为凑某个完成日）。所以**没有"计划开始/完成"输入框**。
- **禁开口端（BR-01）**：除两个**边界里程碑**（`phase="start"` 允许没有前置、`phase="finish"` 允许没有后续）
  外，每个活动都要有前置与后续。体检会把开口端列出来。
- **禁冗余链接（BR-02）**：A→B、B→C 之后再连 A→C 会被拒（材料 §5.5.8 原文的例子）。**建活动时一次性
  塞进冗余前置同样会被拒** —— 两个入口都拦。
- **逻辑链无环（BR-03）**：前置不存在 / 成环 / 自前置 / 重复连，都会被拒。
- **工期规则（BR-04）**：里程碑恒 0（它是**事件**不是工作）；活动必须 > 0。单位是**工作日**。
- **只能挂 WBS 叶子（BR-05）**：挂到有子元素的父元素会被拒，报错会告诉你去它的子元素上挂。
- **名称唯一（BR-06）**：活动与里程碑的描述必须唯一可区分（§5.5.5）。
  ⚠ 材料另有一条**语言学**约定（离散活动名含动词、汇总活动名不含动词）—— **机械判不了**，
  靠人守：写「装配舱板」而不是「舱板装配工作」这类歧义名。
- **基线后锁计划（BR-07）**：已基线的活动改名称/工期/逻辑链/挂靠，必须先 `change`（变更号须**已批准**）。
- **回填实绩不受基线锁（BR-08）**：`record_progress` 随时可做，且**绝不修改基线列**
  （材料 §7.3：against that baseline）。
- 跨应用：`wbs.get` + `wbs.list(parent_no=…)` 判叶子；`change_request.get` 校验变更已批准。两个都**只读**。

## 出错时看哪里

- 建不了活动 → 先看挂靠元素是不是**叶子**（BR-05），再看名称是否重复（BR-06）、工期是否合规（BR-04）
- 连不上前置 → 报错会说清是「冗余链接」还是「成环」还是「不存在」
- 改不了工期 → 活动已基线，先 `change` 挂变更号（BR-07）
- 日期看着不对 → 走 `schedule_view`（派生的），注意后继是在**前驱完成后的下一个工作日**开工
- 元素级设计依据 → `platform_read_app_doc(app="nasa_pms/activity", doc="应用详设")`
