# md_material -- 物料主数据

## 一、应用简介
物料主数据聚合根。管理零件号/名称/单位基础信息。主键 = part_no。数据存同名 SQLite 库。无跨应用调用（纯主数据维护）。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `forecast__md_material__create` | part_no*(str), part_name*(str), uom(str), mat_type(str) | 新建物料。uom 默认"件"，mat_type 默认"成品" |
| `forecast__md_material__get` | part_no*(str) | 取单个物料 |
| `forecast__md_material__list` | part_no(str), part_name(str), mat_type(str), page(int), page_size(int) | 列表查询（part_no/part_name 支持模糊搜索），返回 {total, items} |
| `forecast__md_material__update` | part_no*(str), part_name(str), uom(str), mat_type(str) | 更新物料信息（仅更新传入的非空字段） |
| `forecast__md_material__import_batch` | rows*(list) | 批量导入：逐行判定 create 或 update，返回 {created, updated, errors} |

## 三、标准工作流
1. 维护物料信息：`create(...)` 新建，`update(...)` 修改
2. 查询：`list(part_no="xxx")` 模糊搜索，或用 `get(part_no)` 精确查找
3. 批量导入：准备 rows（每行含 part_no/part_name/uom/mat_type），调 `import_batch(rows)` 批量创建或更新

## 四、前置条件与注意事项
- part_no 为唯一主键，不可重复
- part_name 不可为空
- uom 默认为"件"，mat_type 默认为"成品"
- list 中 part_no 和 part_name 为模糊匹配（LIKE）
- import_batch 中已存在的记录走 update，不存在的走 create
- 物料被 md_project_part 和 md_part_replace 弱引用，删除物料需先清理引用（无级联删除）

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对 |
|---------|------|-----------|
| "零件号必填，不能为空" | part_no 为空 | 请用户提供零件号 |
| "物料 ... 已存在" | part_no 重复 | 使用 update 修改而非 create |
| "零件名称必填，不能为空" | part_name 为空 | 请用户提供零件名称 |
| "物料 ... 不存在" | get/update 时查无此物料 | 先 list 确认物料存在，或先 create |
| "零件号必填" | update 缺 part_no | 补全零件号 |
| "零件名称不能为空" | update 时名称设为空 | 传入非空名称或跳过该字段 |
| "导入数据不能为空" | import_batch 传入空 rows | 传入至少一条数据 |
| "分页参数非法" | page/page_size 无法转 int | 传入合法整数值 |
