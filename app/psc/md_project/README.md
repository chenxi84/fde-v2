# md_project 应用 README（Agent 操作指南）

## 一、应用简介

- **应用组**：`psc`
- **应用名**：`md_project`
- **聚合根**：`MdProject`
- **业务主键**：`project_no`（文本，全局唯一）
- **同名库**：`md_project.db`
- **是否跨应用调用**：否。本应用**不主动调用**其他应用服务。
- **被引用关系**：`project_no` 被 `md_project_part` 应用弱引用（其 create/update 会调用本应用的 `get` 校验项目是否存在），本应用不建物理外键、不做级联。

本应用维护项目生命周期台账（项目号 / 名称 / 阶段 / SOP 时间 / EOP 时间 / 责任销售），为销售预测阶跃检测、爬坡期识别与库存策略清尾管理（离 EOP 判定）提供项目阶段基准。数据来源为「独立创建 + PLM 冗余同步（批量导入）」。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `psc__md_project__create` | `project_no`：str，必填，无默认<br>`project_name`：str，必填，无默认<br>`owner`：str，必填，无默认<br>`stage`：str \| None，可选，默认 `None`（缺省按「进行中」）<br>`sop_date`：str \| None，可选，默认 `None`<br>`eop_date`：str \| None，可选，默认 `None` | 新建项目台账。`project_no` 全局唯一，`stage` 缺省为 `进行中`，`sop_date`/`eop_date` 为 `YYYY-MM-DD` 日期（选填）。返回完整项目对象。 |
| `psc__md_project__get` | `project_no`：str，必填，无默认 | 按项目号查询项目台账详情，返回项目对象。 |
| `psc__md_project__list` | `project_no`：str \| None，可选，默认 `None`（模糊匹配）<br>`project_name`：str \| None，可选，默认 `None`（模糊匹配）<br>`stage`：str \| None，可选，默认 `None`（精确匹配）<br>`page`：int \| None，可选，默认 `None`<br>`size`：int \| None，可选，默认 `None` | 按条件筛选项目台账列表，返回 `{"items": [...], "total": N}`。`page`/`size` 均省略时返回全量；条件之间 AND 关系，按 `project_no` 升序。 |
| `psc__md_project__update` | `project_no`：str，必填，无默认<br>`project_name`：str \| None，可选，默认 `None`<br>`stage`：str \| None，可选，默认 `None`<br>`sop_date`：str \| None，可选，默认 `None`<br>`eop_date`：str \| None，可选，默认 `None`<br>`owner`：str \| None，可选，默认 `None` | 更新项目台账（`project_no` 不可修改，仅作定位键）。`stage` 须遵循单向流转（进行中→SOP→EOP），禁止跳级/回退。返回更新后的项目对象。 |
| `psc__md_project__import_batch` | `rows`：list，必填，无默认（元素为 dict，键：`project_no`/`project_name`/`stage`/`sop_date`/`eop_date`/`owner`） | 批量导入/更新（upsert）。已存在主键行更新，新行新增；逐行校验，失败行记录错误明细。返回 `{"total", "success", "fail", "created", "updated", "errors"}`。 |

---

## 三、标准工作流

### 1. 新建项目台账

1. 若不确定 `project_no` 是否已存在，先调 `psc__md_project__get(project_no="...")` 或 `psc__md_project__list(project_no="...")` 查重。
2. 调 `psc__md_project__create`，传入 `project_no`、`project_name`、`owner`（必填），`stage`/`sop_date`/`eop_date` 按需选填。
3. 创建成功后从返回值取得项目对象，可再调 `psc__md_project__get` 确认。

```text
psc__md_project__get(project_no="P2026001")
psc__md_project__create(project_no="P2026001", project_name="某车型项目", owner="张三")
psc__md_project__get(project_no="P2026001")
```

### 2. 查询项目台账

1. 若用户已给出 `project_no`，直接调 `psc__md_project__get`。
2. 若用户只给片段或筛选条件，先调 `psc__md_project__list`：
   - 按项目号片段：`project_no="P2026"`
   - 按名称片段：`project_name="车型"`
   - 按阶段：`stage="SOP"`
3. 分页时传 `page`/`size`；从返回 `items` 中取目标记录，再调 `psc__md_project__get` 取详情。

```text
psc__md_project__list(project_no="P2026", page=1, size=20)
psc__md_project__get(project_no="P2026001")
```

### 3. 阶段推进（SOP/EOP）

1. 先调 `psc__md_project__get(project_no="...")` 查看当前 `stage`。
2. 项目到达 SOP 时点：调 `psc__md_project__update(project_no, stage="SOP", sop_date="2026-09-30")`。
3. 项目到达 EOP 时点：调 `psc__md_project__update(project_no, stage="EOP", eop_date="2029-12-31")`。
4. 推进后再调 `psc__md_project__get` 确认阶段与时间已生效。

```text
psc__md_project__get(project_no="P2026001")
psc__md_project__update(project_no="P2026001", stage="SOP", sop_date="2026-09-30")
psc__md_project__update(project_no="P2026001", stage="EOP", eop_date="2029-12-31")
```

### 4. 批量导入（PLM 冗余同步）

1. 准备 `rows`（元素为 dict，含列 `project_no`、`project_name`、`stage`、`sop_date`、`eop_date`、`owner`）。
2. 调 `psc__md_project__import_batch(rows=[...])`。
3. 检查返回值：`success`/`fail` 计数；`fail > 0` 时逐条查看 `errors`（含 `row` 行号与 `message`），针对失败行修正后重导。

```text
psc__md_project__import_batch(rows=[
  {"project_no": "P2026001", "project_name": "某车型项目", "owner": "张三", "stage": "进行中", "sop_date": "", "eop_date": ""}
])
```

---

## 四、前置条件与注意事项

1. **必填字段**
   - `project_no`、`project_name`、`owner` 必填，不能为空白。
   - `stage` 选填，缺省 `进行中`；`sop_date`/`eop_date` 选填。

2. **project_no 全局唯一**
   - `project_no` 是单字段主键，重复创建会失败。
   - 创建前建议先 `get` 或 `list` 查重。

3. **阶段枚举约束**
   - `stage` 仅限 `进行中` / `SOP` / `EOP` 三值。

4. **状态机单向流转**
   - 仅可 `进行中 → SOP → EOP` 单向推进，禁止跳级（进行中→EOP）与回退（SOP→进行中、EOP→SOP/EOP）。
   - 新建项目只能从 `进行中` 开始。
   - 推进到 `SOP` 须已填写 `sop_date`；推进到 `EOP` 须已填写 `eop_date`。

5. **日期格式与先后约束**
   - `sop_date`/`eop_date` 格式须为 `YYYY-MM-DD`。
   - 同时填写时 `eop_date` 须晚于 `sop_date`（SOP 先于 EOP）。

6. **project_no 不可修改**
   - `update` 中 `project_no` 仅作定位键，不能被更新；需换号时只能另建记录。

7. **无删除服务**
   - 本应用不提供删除项目服务（避免被 `md_project_part` 引用后的级联问题）。

8. **批量导入为逐行 upsert**
   - 已存在主键行 → 更新 `project_name`/`stage`/`sop_date`/`eop_date`/`owner`；新行 → 新增。
   - 单行失败不影响其他行；失败行通过返回值的 `errors` 给出。

9. **权限由平台控制**
   - Agent 能否调用这些工具，由平台授权决定，应用本身不做鉴权。

---

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `项目号不能为空` | `create`/`get`/`update`/`import_batch` 传入的 `project_no` 为空或空白。 | 向用户索要非空项目号；不知道编号时先调 `psc__md_project__list` 查询。 |
| `该项目号已存在` | `create` 时 `project_no` 已被占用（BR-01）。 | 先调 `psc__md_project__get` 核对；若为同一项目无需重复创建，若要建新项目请更换 `project_no`。 |
| `项目名称不能为空` | `create`/`update`/`import_batch` 的 `project_name` 为空或空白。 | 向用户索要项目名称后重试；`update` 无需修改名称时可省略该参数。 |
| `责任销售不能为空` | `create`/`update`/`import_batch` 的 `owner` 为空或空白。 | 向用户索要责任销售后重试；`update` 无需修改时可省略该参数。 |
| `阶段仅支持进行中/SOP/EOP` | `stage` 不是 `进行中`/`SOP`/`EOP`（BR-03）。 | 将 `stage` 改为合法值后重试；`list` 筛选无需按阶段过滤时可省略该参数。 |
| `SOP 时间格式须为 YYYY-MM-DD` | `sop_date` 非 `YYYY-MM-DD` 格式（BR-04）。 | 将 `sop_date` 改为 `YYYY-MM-DD`（如 `2026-09-30`）后重试；无此时间可省略或传空字符串。 |
| `EOP 时间格式须为 YYYY-MM-DD` | `eop_date` 非 `YYYY-MM-DD` 格式（BR-04）。 | 将 `eop_date` 改为 `YYYY-MM-DD` 后重试；无此时间可省略或传空字符串。 |
| `EOP 时间须晚于 SOP 时间` | `eop_date` 早于或等于 `sop_date`（BR-05）。 | 修正 `eop_date` 使其晚于 `sop_date`，或先推进 SOP 再补 EOP。 |
| `项目记录不存在` | `get`/`update` 传入的 `project_no` 查不到记录。 | 先调 `psc__md_project__list` 核对编号；若确实不存在，先调 `psc__md_project__create` 创建。 |
| `阶段仅可单向推进（进行中→SOP→EOP）` | `stage` 跳级或回退，违反单向流转（BR-06）。 | 先调 `psc__md_project__get` 查看当前阶段；只能按 `进行中→SOP→EOP` 顺序推进，回退/跳级一律拒绝。 |
| `推进到 SOP 阶段须填写 SOP 时间` | 推进到 `SOP` 时未填写 `sop_date`（BR-06）。 | 在同一 `update` 调用中补传 `sop_date` 后重试。 |
| `推进到 EOP 阶段须填写 EOP 时间` | 推进到 `EOP` 时未填写 `eop_date`（BR-06）。 | 在同一 `update` 调用中补传 `eop_date` 后重试。 |
| `导入数据不能为空` | `import_batch` 传入的 `rows` 为空。 | 确认待导入数据非空后重试。 |
| `行数据须为对象` | `import_batch` 的某行不是 dict。 | 确保每行元素为 dict（含列 `project_no`/`project_name`/`stage`/`sop_date`/`eop_date`/`owner`）。 |
| `分页参数非法` | `list` 的 `page`/`size` 无法解析为整数。 | 传合法整数的 `page`/`size`；无分页需求时省略两者。 |
| `页码必须大于等于1` | `list` 的 `page` 小于 1。 | 将 `page` 改为不小于 1 的整数。 |
| `每页条数必须大于等于1` | `list` 的 `size` 小于 1。 | 将 `size` 改为不小于 1 的整数。 |

> `import_batch` 中的行级校验错误会以 `{"row": 行号, "message": "..."}` 形式返回在 `errors` 列表里，而非抛出 `FdeError`；`row` 为原始行序号（从 1 开始），可据此定位并修正对应行。
