# md_vehicle 应用 README（Agent 操作指南）

## 一、应用简介

- **应用名**：`md_vehicle`
- **所属应用组**：`parts-fc`
- **聚合根**：`MdVehicle`
- **业务主键**：`vehicle_code`
- **同名库**：`md_vehicle.db`
- **是否跨应用调用**：本应用不主动调用其他应用服务。本应用会被 `demand_collection` 等应用引用来校验车型是否存在、获取车型下拉选项。

本应用用于维护车型主数据，提供车型创建、按编码查询、列表查询、更新等能力。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `parts-fc__md_vehicle__create` | `vehicle_code: str`，必填<br>`vehicle_name: str`，必填<br>`platform: str`，必填<br>`segment: str`，必填<br>`powertrain: str`，必填<br>`price_range: str`，必填<br>`oem_code: str`，必填 | 创建车型主数据。`vehicle_code` 全局唯一。创建成功返回车型完整信息。 |
| `parts-fc__md_vehicle__get` | `vehicle_code: str`，必填 | 按车型编码查询车型详情。车型不存在时抛出业务错误。 |
| `parts-fc__md_vehicle__list` | `keyword: str`，可选<br>`platform: str`，可选<br>`segment: str`，可选<br>`oem_code: str`，可选<br>`page: int`，可选<br>`page_size: int`，可选 | 查询车型列表。`keyword` 模糊匹配 `vehicle_code`、`vehicle_name`。返回 `{"total": n, "items": [...]}`。 |
| `parts-fc__md_vehicle__update` | `vehicle_code: str`，必填<br>`vehicle_name: str`，可选<br>`platform: str`，可选<br>`segment: str`，可选<br>`powertrain: str`，可选<br>`price_range: str`，可选<br>`oem_code: str`，可选 | 部分更新车型信息。只更新传入的非空字段。车型不存在时抛出业务错误。 |

---

## 三、标准工作流

### 1. 创建车型

```text
parts-fc__md_vehicle__list(keyword="SUV-X3")
parts-fc__md_vehicle__create(vehicle_code="SUV-X3", vehicle_name="某豪华SUV", platform="P1", segment="B级SUV", powertrain="纯电", price_range="20-30万", oem_code="OEM001")
```

### 2. 查询车型

```text
parts-fc__md_vehicle__get(vehicle_code="SUV-X3")
```

### 3. 更新车型

```text
parts-fc__md_vehicle__get(vehicle_code="SUV-X3")
parts-fc__md_vehicle__update(vehicle_code="SUV-X3", price_range="25-35万")
```

---

## 四、前置条件与注意事项

1. `vehicle_code` 全局唯一，创建前建议先查重。
2. 所有字段在创建时均必填，更新时只传需变更的字段。
3. 本应用不提供删除能力，车型主数据创建后不可删除。
4. `oem_code` 为弱引用，关联 `md_customer.customer_code`，但不做强约束校验。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `vehicle_code 必填，不能为空` | 未提供有效车型编码。 | 向用户索要车型编码后重新调用。 |
| `车型编码已存在` | `vehicle_code` 已被占用。 | 先用 `get` 或 `list` 查看已有车型；若为同一车型则无需重复创建。 |
| `vehicle_name 必填，不能为空` | 创建时未提供车型名称。 | 向用户索要车型名称后重新调用。 |
| `车型不存在` | `get` 或 `update` 时未查到对应车型。 | 先用 `list` 核对编码是否正确，或引导用户先创建。 |
| `分页参数非法` | `page` 或 `page_size` 传入了非数字值。 | 去掉分页参数或传合法整数。 |
