# md_customer 应用 README（Agent 操作指南）

## 一、应用简介

- **应用名**：`md_customer`
- **所属应用组**：`parts-fc`
- **聚合根**：`MdCustomer`
- **业务主键**：`customer_code`
- **同名库**：`md_customer.db`
- **是否跨应用调用**：本应用不主动调用其他应用服务。本应用会被 `demand_collection` 等应用调用 `list` 获取客户下拉选项。

本应用用于维护客户主数据（OEM 客户），提供客户创建、按编码查询、列表查询、更新等能力。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `parts-fc__md_customer__create` | `customer_code: str`，必填<br>`customer_name: str`，必填<br>`short_name: str`，必填<br>`settlement_mode: str`，必填<br>`predict_behavior_label: str`，必填 | 创建客户主数据。`customer_code` 全局唯一。创建成功返回客户完整信息。 |
| `parts-fc__md_customer__get` | `customer_code: str`，必填 | 按客户编码查询客户详情。客户不存在时抛出业务错误。 |
| `parts-fc__md_customer__list` | `keyword: str`，可选<br>`settlement_mode: str`，可选<br>`page: int`，可选<br>`page_size: int`，可选 | 查询客户列表。`keyword` 模糊匹配 `customer_code`、`customer_name`、`short_name`。返回 `{"total": n, "items": [...]}`。 |
| `parts-fc__md_customer__update` | `customer_code: str`，必填<br>`customer_name: str`，可选<br>`short_name: str`，可选<br>`settlement_mode: str`，可选<br>`predict_behavior_label: str`，可选 | 部分更新客户信息。只更新传入的非空字段。客户不存在时抛出业务错误。 |

---

## 三、标准工作流

### 1. 创建客户

```text
parts-fc__md_customer__list(keyword="OEM001")
parts-fc__md_customer__create(customer_code="OEM001", customer_name="某主机厂", short_name="某厂", settlement_mode="月结30天", predict_behavior_label="稳定")
```

### 2. 查询客户

```text
parts-fc__md_customer__get(customer_code="OEM001")
```

### 3. 更新客户

```text
parts-fc__md_customer__get(customer_code="OEM001")
parts-fc__md_customer__update(customer_code="OEM001", settlement_mode="月结60天")
```

---

## 四、前置条件与注意事项

1. `customer_code` 全局唯一，创建前建议先查重。
2. 所有字段在创建时均必填，更新时只传需变更的字段。
3. 本应用不提供删除能力，客户主数据创建后不可删除。
4. `demand_collection` 等应用的下拉选项依赖本应用的 `list` 服务。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `customer_code 必填，不能为空` | 未提供有效客户编码。 | 向用户索要客户编码后重新调用。 |
| `客户编码已存在` | `customer_code` 已被占用。 | 先用 `get` 或 `list` 查看已有客户；若为同一客户则无需重复创建。 |
| `customer_name 必填，不能为空` | 创建时未提供客户名称。 | 向用户索要客户名称后重新调用。 |
| `客户不存在` | `get` 或 `update` 时未查到对应客户。 | 先用 `list` 核对编码是否正确，或引导用户先创建。 |
| `分页参数非法` | `page` 或 `page_size` 传入了非数字值。 | 去掉分页参数或传合法整数。 |
