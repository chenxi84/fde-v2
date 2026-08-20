# baseline_borrowing 应用 · Agent 操作指南

## 一、应用简介
基线借用台账——历史不足零件的基线例外登记。聚合根 `BaselineBorrowing`，主键 `jy_no`（编码规则 JY-YYYYMM-NNN），一行一零件一车型。五种借法（先导指标/类比/模板拟合/上移/池化）保证"借来的基线"可复核、可回溯。与 strategy_simulation 分工：历史充足走 D10 选策略；历史不足走本表借基线。跨应用调用：demand_collection（先导指标法获取 OEM 预测）、vehicle_part_mapping（获取形态/生命周期信息）。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `sales-forecast__baseline_borrowing__create` | part_no, veh_model, hist_months, borrow_method, borrow_source, source_params, derived_qty, proc_batch, calibration | 新建借用单；hist_months>0 且无校准→拒绝（BR-02：有早期数据必须校准） |
| `sales-forecast__baseline_borrowing__get` | jy_no | 获取借用单详情 |
| `sales-forecast__baseline_borrowing__list` | part_no="", status="", borrow_method="" | 按零件/状态/借法筛选列表 |
| `sales-forecast__baseline_borrowing__review` | jy_no, approved, comment | 审核：通过→生效，驳回→待审核（意见追记 calibration） |
| `sales-forecast__baseline_borrowing__calibrate` | jy_no, calibration_data | 早期校准更新——有自身历史数据后修正借用参数 |
| `sales-forecast__baseline_borrowing__close` | jy_no, reason | 关闭：历史转充足→已转自产；不再使用→已关闭 |
| `sales-forecast__baseline_borrowing__get_derived_baseline` | jy_no | 获取推导基线各期值（已关闭借用单不可用） |

## 三、标准工作流
1. **新建借用单**：`create(...)` 指定借法与来源参数 → 状态「待审核」。
2. **先导指标法**：`create` 内部弱依赖调用 `demand_collection.get` 校验来源存在性（不阻断）。
3. **形态校验**：`create` 内部弱依赖调用 `vehicle_part_mapping.get` 获取零件-车型形态信息（不阻断）。
4. **审核**：`review(jy_no, approved=True)` → 状态「生效」；BR-02 校验：有早期数据无校准→拒绝。
5. **追补校准**：零件自身历史积累后，`calibrate(jy_no, calibration_data)` 修正借用参数。
6. **关闭**：历史转充足时 `close(jy_no, "切换自产策略")` → 「已转自产」；不再使用 → 「已关闭」。
7. **下游取基线**：D04 调 `get_derived_baseline(jy_no)` 获取各期推导值。

## 四、前置条件与注意事项
- 借用方法五选一：先导指标/类比/模板拟合/上移/池化，输入其他值直接抛错。
- **BR-02 强约束**：`hist_months > 0`（有自身早期数据）时必须传 `calibration`，纯照搬模板不予创建通过；审核阶段同样校验。
- 已关闭/已转自产借用单的 `get_derived_baseline` 调用抛出"推导基线不可用"。
- 先导指标法会跨应用调 `demand_collection.get`，但为弱依赖——调用失败不阻断创建，仅静默跳过。
- vehicle_part_mapping 调用同为弱依赖，不影响创建流程。
- 审核通过后状态→「生效」，驳回后状态保持「待审核」（驳回意见追记在 calibration 字段中）。

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步 |
|---|---|---|
| 零件号必填 | 未传 part_no | 向用户索要零件号后重试 |
| 适用车型必填 | 未传 veh_model | 向用户索要车型后重试 |
| 借用来源必填 | 未传 borrow_source | 向用户索要借用来源（如相似车型/模板编号/OEM预测版本） |
| 来源参数必填 | 未传 source_params | 向用户索要来源参数（峰值/衰减率/分摊权重等） |
| 关联加工批次必填 | 未传 proc_batch | 从 D04 获取当前加工批次号 |
| 借用方法只能为：先导指标/类比/模板拟合/上移/池化 | borrow_method 不在合法列表中 | 提示用户从五种方法中选择 |
| 历史月数必须为整数 | hist_months 非整数 | 确认 hist_months 为整数后重试 |
| 有自身早期数据必须校准参数，纯照搬模板不予通过 | BR-02 违规 | 要求用户补充 calibration_data（峰值调整/衰减率修正/偏差分析） |
| 借用单 {jy_no} 不存在 | 单号错误或已删除 | 用 list 按条件查找正确单号 |
| 审核意见必填 | review 时 comment 为空 | 要求用户提供审核意见 |
| 仅待审核借用单可审核，当前状态：{status} | 状态不对 | get 确认当前状态：已生效无需再审，已关闭走新单 |
| 有早期数据但无校准记录——驳回 | review 阶段 BR-02 校验失败 | 先 calibrate 补校准，再重新提交审核 |
| 仅待审核/生效借用单可校准，当前状态：{status} | 已关闭/已转自产不可校准 | 如需修正，新建借用单 |
| 校准数据必填 | calibrate 时 calibration_data 为空 | 要求用户提供校准内容 |
| 关闭原因必填 | close 时 reason 为空 | 要求用户说明关闭原因（如"历史转充足切换自产"） |
| 借用单已关闭 | 重复关闭 | 无需处理 |
| 借用单已转自产，无需重复关闭 | 重复关闭 | 无需处理 |
| 借用单已关闭，推导基线不可用 | get_derived_baseline 时状态为已关闭 | 换用 strategy_simulation 自产策略或新建借用单 |
| 推导基线数据格式异常 | derived_qty JSON 损坏 | 检查 derived_qty 字段数据完整性 |
| 借用单号生成失败，请重试 | 并发冲突 | 重试 create |
