# md_project -- 项目台账

## 一、应用简介
项目台账聚合根。管理项目生命周期信息，定义活跃行集（进行中项目）。主键 = project_no。数据存同名 SQLite 库。跨应用调用：md_customer.get（创建时校验客户存在）。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `forecast__md_project__create` | project_no*(str), project_name*(str), stage*(str), oem_code*(str), plant_code*(str), veh_model(str), platform(str), sop(str), eop(str), owner(str) | 新建项目。stage: 待定点/定点中/进行中/EOP关闭；校验 oem_code+plant_code 的客户存在 |
| `forecast__md_project__get` | project_no*(str) | 取单个项目 |
| `forecast__md_project__list` | project_no(str), stage(str), oem_code(str), plant_code(str), page(int), page_size(int) | 列表查询（project_no/oem_code/plant_code 支持模糊搜索），返回 {total, items} |
| `forecast__md_project__list_active` | 无 | 取进行中项目列表（stage=进行中），供快照 opening 用 |
| `forecast__md_project__update` | project_no*(str), project_name(str), stage(str), veh_model(str), platform(str), sop(str), eop(str), owner(str) | 更新项目信息（仅更新传入的非空字段） |

## 三、标准工作流
1. 新建项目：先确认客户存在（md_customer.get），再 `create(...)` 创建项目
2. 维护阶段：`update(project_no, stage="进行中")` 推进项目阶段
3. 查询活跃项目：`list_active()` 获取所有进行中项目，供快照 opening 使用
4. 列表筛选：`list(stage="进行中", oem_code="xxx")` 按阶段和客户筛选

## 四、前置条件与注意事项
- project_no 唯一，不可重复
- 创建时校验 oem_code + plant_code 在 md_customer 中存在（跨应用调用）
- stage 枚举：待定点 -> 定点中 -> 进行中 -> EOP关闭（不可逆，但不强制校验）
- list_active 仅返回 stage=进行中的项目，是 forecast_snapshot open_version 的数据源
- 项目被 md_project_part 弱引用，删除项目需先清理零件映射

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对 |
|---------|------|-----------|
| "项目号必填，不能为空" | create/get/update 缺 project_no | 补全项目号 |
| "项目 ... 已存在" | project_no 重复 | 使用 update 修改而非 create |
| "项目名称必填，不能为空" | project_name 为空 | 请用户提供项目名称 |
| "项目阶段只能为 待定点/定点中/进行中/EOP关闭" | stage 不在枚举中 | 修正阶段值 |
| "客户编码和工厂编码必填" | oem_code 或 plant_code 为空 | 补全客户和工厂编码 |
| "客户 .../... 不存在" | 跨应用校验 md_customer 失败 | 先在 md_customer 中创建该客户 |
| "项目 ... 不存在" | get/update 时查无此项目 | 先 list 确认项目存在 |
| "项目号必填" | 操作缺 project_no | 补全项目号 |
| "项目名称不能为空" | update 设名称为空 | 传入非空名称或跳过该字段 |
| "项目阶段筛选不合法" | list 的 stage 不在枚举中 | 修正阶段筛选值 |
| "分页参数非法" | page/page_size 无法转 int | 传入合法整数值 |
