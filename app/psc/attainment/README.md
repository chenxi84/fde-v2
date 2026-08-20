# attainment 应用 README（Agent 操作指南）

## 一、应用简介

- **应用名**：`attainment`
- **所属应用组**：`psc`（产销协同应用组）
- **聚合根**：`Attainment`
- **业务主键**：`customer_no + material_no`（同一客户+物料唯一）
- **同名库**：`attainment.db`
- **数据来源类型**：自动参考创建（无 `create` 服务，前端禁止创建入口）
- **是否跨应用调用**：
  - `compute` 仅调用 `sales_history.list` 单表计算（口径A）：行内 forecast_qty 为 F、qty 为 A，不再 join 销售预测。
  - 本应用会被 `sales_forecast` 应用通过 `self.fde.call("attainment", "get", ...)` 读取 MAPE/bias，用于调整客户预测值（调整后需求 = 原始需求 × (1 − bias)）与异常标记（MAPE 阈值判定）。

本应用维护客户×物料粒度的达成率与置信度派生指标：MAPE（平均绝对百分比误差，幅度准确性，非负）与 bias（预测方向性偏差，多报为正、少报为负）。来源二选一：ERP 统计经 `upsert` 冗余回写，或系统内 `compute`（口径A）计算回写。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `psc__attainment__upsert` | `customer_no: str`，必填，无默认<br>`material_no: str`，必填，无默认<br>`mape: float`，必填，无默认<br>`bias: float`，必填，无默认 | ERP 统计回写 MAPE/bias。同客户+物料已存在则覆盖更新，不存在则插入（幂等），不产生重复行。`mape` 必须非负；`bias` 必须为数值（可正可负）。返回该条记录。 |
| `psc__attainment__get` | `customer_no: str`，必填，无默认<br>`material_no: str`，必填，无默认 | 按客户+物料查询该组合的 MAPE/bias。命中返回完整记录；未命中返回 `None`，不抛异常。 |
| `psc__attainment__list` | `customer_no: str`，可选，默认 `None`<br>`material_no: str`，可选，默认 `None`<br>`page: int`，可选，默认 `None`（None 表示不分页）<br>`size: int`，可选，默认 `None`（默认每页 20 条） | 按客户/物料筛选达成率列表（两个条件为 AND 关系，均为空时返回全部）。返回 `{"items": [...], "total": 总数}`，`total` 为切片前全量行数。 |
| `psc__attainment__compute` | `months: int`，可选，默认 `6` | 口径A **单表**计算 MAPE/bias 并 upsert 回写：直接读 sales_history 行内 forecast_qty(F) 与 qty(A)，无需 join 销售预测；滚动 months 个月，窗口内有效样本<3 或 Σ实际=0 跳过。返回 `{computed, skipped}`。 |

---

## 三、标准工作流

### 1. ERP 统计回写（系统回写，非用户触发）

由 ERP 达成率统计同步任务驱动，Agent 通常不主动触发。若需回写，先取 ERP 统计结果，再按客户×物料逐条 `upsert`。

```text
psc__attainment__upsert(customer_no="C001", material_no="M001", mape=0.12, bias=0.08)
```

同组合再次 `upsert` 会幂等覆盖为最新 mape/bias。

### 2. 按客户+物料查询 MAPE/bias（供销售预测取用）

已知 `customer_no` 与 `material_no` 时，直接调 `get`。

```text
psc__attainment__get(customer_no="C001", material_no="M001")
```

未命中返回 `None`（无该组合的达成率数据），调用方据此决定是否跳过置信度调整。

### 3. 批量查看 / 月度复盘

先按客户或物料筛选列表，必要时再 `get` 单条核对。

```text
psc__attainment__list(customer_no="C001")
psc__attainment__list(material_no="M001", page=1, size=20)
```

---

## 四、前置条件与注意事项

1. **标识字段必填且引用主数据**
   - `customer_no`、`material_no` 为联合主键，必填不可为空。
   - 二者分别是 `md_customer`、`md_material` 的主数据引用，本应用**不校验**其主数据存在性（主数据一致性由 ERP 同步与对应主数据应用各自维护）。

2. **同客户+物料唯一（upsert 幂等）**
   - 达成率以「客户 + 物料」为唯一标识，同一组合只存在一条记录。
   - 重复回写同组合会覆盖 mape/bias，记录数不变，不会产生重复行。

3. **mape 非负**
   - mape 为平均绝对百分比误差（幅度准确性），取值必须非负；负值会被拒绝。
   - bias 为方向性偏差，可正可负（多报为正、少报为负）。

4. **无 create / 无删除 / 无编辑入口**
   - 本应用为「自动参考创建」，不提供 `create`、`delete`、`update` 服务，Agent 不应尝试调用不存在的写入工具。
   - 写入只经 `upsert` 由 ERP 同步驱动。

5. **列表查询行为**
   - `customer_no` 与 `material_no` 同时传入时取交集（AND 关系）；均为空时返回全部数据。
   - `page`/`size` 均为 `None` 时不分页返回全部；默认每页 20 条。

6. **外部适配器 `_load_attainment`**
   - V1 为本地 stub，返回空 dict、不执行任何回写。
   - 真实接入时仅替换该适配器实现（从 ERP 拉取 MAPE/bias 后逐条 `upsert`），公共方法签名不变。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `客户编码/物料号不能为空` | 调用 `upsert` 或 `get` 时，`customer_no` 或 `material_no` 为空。 | 向用户索要客户编码与物料号，确认非空后重新调用。 |
| `MAPE 不能为负` | 调用 `upsert` 时传入的 `mape` 为负值。 | 确认 mape 应为非负的幅度误差（绝对值口径），修正为正数或 0 后重新调用。 |
| `MAPE 必须为数值` | 调用 `upsert` 时传入的 `mape` 无法转换为数字。 | 向用户索要合法的数字 mape（如 0.12），修正后重新调用。 |
| `bias 必须为数值` | 调用 `upsert` 时传入的 `bias` 无法转换为数字。 | 向用户索要合法的数字 bias（如 0.08 或 -0.05），修正后重新调用。 |
| `分页参数非法` | 调用 `list` 时 `page` 或 `size` 无法转换为整数。 | 传入合法的整数值（如 page=1, size=20），或省略以使用默认行为。 |
