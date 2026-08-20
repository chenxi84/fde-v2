# md_user 应用 README（Agent 操作指南）

## 一、应用简介

- **应用名**：`md_user`
- **所属应用组**：`parts-fc`
- **聚合根**：`MdUser`
- **业务主键**：`user_code`
- **同名库**：`md_user.db`
- **是否跨应用调用**：本应用不主动调用其他应用服务。本应用会被预测流程中各类应用引用，用于校验用户/负责人是否存在。

本应用用于维护组织用户主数据，提供用户创建、按编码查询、列表查询、更新等能力。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `parts-fc__md_user__create` | `user_code: str`，必填<br>`user_name: str`，必填<br>`department: str`，必填<br>`role: str`，必填 | 创建用户主数据。`user_code` 全局唯一。创建成功返回用户完整信息。 |
| `parts-fc__md_user__get` | `user_code: str`，必填 | 按用户编码查询用户详情。用户不存在时抛出业务错误。 |
| `parts-fc__md_user__list` | `keyword: str`，可选<br>`department: str`，可选<br>`role: str`，可选<br>`page: int`，可选<br>`page_size: int`，可选 | 查询用户列表。`keyword` 模糊匹配 `user_code`、`user_name`。返回 `{"total": n, "items": [...]}`。 |
| `parts-fc__md_user__update` | `user_code: str`，必填<br>`user_name: str`，可选<br>`department: str`，可选<br>`role: str`，可选 | 部分更新用户信息。只更新传入的非空字段。用户不存在时抛出业务错误。 |

---

## 三、标准工作流

### 1. 创建用户

```text
parts-fc__md_user__list(keyword="U001")
parts-fc__md_user__create(user_code="U001", user_name="张三", department="销售部", role="销售经理")
```

### 2. 查询用户

```text
parts-fc__md_user__get(user_code="U001")
```

### 3. 更新用户

```text
parts-fc__md_user__get(user_code="U001")
parts-fc__md_user__update(user_code="U001", department="市场部")
```

---

## 四、前置条件与注意事项

1. `user_code` 全局唯一，创建前建议先查重。
2. 所有字段在创建时均必填，更新时只传需变更的字段。
3. 本应用不提供删除能力，用户主数据创建后不可删除。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `user_code 必填，不能为空` | 未提供有效用户编码。 | 向用户索要用户编码后重新调用。 |
| `用户编码已存在` | `user_code` 已被占用。 | 先用 `get` 或 `list` 查看已有用户；若为同一用户则无需重复创建。 |
| `user_name 必填，不能为空` | 创建时未提供用户名称。 | 向用户索要用户名称后重新调用。 |
| `用户不存在` | `get` 或 `update` 时未查到对应用户。 | 先用 `list` 核对编码是否正确，或引导用户先创建。 |
| `分页参数非法` | `page` 或 `page_size` 传入了非数字值。 | 去掉分页参数或传合法整数。 |
