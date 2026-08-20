# vehicle_part_mapping 应用 · Agent 操作指南

## 一、应用简介

- **应用组**：`sales-forecast`
- **应用名**：`vehicle_part_mapping`
- **聚合根**：`VehiclePartMapping`
- **主键**：联合业务键 `(part_no, veh_model)`
- **同名库**：`vehicle_part_mapping.db`
- **是否跨应用调用**：本应用是单车用量（usage）与供应份额（share）的**单一权威源**，被 demand_processing、project_info 等下游应用频繁调用以获取量纲数据。本应用不主动调用其他应用。

本应用维护零件与车型的映射关系，记录单车用量（BOM 用量）、供应份额（%）、生命周期阶段与形态。量纲变更必须通过 `set_usage` / `set_share` 生成历史版本（`usage_history` 子表），不可直接覆盖——以支持基线校准、FVA 复盘等需要"当时口径"的场景。`project_info` 中的 `usage` / `share` 仅为本表值的引用展示。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `sales-forecast__vehicle_part_mapping__create` | `part_no: str`，必填<br>`veh_model: str`，必填<br>`platform: str`，可选，默认 `None`<br>`usage: float`，可选，默认 `0`<br>`share: float`，可选，默认 `0`<br>`lc_stage: str`，可选，默认 `""`，实际必填<br>`lc_shape: str`，可选，默认 `"传统"`<br>`sop: str`，可选，默认 `""`，实际必填<br>`eop: str`，可选，默认 `None`<br>`source: str`，可选，默认 `""`，实际必填<br>`status: str`，可选，默认 `"生效"` | 新建车型-零件映射。`lc_stage`、`sop`、`source` 为实际必填；`source` 仅限 `BOM`/`设变通知`/`商务确认` |
| `sales-forecast__vehicle_part_mapping__get` | `part_no: str`，必填<br>`veh_model: str`，必填 | 按联合主键查询映射详情 |
| `sales-forecast__vehicle_part_mapping__list` | `part_no: str`，可选，默认 `None`<br>`veh_model: str`，可选，默认 `None`<br>`lc_stage: str`，可选，默认 `None`<br>`status: str`，可选，默认 `None` | 按零件/车型/生命周期阶段/状态筛选列表（按零件号+车型升序） |
| `sales-forecast__vehicle_part_mapping__update` | `part_no: str`，必填<br>`veh_model: str`，必填<br>`**kwargs`：`platform, lc_stage, lc_shape, sop, eop, status, source` | 更新非量纲字段（`usage`/`share` 不可直接更新） |
| `sales-forecast__vehicle_part_mapping__set_usage` | `part_no: str`，必填<br>`veh_model: str`，必填<br>`new_usage: float`，必填<br>`effective_date: str`，必填<br>`basis: str`，必填 | 变更单车用量并生成历史版本。旧值 `effective_to` 设为新生效日期 |
| `sales-forecast__vehicle_part_mapping__set_share` | `part_no: str`，必填<br>`veh_model: str`，必填<br>`new_share: float`，必填<br>`effective_date: str`，必填<br>`basis: str`，必填 | 变更供应份额并生成历史版本。旧值 `effective_to` 设为新生效日期 |
| `sales-forecast__vehicle_part_mapping__get_usage_history` | `part_no: str`，必填<br>`veh_model: str`，必填 | 查询量纲历史版本列表（用量+份额，按生效日期降序） |
| `sales-forecast__vehicle_part_mapping__disable` | `part_no: str`，必填<br>`veh_model: str`，必填<br>`reason: str`，可选，默认 `""` | 停用映射（设变替代或 EOP）。已停用状态直接返回 |

---

## 三、标准工作流

### 1. 新建映射

1. 确认 `part_no` 和 `veh_model`。
2. 先调 `get(part_no, veh_model)` 查重——若已存在则不可重复创建。
3. 准备生命周期信息（`lc_stage`、`lc_shape`）、SOP、用量、份额、映射依据（`source`）。
4. 调 `create` 完成登记。
5. 创建后调 `get` 确认数据完整。

### 2. 变更单车用量

1. 先调 `get` 确认当前 `usage` 值。
2. 准备新用量值、生效日期（YYYY-MM-DD）、变更依据（设变通知/商务函件号）。
3. 调 `set_usage(part_no, veh_model, new_usage, effective_date, basis)`。
4. 调 `get_usage_history` 确认历史版本已生成（旧值 `effective_to` 被封闭）。

### 3. 变更供应份额

1. 先调 `get` 确认当前 `share` 值。
2. 准备新份额值（%）、生效日期、变更依据。
3. 调 `set_share(part_no, veh_model, new_share, effective_date, basis)`。
4. 调 `get_usage_history` 确认历史版本已生成。

### 4. 停用映射

1. 先调 `get` 确认当前状态为"生效"。
2. 调 `disable(part_no, veh_model, reason="设变替代/EOP")`。
3. 再调 `get` 确认状态已变为"停用"。

### 5. 查询与修改

1. 按条件调 `list` 筛选映射列表（可按零件、车型、阶段、状态交叉筛选）。
2. 找到目标后调 `get` 看详情。
3. 如需修改非量纲字段（如 `lc_stage`、`sop`、`source` 等），调 `update`。
4. 量纲字段变更必须走 `set_usage` / `set_share`。

---

## 四、前置条件与注意事项

1. **联合主键不可重复**：`(part_no, veh_model)` 全局唯一。同一零件在同一车型下只可建一条映射。

2. **量纲变更不可直接 `update`**：`usage` 和 `share` 变更必须通过 `set_usage` / `set_share` 方法——它们会自动生成 `usage_history` 历史版本。若在 `update` 中传入 `usage` 或 `share` 会被明确拒绝。

3. **量纲变更依据必填**：`set_usage` 和 `set_share` 的 `basis` 参数（设变通知号/商务函件号）不可为空，否则抛错。

4. **历史版本封闭语义**：调用 `set_usage` / `set_share` 时，系统将旧值的 `effective_to` 设为新值生效日期（即旧版本在新生效日之前有效）。这是在"使用时点"回溯历史口径的基础。

5. **映射依据取值限制**：`source` 仅限 `"BOM"`、`"设变通知"`、`"商务确认"` 三者之一。

6. **生命周期阶段仅限四种**：`"爬坡"`、`"成熟"`、`"衰退"`、`"EOP临近"`。

7. **生命周期形态仅限两种**：`"传统"`、`"上市高后下滑"`。

8. **状态仅限两种**：`"生效"` 或 `"停用"`。停用不可逆为生效——若需恢复，须与用户确认是否应新建映射。

9. **权威源原则**：`project_info` 的 `usage` / `share` 应定期或按需从本应用同步刷新，不应反方向覆盖。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `零件号和车型必填` | `create`/`get`/`update`/`set_usage`/`set_share` 中 `part_no` 或 `veh_model` 为空。 | 向用户索要完整零件号和车型编码后重试。 |
| `零件 {part_no} 车型 {veh_model} 映射已存在` | `create` 时联合主键冲突。 | 先调 `get` 确认已存在映射的内容；若是误操作则停止；若需修改，用 `update` / `set_usage` / `set_share` 而非 `create`。 |
| `生命周期阶段必填` | `create` 时 `lc_stage` 为空字符串。 | 向用户确认生命周期阶段，只能为"爬坡/成熟/衰退/EOP临近"后重试。 |
| `SOP必填` | `create` 时 `sop` 为空字符串。 | 向用户索要 SOP 日期（格式 YYYY-MM-DD）后重试。 |
| `映射依据必填（BOM/设变通知/商务确认）` | `create` 时 `source` 为空字符串。 | 向用户确认依据类型，填写 `"BOM"`/`"设变通知"`/`"商务确认"` 后重试。 |
| `映射依据只能为：BOM/设变通知/商务确认` | `create`/`update` 时 `source` 取值不在允许列表中。 | 修正为三种合法值之一后重试。 |
| `零件 {part_no} 车型 {veh_model} 映射不存在` | `get`/`update`/`set_usage`/`set_share`/`disable` 时未找到记录。 | 先调 `list` 按零件/车型核对编码；若确实不存在，调用 `create` 先建立映射。 |
| `生命周期阶段只能为：爬坡/成熟/衰退/EOP临近` | 传入了非法生命周期阶段。 | 修正为四种合法值之一后重试。 |
| `生命周期形态只能为：传统/上市高后下滑` | 传入了非法生命周期形态。 | 修正为 `"传统"` 或 `"上市高后下滑"` 后重试。 |
| `状态只能为：生效/停用` | 传入了非法状态值。 | 修正为 `"生效"` 或 `"停用"` 后重试。 |
| `{usage/share} 变更必须通过 set_{usage/share} 方法生成历史版本，不可直接覆盖` | 试图通过 `update` 直接修改用量或份额。 | 改用 `set_usage` 或 `set_share`，并提供 `effective_date` + `basis`。 |
| `量纲变更依据必填（设变通知/商务函件号）` | `set_usage` 的 `basis` 为空。 | 向用户索要设变通知号或商务函件号后重试。 |
| `份额变更依据必填（设变通知/商务函件号）` | `set_share` 的 `basis` 为空。 | 向用户索要设变通知号或商务函件号后重试。 |
