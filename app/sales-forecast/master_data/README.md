# master_data 应用 · Agent 操作指南

## 一、应用简介

- **应用组**：`sales-forecast`
- **应用名**：`master_data`
- **聚合根**：`MasterData`
- **同名库**：`master_data.db`
- **是否跨应用调用**：本应用是通用主数据的本地冗余层，被 sales-forecast 组内其他应用频繁调用以校验实体是否存在、获取主数据属性。本应用不主动调用其他应用。

本应用维护五类实体（客户/物料/车型/用户/日历）的本地副本，权威源在外部系统（MDM / ERP / HR），本地只读主体字段。通过 `sync_*` 系列服务从外部接口批量覆盖同步。**各实体主键**: 客户 `oem_code`、物料 `part_no`、车型 `veh_model`、用户 `userno`、日历 `date`。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `sales-forecast__master_data__get_customer` | `oem_code: str`，必填 | 按客户编码查询客户详情（含工厂列表、结算模式、行为标签） |
| `sales-forecast__master_data__list_customers` | `settle_mode: str`，可选，默认 `None`<br>`keyword: str`，可选，默认 `None` | 按结算模式或关键词（模糊匹配编码/名称）筛选客户列表 |
| `sales-forecast__master_data__get_part` | `part_no: str`，必填 | 按零件号查询物料详情（含名称、单位、类型、状态） |
| `sales-forecast__master_data__list_parts` | `part_type: str`，可选，默认 `None`<br>`status: str`，可选，默认 `"在用"`<br>`keyword: str`，可选，默认 `None` | 按类型/状态/关键词筛选物料列表 |
| `sales-forecast__master_data__get_vehicle` | `veh_model: str`，必填 | 按车型编码查询车型详情（含平台、细分市场、动力类型、价格区间） |
| `sales-forecast__master_data__list_vehicles` | `oem_code: str`，可选，默认 `None`<br>`platform: str`，可选，默认 `None` | 按客户或平台筛选车型列表 |
| `sales-forecast__master_data__get_user` | `userno: str`，必填 | 按用户编号查询用户详情（含姓名、部门、角色、责任范围） |
| `sales-forecast__master_data__list_users` | `role: str`，可选，默认 `None`<br>`department: str`，可选，默认 `None` | 按角色或部门筛选用户列表 |
| `sales-forecast__master_data__get_calendar` | `date: str`，必填 | 按日期查询日历详情（含工作日标记、停线信息） |
| `sales-forecast__master_data__list_calendars` | `date_from: str`，必填<br>`date_to: str`，必填 | 按日期范围查询日历列表（升序） |
| `sales-forecast__master_data__sync_customers` | `data: list[dict]`，必填，每项含 `oem_code, oem_name, plants, settle_mode` | 批量同步客户主数据（INSERT OR REPLACE） |
| `sales-forecast__master_data__sync_parts` | `data: list[dict]`，必填，每项含 `part_no, part_name, uom, part_type, status` | 批量同步物料主数据 |
| `sales-forecast__master_data__sync_vehicles` | `data: list[dict]`，必填，每项含 `veh_model, veh_name, platform, segment, powertrain, price_range, oem_code` | 批量同步车型主数据 |
| `sales-forecast__master_data__sync_users` | `data: list[dict]`，必填，每项含 `userno, name, department, role, responsible_scope` | 批量同步用户主数据 |
| `sales-forecast__master_data__sync_calendars` | `data: list[dict]`，必填，每项含 `date, is_workday, shutdowns` | 批量同步日历数据 |

---

## 三、标准工作流

### 1. 查询实体是否存在（被其他应用调用）

1. 收到其他应用传入的实体编码（如 `oem_code`、`part_no` 等）。
2. 调用对应 `get_*` 服务查询。
3. 若返回"不存在"错误，提示调用方先同步该实体或修正编码。

### 2. 按模糊条件查找实体

1. 用户提供部分信息（如客户名称片段、零件类型等）。
2. 调用对应 `list_*` 服务筛选候选列表。
3. 从返回结果中确认目标实体编码。
4. 再调用对应 `get_*` 服务获取详情。

### 3. 同步外部主数据

1. 从外部系统获取原始数据。
2. 按分类调用对应的 `sync_*` 服务，传入数据列表。
3. 同步完成后可调用 `get_*` 或 `list_*` 验证数据已入库。

---

## 四、前置条件与注意事项

1. **权威源在外部**：本应用仅存储本地冗余副本，不负责主数据的创建与维护。增删改须回到外部权威系统，然后通过 `sync_*` 同步。

2. **`sync_*` 会覆盖已有数据**：使用 `INSERT OR REPLACE` 语义，按主键覆盖同编码的已有记录，不可用于部分字段更新。

3. **实体不存在即非"已同步"**：若 `get_*` 返回实体不存在，说明该实体未被同步到本地。Agent 不应尝试直接 INSERT——应引导用户先完成外部系统同步再调 `sync_*`。

4. **日历按日期范围查询**：`list_calendars` 的 `date_from` 和 `date_to` 均必填，不能省略。

5. **物料默认状态为"在用"**：`list_parts` 默认筛选 `status="在用"`，如需查已停用物料需显式传入 `status=None` 或具体状态码。

6. **跨应用弱引用**：其他应用通过实体编码（如 `part_no`）引用本应用数据，不建物理外键。若本应用数据被覆盖或缺失，可能导致下游校验失败。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `客户 {oem_code} 不存在于本地冗余表` | `get_customer` 未找到该客户。 | 先调 `list_customers(keyword="...")` 核对编码是否拼错；若确认未同步，建议用户从 MDM 同步该客户数据。 |
| `零件 {part_no} 不存在于本地冗余表` | `get_part` 未找到该物料。 | 先调 `list_parts(keyword="...")` 核对编码；若确认未同步，建议用户从 ERP 同步该物料数据。 |
| `车型 {veh_model} 不存在于本地冗余表` | `get_vehicle` 未找到该车型。 | 先调 `list_vehicles(oem_code="...")` 按客户缩小范围；若确认未同步，建议用户从 MDM 同步该车型数据。 |
| `用户 {userno} 不存在于本地冗余表` | `get_user` 未找到该用户。 | 先调 `list_users(department="...")` 按部门缩小范围；若确认未同步，建议用户从 HR 系统同步该用户数据。 |
| `日历 {date} 不存在` | `get_calendar` 未找到该日期。 | 先调 `list_calendars` 按日期范围查看附近已同步日期；若整段缺失，调用 `sync_calendars` 补充。 |
