# demand_processing 应用 . Agent 操作指南

## 一、应用简介

- **应用组**：`sales-forecast`
- **应用名**：`demand_processing`
- **聚合根**：`DemandProcessing`
- **主键**：`proc_batch`（系统生成，格式 `PRC-YYYYMM-HHMMSS`）
- **同名库**：`demand_processing.db`
- **是否跨应用调用**：是。`generate_baseline` 会跨应用调用 `demand_collection.get`（获取拆解后真实需求）、`strategy_simulation.get_strategy`（获取基线策略）。本应用是加工链总账，被下游 D09 发布流程调用。

本应用是销售预测加工链的核心——五层结构：**加工单头**（D04-H）-> **基线明细**（D04-B，双路径：时序外推/借用）-> **修正明细**（D04-A，销售提交 + 三件套强制）-> **核对明细**（D04-C，多轮核对 + 退回重报 + 2 轮升级预警）-> **调整登记**（D04-L，全角色全程审计日志）。核心加工链：`create_batch` -> `generate_baseline` -> `confirm_baseline` -> `submit_adjustment` -> `check_line` -> `lock_batch`。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `sales-forecast__demand_processing__create_batch` | `fcst_version: str`，必填<br>`oem_code: str`，必填<br>`plant_code: str`，必填 | 创建加工批次（状态初始"进行中"），由拆解确认后触发。自动生成 `proc_batch` |
| `sales-forecast__demand_processing__generate_baseline` | `proc_batch: str`，必填 | 系统预计算双路径基线：调用 `demand_collection.get` 取 `true_qty`，调用 `strategy_simulation.get_strategy` 取策略（有时序策略走"时序外推"路径，无则走"借用"路径） |
| `sales-forecast__demand_processing__confirm_baseline` | `proc_batch: str`，必填<br>`part_no: str`，必填<br>`veh_model: str`，必填<br>`period: str`，必填<br>`base_qty: float`，可选，默认 `None`<br>`deviation_reason: str`，可选，默认 `None` | 人工确认/裁决基线。可覆盖 `base_qty` 并记录 `deviation_reason`。确认后自动创建待修正行（D04-A，初始 `adj_qty=base_qty`） |
| `sales-forecast__demand_processing__submit_adjustment` | `proc_batch: str`，必填<br>`part_no: str`，必填<br>`veh_model: str`，必填<br>`period: str`，必填<br>`adj_qty: float`，必填<br>`adj_reason_cat: str`，必填<br>`adj_evidence: str`，可选，默认 `""` | 销售提交修正值。修正幅度率超 20%（theta_rev）且无证据时强制举证。三件套（baseline/修正值/原因类别）强制。写入 D04-L 调整日志 |
| `sales-forecast__demand_processing__check_line` | `proc_batch: str`，必填<br>`part_no: str`，必填<br>`veh_model: str`，必填<br>`period: str`，必填<br>`chk_result: str`，必填（`"通过"` 或 `"退回"`）<br>`chk_reason: str`，可选，默认 `""`<br>`chk_adj_qty: float`，可选，默认 `None` | 核对：通过/退回。退回须附书面理由。通过时可调数（写入 D04-L）。退回重置提交状态"已退回·待重报"。2 轮退回触发升级预警 |
| `sales-forecast__demand_processing__get_line_status` | `proc_batch: str`，必填<br>`part_no: str`，必填<br>`veh_model: str`，必填<br>`period: str`，必填 | 查看行级状态——当前修正信息 + 全部核对轮次记录 |
| `sales-forecast__demand_processing__lock_batch` | `proc_batch: str`，必填 | 锁定批次（D09 发布联动触发）。仅"全部核定"状态可锁定->"已锁定" |
| `sales-forecast__demand_processing__get` | `proc_batch: str`，必填 | 获取批次全貌（单头 + 全部基线 + 全部修正 + 全部核对 + 全部调整日志） |
| `sales-forecast__demand_processing__list` | `oem_code: str`，可选，默认 `None`<br>`status: str`，可选，默认 `None` | 按客户/状态筛选批次列表 |

---

## 三、标准工作流

### 1. 完整加工流程

1. **创建批次**：`create_batch(fcst_version, oem_code, plant_code)` 获得 `proc_batch`。
2. **生成基线**：`generate_baseline(proc_batch)` ——系统从 D03 取 `true_qty`，从 D10 取策略，逐行生成双路径基线。
3. **确认基线**：对每条基线行调用 `confirm_baseline(proc_batch, part_no, veh_model, period, base_qty, deviation_reason)` ——人工裁决基线值，系统自动创建对应修正行。
4. **销售提交修正**：`submit_adjustment(proc_batch, part_no, veh_model, period, adj_qty, adj_reason_cat, adj_evidence)` ——三件套强制，超 20% 强制举证。
5. **核对**：`check_line(proc_batch, part_no, veh_model, period, chk_result, chk_reason, chk_adj_qty)`。
   - 若 `chk_result="退回"` -> 销售重报修正 -> 再次核对。
   - 若 2 轮退回 -> 触发升级预警（系统提示，不自动阻断）。
6. **全部核定后锁定**：`lock_batch(proc_batch)`（通常由 D09 发布联动触发）。

### 2. 退回重报循环

1. 核对退回 `check_line(..., chk_result="退回", chk_reason="...")`。
2. 修正状态变为"已退回·待重报"。
3. 销售重新调用 `submit_adjustment` 提交新修正值。
4. 核对再次 `check_line`（轮次自动 +1）。

### 3. 查询行状态

1. 用户询问某行的处理进度。
2. 调 `get_line_status(proc_batch, part_no, veh_model, period)`。
3. 返回当前修正信息 + 所有核对轮次记录，据此判断下一步操作。

---

## 四、前置条件与注意事项

1. **批次状态流转**：`进行中`（可生成基线/修正/核对）-> `全部核定`（可锁定）-> `已锁定`（终端）。

2. **基线生成依赖上游数据**：
   - `generate_baseline` 调用 `demand_collection.get` 获取拆解数据——需确保对应收集单已完成 `confirm_decomposition`。
   - 同时尝试调用 `strategy_simulation.get_strategy` 获取时序策略——若获取失败不阻断，走"借用"路径。

3. **修正三件套强制**：`submit_adjustment` 必须提供基线、修正值（`adj_qty`）、原因类别（`adj_reason_cat`）。修正幅度率 `|adj_qty - base_qty| / base_qty > 20%` 且 `adj_evidence` 为空时强制举证（抛出错误）。

4. **核对双向约束**：
   - 退回必须附书面理由（`chk_reason` 非空）。
   - 通过时可调数（`chk_adj_qty`），调数动作自动写入 D04-L 调整日志。
   - 2 轮及以上退回触发升级预警（系统层面处理，不在此应用内阻断）。

5. **调整日志全程审计**：每次 `submit_adjustment`（销售修正）和 `check_line`（核对人调数）都会写入 D04-L 审计日志（角色、修正前值、修正后值、原因类别、证据）。

6. **`lock_batch` 仅"全部核定"可执行**：需确保所有修正行均已完成核对并通过后，才能锁定。

7. **跨应用调用链**：
   - `generate_baseline` -> `demand_collection.get`（获取 D03 拆解数据）
   - `generate_baseline` -> `strategy_simulation.get_strategy`（获取时序策略）
   - 下游 D09 发布流程 -> `lock_batch`（锁定批次）

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `加工批次 {proc_batch} 不存在` | `get`/`generate_baseline`/`lock_batch` 等操作的批次编号无效。 | 先调 `list` 核对批次编号；若确认批次不存在，调用 `create_batch` 创建。 |
| `仅进行中批次可生成基线` | `generate_baseline` 时批次状态非"进行中"。 | 先调 `get` 确认批次状态；若已锁定/已核定，不可重新生成基线，需新建批次。 |
| `获取收集数据失败：{原因}` | `generate_baseline` 调用 `demand_collection.get` 失败。 | 检查对应收集单是否已完成 `confirm_decomposition`，确认 D03 数据可用后重试。 |
| `基线行不存在，请先生成基线` | `confirm_baseline` 的目标行不存在于 D04-B 表中。 | 先调 `generate_baseline(proc_batch)` 生成基线后，再确认该行。 |
| `基线未生成，无法修正` | `submit_adjustment` 的目标行无基线记录。 | 先调 `generate_baseline` 生成基线，再 `confirm_baseline` 确认，最后再提交修正。 |
| `仅进行中批次可提交修正` | `submit_adjustment` 时批次状态非"进行中"。 | 先调 `get` 确认批次状态；若已锁定，无法再修正。 |
| `修正幅度率 X% 超过20%阈值，必须附数据依据（客户函件/邮件记录/数据截图）` | 修正偏离基线超过 20% 但未提供 `adj_evidence`。 | 向用户索要数据依据（如客户函件截图、邮件记录等），填入 `adj_evidence` 后重试。 |
| `原因类别不可为空（三件套强制）` | `submit_adjustment` 的 `adj_reason_cat` 为空字符串。 | 向用户确认修正原因类别（如"客户增量需求"、"产能约束"、"市场波动"等），填写后重试。 |
| `核对结论必须为'通过'或'退回'` | `check_line` 的 `chk_result` 不合法。 | 修正为 `"通过"` 或 `"退回"` 后重试。 |
| `退回必须附书面理由（哪个视角不通过+需要什么证据）` | `check_line` 退回但 `chk_reason` 为空。 | 向用户索要退回理由（说明哪个视角不通过、需要什么补充证据），填写后重试。 |
| `修正行不存在` | `check_line` 的目标行在 D04-A 中不存在。 | 先确认是否已调用 `confirm_baseline`（确认基线后会自动创建修正行），再调 `submit_adjustment` 提交修正，最后再核对。 |
| `批次状态 {status}，非全部核定不可锁定` | `lock_batch` 要求所有行核对通过后批次处于"全部核定"状态，当前不满足。 | 先调 `get` 查看批次全貌，确认是否所有修正行均已完成核对并通过。若有未核对或退回行，先完成核对流程。 |
