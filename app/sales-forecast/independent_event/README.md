# independent_event 应用 . Agent 操作指南

## 一、应用简介

- **应用组**：`sales-forecast`
- **应用名**：`independent_event`
- **聚合根**：`IndependentEvent`
- **主键**：`event_no`（系统生成，格式 `EVT-YYYYMM-NNN`）
- **同名库**：`independent_event.db`
- **是否跨应用调用**：本应用被 `demand_collection.confirm_decomposition` 调用——拆解确认时对有脉冲的明细行自动 `create` 水位脉冲事件。本应用不主动调用其他应用。

本应用是叠加结构中**独立加项的唯一载体**——承载三类事件：(1) **水位脉冲**（拆解产出，阶跃检测自动生成）；(2) **断点**（ECN / 零件切换，必须成对登记：旧件截断 + 新件启动，通过 `create_bp_pair` 入口）；(3) **其他一次性事件**（人工登记，如促销、清库）。系统常量：`in_demand` 恒为 1（是，当期计入需求）、`in_trend` 恒为 0（否，不进趋势外推）——不可通过参数修改。状态机：**待确认 -> 生效 -> 持续中 / 已回落 -> 已关闭**（已取消为终态分支）。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `sales-forecast__independent_event__create` | `event_type: str`，必填（`"水位脉冲"`/`"断点.旧件截断"`/`"断点.新件启动"`/`"其他"`）<br>`part_no: str`，必填<br>`period: str`，必填<br>`event_qty: float`，必填<br>`source_basis: str`，必填<br>`oem_code: str`，可选，默认 `""`，实际必填<br>`veh_model: str`，可选，默认 `""`，实际必填<br>`source_ref: str`，可选，默认 `None`<br>`bp_batch: str`，可选，默认 `None`<br>`bp_date: str`，可选，默认 `None` | 新建独立事件。`in_demand=1`、`in_trend=0` 由系统强制。断点类须通过 `create_bp_pair` 入口。脉冲防重：同零件+期间+脉冲+生效/持续中不可重复 |
| `sales-forecast__independent_event__get` | `event_no: str`，必填 | 按事件编号查询事件详情 |
| `sales-forecast__independent_event__list` | `part_no: str`，可选，默认 `None`<br>`event_type: str`，可选，默认 `None`<br>`status: str`，可选，默认 `None`<br>`period: str`，可选，默认 `None` | 按零件/类型/状态/期间筛选事件列表（按创建日期 + 编号降序） |
| `sales-forecast__independent_event__confirm` | `event_no: str`，必填 | 确认事件：待确认->生效。仅总部计划可操作 |
| `sales-forecast__independent_event__mark_sustained` | `event_no: str`，必填 | 标记持续中：生效->持续中（水位脉冲未达标，不重复登记） |
| `sales-forecast__independent_event__mark_subsided` | `event_no: str`，必填<br>`close_basis: str`，必填 | 标记已回落：生效/持续中->已回落（水位达标）。`close_basis` 记录水位达标证明 |
| `sales-forecast__independent_event__close` | `event_no: str`，必填<br>`close_basis: str`，必填 | 关闭事件：已回落/生效->已关闭。`close_basis` 必填记录关闭依据 |
| `sales-forecast__independent_event__cancel` | `event_no: str`，必填<br>`close_basis: str`，必填 | 取消事件：误判/误登记时使用->已取消。`close_basis` 记录复盘结论。已关闭/已取消状态不可再取消 |
| `sales-forecast__independent_event__create_bp_pair` | `old_part_no: str`，必填<br>`new_part_no: str`，必填<br>`bp_date: str`，必填<br>`old_qty: float`，必填<br>`new_qty: float`，必填<br>`oem_code: str`，必填<br>`veh_model: str`，必填<br>`period: str`，必填<br>`source_basis: str`，可选，默认 `"设变通知"`<br>`source_ref: str`，可选，默认 `None` | 创建成对断点——旧件截断（负量）+ 新件启动（正量），同 `bp_batch`（格式 `BP-YYYYMM-NN`）关联。断点必须成对登记，禁止单边 |

---

## 三、标准工作流

### 1. 人工登记独立事件（其他一次性事件/手动脉冲）

1. 确认事件类型、零件、客户、车型、期间、事件量、来源依据。
2. 调 `create(event_type, part_no, period, event_qty, source_basis, oem_code, veh_model, ...)` 获得 `event_no`。
3. 调 `confirm(event_no)` 确认事件（待确认->生效）。
4. 根据事件演进调用后续操作：
   - 脉冲未达标 -> `mark_sustained(event_no)`（生效->持续中）
   - 水位达标 -> `mark_subsided(event_no, close_basis)`（生效/持续中->已回落）
   - 事件结束 -> `close(event_no, close_basis)`（已回落/生效->已关闭）

### 2. 登记断点（ECN / 零件切换）

1. 确认新旧零件号、断点时点、车型、客户、归属期间。
2. **必须**调用 `create_bp_pair` 成对登记（禁止分别调 `create` 创建单边断点）。
3. 获得 `bp_batch` 及两条事件的 `event_no`。
4. 分别调用 `confirm` 确认两条事件。

### 3. 误判处理

1. 先调 `get` 确认事件当前状态。
2. 若状态非"已关闭"且非"已取消"：
   - 调 `cancel(event_no, close_basis="复盘结论...")` 将事件置为"已取消"。
   - `close_basis` 须写入复盘结论而非仅"误判"。

### 4. 查询事件

1. 调 `list` 按零件/类型/状态/期间筛选。
2. 找到目标 `event_no` 后调 `get` 获取详情。
3. 根据当前状态决定下一步操作。

---

## 四、前置条件与注意事项

1. **`in_demand` / `in_trend` 不可修改**：系统强制 `in_demand=1`（当期计入）、`in_trend=0`（不进趋势），即使 `create` 传入对应参数也会被忽略。这是业务的根本约束。

2. **事件类型仅限四种**：`"水位脉冲"`、`"断点.旧件截断"`、`"断点.新件启动"`、`"其他"`。

3. **来源依据仅限四种**：`"阶跃检测"`、`"发运-结算倒推"`、`"设变通知"`、`"人工登记+说明"`。人工创建事件时来源依据不可为空。

4. **断点必须成对登记**：通过 `create` 直接创建 `"断点.旧件截断"` 或 `"断点.新件启动"` 会被拒绝（要求必须走 `create_bp_pair`）。断点成对登记生成同一个 `bp_batch` 编号。

5. **脉冲防重**：同一零件 + 同一期间 + 类型为"水位脉冲" + 状态为"生效"或"持续中"时，不允许重复创建。防止阶跃检测重复触发。

6. **人工登记必须附依据**：`create` 的 `source_basis` 不可为空，且必须在四种合法值之内。

7. **状态机规则**：
   - `待确认` -> `confirm` -> `生效`
   - `生效` -> `mark_sustained` -> `持续中`；`生效` -> `mark_subsided` -> `已回落`；`生效` -> `close` -> `已关闭`
   - `持续中` -> `mark_subsided` -> `已回落`
   - `已回落` -> `close` -> `已关闭`
   - `待确认` / `生效` / `持续中` / `已回落` -> `cancel` -> `已取消`
   - `已关闭` 和 `已取消` 不可再流转。

8. **`close_basis` 必填场景**：`mark_subsided`（水位达标证明）、`close`（关闭依据）、`cancel`（复盘结论）均不可为空。

9. **跨应用调用来源**：`demand_collection.confirm_decomposition` 会自动调用 `create` 创建水位脉冲事件。Agent 在看到来源依据为"阶跃检测"的脉冲事件时，应识别其可能来自 D03 拆解确认。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `事件类型只能为：水位脉冲/断点.旧件截断/断点.新件启动/其他` | `create` 传入了非法事件类型。 | 修正为四种合法类型之一后重试。 |
| `零件号必填` | `create` 的 `part_no` 为空。 | 向用户索要零件号后重试。 |
| `归属期间必填` | `create` 的 `period` 为空。 | 向用户索要归属期间（格式 YYYY-MM 或 YYYY-MM-DD）后重试。 |
| `来源依据必填（人工登记必须附依据）` | `create` 的 `source_basis` 为空。 | 向用户确认来源依据，从"阶跃检测/发运-结算倒推/设变通知/人工登记+说明"中选择后重试。 |
| `来源依据只能为：阶跃检测/发运-结算倒推/设变通知/人工登记+说明` | `create` 的 `source_basis` 不在允许列表中。 | 修正为四种合法值之一后重试。 |
| `客户编码必填` | `create` 的 `oem_code` 为空。 | 向用户索要客户编码，可先调 `master_data.list_customers` 确认后重试。 |
| `车型编码必填` | `create` 的 `veh_model` 为空。 | 向用户索要车型编码，可先调 `master_data.list_vehicles` 确认后重试。 |
| `断点类事件必须通过 create_bp_pair 成对登记，不可单独创建` | 试图通过 `create` 直接创建断点单边事件。 | 改用 `create_bp_pair` 成对登记，提供新旧零件号及两端事件量。 |
| `零件 {part_no} 期间 {period} 已存在持续中的水位脉冲，不得重复登记` | 脉冲防重触发——同一零件+期间已有生效/持续中的水位脉冲。 | 先调 `list(part_no="...", period="...", event_type="水位脉冲", status="生效")` 查看已有脉冲；若需更新，先关闭旧脉冲再创建新脉冲；若脉冲仍在持续，调用 `mark_sustained` 或 `mark_subsided` 推进状态。 |
| `事件编号必填` | `get` 的 `event_no` 为空。 | 向用户索要事件编号，或先调 `list` 查询后获取编号。 |
| `事件 {event_no} 不存在` | `get`/`confirm`/`mark_sustained`/`mark_subsided`/`close`/`cancel` 时编号无效。 | 先调 `list` 核对事件编号；若确认编号正确但查不到，事件可能已被取消或编号错误。 |
| `仅待确认事件可确认，当前状态：{status}` | `confirm` 时事件非待确认状态。 | 先调 `get` 确认当前状态；若已生效，无需重复确认；若已是终态，检查是否应取消重建。 |
| `仅生效事件可标记持续中，当前状态：{status}` | `mark_sustained` 时事件非生效状态。 | 先调 `get` 确认当前状态；若已是持续中/已回落，无需重复；若状态不对，确认事件流转路径。 |
| `回落依据必填（水位达标证明）` | `mark_subsided` 的 `close_basis` 为空。 | 向用户索要水位达标证明（如实际水位数据、监测报告）后重试。 |
| `仅生效/持续中事件可标记回落，当前状态：{status}` | `mark_subsided` 时事件状态不合规。 | 先调 `get` 确认当前状态；若已是已回落/已关闭，无需重复；若为待确认，先 `confirm`。 |
| `关闭依据必填` | `close` 的 `close_basis` 为空。 | 向用户索要关闭依据（如"脉冲已完全消化"、"ECN 切换完毕"）后重试。 |
| `事件已关闭，不可重复关闭` | `close` 时事件已是"已关闭"状态。 | 无需操作，事件已关闭。 |
| `已取消事件不可关闭` | `close` 时事件已取消。 | 已取消事件不可关闭；若需恢复，与用户确认是否取消有误。 |
| `取消原因必填（复盘结论）` | `cancel` 的 `close_basis` 为空。 | 向用户索要取消复盘结论（如"阶跃误判，实际为噪声"），填写后重试。 |
| `已关闭事件不可取消` | `cancel` 时事件已关闭。 | 已关闭事件不可取消——事件量已计入需求并发布。若确需调整，应通过 D09 后续版本进行对冲调整，而非取消历史事件。 |
| `事件已取消` | `cancel` 时事件已经是"已取消"状态。 | 无需操作，事件已取消。 |
| `新旧零件号均必填` | `create_bp_pair` 的 `old_part_no` 或 `new_part_no` 为空。 | 向用户确认新旧零件号（两者均不可为空）后重试。 |
| `断点时点必填` | `create_bp_pair` 的 `bp_date` 为空。 | 向用户索要断点日期（格式 YYYY-MM-DD）后重试。 |
| `事件编号生成失败，请重试` | 系统生成 `event_no` 时连续冲突（极少发生）。 | 直接重试对应操作（`create` 或 `create_bp_pair`）；若多次失败，提示人工介入。 |
| `断点批次号生成失败，请重试` | 系统生成 `bp_batch` 时连续冲突（极少发生）。 | 直接重试 `create_bp_pair`；若多次失败，提示人工介入。 |
