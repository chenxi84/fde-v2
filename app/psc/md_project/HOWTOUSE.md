# md_project 使用要点

**管什么**：车型项目的生命周期台账——阶段（进行中/SOP/EOP）、SOP/EOP 日期、责任销售。

## 标准工作流（按此顺序）

1. `list` / `get` — 用 `project_no`（模糊）、`project_name`（模糊）、`stage`（精确）定位；不确定编号就先查
2. `create` — 新建台账，`project_no` / `project_name` / `owner` 必填，`stage` 缺省「进行中」
3. `get` — 推进阶段前先看当前 `stage`
4. `update` — 推进：`update(stage="SOP", sop_date="...")` → 后续 `update(stage="EOP", eop_date="...")`
5. `get` — 推进后回读确认
6. `import_batch` — 批量同步（PLM 冗余）：`rows` 逐行 upsert，读 `errors` 修正失败行后重导

## 前置条件与禁忌

- **阶段只能单向推进：进行中 → SOP → EOP**。跳级（进行中→EOP）与回退（SOP→进行中 / EOP→SOP）一律被拒；新建项目只能从「进行中」开始。
- **推进到 SOP 必须在同一次 `update` 里带上 `sop_date`**；推进到 EOP 必须带上 `eop_date`。否则报「推进到 SOP/EOP 阶段须填写…时间」。
- 日期格式须为 `YYYY-MM-DD`；同时填写时 **`eop_date` 必须晚于 `sop_date`**。
- **`project_no` 全局唯一且不可修改**，`update` 里它仅作定位键；没有删除服务（被 `md_project_part` 引用）。
- `list` 的 `page` / `size` 省略时返回全量；`stage` 筛选是精确匹配。
- `import_batch` 逐行 upsert，单行失败不影响其他行，失败行写进 `errors`（含行号）。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/md_project", doc="README")` 读完整操作指南再处置。
