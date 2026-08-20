# demand_release 应用 · Agent 操作指南

## 一、应用简介
毛需求发布单——加工链终点，冻结口径 R 版下达，净需求/S&OP 唯一输入。聚合根 `DemandRelease`，主键 `rel_no`（编码 REL-YYYYMM-DDHHMM），版本号 `rel_version`（如 R202601.1）。发布口径 = 消耗驱动量（D08 终端口径）+ 生效事件量（D06），构成列示明细。发布时联动锁定上游 D04 加工批次和 D03 预测版本，确保数据口径冻结。支持版本修订（子版本机制）与版本差异比对。跨应用调用：demand_processing（lock_batch 锁定加工批次）、demand_collection（lock 锁定预测版本）。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `sales-forecast__demand_release__create_draft` | base_period | 生成发布草稿，自动生成版本号（首版 R{period}，修订版递进 .1 .2 ...） |
| `sales-forecast__demand_release__add_line` | rel_no, part_no, veh_model, period, cons_qty, event_items, basis, lineage, split_qty | 添加发布明细行；rel_qty 系统强制 = cons_qty + 事件量合计 |
| `sales-forecast__demand_release__get` | rel_no | 获取发布单全貌（header + 所有明细行） |
| `sales-forecast__demand_release__list` | rel_version="", status="" | 按版本号/状态筛选列表，按版本倒序 |
| `sales-forecast__demand_release__checklist_verify` | rel_no | 发布前五项校验（D04 核定/D08 结论/D06 齐备/客户对齐/版本差异），全部 PASS/WARN → 待发布 |
| `sales-forecast__demand_release__publish` | rel_no | 正式发布，联动锁定 D04 批次 + D03 版本 |
| `sales-forecast__demand_release__revise` | rel_no, reason | 版本修订——产生子版本（旧版→已替代），新版→草稿 |
| `sales-forecast__demand_release__version_diff` | rel_no | 版本比对 R_n vs R_{n-1}，输出增/减明细 |

## 三、标准工作流
1. **创建草稿**：`create_draft(base_period)` → 自动生成 rel_no 与版本号，状态「草稿」。
2. **逐行填充**：从上游汇总 D04/D06/D07/D08 结果，逐零件调用 `add_line(...)`，注意 `event_items` 传入事件列表后系统强制计算 rel_qty = cons_qty + 事件量合计。
3. **Checklist 校验**：`checklist_verify(rel_no)` → 五项校验全部 PASS 或 WARN 后状态→「待发布」；明细为空时 FAIL。
4. **发布**：`publish(rel_no)` → 状态→「已发布」。联动锁定：遍历明细 lineage 中的 proc_batch 调 `demand_processing.lock_batch`，遍历 fcst_version 调 `demand_collection.lock`。
5. **版本修订**：已发布版本需修订时 `revise(rel_no, reason)` → 旧版→「已替代」，新版→「草稿」。
6. **差异分析**：`version_diff(rel_no)` 比对当前版本与上一版本的零件-周期维度数量变化。

## 四、前置条件与注意事项
- `add_line` 仅在「草稿」状态可调用；checklist 通过后状态变为「待发布」，不可再添加明细。
- **rel_qty 强制计算**：系统不允许手动指定 rel_qty，始终由 `cons_qty + Σevent_items[].qty` 计算——确保口径一致性。
- `publish` 仅在「待发布」状态可调用。
- `revise` 仅在「已发布」状态可调用；修订原因不可为空。
- **联动锁定为弱依赖**：lock_batch / lock 调用失败不阻断发布，仅静默跳过。Agent 应关注返回的 locked_batches 列表确认实际锁定了哪些批次。
- 版本差异比对仅当存在 prev_version（即非首版）时才有意义；首版返回提示"无上一版本"。
- lineage 字段记录数据血缘（proc_batch + fcst_version），供发布时联动锁定追溯。
- basis 字段记录发布依据，split_qty 记录拆分分配结果。

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步 |
|---|---|---|
| 发布单 {rel_no} 不存在 | 单号错误或已替代 | 用 list 按版本号查找正确单号 |
| 仅草稿状态可添加明细 | 已通过 checklist | 如需追加明细，revise 创建子版本后在新草稿中添加 |
| 仅草稿状态可执行 checklist | 已校验过或已发布 | get 确认当前状态 |
| 当前状态 {status}，须先通过 checklist 至'待发布' | 草稿未校验 | 先调 checklist_verify 通过后重试 |
| 仅已发布版本可修订 | 草稿/待发布不可修订 | 先发布后再修订，或直接修改草稿 |
| 修订原因不可为空 | revise 时 reason 为空 | 要求用户提供修订原因（如"客户确认变更/事件更新"） |
