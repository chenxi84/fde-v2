# forecast_assessment — Agent 操作指南

## 一、应用简介
预测转单率考核（ForecastAssessment）是毛需求加工链的事后闭环：考核预测准确率（FVA/达成率）与转单率，按可控性归因（销售多报/OEM需求塌方/事件影响/基线方法失准），反哺信任折扣（D04 信任校准）、策略重拟合（D10）、参数校准。

- **主键**: `fa_no`（FA-YYYYMM-NNN）
- **数据库**: `forecast_assessment.db`
- **跨应用调用**: 调用 demand_release.get（取发布快照）、demand_processing.get_approved（取基线快照）；被 D04 调用 get_trust_discount/get_fva；反哺 D10 告警触发

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `parts-fc__forecast_assessment__create` | part_no(必填), veh_model(必填), period(必填), fcst_qty(必填), actual_qty(必填), settle_qty(必填), base_qty(必填), adj_qty(必填) | 创建考核记录（系统自动取快照+实际） |
| `parts-fc__forecast_assessment__get` | fa_no(必填) | 取考核详情+完整审计日志 |
| `parts-fc__forecast_assessment__list` | part_no?, period?, cycle?, attribution?, result?, assessor? | 筛选考核记录列表 |
| `parts-fc__forecast_assessment__attribute` | fa_no(必填), attribution(必填), evidence(必填) | 归因认定：销售多报/OEM需求塌方/事件影响/基线方法失准 |
| `parts-fc__forecast_assessment__conclude` | fa_no(必填), result(必填: 计入考核/免责剔除/归因流程·策略) | 考核结论（须与归因逻辑一致） |
| `parts-fc__forecast_assessment__appeal` | fa_no(必填), new_evidence(必填) | 销售申诉（须附新证据），状态回退待归因 |
| `parts-fc__forecast_assessment__get_trust_discount` | oem_code(必填), part_no? | 取客户/零件维度的信任折扣系数（供 D04 调用） |
| `parts-fc__forecast_assessment__get_fva` | part_no(必填), period(必填) | 取 FVA 数据：基线误差 vs 核定误差（供 D04/D10 调用） |

## 三、标准工作流

### 3.1 月度考核
1. 每月结算数据到达后，系统自动 `create` 创建考核记录
2. 总部计划审核 → `attribute` 归因认定（区分可控/不可控）
3. `conclude` 考核结论

### 3.2 申诉处理
1. 销售对考核结论有异议 → `appeal` 附新证据
2. 状态回退为"待归因" → 总部计划重新 `attribute` + `conclude`

### 3.3 反哺查询
- D04 信任校准：`get_trust_discount(oem_code)` → 获取该客户历史达成率与折扣系数
- D10 重拟合触发：若 FVA 显示 baseline 持续恶化 → D12 告警 → D10 触发即时重拟合

## 四、前置条件与注意事项
- 考核引用发布快照（R版）与实际结算，"当时报了什么、实际是什么"不可变
- 双口径各评各的：转单率（发运口径）评报数质量，FVA/准确率（消耗口径）评预测能力
- 可控性原则：只追可控、剔除不可控（OEM需求塌方须举证方可免责）
- 容忍区间 ±10%：区间内不追责
- 通用件考核上移到总量层面，不下沉到个别销售
- 归因"免责剔除" 时 evidence 强制非空（须附外部减产信息/销量骤降等证明）

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步 |
|---------------|------|-------------|
| 该零件+车型+期间已存在考核记录 | 重复创建 | 使用 list 查现有记录，如需更新走 appeal 流程 |
| 归因必须说明依据 | 归因时缺少 evidence | 补充举证材料（客户函件/外部数据/排产证据）后重试 |
| 归因与结论逻辑不一致：免责剔除只能对应 'OEM需求塌方' 归因 | 归因与结论矛盾 | 确认归因分类正确后调整结论，或反之 |
| 申诉必须提供新证据 | 申诉无证据 | 收集新的证明材料后重新申诉 |
| 无该客户/零件的考核记录，无法计算信任折扣 | 数据不足 | 等待该客户至少一个完整考核周期后再查询 |
| 转单率超出合理范围 | 数据异常 | 核对 actual_qty 数据源（IF-A4接口）是否正确 |