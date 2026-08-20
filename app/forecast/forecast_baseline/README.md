# forecast_baseline -- 统计基线

## 一、应用简介
统计基线聚合根。基于寄售结算量（干净口径）的客观统计锚，系统预计算+计划确认。主键 = base_batch + oem_code + plant_code + part_no + period。数据存同名 SQLite 库。跨应用调用：forecast_snapshot.list、md_customer.get。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `forecast__forecast_baseline__generate` | base_batch*(str), fcst_version*(str) | 按月生成基线行集：从快照行集展开，基于历史结算量计算基线值（指数平滑 α=0.3 / 借用） |
| `forecast__forecast_baseline__confirm` | base_batch*(str), oem_code*(str), plant_code*(str), part_no*(str), period*(str) | 计划确认单行 |
| `forecast__forecast_baseline__confirm_batch` | base_batch*(str) | 计划确认整批（预计算 -> 已确认） |
| `forecast__forecast_baseline__update_method` | base_batch*(str), oem_code*(str), plant_code*(str), part_no*(str), period*(str), base_method*(str) | 调整方法/参数（须登记依据） |
| `forecast__forecast_baseline__get` | base_batch*(str), oem_code*(str), plant_code*(str), part_no*(str), period*(str) | 取单行基线 |
| `forecast__forecast_baseline__list` | base_batch(str), oem_code(str), plant_code(str), part_no(str), period(str), status(str), base_path(str), page(int), page_size(int) | 列表查询，返回 {total, items} |
| `forecast__forecast_baseline__get_batch_status` | base_batch*(str) | 批次状态汇总：总数、预计算/已确认分布 |

## 三、标准工作流
1. 快照版本准备好后：`generate(base_batch, fcst_version)` 自动生成基线行集
2. 计划员逐行或批量确认：`confirm_batch(base_batch)` 或逐行 `confirm(...)`
3. 对借用路径行可调整方法：`update_method(...)` 登记变更依据

## 四、前置条件与注意事项
- generate 前须确保 forecast_snapshot 中 fcst_version 有数据（已 opening + fill）
- base_batch 生成后不可重复 generate（同名批次已存在会报错）
- base_path 由系统根据历史数据量自动判定（>=3 期->时序外推，<3 期->借用）
- 寄售客户取历史结算量，非寄售客户目前返回空历史（V1 stub），全部走借用路径
- status 只有"预计算"/"已确认"两种；已确认不可回退

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对 |
|---------|------|-----------|
| "基线批次必填" | base_batch 为空 | 请用户提供基线批次号 |
| "预测版本必填" | fcst_version 为空 | 先调 md_fcst_version.get_active 确认活跃版本 |
| "基线批次 ... 已存在，不允许重复生成" | 同名批次已 generate | 使用新批次号或告知用户该批次已存在 |
| "取快照版本 ... 数据失败" | 跨应用调用 forecast_snapshot 失败 | 检查快照版本是否存在且有数据 |
| "快照版本 ... 无数据，无法生成基线" | 快照行集为空 | 先执行 forecast_snapshot.open_version + fill |
| "该行已确认" | confirm 重复操作 | 告知用户该行已确认 |
| "基线批次、客户编码、工厂编码、零件号、期间均必填" | 单行操作缺参数 | 补全缺失的五个参数 |
| "基线行不存在：..." | 查询的基线行不存在 | 先 list 核对基线行是否存在 |
| "方法/参数描述必填（变更须登记依据）" | update_method 未填依据 | 请用户提供变更理由 |
| "状态筛选不合法" | status 不是 预计算/已确认 | 修正状态筛选值 |
| "基线路径筛选不合法" | base_path 不是 时序外推/借用 | 修正路径筛选值 |
| "分页参数非法" | page/page_size 无法转 int | 传入合法整数值 |
