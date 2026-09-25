# configuration_item 使用要点

**管什么**：纳入配置管理的工作产品（配置项）——名称、类型、当前版本、所属基线、状态。**不含变更审批**：批没批在 `change_request`，本应用只认"带没带变更号"。

## 标准工作流（按此顺序）

1. `create` — 建档（`name` + `ci_type` 必填），落 `draft`、**版本恒为 v1**、编号自动 `CI-001` 起
2. `control` — `draft → controlled`（纳入配置管理的时点，**未受控不能进基线**）
3. `assign_baseline` — 纳入四条基线之一（`functional` / `allocated` / `product` / `as_deployed`），可带 `baseline_ver` 标记
4. `release` — `controlled → released`；**首次发版不需要变更号**
5. `bump_version` — 版本变更：`new_version`（正整数）+ `change_no` 必填；**状态回落为「受控」**，新版本要重新 `release` 才算发布
6. `update` 改内容（白名单只有名称 / 类型 / 责任人）；收尾 `archive` → `archived`（终态）

核对用：`list`（按 `ci_type` / `status` / `baseline` 筛）→ `get`。

## 前置条件与禁忌

- **状态闸**：`control` 只认 `draft`；`release` 只认 `controlled`；`archive` 只认 `released`；已归档拒绝一切（改内容 / 变更版本 / 纳基线）。
- **守卫顺序（负例话术取决于它）**：`control` 先报「已经是受控状态」、再报「只有草稿状态才能提交受控」；`assign_baseline` 依次 基线字典 → 草稿拒 → 已归档拒 → 重复纳入同一条基线拒；`update` 先判已归档、再判已发布缺变更号、最后才校验字段；`release` 先判状态、再判非首次发版缺变更号。
- **非首次发版 = 一次版本变更**：`released_ver` 非空时 `release` 必须带 `change_no`。`change_no` 只校验"带了没有"，"是否已批准"由 `change_request` 保证 —— **顺序是先走完 change_request 全链拿到 `cr_no`，再回本应用 `bump_version` / 非首次 `release`**，别倒着来。
- **版本只能递增、只有一个入口**：`new_version` 必须正整数且严格大于当前版本；`update` 的参数表里**没有版本与编号**（编号 `CI-三位序号`不可改）。
- 字典：`ci_type` ∈ `hardware` / `software` / `document` / `model` / `data`；`baseline` 为上述四条。`baseline` 是**单值**，不能重复纳入同一条；归档不删除记录。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="nasa_pms/configuration_item", doc="应用详设")` 读完整详设再处置。
