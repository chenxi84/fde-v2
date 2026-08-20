# demand_collection 应用 · Agent 操作指南

## 一、应用简介

- **应用组**：`sales-forecast`
- **应用名**：`demand_collection`
- **聚合根**：`DemandCollection`
- **主键**：`collect_no`（系统生成，格式 `COL-YYYYMM-HHMMSS`）
- **同名库**：`demand_collection.db`
- **是否跨应用调用**：是。`confirm_decomposition` 在拆解确认时，对每条有脉冲的明细行自动调用 `independent_event.create` 生成水位脉冲事件（脉冲->事件）。本应用还被 `demand_processing.generate_baseline` 调用以获取拆解后的真实需求数据。

本应用是销售预测加工链的入口——主机厂（OEM）滚动预测的版本化收集与信号拆解。三层结构：**收集单头**（D03-H，唯一键 `(oem_code, plant_code, fcst_version)`）-> **明细**（D03-D，纵表：零件x项目x车型x期间）-> **拆解快照**（D03-S，1:1：原始量 = 真实需求 + 脉冲量 + 噪声调整）。支持版本生命周期（草稿->已拆解->已锁定->已替代/已作废）、版本差异比对、信号分解（阶跃脉冲/噪声分离）。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `sales-forecast__demand_collection__create` | `oem_code: str`，必填<br>`plant_code: str`，必填<br>`fcst_version: str`，必填<br>`base_period: str`，必填<br>`demand_type: str`，可选，默认 `"月度滚动预测"`<br>`source_channel: str`，可选，默认 `""`<br>`recv_date: str`，可选，默认 `""`（为空时取当天）<br>`remark: str`，可选，默认 `""` | 新建收集单头。`(oem_code, plant_code, fcst_version)` 唯一，自动生成 `collect_no` 并关联上一版本 |
| `sales-forecast__demand_collection__add_lines` | `collect_no: str`，必填<br>`lines: list[dict]`，必填，每项含 `part_no, project_no, veh_model, period, orig_qty`，可选 `proj_stage, uom, data_flag` | 批量录入明细行。仅草稿状态可操作 |
| `sales-forecast__demand_collection__get` | `collect_no: str`，必填 | 获取收集单全貌（单头 + 全部明细 + 全部拆解快照） |
| `sales-forecast__demand_collection__list` | `oem_code: str`，可选，默认 `None`<br>`fcst_version: str`，可选，默认 `None`<br>`status: str`，可选，默认 `None` | 按客户/版本/状态筛选收集单列表（按版本降序） |
| `sales-forecast__demand_collection__set_decomposition` | `collect_no: str`，必填<br>`line_no: int`，必填<br>`period: str`，必填<br>`noise_adj: float`，必填<br>`pulse_qty: float`，必填<br>`method: str`，必填<br>`basis: str`，必填 | 记录单行拆解结果。`true_qty = orig_qty - pulse_qty - noise_adj`（系统强制计算）。`data_flag="OEM未提供"` 的行跳过 |
| `sales-forecast__demand_collection__confirm_decomposition` | `collect_no: str`，必填 | 拆解确认——执行恒等式校验 + 噪声守恒校验，冻结版本（状态->已拆解），并为每条脉冲自动生成 `independent_event` |
| `sales-forecast__demand_collection__lock` | `collect_no: str`，必填 | 锁定版本（由 D09 发布联动触发），仅"已拆解"状态可锁定->"已锁定" |
| `sales-forecast__demand_collection__supersede` | `collect_no: str`，必填<br>`new_collect_no: str`，必填 | 版本替代——当前版本状态->"已替代"，记录替代者 |
| `sales-forecast__demand_collection__cancel` | `collect_no: str`，必填<br>`reason: str`，必填 | 作废收集单。仅"草稿"状态可作废，原因存入 `remark` |
| `sales-forecast__demand_collection__version_diff` | `collect_no: str`，必填 | 版本比对：当前版本 vs 上一版本，逐零件x期间差异（delta），无上一版本时返回提示 |

---

## 三、标准工作流

### 1. 完整收集->拆解->确认流程

1. **创建收集单**：`create(oem_code, plant_code, fcst_version, base_period, ...)` 获得 `collect_no`。
2. **录入明细**：`add_lines(collect_no, lines=[{...}, ...])` 批量录入预测行。
3. **信号拆解**：逐行调用 `set_decomposition(collect_no, line_no, period, noise_adj, pulse_qty, method, basis)`。
4. **拆解确认**：`confirm_decomposition(collect_no)` ——系统自动执行：
   - 校验每条非"OEM未提供"行均有拆解快照
   - 恒等式校验：`true_qty == orig_qty - pulse_qty - noise_adj`
   - 噪声守恒校验：跨行 `noise_adj` 总和必须约为 0
   - 脉冲确认->自动调用 `independent_event.create` 生成水位脉冲事件
   - 状态->"已拆解"
5. **锁定**（D09 发布时联动）：`lock(collect_no)` -> 状态->"已锁定"
6. **新版本替代**：下一周期创建新收集单后，调用 `supersede(old_collect_no, new_collect_no)`。

### 2. 版本比对

1. 先调 `list` 确认存在上一版本（`prev_version` 非空）。
2. 调 `version_diff(collect_no)` 获取逐零件x期间差异列表。

### 3. 作废草稿

1. 先调 `get` 确认状态为"草稿"。
2. 调 `cancel(collect_no, reason="数据错误，重新收集")` -> 状态->"已作废"。

---

## 四、前置条件与注意事项

1. **单据唯一性**：`(oem_code, plant_code, fcst_version)` 唯一约束。同客户+工厂+版本只能有一张收集单。

2. **状态流转限制**：
   - `草稿` -> 可录入明细、可设置拆解、可作废
   - `已拆解` -> 可锁定
   - `已锁定` -> 终端状态（不可再变更）
   - `已替代` / `已作废` -> 终端状态

3. **`confirm_decomposition` 必须全部完成**：
   - 必须有至少一条明细（空单无法确认）。
   - 每条非"OEM未提供"明细行必须有拆解快照。
   - 恒等式 `true_qty = orig_qty - pulse_qty - noise_adj` 必须成立。
   - 跨行噪声调整总额 `noise_adj` 必须约为 0（容差 0.1）。

4. **脉冲->事件创建可能失败但不阻断**：`confirm_decomposition` 中调用 `independent_event.create` 创建脉冲事件时，若失败会静默吞噬（不阻断拆解确认），但快照的 `event_no` 不会写入。后续需手动补建事件。

5. **`version_diff` 依赖上一版本**：若收集单无 `prev_version`（首版），返回提示信息而非错误。

6. **拆解计算公式不可绕过**：`true_qty = orig_qty - pulse_qty - noise_adj` 由系统强制计算，`set_decomposition` 传入的 `true_qty` 会被忽略（代码中直接计算）。

7. **跨应用调用**：
   - `confirm_decomposition` -> `independent_event.create`（脉冲->事件）
   - `demand_processing.generate_baseline` -> `demand_collection.get`（获取拆解后数据）

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `客户 {oem_code} 工厂 {plant_code} 版本 {fcst_version} 已存在收集单` | `create` 时唯一约束冲突。 | 先调 `list` 查看已存在的收集单；若需创建新版，使用不同的 `fcst_version`；若是同一版本，直接对已有收集单操作。 |
| `仅草稿状态可录入明细` | `add_lines` 时收集单非草稿状态。 | 先调 `get` 确认当前状态；若已是"已拆解"/"已锁定"，需新建收集单录入；若需修改草稿，确认是否应作废后重建。 |
| `收集单 {collect_no} 不存在` | `add_lines`/`get`/`set_decomposition`/`confirm_decomposition` 等操作时编号无效。 | 先调 `list` 核对收集单编号；确认编号正确性。 |
| `仅草稿状态可设置拆解` | `set_decomposition` 时收集单状态非草稿。 | 先调 `get` 确认状态；若已确认拆解，无需重复设置；若需修改拆解，需作废后重建。 |
| `明细行 {collect_no}/{line_no} 不存在` | `set_decomposition` 的目标明细行不存在。 | 先调 `get` 查看明细行列表，确认 `line_no` 正确；若行确实缺失，先调 `add_lines` 补充。 |
| `仅草稿状态可确认拆解` | `confirm_decomposition` 时状态非草稿。 | 先调 `get` 确认状态；若已确认过则无需重复；若需重新拆解，先作废再重建收集单。 |
| `无明细数据，无法确认拆解` | 收集单没有任何明细行。 | 先调 `add_lines` 录入明细后，再确认拆解。 |
| `明细行 {line_no} 期间 {period} 缺少拆解快照` | 有明细行但尚未设置拆解（少了对应 `set_decomposition` 调用）。 | 检查该行是否"OEM未提供"（data_flag 为"OEM未提供"的行不要求快照）；若为正常数据，调 `set_decomposition` 补全该行拆解。 |
| `行{line_no}期间{period}拆解恒等式不成立：{true} != {orig}-{pulse}-{noise}` | 拆解快照中 `true_qty` 与 `orig_qty - pulse_qty - noise_adj` 不一致。 | 重新调 `set_decomposition`，确保传入的 `noise_adj` 和 `pulse_qty` 满足恒等式。系统会自动计算 `true_qty`。 |
| `噪声调整跨期总额不守恒：noise_adj={sum}，拆解不通过` | 同一收集单下所有行的 `noise_adj` 之和偏离 0 超过容差（0.1）。 | 检查各行的 `noise_adj` 分配——信号拆解中噪声应为"此消彼长"，总效应为零。调整各行 `noise_adj` 后重新 `set_decomposition` 再确认。 |
| `当前状态 {status} 不可锁定` | `lock` 要求状态为"已拆解"，当前状态不符合。 | 先调 `get` 确认状态；若为"草稿"，先 `confirm_decomposition`；若已锁定，无需重复操作。 |
| `当前状态 {status} 不可作废` | `cancel` 仅允许草稿状态，当前状态非草稿。 | 先调 `get` 确认状态；若已是终态（已锁定/已替代），无法作废，只能通过版本替代管理。 |
| `作废必须填写原因` | `cancel` 的 `reason` 为空或仅空白字符。 | 向用户索要作废原因（如"数据错误"、"OEM撤回"）后重试。 |
