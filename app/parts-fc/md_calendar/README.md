# md_calendar 应用 README（Agent 操作指南）

## 一、应用简介

- **应用名**：`md_calendar`
- **所属应用组**：`parts-fc`
- **聚合根**：`MdCalendar`
- **业务主键**：`date`
- **同名库**：`md_calendar.db`
- **是否跨应用调用**：本应用不主动调用其他应用服务。本应用会被预测流程中各应用引用，用于判断工作日/节假日、计算有效工作天数。

本应用用于维护日历主数据，提供日历日期创建、按日期查询、列表查询、更新等能力。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `parts-fc__md_calendar__create` | `date: str`，必填<br>`is_workday: int`，必填（0 或 1）<br>`holiday_name: str`，必填（非工作日时） | 创建日历日期。`date` 全局唯一。非工作日时必须提供 `holiday_name`。创建成功返回日历完整信息。 |
| `parts-fc__md_calendar__get` | `date: str`，必填 | 按日期查询日历详情。日期不存在时抛出业务错误。 |
| `parts-fc__md_calendar__list` | `keyword: str`，可选<br>`is_workday: int`，可选（0 或 1）<br>`page: int`，可选<br>`page_size: int`，可选 | 查询日历列表。`keyword` 模糊匹配 `date`、`holiday_name`。返回 `{"total": n, "items": [...]}`。 |
| `parts-fc__md_calendar__update` | `date: str`，必填<br>`is_workday: int`，可选（0 或 1）<br>`holiday_name: str`，可选 | 部分更新日历信息。只更新传入的非空字段。日期不存在时抛出业务错误。 |

---

## 三、标准工作流

### 1. 创建日历日期

```text
parts-fc__md_calendar__list(keyword="2026-10-01")
parts-fc__md_calendar__create(date="2026-10-01", is_workday=0, holiday_name="国庆节")
```

### 2. 查询日期

```text
parts-fc__md_calendar__get(date="2026-08-08")
```

### 3. 更新日历

```text
parts-fc__md_calendar__get(date="2026-08-08")
parts-fc__md_calendar__update(date="2026-08-08", holiday_name="调休日")
```

---

## 四、前置条件与注意事项

1. `date` 全局唯一，建议格式为 `YYYY-MM-DD`。
2. 创建时 `is_workday` 必填，只能为 0（非工作日）或 1（工作日）。
3. 非工作日（`is_workday=0`）时 `holiday_name` 必填；工作日时 `holiday_name` 可为空。
4. 本应用不提供删除能力，日历日期创建后不可删除。
5. 预测流程中各类时间计算依赖本应用判断工作日。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `date 必填，不能为空` | 未提供有效日期。 | 向用户索要日期后重新调用。 |
| `该日期已存在` | `date` 已被占用。 | 先用 `get` 查看已有记录，或改用 `update` 更新。 |
| `is_workday 必填，不能为空` | 创建时未提供工作日标记。 | 向用户确认是否为工作日（0 或 1）后重新调用。 |
| `is_workday 只能为 0 或 1` | 传入了非法值。 | 修正为 0（非工作日）或 1（工作日）后重新调用。 |
| `非工作日时 holiday_name 必填，不能为空` | 非工作日未提供假期名称。 | 向用户索要假期名称后重新调用。 |
| `日期不存在` | `get` 或 `update` 时未查到对应日期。 | 先用 `list` 核对日期是否正确，或引导用户先创建。 |
| `分页参数非法` | `page` 或 `page_size` 传入了非数字值。 | 去掉分页参数或传合法整数。 |
