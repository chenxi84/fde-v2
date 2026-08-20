# attainment -- 达成率与置信度

## 一、应用简介
达成率与置信度聚合根。月度闭环自动生成客户预测达成率与置信系数，供下期加工表置信度调整使用。主键 = oem_code + period + horizon。数据存同名 SQLite 库。数据来源类型：自动参考创建（由月度闭环 compute_batch 触发，前端禁止创建入口）。跨应用调用：forecast_snapshot.list、md_customer.get。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `forecast__attainment__compute` | oem_code*(str), period*(str) | 按月+客户计算 H1/H2/H3 三个 horizon 的达成率与置信系数 |
| `forecast__attainment__compute_batch` | fcst_version*(str) | 批量计算（月度闭环触发）：对全部客户计算最新期间的达成率 |
| `forecast__attainment__get` | oem_code*(str), period*(str) | 取客户某期间全部 horizon 的达成率数据（返回 list） |
| `forecast__attainment__list` | oem_code(str), period(str), horizon(str), page(int), page_size(int) | 列表查询（oem_code 支持模糊搜索），返回 {total, items} |
| `forecast__attainment__get_conf_factor` | oem_code*(str), period*(str) | 取置信系数（默认 1.0），供加工表置信度调整使用 |

## 三、标准工作流
1. 月度闭环：发布完成后调 `compute_batch(fcst_version)` 批量计算全部客户达成率
2. 查达成率：`get(oem_code, period)` 获取某客户某期间的 H1/H2/H3 三层达成率
3. 加工表取置信系数：`get_conf_factor(oem_code, period)` 获取该客户期间的置信系数（默认 1.0），填入 forecast_processing.fill_line 的 conf_adj 依据

## 四、前置条件与注意事项
- compute_batch 依赖 forecast_snapshot 中有对应 fcst_version 的快照数据
- horizon 枚举：H1（当期 M+1 预测）、H2（上月 M+2 预测）、H3（前两月 M+3 预测）
- 达成率 = settle_qty / snap_qty（snap_qty > 0 时）
- 置信系数通过近 3 期达成率滚动平均计算，截断 [0.8, 1.2]，达成率 >= 0.95 返回 1.0
- 结算数据 V1 stub：寄售客户默认返回快照量的 95%，非寄售返回 0
- INSERT OR REPLACE 语义：同一主键重复 compute 会覆盖

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对 |
|---------|------|-----------|
| "客户编码必填" | compute 缺 oem_code | 补全客户编码 |
| "期间必填" | compute 缺 period | 补全期间 |
| "版本号必填" | compute_batch 缺 fcst_version | 提供版本号 |
| "取快照数据失败: ..." | 跨应用调 forecast_snapshot 失败 | 检查 fcst_version 是否有快照数据 |
| "客户编码和期间必填" | get 缺联合键 | 补全两个参数 |
| "客户 ... 期间 ... 的达成率数据不存在" | get 查无数据 | 先调 compute 或 compute_batch 生成数据 |
| "horizon 只能为 H1/H2/H3" | list 的 horizon 筛选不合法 | 修正为 H1/H2/H3 |
| "分页参数非法" | page/page_size 无法转 int | 传入合法整数值 |
