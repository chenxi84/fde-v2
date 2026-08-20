# md_part_replace -- 替换关系

## 一、应用简介
替换关系聚合根。管理零件间替换/替代关系与 ECN 依据。主键 = rel_no。数据存同名 SQLite 库。跨应用调用：md_material.get（创建时校验新旧件物料存在）。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `forecast__md_part_replace__create` | rel_no*(str), rel_type*(str), old_part*(str), new_part*(str), switch_date(str), ecn_no(str) | 新建替换关系。rel_type: 替换/替代；校验新旧件在 md_material 中存在；替换关系中新旧件不可相同 |
| `forecast__md_part_replace__get` | rel_no*(str) | 取单条替换关系 |
| `forecast__md_part_replace__list` | rel_type(str), old_part(str), new_part(str), status(str), page(int), page_size(int) | 列表查询（old_part/new_part 支持模糊搜索），返回 {total, items} |
| `forecast__md_part_replace__update` | rel_no*(str), rel_type(str), old_part(str), new_part(str), switch_date(str), ecn_no(str), status(str) | 更新替换关系（仅更新传入的非空字段） |
| `forecast__md_part_replace__disable` | rel_no*(str) | 失效替换关系（status 生效 -> 失效） |

## 三、标准工作流
1. 维护替换关系：`create(...)` 新建替换/替代关系，关联 ECN 编号
2. 查询：`list(old_part="xxx")` 查某旧件的所有替换关系，`list(rel_type="替换")` 按类型筛选
3. 变更：`update(...)` 更新切换日期、ECN 等信息
4. 失效：`disable(rel_no)` 将已不再适用的替换关系设为失效

## 四、前置条件与注意事项
- rel_no 唯一主键，不可重复
- rel_type 枚举：替换（旧件停用->新件启用）/ 替代（兼容替代，非强制切换）
- 替换关系（rel_type=替换）要求 old_part != new_part
- 创建时校验 old_part 和 new_part 在 md_material 中均存在（跨应用调用）
- status 枚举：生效 / 失效；已失效的关系不可再次 disable
- 替换关系被 part_level_adj 间接使用（作为断点处理依据），失效不影响已应用的调整

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对 |
|---------|------|-----------|
| "关系号必填，不能为空" | create/get/update 缺 rel_no | 补全关系号 |
| "替换关系 ... 已存在" | rel_no 重复 | 使用 update 修改而非 create |
| "关系类型只能为 替换/替代" | rel_type 不在枚举中 | 修正为 替换 或 替代 |
| "旧件号和新件号必填" | old_part 或 new_part 为空 | 补全两个件号 |
| "替换关系中旧件号与新件号不能相同" | rel_type=替换 且新旧件相同 | 换用不同件号，或改为替代关系 |
| "旧件物料 ... 不存在" | 跨应用校验 old_part 失败 | 先在 md_material 中创建该物料 |
| "新件物料 ... 不存在" | 跨应用校验 new_part 失败 | 先在 md_material 中创建该物料 |
| "关系号必填" | get/disable 缺 rel_no | 补全关系号 |
| "替换关系 ... 不存在" | get/update/disable 查无此关系 | 先 list 确认关系存在 |
| "关系类型筛选不合法" | list 的 rel_type 不在枚举中 | 修正筛选值 |
| "状态筛选不合法" | list 的 status 不是 生效/失效 | 修正状态筛选值 |
| "关系类型不合法" | update 的 rel_type 不在枚举中 | 修正为 替换 或 替代 |
| "旧件号不能为空" | update 设旧件为空 | 传入非空件号或跳过该字段 |
| "新件号不能为空" | update 设新件为空 | 传入非空件号或跳过该字段 |
| "状态不合法" | update 的 status 不是 生效/失效 | 修正状态值 |
| "替换关系已失效" | disable 已失效的关系 | 告知用户该关系已失效 |
| "分页参数非法" | page/page_size 无法转 int | 传入合法整数值 |
