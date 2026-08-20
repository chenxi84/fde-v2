# baseline_borrowing · Agent 操作指南

## 一、应用简介

基线借用台账——为历史不足零件登记基线例外（五种借法），保证"借来的基线"可复核、可回溯。

- **聚合根**：BaselineBorrowing
- **主键**：jy_no（JY-YYYYMM-NNN）
- **数据库**：baseline_borrowing.db（同名库，单表）
- **跨应用调用**：出站调 vehicle_part_map.get_active_mapping、demand_collection.get_true_qty；入站被 demand_processing.generate_baseline 调用 get_derived_qty

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `parts-fc__baseline_borrowing__create` | `part_no: str` 零件号，`veh_model: str` 适用车型，`hist_months: int` 可用历史月数，`borrow_method: str` 先导指标/类比/模板拟合/上移/池化，`borrow_source: str` 借用来源，`source_params: str` 来源参数，`proc_batch: str` D04加工批次，`derived_qty: str` 推导基线JSON（默认`{}`），`calibration: str` 早期校准（可选） | 新建借用单→待审核 |
| `parts-fc__baseline_borrowing__get` | `jy_no: str` 借用单号 | 查看借用单详情 |
| `parts-fc__baseline_borrowing__list` | `part_no: str` 零件号（可选），`status: str` 状态（可选），`borrow_method: str` 借法（可选） | 条件筛选借用单列表 |
| `parts-fc__baseline_borrowing__review` | `jy_no: str` 借用单号，`approved: bool` true=通过/false=驳回，`comment: str` 审核意见 | 审核→通过（生效）或驳回 |
| `parts-fc__baseline_borrowing__calibrate` | `jy_no: str` 借用单号，`calibration_data: str` 校准数据 | 用自身实际数据校准借用参数 |
| `parts-fc__baseline_borrowing__get_derived_qty` | `jy_no: str` 借用单号 | 取推导基线各期值（供D04调用） |
| `parts-fc__baseline_borrowing__close` | `jy_no: str` 借用单号，`reason: str` 关闭原因 | 关闭借用单→已转自产/已关闭 |

## 三、标准工作流

### 流程 A：新车型类比法借用基线

1. D04 判定某零件历史不足(hist_months < 12)，触发借用登记
2. 总部计划调用 `create`：传入 part_no、veh_model、hist_months、borrow_method="类比"、borrow_source="相似车型A"、source_params、proc_batch
3. 若有早期数据(hist_months > 0)，同步填写 calibration，否则审核会被驳回
4. 总部计划（核对人）调用 `review(jy_no, approved=true, comment="...")` 审核通过→生效
5. D04 调用 `get_derived_qty(jy_no)` 获取基线各期值
6. 历史转充足后调用 `close(jy_no, reason="历史转充足...")`→已转自产

### 流程 B：先导指标法借用（未上市车型）

1. 总部计划调用 `create`：borrow_method="先导指标"、borrow_source=D03收集单号
2. 系统自动调 demand_collection.get_true_qty 获取拆解后真实消耗
3. 总部计划调用 `review(jy_no, approved=true, comment)` 审核
4. 后续有数据后调用 `calibrate` 校准参数

### 流程 C：驳回重审

1. 总部计划调用 `review(jy_no, approved=false, comment="驳回理由")` 驳回
2. 驳回意见记录在 calibration 字段，借用单状态保持"待审核"
3. 补充校准或修改参数后，重新调用 `review(jy_no, approved=true, comment)` 审核
4. 通过→生效

## 四、前置条件与注意事项

- **BR-01**：hist_months < 12 或无完整季节周期方可登记，历史充足请走 D10 策略仿真拟合
- **BR-02**：hist_months > 0 时 calibration 必填，否则审核驳回
- **BR-03**：先导指标法必须取 true_qty（拆解后真实消耗），不取 orig_qty
- **BR-30**：同一 part_no+veh_model+proc_batch 只能有一张生效借用单
- 五种借法枚举：先导指标 / 类比 / 模板拟合 / 上移 / 池化
- 衍生基线 derived_qty 由系统生成（JSON），不可手动修改
- 跨应用调用（demand_collection、vehicle_part_map）为弱依赖，失败不阻断创建

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 应对策略 |
|---|---|---|
| "历史充足，请走 D10 策略仿真拟合" | hist_months >= 12，不满足借用条件 | 引导用户走 demand_processing.generate_baseline，用 strategy_fitting 自产基线 |
| "有自身早期数据必须校准参数，纯照搬模板不予通过" | hist_months > 0 但 calibration 为空 | 索要实际数据（如首N月消耗量），填入 calibration 字段后重试 |
| "借用方法只能为：..." | borrow_method 不在五种枚举内 | 列出五种借法（先导指标/类比/模板拟合/上移/池化），请用户选择 |
| "同一零件×车型在该加工批次已存在待审核/生效的借用单" | BR-30 冲突 | 提示用户先查看已有借用单，如需替换则先 close 旧单 |
| "仅待审核借用单可审核" | 借用单已不在待审核状态 | 调用 get 查看当前状态，确认是否已被审核或已关闭 |
| "借用单未生效" | get_derived_qty 要求状态="生效" | 提示用户先完成 review 审核通过 |
| "仅生效借用单可关闭" | close 要求状态="生效" | 调用 get 确认当前状态 |
