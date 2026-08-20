# strategy_simulation 应用 · Agent 操作指南

## 一、应用简介
策略仿真拟合表——基线方法的"军火库"，回测选优输出方法+参数。聚合根 `StrategySimulation`，主键 `fit_no`（编码 D10-YYYYQ{N}-DDHHMM），一行一零件一车型。对历史充足的零件，多候选策略（如移动平均/Holt-Winters/Croston 等）进行滚动回测，按 MAPE/偏差/服务水平/库存成本综合打分排名，选定最优策略供 D04 基线生成使用。综合分低于可接受线（60 分）时建议转 D05 基线借用。跨应用调用：independent_event（获取清洗标记，排除异常事件干扰回测）。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `sales-forecast__strategy_simulation__create` | part_no, veh_model, demand_shape, data_range | 新建拟合任务，状态「拟合中」 |
| `sales-forecast__strategy_simulation__add_candidate` | fit_no, strategy, inv_policy | 添加候选策略（strategy=方法名，inv_policy=库存策略） |
| `sales-forecast__strategy_simulation__run_backtest` | fit_no | 执行滚动回测，计算 MAPE/偏差/服务水平/库存成本/综合分并排名 |
| `sales-forecast__strategy_simulation__select_strategy` | fit_no, cand_no | 选定策略（综合分<60 拒绝）；状态→「生效中」 |
| `sales-forecast__strategy_simulation__get` | fit_no | 获取拟合单全貌（header + 候选策略列表含评分排名） |
| `sales-forecast__strategy_simulation__get_strategy` | part_no, veh_model | 供 D04 调用：获取该零件-车型当前生效策略（最新生效中的 selected=1） |
| `sales-forecast__strategy_simulation__list` | part_no="", status="" | 按零件/状态筛选拟合任务列表 |

## 三、标准工作流
1. **新建拟合任务**：`create(part_no, veh_model, demand_shape, data_range)` → 状态「拟合中」。
2. **添加候选策略**：逐候选策略调用 `add_candidate(fit_no, strategy, inv_policy)`——至少添加 2 个候选以形成对比。
3. **执行回测**：`run_backtest(fit_no)` → 对全部候选计算 MAPE/偏差/服务水平/库存成本，按 score 降序排名，状态→「已选定」。
4. **选定策略**：`select_strategy(fit_no, cand_no)` → 综合分 >= 60 则选定，标记 selected=1，状态→「生效中」；综合分 < 60 拒绝，建议转 D05 基线借用。
5. **D04 取策略**：D04 生成基线时调 `get_strategy(part_no, veh_model)` 获取生效中的策略方法及库存策略。

## 四、前置条件与注意事项
- `add_candidate` 仅在「拟合中」状态可调用；`run_backtest` 仅在「拟合中」状态可调用。
- `run_backtest` 前必须至少有一个候选策略，否则抛"无候选策略"。
- **综合分门槛**：`select_strategy` 时若候选综合分 < 60，拒绝并提示"建议转借用基线 D05"——此时应走 baseline_borrowing 流程。
- `select_strategy` 会自动清除同拟合单下旧的 selected 标记，确保只有唯一生效策略。
- `get_strategy` 按 part_no + veh_model 查询最新生效中（status='生效中' + selected=1）的策略，无结果返回 None。
- data_range 可指定回测数据范围（如"2024-01~2025-12"），供回测引擎确定训练/测试窗口。
- demand_shape 用于描述需求形态（平稳/趋势/季节性/间歇性），辅助策略初筛。

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步 |
|---|---|---|
| 拟合单 {fit_no} 不存在 | 单号错误或已删除 | 用 list 按条件查找正确单号 |
| 仅拟合中状态可添加候选 | 已执行回测或已选定 | 如需追加策略，新建拟合任务 |
| 仅拟合中状态可执行回测 | 已回测过 | get 查看当前排名结果；如需重测，新建拟合任务 |
| 无候选策略，请先添加 | fit_no 下无候选 | 先调 add_candidate 添加至少 1 个候选策略 |
| 状态 {status} 不可选定 | 非「已选定」或「拟合中」 | get 确认当前状态；已生效中无需重复选定 |
| 候选 {cand_no} 不存在 | cand_no 输入错误 | get 查看候选列表确认正确编号 |
| 候选综合分 {score} 低于可接受线(60)，建议转借用基线D05 | 策略质量不足 | 终止策略仿真流程，转 baseline_borrowing.create 借用基线 |
