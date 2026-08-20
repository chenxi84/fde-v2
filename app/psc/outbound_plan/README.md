# outbound_plan 应用 README（Agent 操作指南）

## 一、应用简介

- **应用组**：`psc`
- **应用名**：`outbound_plan`
- **聚合根**：`OutboundPlan`（出库计划）
- **主键**：`plan_no`（系统自动生成，格式 `OB` + 日期 + 流水，如 `OB202608200001`）
- **同名库**：`outbound_plan.db`
- **数据来源类型**：手工参考创建 —— 业务人员手工登记对客户的出库计划（客户、物料、数量、计划出库日期、实际出库单号）。
- **状态机**：`待出库 → 已关闭`。计划出库日期早于今日即自动关闭（**惰性关闭**：list / get 读取时结算，无需常驻定时器）；已关闭计划仍可 `update` 编辑延期——日期延到今日及以后自动恢复 `待出库`。
- **是否跨应用**：是。
  - `create` / `update` 调用 `md_material.get`、`md_customer.get` 校验主数据存在性（主数据引用铁律）。
  - 被 `inventory_projection.refresh` 消费：`outbound_plan.list(status=待出库)` 生成推移表预计出库量。
- **引用关系**：`material_no` / `customer_no` 分别为对 `md_material` / `md_customer` 的**弱引用**，不建物理外键，不做级联更新/删除。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `psc__outbound_plan__create` | `customer_no`：str，必填<br>`material_no`：str，必填<br>`qty`：number，必填（>0）<br>`out_date`：str，必填（YYYY-MM-DD）<br>`actual_out_no`：str \| None，可选 | 手工新建出库计划；日期早于今日直接记为 `已关闭`，否则 `待出库`。返回计划对象。 |
| `psc__outbound_plan__update` | `plan_no`：str，必填<br>其余字段可选（传入即覆盖） | 编辑出库计划（**已关闭亦可编辑延期**）；状态按最终 `out_date` 重算（今日及以后 → `待出库`）。 |
| `psc__outbound_plan__delete` | `plan_no`：str，必填 | 删除出库计划：仅 `待出库` 可删；已关闭为历史留痕，后端拦截。 |
| `psc__outbound_plan__close_expired` | 无 | 关闭到期计划：`待出库` 且 `out_date` 早于今日的计划批量置 `已关闭`（幂等），返回 `{closed: N}`。 |
| `psc__outbound_plan__get` | `plan_no`：str，必填 | 按计划号查看单条计划详情（读取前先惰性关闭到期计划）。 |
| `psc__outbound_plan__list` | `material_no`：str \| None，可选（精确）<br>`customer_no`：str \| None，可选（精确）<br>`status`：str \| None，可选（待出库 / 已关闭）<br>`page`：int \| None，可选<br>`size`：int \| None，可选 | 按物料 / 客户 / 状态筛选分页列表（读取前先惰性关闭到期计划），按 `out_date` 降序，返回 `{"items", "total"}`。 |

---

## 三、标准工作流

### 1. 登记一笔出库计划

1. 确认 `customer_no` / `material_no` 分别来自 `md_customer` / `md_material`（主数据引用铁律）。
2. 调 `psc__outbound_plan__create`，传 `customer_no`、`material_no`、`qty`、`out_date`（计划出库日期）。
3. 实际出库发生后，调 `psc__outbound_plan__update` 回填 `actual_out_no`（实际出库单号）。

### 2. 到期未执行 → 自动关闭 → 延期恢复

1. 计划出库日期早于今日后，下一次 list / get 读取时系统自动置 `已关闭`（无需手工触发）。
2. 如需继续执行：调 `psc__outbound_plan__update` 传 `plan_no` + 新的 `out_date`（今日及以后），状态自动恢复 `待出库`，重新进入库存推移表预计出库量。

### 3. 库存推移表消费

1. `inventory_projection.refresh` 内部调 `psc__outbound_plan__list(material_no, status=待出库)`。
2. 按计划出库日期合计为逐日预计出库量；已关闭计划不计入。

---

## 四、前置条件与注意事项

1. **主数据引用铁律**：`customer_no` 必须存在于 `md_customer`，`material_no` 必须存在于 `md_material`，创建/编辑时后端校验。
2. **惰性自动关闭**：关闭动作在 list / get 读取时结算；长期不访问页面时到期计划不会物理变化，但任何读取看到的都是已关闭状态，语义一致。
3. **删除约束**：仅 `待出库` 可删除；已关闭记录留作历史，如需继续执行请用编辑延期。
4. **数量约束**：`qty` 必须为大于 0 的数字。
5. **日期约束**：`out_date` 形如 YYYY-MM-DD（兼容 YYYYMMDD 输入，统一规范化）。
