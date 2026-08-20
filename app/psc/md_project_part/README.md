# 项目零件映射 · md_project_part

## 一、应用简介

- **聚合根**: 项目零件映射（`MdProjectPart`），定义「项目 × 零件 × 车型」的用量/份额量纲关系。
- **主键**: 复合主键 `project_no + material_no`（一个项目对一个物料一条量纲）。
- **数据**: 存于本应用同名库 `md_project_part.db`（平台管理，应用不自行连接）。
- **跨应用调用**: `create` / `update` / `import_batch` 会通过 `self.fde.call` 校验引用完整性——
  - `md_project.get(project_no)` 校验项目存在（同组 `psc` 下的主数据应用）。
  - `md_material.get(material_no)` 校验物料存在（同组 `psc` 下的主数据应用）。

## 二、对外服务（工具）

| 工具名 | 参数（类型 / 必填 / 默认） | 说明 |
|---|---|---|
| `psc__md_project_part__create` | `project_no`(str, 必填)、`material_no`(str, 必填)、`veh_model`(str, 必填)、`usage`(数字, 必填)、`share`(数字, 必填) | 新建映射；校验引用存在、组合唯一、量纲范围 |
| `psc__md_project_part__get` | `project_no`(str, 必填)、`material_no`(str, 必填) | 按复合主键查单条映射详情 |
| `psc__md_project_part__list` | `project_no`(str, 选填, 模糊)、`material_no`(str, 选填, 模糊)、`veh_model`(str, 选填, 模糊)、`page`(int, 选填, 默认1)、`size`(int, 选填, 默认20) | 分页列表，返回 `{"items": [...], "total": N}` |
| `psc__md_project_part__update` | `project_no`(str, 必填, 定位键)、`material_no`(str, 必填, 定位键)、`veh_model`(str, 选填)、`usage`(数字, 选填)、`share`(数字, 选填) | 更新可编辑字段；主键不可改；重新校验引用 |
| `psc__md_project_part__list_by_material` | `material_no`(str, 必填) | 按物料号返回其全部项目映射（不分页，纯列表） |
| `psc__md_project_part__import_batch` | `rows`(list[dict], 必填) | 批量导入/更新（upsert），逐行校验，返回成功/失败摘要 |

## 三、标准工作流

1. **新建映射**：先 `list` 核对（或用 `md_project.list` / `md_material.list` 选号），确认 `project_no`、`material_no` 真实存在后，调 `create(project_no, material_no, veh_model, usage, share)`。
2. **查看列表/详情**：先 `list(project_no=..., material_no=..., veh_model=..., page=1, size=20)` 浏览；定位到目标行后调 `get(project_no, material_no)` 看完整量纲。
3. **修改量纲**：先 `get` 回填当前值，再 `update(project_no, material_no, veh_model=..., usage=..., share=...)`（只需传要改的字段）。
4. **按物料取全部项目映射**（供量纲折算/预测分摊）：直接调 `list_by_material(material_no)`，得到该物料在所有项目中的 `project_no / veh_model / usage / share`。
5. **批量导入 / PLM 冗余同步**：把导入行整理成 `rows = [{"project_no","material_no","veh_model","usage","share"}, ...]`，调 `import_batch(rows)`；按返回的 `errors` 逐条修正失败行后重导。

## 四、前置条件与注意事项

- **引用完整性铁律**：`project_no` 必须先存在于 `md_project`，`material_no` 必须先存在于 `md_material`；`create`/`update`/`import_batch` 均强制 `self.fde.call` 校验，禁止手工录入不存在的编号。
- **复合主键唯一**：`project_no + material_no` 全局唯一，重复创建会被拒绝。
- **量纲范围**：`usage`（单车用量）须 > 0；`share`（供应份额）须在 `[0, 1]` 区间（含 0 和 1）。
- **主键不可修改**：`update` 不接受变更 `project_no` / `material_no`；如需变更，先删除旧映射再新建（当前应用未提供删除服务，删除需另行处理）。
- **无删除服务**：V1 只增改不删，避免量纲折算/分摊级联问题。
- **list 返回格式**：`list` 返回 `{"items": [...], "total": N}`，`total` 为切片前全量行数；`page`/`size` 均传 `None` 时返回全部。
- **跨应用无分布式事务**：引用校验读的是其它应用的库，仅做存在性校验，不保证强一致。

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 下一步该怎么做 |
|---|---|---|
| `项目号不能为空` | project_no 缺失或空字符串 | 向用户索要项目号（可先调 `md_project.list` 让其挑选） |
| `物料号不能为空` | material_no 缺失或空字符串 | 向用户索要物料号（可先调 `md_material.list` 让其挑选） |
| `车型不能为空` | veh_model 缺失或空字符串 | 向用户索要车型 |
| `单车用量不能为空` / `单车用量格式非法` | usage 缺失或非数字 | 向用户索要合法的单车用量数值 |
| `供应份额不能为空` / `供应份额格式非法` | share 缺失或非数字 | 向用户索要合法的供应份额数值 |
| `单车用量须大于0` | usage ≤ 0 | 请用户改为正数（单车用量必须 > 0） |
| `供应份额须在0~1之间` | share 越界 | 请用户改为 0~1 之间的值（含 0 和 1） |
| `该项目-物料映射已存在` | project_no+material_no 组合已存在 | 改用 `update` 更新该映射，或换一个项目/物料组合 |
| `项目不存在` | 引用的 project_no 在 md_project 中不存在 | 先调 `md_project.list` 核对项目号，或先在 md_project 中建好该项目 |
| `物料不存在` | 引用的 material_no 在 md_material 中不存在 | 先调 `md_material.list` 核对物料号，或先在 md_material 中建好该物料 |
| `映射记录不存在` | get/update 目标映射不存在 | 先 `list` 核对 project_no+material_no，或改用 `create` 新建 |
| `分页参数非法` | page/size 非整数 | 传入整数页码与每页条数，或省略走默认值 |
| `导入数据须为列表` | import_batch 的 rows 不是列表 | 将导入行整理为 list[dict] 后再调 |
| `行数据格式非法` | 导入行不是 dict | 检查导入数据每行是否为对象（字典）结构 |
