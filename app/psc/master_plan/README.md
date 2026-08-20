# 主计划（master_plan）· Agent 操作指南

## 一、应用简介

主计划聚合根 `MasterPlan`，数据存于同名库 `master_plan.db`（表 `master_plan`）。业务定位：线下产能平衡结果导回系统，按**计划版本号（plan_version）**版本化，是库存推移表「预计入库量」的输入来源。

- **主键（复合）**：`plan_version + material_no + rolling_month`；另有 `version_no + material_no + rolling_month + plan_version` 唯一约束。
- **数据来源类型**：手工参考创建——本系统**不生成**主计划，仅经 `import_plan` 导回线下结果（无「新建」入口）。
- **版本化规则**：`plan_version` 按「物料 × 滚动月度」递增，每次导入取当前最大 `plan_version + 1`，旧版本保留、不覆盖。
- **跨应用调用**：`import_plan` 前会调用 `demand.export_net(version_no)` 导出净需求供线下产能平衡参考（结果不强制，失败不阻断导入）。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `psc__master_plan__import_plan` | `version_no`（文本，必填，YYYYMM）、`rows`（list[dict]，必填） | 批量导回线下产能平衡结果；每条行含 `material_no`/`rolling_month`/`plan_qty`/`latest_inbound_date`；逐行校验，合法行落新版本（`plan_version +1`），返回导入摘要 |
| `psc__master_plan__get` | `plan_version`（整数，必填）、`material_no`（文本，必填）、`rolling_month`（文本，必填） | 按主键查询单行主计划 |
| `psc__master_plan__list` | `version_no`（文本，选填）、`material_no`（文本，选填）、`page`（整数，选填，默认 1）、`size`（整数，选填，默认 20） | 分页列表，按 `plan_version` 降序；返回 `{"items", "total"}` |
| `psc__master_plan__get_latest` | `version_no`（文本，必填）、`material_no`（文本，必填） | 取该物料在指定月度版本下、每个滚动月度最大 `plan_version` 的行（列表，无记录返回空列表） |

`rows` 行字段：`material_no`（物料号）、`rolling_month`（枚举 N+1/N+2/N+3）、`plan_qty`（数字，≥0）、`latest_inbound_date`（日期，YYYY-MM-DD）。

## 三、标准工作流

1. **导入主计划（唯一数据入口）**：计划在线下完成产能平衡后，调用 `psc__master_plan__import_plan(version_no, rows)`。服务内部先自动调用 `demand.export_net(version_no)` 导出净需求作参考，再逐行校验并入库，返回 `{version_no, plan_version, success, fail, errors}`。
2. **浏览主计划**：调用 `psc__master_plan__list(version_no=..., material_no=..., page=..., size=...)` 分页浏览；需要核对某行时，用返回的 `plan_version + material_no + rolling_month` 调 `psc__master_plan__get` 取详情。
3. **下游取预计入库量**（库存推移表）：对每个物料调 `psc__master_plan__get_latest(version_no, material_no)`，返回该物料各滚动月度最新版本行的 `plan_qty`/`latest_inbound_date`。

## 四、前置条件与注意事项

- `rolling_month` 仅限 `N+1` / `N+2` / `N+3`。
- `plan_qty` 必须 ≥ 0；`latest_inbound_date` 必填且格式为 `YYYY-MM-DD`。
- `import_plan` 为**逐行校验**：非法行返回错误明细（`errors`），合法行正常入库；不会因个别行失败而整批回滚。
- `plan_version` 为系统自动生成（按「物料 × 滚动月度」取当前最大 +1），调用方**无需也不应**传入；同一物料同一滚动月度多次导入会得到递增版本（v1 → v2 → v3…），旧版本始终保留。
- 主计划不可删除/覆盖历史版本，仅保留版本链（可追溯、可回滚）。
- 跨应用依赖：`demand.export_net` 仅为导入前参考，其失败（如「净需求未运算」）不会阻断导入。
- `list` 的 `version_no`/`material_no` 为**精确匹配**、AND 关系，均可选。

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 下一步 |
|---|---|---|
| `月度版本不能为空` | `import_plan` / `get_latest` 未传 version_no | 向用户索要月度版本号（YYYYMM，如 202608）后重试 |
| `导入行不能为空` | `rows` 非列表或为空 | 向用户索要至少一行平衡结果后再导入 |
| `物料号不能为空` | 导入行缺 material_no 或 `get`/`get_latest` 未传 material_no | 补全物料号后重试 |
| `滚动月度不能为空` | 导入行缺 rolling_month 或 `get` 未传 rolling_month | 补全滚动月度后重试 |
| `滚动月度仅支持 N+1/N+2/N+3` | rolling_month 取值非法（导入行） | 更正为 N+1/N+2/N+3 后重试 |
| `需求量不能为空` | 导入行 plan_qty 缺失/空 | 补全计划生产量后重试 |
| `需求量必须为数字` | plan_qty 非数值 | 更正为数字后重试 |
| `需求量不能为负` | plan_qty < 0 | 更正为非负数值后重试 |
| `最迟入库日期不能为空` | 导入行 latest_inbound_date 缺失 | 补全最迟入库日期后重试 |
| `最迟入库日期格式应为 YYYY-MM-DD` | 日期格式非法 | 更正为 YYYY-MM-DD 后重试 |
| `导入行格式必须为对象` | rows 中某元素不是 dict | 修正该行结构后重试 |
| `计划版本号不能为空` | `get` 未传 plan_version | 先 `list` 定位该行，取到 plan_version 再 `get` |
| `计划版本号不合法` | plan_version 非正整数 | 用 `list` 返回的真实 plan_version 重试 |
| `主计划记录不存在` | `get` 的主键无对应记录 | 先 `list` 核对编号，或确认该物料/滚动月度已导入 |
| `分页参数不合法` | `list` 的 page/size 非整数 | 改用正整数 page/size，或省略用默认值 |
