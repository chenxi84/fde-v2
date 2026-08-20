# md_fcst_version -- 月度版本主数据

## 一、应用简介
月度版本主数据聚合根。计划周期节奏载体，触发自动生成行、期间折算基准。主键 = fcst_version。数据存同名 SQLite 库。无主动跨应用调用（被 forecast_snapshot.open_version 和 demand_release.publish 调用）。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `forecast__md_fcst_version__create` | fcst_version*(str), base_period*(str), periods*(list), opening_date(str) | 新建月度版本。periods 至少一项；同一时刻只能有一个活跃版本 |
| `forecast__md_fcst_version__get` | fcst_version*(str) | 取单个版本（periods 自动 JSON 解析为 list） |
| `forecast__md_fcst_version__list` | page(int), page_size(int) | 列表查询全部版本（按 fcst_version DESC），返回 {total, items} |
| `forecast__md_fcst_version__get_active` | 无 | 取当前活跃版本（status=活跃 的最新一条） |
| `forecast__md_fcst_version__set_linked` | fcst_version*(str), rel_no(str) | R 版发布联动锁定：status 活跃 -> 锁定，记录 linked_batch |

## 三、标准工作流
1. 月初创建版本：`create(fcst_version="2026M09", base_period="2026-09", periods=["2026-10","2026-11","2026-12"])` -> N+1~N+3 期间
2. 预测流程中：`get_active()` 取当前活跃版本号，作为其他应用的 fcst_version 入参
3. R 版发布时，demand_release.publish 自动调 `set_linked(fcst_version, rel_no)` 锁定版本
4. 版本锁定后：新建下一周期版本的 create 方可成功（系统检查无活跃版本才允许创建）

## 四、前置条件与注意事项
- 同时只能有一个 status=活跃 的版本；创建新版本前旧版本须已锁定
- periods 以 JSON 数组存储（如 ["2026-10","2026-11","2026-12"]）
- get_active 无活跃版本时抛 FdeError
- set_linked 由 demand_release.publish 自动调用，一般不需 Agent 手动触发
- 版本锁定后不可逆

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对 |
|---------|------|-----------|
| "版本号必填，不能为空" | create/get/set_linked 缺 fcst_version | 补全版本号 |
| "版本 ... 已存在" | fcst_version 重复 | 检查已有版本，或使用其他版本号 |
| "锚定期间必填" | base_period 为空 | 提供锚定期间（如 2026-09） |
| "对应期间（periods）必填且至少一项" | periods 为空或非 list | 传入至少包含一个期间的 list |
| "当前已有活跃版本 ...，请先完成或锁定旧版本后再创建新版本" | 已有活跃版本 | 先完成当前版本预测周期，或调 set_linked 锁定后创建新版本 |
| "版本号必填" | get/set_linked 缺 fcst_version | 补全版本号 |
| "版本 ... 不存在" | get/set_linked 查无此版本 | 先 list 核对版本号 |
| "无活跃版本，请先创建月度版本" | get_active 无活跃版本 | 先 create 创建新版本 |
| "版本 ... 已锁定" | set_linked 重复锁定 | 告知用户版本已锁定，无需重复操作 |
| "分页参数非法" | page/page_size 无法转 int | 传入合法整数值 |
