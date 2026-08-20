# md_project_part -- 项目-零件映射

## 一、应用简介
项目-零件映射聚合根。管理项目x零件x车型的量纲关系（单件用量 usage / 供应份额 share），是通用件识别与断点定量的依据。主键 = project_no + part_no。数据存同名 SQLite 库。跨应用调用：md_project.get、md_project.list_active、md_material.get。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `forecast__md_project_part__create` | project_no*(str), part_no*(str), veh_model(str), usage(float), share(float), eff_from(str), eff_to(str) | 新建映射。校验 project_no 和 part_no 分别存在于 md_project 和 md_material；share 必须在 0~1 之间 |
| `forecast__md_project_part__get` | project_no*(str), part_no*(str) | 取单条映射 |
| `forecast__md_project_part__list` | project_no(str), part_no(str), veh_model(str), page(int), page_size(int) | 列表查询（均支持模糊搜索），返回 {total, items} |
| `forecast__md_project_part__list_active` | 无 | 取进行中项目的全部零件映射（跨应用调 md_project.list_active 获取活跃项目列表，再过滤本地数据） |
| `forecast__md_project_part__list_by_part` | part_no*(str) | 按零件查所有项目映射，用于通用件识别（同一 part_no 出现在 >=2 个不同客户的项目中） |
| `forecast__md_project_part__update` | project_no*(str), part_no*(str), veh_model(str), usage(float), share(float), eff_from(str), eff_to(str) | 更新映射信息（仅更新传入的非空字段） |

## 三、标准工作流
1. 维护映射关系：`create(project_no, part_no, ...)` 新建映射，`update(...)` 修改用量/份额
2. 通用件识别：`list_by_part(part_no)` 查同一零件在哪些项目中出现，>=2 个项目则为通用件
3. 快照 opening 支持：`list_active()` 获取进行中项目的全部零件映射
4. 列表查询：`list(project_no="xxx")` 查看某项目下所有零件

## 四、前置条件与注意事项
- 创建时校验 project_no 在 md_project 中存在，part_no 在 md_material 中存在（跨应用调用）
- share 取值 0~1，表示该零件在该项目中的供应份额
- list_active 通过跨应用调用获取活跃项目列表，不跨库 JOIN
- 同一 project_no+part_no 唯一，不可重复创建
- eff_from/eff_to 为生效日期范围，字符串形式自由填写
- 映射是快照 opening 的关键数据源，删除映射会导致快照缺失该零件行

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对 |
|---------|------|-----------|
| "项目号必填，不能为空" | create 缺 project_no | 补全项目号 |
| "零件号必填，不能为空" | create 缺 part_no | 补全零件号 |
| "项目 ... 与零件 ... 的映射已存在" | 联合主键重复 | 使用 update 修改而非 create |
| "项目 ... 不存在" | 跨应用校验 md_project 失败 | 先在 md_project 中创建该项目 |
| "物料 ... 不存在" | 跨应用校验 md_material 失败 | 先在 md_material 中创建该物料 |
| "供应份额必须在 0~1 之间" | share 超出范围 | 传入 0~1 之间的数值 |
| "项目号和零件号必填" | get/update 缺联合主键 | 补全两个参数 |
| "项目 ... 与零件 ... 的映射不存在" | get/update 时查无此映射 | 先 list 确认映射存在 |
| "零件号必填" | list_by_part 缺 part_no | 补全零件号 |
| "数值参数非法" | usage/share 等无法转 float | 传入合法数值 |
| "分页参数非法" | page/page_size 无法转 int | 传入合法整数值 |
