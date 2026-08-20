# forecast_snapshot — 预测快照

## 一、应用简介
客户 N+1~N+3 月度滚动预测的唯一入口。主键 = fcst_version + oem_code + plant_code + part_no + period。数据存同名 SQLite 库。跨应用调用：md_fcst_version.get / get_active、md_project_part.list_active、md_project.get。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `forecast__forecast_snapshot__open_version` | fcst_version*(str) | 月度 opening：按活跃零件集自动生成 N+1~N+3 三行（标记"未提供"） |
| `forecast__forecast_snapshot__fill` | fcst_version*, oem_code*, plant_code*, part_no*, period*, orig_qty*(float), data_flag(str), source_channel(str) | 填/更新预测量。orig_qty 首次录入后冻结不可改 |
| `forecast__forecast_snapshot__get` | fcst_version*, oem_code*, plant_code*, part_no*, period* | 取单行快照 |
| `forecast__forecast_snapshot__list` | fcst_version, oem_code, plant_code, part_no, period, data_flag, page(int), page_size(int) | 列表查询，返回 `{total, items}` |
| `forecast__forecast_snapshot__get_version_status` | fcst_version*(str) | 版本状态：总行数、未填行数、渠道分布 |
| `forecast__forecast_snapshot__lock_version` | fcst_version*(str) | R版发布联动锁定（由 demand_release.publish 调用） |

## 三、标准工作流
1. 确认月度版本已创建：`md_fcst_version.get_active()` → 取 fcst_version
2. `open_version(fcst_version)` → 自动生成快照行
3. 销售对各行 `fill(...)` 填预测量
4. `get_version_status(fcst_version)` 查看完成率

## 四、前置条件与注意事项
- opening 前须确保 md_project_part 有活跃映射（进行中项目的零件）
- 快照行**不可变**：fill 后 orig_qty 永久冻结，变更须新版本
- data_flag="OEM未提供" 的行才能 fill
- 客户预测缺失时显式标记"未提供"，禁止隐性补 0

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对 |
|---------|------|-----------|
| "版本 … 非活跃状态" | 版本已锁定或不存在 | 先调 md_fcst_version.get_active 确认活跃版本 |
| "已有快照数据" | 重复 opening | 说明该版本已 opening，直接 fill 或使用新版本 |
| "快照行已录入，不可修改" | 行已填过 | 告知用户该行已锁定，变更请使用新版本创建新快照 |
| "快照行不存在" | 行未生成 | 先执行 open_version 生成行 |
| "无活跃零件" | 无进行中项目的零件映射 | 检查 md_project_part 是否有进行中项目的数据 |
