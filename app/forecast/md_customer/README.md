# md_customer -- 客户主数据

## 一、应用简介
客户主数据聚合根。管理客户/OEM 工厂基础信息与结算模式（寄售/非寄售）。主键 = oem_code + plant_code。数据存同名 SQLite 库。无跨应用调用（纯主数据维护）。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `forecast__md_customer__create` | oem_code*(str), oem_name*(str), plant_code*(str), plant_name*(str), settle_mode*(str) | 新建客户。settle_mode: 寄售/非寄售 |
| `forecast__md_customer__get` | oem_code*(str), plant_code*(str) | 取单个客户（按联合主键） |
| `forecast__md_customer__list` | oem_code(str), plant_code(str), settle_mode(str), page(int), page_size(int) | 列表查询（oem_code/plant_code 支持模糊搜索），返回 {total, items} |
| `forecast__md_customer__update` | oem_code*(str), plant_code*(str), oem_name(str), plant_name(str), settle_mode(str) | 更新客户信息（仅更新传入的非空字段） |
| `forecast__md_customer__import_batch` | rows*(list) | 批量导入：逐行判定 create 或 update，返回 {created, updated, errors} |

## 三、标准工作流
1. 维护客户信息：`create(...)` 新建，`update(...)` 修改
2. 查询：`list(settle_mode="寄售")` 筛选寄售客户，或用 get 精确查找
3. 批量导入：准备 rows（每行含 oem_code/plant_code/oem_name/plant_name/settle_mode），调 `import_batch(rows)` 批量创建或更新

## 四、前置条件与注意事项
- oem_code + plant_code 联合唯一，作为客户标识
- settle_mode 枚举：寄售 / 非寄售，影响 baseline 生成时的历史数据源选择
- list 中 oem_code 和 plant_code 为模糊匹配（LIKE）
- import_batch 中已存在的记录走 update，不存在的走 create
- 名称字段（oem_name / plant_name）不可设为空字符串

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对 |
|---------|------|-----------|
| "客户编码必填，不能为空" | oem_code 为空 | 请用户提供客户编码 |
| "客户名称必填，不能为空" | oem_name 为空 | 请用户提供客户名称 |
| "工厂编码必填，不能为空" | plant_code 为空 | 请用户提供工厂编码 |
| "工厂名称必填，不能为空" | plant_name 为空 | 请用户提供工厂名称 |
| "结算模式只能为 寄售 或 非寄售" | settle_mode 不在枚举中 | 修正为 寄售 或 非寄售 |
| "客户 .../... 已存在" | 联合主键重复 | 使用 update 修改而非 create，或换一套编码 |
| "客户 .../... 不存在" | get/update 时查无此客户 | 先 list 确认客户存在，或先 create |
| "客户编码和工厂编码必填" | get/update 缺联合主键 | 补全两个参数 |
| "客户名称不能为空" | update 时名称设为空 | 传入非空名称或跳过该字段 |
| "工厂名称不能为空" | update 时工厂名设为空 | 传入非空名称或跳过该字段 |
| "结算模式筛选不合法" | list 的 settle_mode 不在枚举中 | 修正为 寄售 或 非寄售 |
| "导入数据不能为空" | import_batch 传入空 rows | 传入至少一条数据 |
| "分页参数非法" | page/page_size 无法转 int | 传入合法整数值 |
