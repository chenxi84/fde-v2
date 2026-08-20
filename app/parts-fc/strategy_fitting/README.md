# strategy_fitting — Agent 操作指南

## 一、应用简介
策略仿真拟合（StrategyFitting）是基线方法的"军火库"：在清洗后历史数据上滚动回测，为每个物料选出拟合最优的预测策略（方法+参数+配套库存策略），供 D04 基线生成直接引用。

- **主键**: `fit_no`（D10-YYYYQN-NNN）
- **数据库**: `strategy_fitting.db`
- **跨应用调用**: 被 demand_processing 调用 get_strategy/forecast；调用 independent_event（取清洗标记）

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `parts-fc__strategy_fitting__create` | part_no(必填), veh_model(必填), demand_shape(必填), data_range(必填), backtest_spec(可选) | 新建拟合单，系统自动枚举候选策略 |
| `parts-fc__strategy_fitting__add_candidate` | fit_no(必填), strategy(必填), inv_policy(必填) | 人工增补候选策略 |
| `parts-fc__strategy_fitting__get` | fit_no(必填) | 取拟合单全貌（单头+全部候选明细+回测结果） |
| `parts-fc__strategy_fitting__list` | part_no?, veh_model?, demand_shape?, status?, fitter? | 筛选拟合单列表 |
| `parts-fc__strategy_fitting__run_backtest` | fit_no(必填) | 执行滚动回测，产出各候选 MAPE/Bias/Score/Rank |
| `parts-fc__strategy_fitting__select` | fit_no(必填), cand_no(必填), select_reason(必填) | 选定最优候选 |
| `parts-fc__strategy_fitting__confirm_effective` | fit_no(必填) | 确认策略生效（替代旧生效策略） |
| `parts-fc__strategy_fitting__get_strategy` | part_no(必填), veh_model(必填) | 取当前生效策略（供 D04 调用） |
| `parts-fc__strategy_fitting__forecast` | method(必填), params(必填-JSON), history_data(必填-JSON), horizon(必填) | 执行预测外推：SMA/HoltWinters/SeasonalDecomp/Gompertz |
| `parts-fc__strategy_fitting__refit` | fit_no(必填), mode(必填: monthly/quarterly) | 重拟合：月度轻量参数重估 或 季度全量重选 |
| `parts-fc__strategy_fitting__shadow_compare` | old_fit_no(必填), new_fit_no(必填) | 影子并行对比 |

## 三、标准工作流

### 3.1 首次拟合（历史充足物料）
1. 确认物料历史 >= 12 个月 → `create` 新建拟合单
2. 审核系统枚举候选 → 可选 `add_candidate` 增补
3. `run_backtest` 执行回测 → `get` 查看结果
4. `select` 选定最优候选 → `confirm_effective` 生效

### 3.2 D04 基线生成调用
1. `get_strategy(part_no, veh_model)` 取生效策略
2. `forecast(method, params, history_data, horizon)` 执行外推计算
3. 若无生效策略 → 触发首次拟合，或走 baseline_borrowing

## 四、前置条件与注意事项
- 创建拟合单前 part_no+veh_model 必须在 vehicle_part_map 中有生效映射
- 历史数据区间须 >= 12 个月且覆盖完整季节周期（不足则提示走 D05）
- 候选明细 >= 2 条方可执行回测
- 回测数据必须清洗（脉冲/断点/异常已剔除）
- 回测严禁未来信息泄漏（训练窗口截止时间 <= 验证窗口起始时间）
- 策略切换须登记依据（影子对比报告或人工判定理由）
- 同一 part_no+veh_model 只能有一个生效中拟合单

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步 |
|---------------|------|-------------|
| 零件 {part_no} 车型 {veh_model} 在 vehicle_part_map 中不存在生效映射 | 映射缺失 | 先在 vehicle_part_map 中创建该零件的生效映射行 |
| 历史数据区间不足12个月，建议走基线借用(D05) | 历史不足 | 改用 baseline_borrowing.create 登记借用基线 |
| 候选策略至少需要2条才能执行回测 | 候选不足 | 用 add_candidate 增补至少1条候选策略 |
| 回测数据必须经过清洗 | 数据未清洗 | 确认 D03 拆解已完成、D06 异常已标记 |
| 最优候选综合分低于可接受线({theta_accept})，不建议选定 | 候选质量差 | 转 D05 基线借用 或 人工判断后强制选定 |
| 该物料已有生效策略 {old_fit_no}，确认后将替代旧策略 | 策略冲突 | 确认新策略确实更优后再执行 |
| 未知预测方法: {method} | 方法名错误 | 只支持 SMA/HoltWinters/SeasonalDecomp/Gompertz |
| {method} 需要至少 {min_len} 期历史数据，当前仅 {len} 期 | 数据不足 | 等待更多数据积累或换用对数据要求更低的方法 |
