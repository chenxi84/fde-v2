# md_part_replace · 替换关系

## 一、应用简介

- **聚合根**：替换关系（零件间「原物料 → 替换物料」的替代关系）。
- **主键**：`rel_no`（关系号，系统自动生成，格式 `R` + 大写随机串）。
- **数据存放**：本应用同名库 `app/psc/md_part_replace/md_part_replace.db`（由平台创建/管理连接）。
- **业务唯一键**：`old_material_no + new_material_no`（一对新旧件只能有一条替换关系）。
- **状态机**：`(新建) → 生效 → 失效`；`失效` 是单向终点（V1 不支持反向激活，恢复生效须重新 `create`）。
- **跨应用调用**：`create`/`update` 时通过 `self.fde.call("md_material", "get", material_no=...)` 校验原/替换物料存在。

## 二、对外服务（工具）

| 工具名 | 参数（类型 / 必填 / 默认） | 说明 |
|---|---|---|
| `psc__md_part_replace__create` | `old_material_no` (str, 必填) · `new_material_no` (str, 必填) · `ecn_no` (str, 选填, None) | 新建替换关系，status 默认「生效」 |
| `psc__md_part_replace__get` | `rel_no` (str, 必填) | 查看单条详情 |
| `psc__md_part_replace__list` | `old_material_no` (str, 选填) · `new_material_no` (str, 选填) · `status` (str, 选填) · `page` (int, 选填) · `size` (int, 选填) | 分页列表；old/new 模糊、status 精确；返回 `{"items","total"}` |
| `psc__md_part_replace__update` | `rel_no` (str, 必填) · `old_material_no` (str, 必填) · `new_material_no` (str, 必填) · `ecn_no` (str, 选填, None) | 更新原/替换物料号与 ECN 依据（重新校验） |
| `psc__md_part_replace__disable` | `rel_no` (str, 必填) | 设为「失效」（幂等） |

## 三、标准工作流

**流程 1：建立替换关系（计划员）**
1. 先调 `psc__md_material__list`（或 `get`）确认原物料号与替换物料号真实存在。
2. 调 `psc__md_part_replace__create`，传 `old_material_no` / `new_material_no` / `ecn_no`。
3. 拿到返回的 `rel_no` 后，调 `psc__md_part_replace__get` 核对入库结果。

**流程 2：查询/核对替换关系（计划员、责任销售）**
1. 调 `psc__md_part_replace__list`，按需传 `old_material_no` / `new_material_no`（模糊）或 `status=生效`（精确）。
2. 对列表中的目标行，调 `psc__md_part_replace__get(rel_no)` 查看完整字段。

**流程 3：维护替换关系（计划员）**
1. 调 `psc__md_part_replace__get(rel_no)` 回填当前值。
2. 调 `psc__md_part_replace__update` 修改 `ecn_no`（或原/替换物料号）。
3. 替换件替代完成、原物料退出后，调 `psc__md_part_replace__disable(rel_no)` 置失效（失效后下游合并自动排除）。

## 四、前置条件与注意事项

- **物料引用铁律**：`old_material_no` / `new_material_no` 必须已存在于 `md_material`，后端 `create`/`update` 强制 `self.fde.call("md_material", "get")` 校验，禁止手工录入不存在的物料号。
- **必填**：`old_material_no`、`new_material_no` 非空；`ecn_no` 选填且不超过 50 字符。
- **组合唯一**：同一 `old_material_no + new_material_no` 全局唯一（含已失效记录），重复即拒绝。
- **原≠替换**：`old_material_no` 与 `new_material_no` 不能相同。
- **rel_no 只读**：主键不可修改，`update` 不接受变更 `rel_no`。
- **失效是单向**：`disable` 幂等，已失效再调无副作用；不支持反向激活。
- **不要用 update 改状态**：需将 status 置「失效」应使用 `disable` 而非 `update`。
- **跨应用依赖**：校验物料存在依赖 `psc__md_material__get`；本应用被 `demand` 通过 `list(status=生效)` 调用做替换件合并（弱引用、无级联删除）。

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步 |
|---|---|---|
| 原物料号不能为空 | `old_material_no` 缺失或空 | 向用户索要原物料号 |
| 替换物料号不能为空 | `new_material_no` 缺失或空 | 向用户索要替换物料号 |
| 关系号不能为空 | `rel_no` 缺失或空 | 向用户索要关系号 |
| 原物料号与替换物料号不能相同 | `old_material_no == new_material_no`（BR-02） | 请用户改填不同的原/替换物料号 |
| 原物料号不存在 | `md_material.get(old_material_no)` 未命中（BR-04） | 先调 `psc__md_material__list` 核对，或先建对应物料 |
| 替换物料号不存在 | `md_material.get(new_material_no)` 未命中（BR-05） | 先调 `psc__md_material__list` 核对，或先建对应物料 |
| 原物料号校验失败 | 调用 `md_material.get` 发生非业务异常 | 确认 `md_material` 应用已部署可用后重试 |
| 替换物料号校验失败 | 调用 `md_material.get` 发生非业务异常 | 确认 `md_material` 应用已部署可用后重试 |
| 该原物料+替换物料组合已存在 | 同原+替换组合已存在（BR-01，含失效记录） | 先 `list` 核对已有关系，改用 `update` 或换组合 |
| ECN依据长度不能超过50 | `ecn_no` 超 50 字符 | 请用户缩短 ECN 依据编号 |
| 替换关系不存在 | `rel_no` 查无此记录（get/update/disable） | 先 `list` 核对正确的关系号 |
| 状态仅支持生效/失效 | `list` 的 `status` 筛选值非法（BR-06） | 改用「生效」或「失效」 |
| 分页参数不合法 | `page`/`size` 非数字 | 改用正整数页码/每页条数 |
| 页码必须大于等于1 | `page < 1` | 改用 ≥1 的页码 |
| 每页条数必须大于等于1 | `size < 1` | 改用 ≥1 的每页条数 |
| 关系号生成失败，请重试 | rel_no 自动生成多次冲突 | 直接重试 `create` |
