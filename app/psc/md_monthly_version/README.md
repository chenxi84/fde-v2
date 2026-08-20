# md_monthly_version 应用 README（Agent 操作指南）

## 一、应用简介

- **应用组**：`psc`
- **应用名**：`md_monthly_version`
- **聚合根**：`MdMonthlyVersion`（月度版本主数据）
- **主键**：`version_no`（YYYYMM，文本，全局唯一）
- **同名库**：`md_monthly_version.db`
- **是否跨应用**：否。本应用**不主动调用**其他应用服务。
- **被引用关系**（入向，其他应用通过 `self.fde.call` 调用本应用）：
  - `sales_forecast.open_version` → `md_monthly_version.get(version_no)` 校验版本存在
  - `demand.publish` → `md_monthly_version.publish(version_no)` 联动锁定版本
  - `demand.calc_net` → `md_monthly_version.freeze(version_no)` 净需求运算后冻结版本

月度版本是产销协同体系的「计划周期节奏载体」，为销售预测、库存策略、毛需求发布、净需求运算提供统一的版本键与「同一时刻仅一个活跃版本」的节奏边界。锁定状态 `lock_status` 单向流转：`草稿 --publish--> 发布（锁定） --freeze--> 冻结`，冻结为终态、不可逆。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `psc__md_monthly_version__create` | `version_no`：str，必填，无默认<br>`anchor_period`：str，必填，无默认<br>`opening_date`：str，必填，无默认 | 创建月度版本。`version_no` 必须为 YYYYMM 且全局唯一；`opening_date` 必须为 `YYYY-MM-DD` 合法日期；同一时刻仅允许一个活跃版本。初始 `lock_status` 固定为 `草稿`。返回版本对象。 |
| `psc__md_monthly_version__get` | `version_no`：str，必填，无默认 | 按版本号查询版本详情，返回版本对象。 |
| `psc__md_monthly_version__list` | `version_no`：str \| None，可选，默认 `None`<br>`lock_status`：str \| None，可选，默认 `None`<br>`page`：int \| None，可选，默认 `None`<br>`size`：int \| None，可选，默认 `None` | 按版本号、锁定状态组合筛选版本列表（条件 AND 关系），按 `version_no` 降序。返回 `{"items": [...], "total": N}`；`page`/`size` 为 `None` 时返回全部，否则服务端分页。 |
| `psc__md_monthly_version__publish` | `version_no`：str，必填，无默认 | 将 `草稿` 版本发布为 `发布（锁定）`。仅草稿状态可发布。返回更新后的版本对象。 |
| `psc__md_monthly_version__freeze` | `version_no`：str，必填，无默认 | 将 `发布（锁定）` 版本冻结为 `冻结`（终态、不可逆）。仅发布（锁定）状态可冻结。返回更新后的版本对象。 |
| `psc__md_monthly_version__get_active` | 无参数 | 返回当前唯一活跃版本（`lock_status != 冻结` 中 `version_no` 最新的一条）。无活跃版本时返回 `null`。 |

---

## 三、标准工作流

### 1. 创建月度版本

推荐顺序：

1. 先调 `psc__md_monthly_version__get_active()`，确认当前无活跃版本。
2. 再调 `psc__md_monthly_version__list(version_no="拟建版本号")` 核对版本号是否已存在。
3. 确认无冲突后，调 `psc__md_monthly_version__create` 传入 `version_no`（YYYYMM）、`anchor_period`、`opening_date`（`YYYY-MM-DD`）。
4. 创建成功后，可调 `psc__md_monthly_version__get(version_no)` 确认记录已入库且 `lock_status` 为 `草稿`。

示例顺序：

```text
psc__md_monthly_version__get_active()
psc__md_monthly_version__list(version_no="202608")
psc__md_monthly_version__create(version_no="202608", anchor_period="N+1~N+3", opening_date="2026-08-01")
psc__md_monthly_version__get(version_no="202608")
```

### 2. 版本生命周期流转（创建 → 发布 → 冻结）

推荐顺序：

1. 确认目标版本当前状态：调 `psc__md_monthly_version__get(version_no)`。
2. 状态为 `草稿` 时，调 `psc__md_monthly_version__publish(version_no)` 发布锁定。
3. 状态为 `发布（锁定）` 时，调 `psc__md_monthly_version__freeze(version_no)` 冻结归档。

示例顺序：

```text
psc__md_monthly_version__get(version_no="202608")
psc__md_monthly_version__publish(version_no="202608")
psc__md_monthly_version__freeze(version_no="202608")
```

### 3. 查询版本列表与详情

推荐顺序：

1. 先调 `psc__md_monthly_version__list`，按需传入 `version_no`（精确）或 `lock_status`（精确）筛选。
2. 从返回 `items` 中取得目标 `version_no`。
3. 调 `psc__md_monthly_version__get(version_no)` 获取单条详情。

示例顺序：

```text
psc__md_monthly_version__list(lock_status="草稿")
psc__md_monthly_version__get(version_no="202608")
```

---

## 四、前置条件与注意事项

1. **版本号格式**
   - `version_no` 必须为 6 位数字，年月 `YYYYMM`，月取值 `01~12`。
   - 合法示例：`202608`；非法示例：`2026-13`、`20268`、`abc`。

2. **版本号全局唯一**
   - `version_no` 是单字段主键，重复创建会失败（提示「该版本号已存在」）。
   - 创建前建议先 `psc__md_monthly_version__list(version_no=...)` 或 `get` 核对。

3. **同一时刻仅一个活跃版本**
   - 存在 `草稿` 或 `发布（锁定）` 状态的版本时，不允许再创建新版本（提示「已存在活跃版本」）。
   - 若要开新版本，须先将当前活跃版本 `publish`（若为草稿）再 `freeze`（若已发布）至冻结终态。

4. **状态机单向流转**
   - `草稿 --publish--> 发布（锁定） --freeze--> 冻结`，禁止逆向、禁止跳级。
   - `publish` 仅对 `草稿` 生效；`freeze` 仅对 `发布（锁定）` 生效。
   - 冻结为终态、不可逆，本应用不提供删除、回滚服务。

5. **必填字段**
   - `create` 的 `version_no`、`anchor_period`、`opening_date` 均必填，不可为空。
   - `opening_date` 必须为 `YYYY-MM-DD` 合法日期（如 `2026-08-01`；`2026-13-40` 非法）。

6. **列表查询行为**
   - `list` 的筛选条件均可选，条件之间为 AND 关系。
   - `version_no` 与 `lock_status` 均为精确匹配。
   - `lock_status` 一旦传入非空值，只能为 `草稿`、`发布（锁定）`、`冻结`。
   - 无匹配结果返回 `{"items": [], "total": 0}`，不抛错。
   - 默认按 `version_no` 降序（新版本在前）。

7. **活跃版本定义**
   - 活跃版本 = `lock_status != 冻结` 的最新版本（按 `version_no` 降序取第一条）。
   - 无活跃版本时 `get_active` 返回 `null`，不是错误。

8. **锚定期间口径待确认**
   - `anchor_period` 为文本必填，但具体格式/口径业务尚未展开，本应用只做非空校验，不做格式校验。

9. **权限由平台控制**
   - Agent 能否调用这些工具，由平台授权决定，应用本身不做鉴权。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `版本号不能为空` | `create` / `get` / `publish` / `freeze` 传入的 `version_no` 为空或全是空白。 | 向用户索要有效版本号（YYYYMM），或先调 `list` 查询取得版本号后重试。 |
| `版本号格式必须为 YYYYMM` | `create` 传入的 `version_no` 不是 6 位数字或月份不在 `01~12`。 | 将 `version_no` 修正为 `YYYYMM` 格式（如 `202608`）后重试。 |
| `锚定期间不能为空` | `create` 传入的 `anchor_period` 为空或全是空白。 | 向用户索要锚定期间后重新调用 `create`。 |
| `opening 日不能为空` | `create` 传入的 `opening_date` 为空或全是空白。 | 向用户索要 opening 日后重新调用 `create`。 |
| `opening 日必须为合法日期` | `create` 传入的 `opening_date` 不是合法日期或不是 `YYYY-MM-DD` 格式。 | 将 `opening_date` 修正为 `YYYY-MM-DD`（如 `2026-08-01`）后重试。 |
| `该版本号已存在` | `create` 传入的 `version_no` 已被占用。 | 先调 `list(version_no=...)` 或 `get` 查看已有版本；若需开新版本，更换新的 `version_no`。 |
| `已存在活跃版本` | `create` 时已存在草稿或发布（锁定）状态的活跃版本。 | 先调 `get_active()` 找到当前活跃版本，将其 `publish`（若草稿）后 `freeze` 至冻结，再重新 `create`。 |
| `版本记录不存在` | `get` / `publish` / `freeze` 指定的 `version_no` 查不到记录。 | 先调 `list` 核对版本号是否拼写错误或尚未创建；确认后重试。 |
| `锁定状态筛选不合法` | `list` 传入的 `lock_status` 不是 `草稿`、`发布（锁定）`、`冻结`。 | 只使用合法状态筛选，或省略 `lock_status` 参数后重试。 |
| `分页参数不合法` | `list` 传入的 `page` / `size` 无法转换为整数。 | 将 `page` / `size` 改为整数后重试，或省略以使用默认值。 |
| `页码必须大于等于1` | `list` 传入的 `page` 小于 1。 | 将 `page` 改为 `>= 1` 后重试。 |
| `每页条数必须大于等于1` | `list` 传入的 `size` 小于 1。 | 将 `size` 改为 `>= 1` 后重试。 |
| `仅草稿状态可发布` | 对 `发布（锁定）` 或 `冻结` 状态的版本调用了 `publish`。 | 先调 `get` 确认当前状态；仅 `草稿` 可 `publish`，已发布/冻结无需再发布。 |
| `仅发布（锁定）状态可冻结` | 对 `草稿` 状态的版本调用了 `freeze`。 | 先调 `publish` 将版本发布为 `发布（锁定）`，再调 `freeze`。 |
| `版本已冻结，不可逆` | 对已 `冻结` 的版本再次调用了 `freeze`。 | 冻结为终态、不可逆，停止操作；如仍需新版本，先确认无活跃版本后调 `create` 新建。 |
