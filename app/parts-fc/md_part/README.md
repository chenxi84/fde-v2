# md_part 应用 README（Agent 操作指南）

## 一、应用简介

- **应用名**：`md_part`
- **所属应用组**：`parts-fc`
- **聚合根**：`MdPart`
- **业务主键**：`part_no`
- **同名库**：`md_part.db`
- **是否跨应用调用**：本应用不主动调用其他应用服务。本应用会被 `demand_collection` 等应用引用来校验零件号是否存在。

本应用用于维护物料主数据（零部件），提供物料创建、按编码查询、列表查询、更新等能力。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `parts-fc__md_part__create` | `part_no: str`，必填<br>`part_name: str`，必填<br>`part_type: str`，必填<br>`unit: str`，必填<br>`status: str`，必填 | 创建物料主数据。`part_no` 全局唯一。创建成功返回物料完整信息。 |
| `parts-fc__md_part__get` | `part_no: str`，必填 | 按物料编码查询物料详情。物料不存在时抛出业务错误。 |
| `parts-fc__md_part__list` | `keyword: str`，可选<br>`part_type: str`，可选<br>`status: str`，可选<br>`page: int`，可选<br>`page_size: int`，可选 | 查询物料列表。`keyword` 模糊匹配 `part_no`、`part_name`。返回 `{"total": n, "items": [...]}`。 |
| `parts-fc__md_part__update` | `part_no: str`，必填<br>`part_name: str`，可选<br>`part_type: str`，可选<br>`unit: str`，可选<br>`status: str`，可选 | 部分更新物料信息。只更新传入的非空字段。物料不存在时抛出业务错误。 |

---

## 三、标准工作流

### 1. 创建物料

```text
parts-fc__md_part__list(keyword="PART-001")
parts-fc__md_part__create(part_no="PART-001", part_name="制动片", part_type="易损件", unit="件", status="启用")
```

### 2. 查询物料

```text
parts-fc__md_part__get(part_no="PART-001")
```

### 3. 更新物料

```text
parts-fc__md_part__get(part_no="PART-001")
parts-fc__md_part__update(part_no="PART-001", status="停用")
```

---

## 四、前置条件与注意事项

1. `part_no` 全局唯一，创建前建议先查重。
2. 所有字段在创建时均必填，更新时只传需变更的字段。
3. 本应用不提供删除能力，物料主数据创建后不可删除。
4. `demand_collection` 的明细行中引用的零件号应在本应用中存在。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `part_no 必填，不能为空` | 未提供有效物料编码。 | 向用户索要物料编码后重新调用。 |
| `物料编码已存在` | `part_no` 已被占用。 | 先用 `get` 或 `list` 查看已有物料；若为同一物料则无需重复创建。 |
| `part_name 必填，不能为空` | 创建时未提供物料名称。 | 向用户索要物料名称后重新调用。 |
| `物料不存在` | `get` 或 `update` 时未查到对应物料。 | 先用 `list` 核对编码是否正确，或引导用户先创建。 |
| `分页参数非法` | `page` 或 `page_size` 传入了非数字值。 | 去掉分页参数或传合法整数。 |
