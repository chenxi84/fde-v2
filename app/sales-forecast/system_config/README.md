# system_config 应用 · Agent 操作指南

## 一、应用简介

- **应用组**：`sales-forecast`
- **应用名**：`system_config`
- **聚合根**：`SystemConfig`
- **同名库**：`system_config.db`
- **是否跨应用调用**：本应用是 sales-forecast 组的系统配置中心，被组内其他应用调用以读取运行参数、获取信任折扣系数等。本应用不主动调用其他应用。

本应用维护三大类配置：(1) 参数配置表（`param_config`）——含参数修改历史（`param_history`）；(2) 沉淀知识库——模板库（`template_lib`）、类比库（`analogy_lib`）、信任折扣表（`trust_discount`）；(3) 外部数据源台账（`ext_data_source`）。参数配置的主键为 `param_code`，模板库主键为 `tpl_no`，类比库主键为 `ana_no`，信任折扣联合主键为 `(oem_code, part_no)`，外部数据源主键为 `src_no`。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `sales-forecast__system_config__get_param` | `param_code: str`，必填 | 按参数编码查询参数详情（含当前值、默认值、生效周期、校准说明、审批人） |
| `sales-forecast__system_config__list_params` | `dimension: str`，可选，默认 `None` | 按维度（如"全局"）筛选参数列表。不传则返回全部 |
| `sales-forecast__system_config__set_param` | `param_code: str`，必填<br>`value: str`，必填<br>`calibration: str`，必填<br>`approver: str`，必填 | 修改参数值并记录变更历史（旧值→新值、变更人、原因）。值未变化时返回 `changed: false` |
| `sales-forecast__system_config__list_templates` | 无 | 列出全部模板（按使用次数降序），含形状参数、来源车型、适用细分市场、FVA 效果 |
| `sales-forecast__system_config__get_template` | `tpl_no: str`，必填 | 按模板编号查询模板详情 |
| `sales-forecast__system_config__create_template` | `tpl_no: str`，必填<br>`shape_params: str`，必填<br>`source_vehicle: str`，可选，默认 `None`<br>`applicable_segment: str`，可选，默认 `None` | 创建新模板。`tpl_no` 全局唯一 |
| `sales-forecast__system_config__list_analogies` | 无 | 列出全部类比记录（新车→相似车→依据→历史效果） |
| `sales-forecast__system_config__create_analogy` | `ana_no: str`，必填<br>`new_vehicle: str`，必填<br>`similar_vehicle: str`，必填<br>`basis: str`，必填 | 创建类比记录 |
| `sales-forecast__system_config__get_trust_discount` | `oem_code: str`，必填<br>`part_no: str`，可选，默认 `None` | 查询客户（+零件）的信任折扣系数。未配置时返回默认系数 `1.0`（直采） |
| `sales-forecast__system_config__update_trust_discount` | `oem_code: str`，必填<br>`coefficient: float`，必填<br>`direction: str`，必填<br>`basis: str`，可选，默认 `None`<br>`part_no: str`，可选，默认 `None` | 设置或更新信任折扣系数。有 `basis` 时来源记为"人工调整"，否则记为"D12自动" |
| `sales-forecast__system_config__list_ext_sources` | 无 | 列出全部外部数据源台账（含数据类别、渠道、口径、频率、滞后、合规、消费者、质量） |
| `sales-forecast__system_config__register_ext_source` | `src_no: str`，必填<br>`data_cat: str`，必填<br>`channel: str`，必填<br>`caliber: str`，必填<br>`freq: str`，必填<br>`lag: str`，必填<br>`compliance: str`，必填<br>`consumers: str`，必填 | 注册新的外部数据源 |

---

## 三、标准工作流

### 1. 查询参数

1. 若知道参数编码，直接调 `get_param(param_code="...")`。
2. 若不知道编码，先调 `list_params(dimension="...")` 按维度浏览全部参数及其当前值。
3. 从返回列表中找到目标参数编码，再调 `get_param` 获取详情。

### 2. 修改参数

1. 先调 `get_param` 确认参数当前值。
2. 确认修改内容、校准说明（calibration）、审批人（approver）。
3. 调用 `set_param`，传入新值 + 校准说明 + 审批人。值未变时自动跳过。
4. 修改成功后，可通过 `get_param` 验证新值已生效。

### 3. 查信任折扣

1. 知道客户编码（和可选零件号）后，直接调 `get_trust_discount(oem_code="...", part_no="...")`。
2. 若返回默认系数（1.0，来源"默认"），与用户确认是否需要基于历史合作数据人工调整。
3. 若需调整，调 `update_trust_discount` 设置新系数。

### 4. 沉淀模板/类比

1. 整理好模板的形状参数、来源车型、适用细分市场。
2. 调 `create_template` 或 `create_analogy` 录入。
3. 录入后可通过 `list_templates` / `list_analogies` 确认已入库。

---

## 四、前置条件与注意事项

1. **预设参数须初始化**：应用内置 `_ensure_default_params` 用于初始化 `θ_step`、`θ_noise`、`θ_baseline`、`θ_rev`、`θ_amp`、`θ_exo`、对账警戒线、考核容忍区间、核对升级轮次等预设参数。Agent 不应代劳，由平台加载时调用。

2. **`set_param` 参数必须已存在**：只能修改已有参数，不能通过 `set_param` 新增。若参数不存在，须先确认参数编码是否正确，或由人工在数据库层面初始化。

3. **`set_param` 会自动记历史**：每次值变更都会写入 `param_history` 表（旧值、新值、变更人、原因），不可逆。

4. **`set_param` 相同值不记历史**：若新值与当前值完全相同，直接返回且不产生历史记录。

5. **信任折扣默认全部信任**：未配置的客户（或客户+零件组合）默认返回系数 1.0（direction="直采"），即不扣减。只有显式配置的组合才有非 1.0 系数。

6. **信任折扣按 `(oem_code, part_no)` 唯一**：同一客户+零件不可有两条记录；`update_trust_discount` 用 `INSERT OR REPLACE`。

7. **模板编号全局唯一**：`create_template` 时 `tpl_no` 不可重复。创建前建议先 `get_template` 查重。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `参数 {param_code} 未配置` | `get_param` 找不到该参数编码。 | 先调 `list_params` 查看全部参数，核对编码；若编码正确但参数确实不在表中，需由人工初始化该参数后再查。 |
| `参数 {param_code} 不存在，请先初始化` | `set_param` 时目标参数不存在，无法修改。 | 先调 `list_params` 确认参数是否已定义；若未定义，需人工通过数据库或平台初始化该参数后再调用 `set_param`。 |
| `模板 {tpl_no} 不存在` | `get_template` 未找到该模板编号。 | 先调 `list_templates` 查看全部模板；若确认需要该模板，调用 `create_template` 创建。 |
| `模板 {tpl_no} 已存在` | `create_template` 时编号冲突。 | 先调 `get_template(tpl_no="...")` 查看已存在模板内容；若不是重复录入则更换 `tpl_no` 后重试。 |
