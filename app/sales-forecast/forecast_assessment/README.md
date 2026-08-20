# forecast_assessment 应用 · Agent 操作指南

## 一、应用简介
预测转单率考核表——事后闭环评估。聚合根 `ForecastAssessment`，主键 `fa_no`（编码 FA-YYYYMM-HHMMSS），一行一零件一车型一周期。双口径设计：消耗口径（actual_qty vs fcst_qty）评预测能力，发运口径（settle_qty vs base_qty/adj_qty）评报数质量。FVA（Forecast Value Added）视图量化从基线到核定的每一步误差改善。归因认定区分"计入考核/免责剔除/归因流程·策略"三类结论。跨应用调用：system_config（获取客户信任折扣系数 get_trust_discount）。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `sales-forecast__forecast_assessment__create` | period | 创建考核期批次，返回 fa_no（需后续逐个零件 add_record） |
| `sales-forecast__forecast_assessment__add_record` | fa_no, part_no, veh_model, period, fcst_qty, actual_qty, settle_qty, base_qty, adj_qty | 添加单零件考核记录，自动计算转化率与偏差量 |
| `sales-forecast__forecast_assessment__calculate` | period | 批量计算考核期所有记录指标（从 D09/D04 取快照后重算） |
| `sales-forecast__forecast_assessment__attribute` | fa_no, part_no, period, attribution, result, evidence="" | 归因认定——免责剔除须附举证 |
| `sales-forecast__forecast_assessment__get` | fa_no | 获取单条考核记录 |
| `sales-forecast__forecast_assessment__list` | part_no="", period="", result="" | 按零件/周期/考核结论筛选列表 |
| `sales-forecast__forecast_assessment__get_fva_view` | part_no, period | FVA 视图：基线误差 vs 核定误差，量化各环节价值贡献 |
| `sales-forecast__forecast_assessment__get_trust_discount` | oem_code | 供 D04 调用：获取客户信任折扣系数（消耗口径→报数口径转换） |

## 三、标准工作流
1. **创建考核期**：`create(period)` → 返回 fa_no。注意初始记录为空壳，需后续逐零件填充。
2. **逐零件录入**：从 D09 发布快照与结算/发运实绩取数，逐个零件调 `add_record(...)`，系统自动计算 conv_rate（转化率 = actual_qty / fcst_qty）与 dev_qty（偏差 = actual_qty - fcst_qty）。
3. **批量计算**：考核期末 `calculate(period)` → 对全周期所有记录重算 conv_rate 与 dev_qty。
4. **归因认定**：对每条记录调 `attribute(fa_no, part_no, period, attribution, result, evidence)`——免责剔除必须附举证材料。
5. **FVA 分析**：`get_fva_view(part_no, period)` → 拆解基线误差与核定误差，计算 FVA = base_error - adj_error，正值表示核定环节降低了误差。
6. **D04 取信任折扣**：D04 生成基线时调 `get_trust_discount(oem_code)` 获取客户级信任折扣系数，失败降级默认 1.0。

## 四、前置条件与注意事项
- `add_record` 中 `fcst_qty` 为 0 时，`conv_rate` 计算式为 `actual_qty / max(abs(fcst_qty), 0.01)` 避免除零，但此时转化率无业务意义，建议先检查预测数据。
- **归因结论三选一**："计入考核"/"免责剔除"/"归因流程·策略"，输入其他值抛错。
- **免责剔除必须举证**：result="免责剔除" 且 evidence 为空时抛错。举证材料可为"外部减产信息/销量骤降/结算趋势/客户函件"。
- `get_fva_view` 依赖 settle_qty/base_qty/adj_qty 字段——三者缺一则误差数据为 0，FVA 无意义。
- `get_trust_discount` 为跨应用弱依赖：调用 system_config 失败时降级返回 coefficient=1.0、direction="直采"、source="默认"，不阻断流程。
- 考核周期 cycle 字段与 period 一致，用于按考核期批量筛选。
- 归因认定结果存储在 attribution 和 result 字段中，assessor 字段记录操作人。

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步 |
|---|---|---|
| 考核单 {fa_no} 不存在 | 单号错误或已删除 | 用 list 按周期查找正确单号 |
| 考核结论必须为：计入考核/免责剔除/归因流程·策略 | result 不在合法枚举中 | 提示用户从三个选项中选择 |
| 免责剔除须附举证（外部减产信息/销量骤降/结算趋势/客户函件） | 免责剔除但 evidence 为空 | 向用户索要举证材料后重试 |
