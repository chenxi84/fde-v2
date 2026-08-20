# project_info 应用 · Agent 操作指南

## 一、应用简介

- **应用组**：`sales-forecast`
- **应用名**：`project_info`
- **聚合根**：`ProjectInfo`
- **主键**：联合业务键 `(project_no, part_no)`
- **同名库**：`project_info.db`
- **是否跨应用调用**：本应用是毛需求加工的主数据底座，被 demand_collection、demand_processing 等下游应用调用以获取项目阶段、车型、客户等六维属性。本应用不主动调用其他应用。

本应用记录项目与零件的六维属性（客户、工厂、车型、平台、零件类别、生命周期阶段），并通过阶段状态机控制需求去向：**进行中**阶段的项目进入近端毛需求加工；**待定点 / 定点中**阶段仅参与长期产能规划。`usage` / `share` 为引用展示字段，权威源在 `vehicle_part_mapping`。所有变更通过 `update` 自动记录 `change_log`，阶段迁移须走 `set_stage`。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `sales-forecast__project_info__create` | `project_no: str`，必填<br>`part_no: str`，必填<br>`stage: str`，可选，默认 `"待定点"`<br>`oem_code: str`，可选，默认 `""`，实际必填<br>`plant_code: str`，可选，默认 `""`，实际必填<br>`veh_model: str`，可选，默认 `""`，实际必填<br>`part_kind: str`，可选，默认 `"专用"`<br>`sop: str`，可选，默认 `""`，实际必填<br>`owner_sales: str`，可选，默认 `""`，实际必填<br>`award_prob: float`，可选，默认 `None`<br>`platform: str`，可选，默认 `None`<br>`usage: float`，可选，默认 `0`<br>`share: float`，可选，默认 `0`<br>`eop: str`，可选，默认 `None`<br>`lc_shape: str`，可选，默认 `None` | 创建项目-零件关联记录。实际必填字段：`oem_code`、`plant_code`、`veh_model`、`sop`、`owner_sales` |
| `sales-forecast__project_info__get` | `project_no: str`，必填<br>`part_no: str`，必填 | 按联合主键查询项目-零件详情 |
| `sales-forecast__project_info__list` | `stage: str`，可选，默认 `None`<br>`oem_code: str`，可选，默认 `None`<br>`owner_sales: str`，可选，默认 `None` | 按阶段/客户/责任销售筛选列表（按项目号+零件号升序） |
| `sales-forecast__project_info__update` | `project_no: str`，必填<br>`part_no: str`，必填<br>`**kwargs`：`stage, award_prob, oem_code, plant_code, veh_model, platform, part_kind, usage, share, sop, eop, lc_shape, owner_sales` | 更新指定字段，自动对比旧值并记录变更日志。阶段变更须同时提供 `_reason` |
| `sales-forecast__project_info__set_stage` | `project_no: str`，必填<br>`part_no: str`，必填<br>`new_stage: str`，必填<br>`reason: str`，必填 | 按状态机规则推进阶段（含校验 + 日志）。目标阶段与当前阶段相同时直接返回 |
| `sales-forecast__project_info__get_change_log` | `project_no: str`，必填<br>`part_no: str`，必填 | 获取变更日志列表（按 seq 升序） |

---

## 三、标准工作流

### 1. 创建项目-零件关联

1. 确认项目号 `project_no` 和零件号 `part_no` 合法。
2. 先调 `get(project_no, part_no)` 查重——若已存在则不可重复登记。
3. 准备六维属性（`oem_code`、`plant_code`、`veh_model`、`platform`、`part_kind`、`stage`）及 `sop`、`owner_sales`。
4. 调 `create` 完成登记，默认阶段为"待定点"。
5. 创建后调 `get` 确认数据完整。

### 2. 阶段推进

1. 先调 `get` 确认当前阶段。
2. 查状态机规则确认目标阶段合法：
   - `待定点` -> `定点中`
   - `定点中` -> `进行中` 或 `待定点`（退回）
   - `进行中` -> `EOP关闭`
   - `EOP关闭` -> `进行中`（年型/改款重新激活）
3. 准备迁移原因 `reason`。
4. 调 `set_stage(project_no, part_no, new_stage, reason)`。
5. 再调 `get` 确认阶段已变更。

### 3. 修改属性

1. 先调 `get` 确认当前值。
2. 调 `update` 传入需要修改的字段（注意：`stage` 变更建议用 `set_stage` 而非 `update`）。
3. 修改后调 `get_change_log` 查看变更记录。

### 4. 按需查询项目

1. 按条件调 `list`（可按阶段、客户、责任销售筛选）。
2. 从列表中找到目标 `(project_no, part_no)`。
3. 调 `get` 获取详情。

---

## 四、前置条件与注意事项

1. **联合主键不可重复**：`(project_no, part_no)` 全局唯一。同一项目下同一零件只可登记一次。

2. **`create` 必需字段**：`oem_code`、`plant_code`、`veh_model`、`sop`、`owner_sales` 在接口签名中虽设默认值 `""`，但实际校验为必填——传空字符串会抛错。

3. **阶段迁移严格受状态机约束**：不得跳过中间阶段，`EOP关闭` 可重新激活为 `进行中`（年型/改款场景）。非法的阶段跳转会明确告知允许的目标阶段。

4. **阶段迁移原因必填**：`set_stage` 的 `reason` 为空或仅空白字符会拒绝执行。

5. **用量/份额以 vehicle_part_mapping 为准**：本应用的 `usage` / `share` 仅为引用展示字段，不参与需求计算。量纲要变更应去 `vehicle_part_mapping`。

6. **零件类别仅限两种**：`"专用"` 或 `"通用"`。通用件时隐含多客户判断。

7. **变更日志自动记录**：`update` 和 `set_stage` 的所有字段变更自动写入 `change_log` 子表（含旧值、新值、操作人、时间、原因）。不可删除或回滚。

8. **弱引用上游主数据**：`oem_code`、`part_no`、`veh_model` 等依赖 `master_data` 应用，但本应用不主动校验其存在性。创建前建议确认主数据已同步。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `项目号和零件号必填` | `create`/`get`/`update`/`set_stage` 中 `project_no` 或 `part_no` 为空。 | 向用户索要完整的项目号和零件号后重试。 |
| `项目 {project_no} 下零件 {part_no} 已存在，不可重复登记` | `create` 时联合主键冲突。 | 先调 `get` 确认已存在记录的内容；若是误操作则停止；若需修改属性，用 `update` 而非 `create`。 |
| `客户编码必填` | `create` 时 `oem_code` 为空字符串。 | 向用户索要客户编码（如 `OEM001`），可先调 `master_data.list_customers` 确认客户存在。 |
| `工厂编码必填` | `create` 时 `plant_code` 为空字符串。 | 向用户索要工厂编码。 |
| `车型必填` | `create` 时 `veh_model` 为空字符串。 | 向用户索要车型编码，可先调 `master_data.list_vehicles` 确认车型存在。 |
| `SOP必填` | `create` 时 `sop` 为空字符串。 | 向用户索要 SOP 日期（格式 YYYY-MM-DD）。 |
| `责任销售必填` | `create` 时 `owner_sales` 为空字符串。 | 向用户索要责任销售的用户编号，可先调 `master_data.list_users` 确认用户存在。 |
| `项目 {project_no} 零件 {part_no} 不存在` | `get`/`update`/`set_stage` 时未找到记录。 | 先调 `list` 按条件核对项目号/零件号是否拼错；若确实不存在，调用 `create` 先登记。 |
| `阶段只能为：待定点/定点中/进行中/EOP关闭` | `create`/`update`/`set_stage` 传入了非法阶段值。 | 修正为四种合法阶段之一后重试。 |
| `零件类别只能为：专用/通用` | `create`/`update` 传入了非法零件类别。 | 修正为 `"专用"` 或 `"通用"` 后重试。 |
| `阶段迁移必须提供变更原因` | `update` 中包含了 `stage` 字段但未提供 `_reason`。 | 补充变更原因后重试；或改用 `set_stage`（其 `reason` 为显式必填参数）。 |
| `阶段迁移原因必填` | `set_stage` 的 `reason` 为空或仅空白。 | 向用户索要阶段迁移的具体原因（如"商务定点确认"、"EOP日期已定"），非空后重试。 |
| `阶段 {old_stage} 不可迁移至 {new_stage}，允许的目标阶段：...` | 状态机校验失败，目标阶段不在合法跳转路径中。 | 根据错误信息中提示的允许目标阶段，与用户确认正确的下一阶段。例如从 `待定点` 不可直接跳到 `进行中`，应先走 `定点中`。 |
