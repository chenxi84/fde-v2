# demand_pool 应用 README（Agent 操作指南）

## 一、应用简介

- **应用组**：`psc`
- **应用名**：`demand_pool`
- **聚合根**：`DemandPool`（需求池 / 补库单）
- **主键**：`replenish_no`（系统自动生成，格式 `RP` + 日期 + 流水，如 `RP202608140001`）
- **同名库**：`demand_pool.db`
- **数据来源类型**：自动参考创建 —— 补库单由上游库存推移表（`inventory_projection.scan_alert`）击穿水位线时跨应用调用 `create` 自动生成，**前端不提供「新建」入口**。
- **是否跨应用**：是。
  - `create` 时调用 `md_material` 应用的 `get` 服务校验 `material_no` 是否存在（主数据引用铁律）。
  - `release` 时经应用内 `_dispatch_to_erp` 适配器下发生产计划给 ERP（出向，非跨应用调用）。
- **引用关系**：`demand_pool.material_no` 是对 `md_material.material_no` 的**弱引用**，不建物理外键，不做级联更新/删除。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `psc__demand_pool__create` | `material_no`：str，必填<br>`replenish_type`：str，必填（缺货补库 / 最低库存补库 / 安全库存补库）<br>`replenish_qty`：number，必填（触发档补货量）<br>`required_inbound`：str，必填（要求入库时间，击穿时点）<br>`stock_on_hand`：number \| None，可选<br>`min_level_a`：number \| None，可选<br>`safety_level_c`：number \| None，可选<br>`batch_level_b`：number \| None，可选<br>`capacity_tight`：bool \| None，可选，默认富余（False） | 库存推移表击穿触发自动生成补库单，初始状态 `待下达`，返回补库单对象。 |
| `psc__demand_pool__release` | `replenish_no`：str，必填<br>`promised_inbound`：str \| None，可选 | 下达生产：`待下达 → 已下达`，经 `_dispatch_to_erp` 下发生产计划给 ERP，可回填承诺入库时间。 |
| `psc__demand_pool__on_workorder_started` | `replenish_no`：str，必填 | ERP 回传工单开工：`已下达 → 生产中`。 |
| `psc__demand_pool__on_inbound` | `replenish_no`：str，必填 | ERP 回传入库：`生产中 → 已完成`（终态）。 |
| `psc__demand_pool__cancel` | `replenish_no`：str，必填 | 需求消失作废：`待下达 / 已下达 → 已取消`（终态）。 |
| `psc__demand_pool__get` | `replenish_no`：str，必填 | 按补库单号查看单条补库单详情。 |
| `psc__demand_pool__list` | `material_no`：str \| None，可选（精确）<br>`replenish_type`：str \| None，可选（精确）<br>`status`：str \| None，可选（精确）<br>`page`：int \| None，可选<br>`size`：int \| None，可选 | 按物料 / 类型 / 状态筛选分页列表，返回 `{"items", "total"}`。 |

---

## 三、标准工作流

### 1. 补库单生成（系统击穿触发，Agent 一般不手工发起）

1. `inventory_projection.scan_alert` 击穿水位线时，跨应用调用 `psc__demand_pool__create`。
2. 传入 `material_no`、`replenish_type`（按三类优先级判定：缺货 > 最低库存 > 安全库存）、`replenish_qty`、`required_inbound`。
3. 如需按产能松紧分档补货量，另传 `stock_on_hand`、`min_level_a`、`safety_level_c`、`batch_level_b`、`capacity_tight`：
   - 产能富余（默认）：补到组批水位 `batch_level_b`（补货量 = B − 当前库存）；
   - 产能紧张（`capacity_tight=True`）：补到触发水位线（缺货补回 0 / 最低补到 A / 安全补到 A+C）。
4. 创建成功后从返回值取得 `replenish_no`，状态为 `待下达`。

### 2. 下达生产闭环（标准状态机推进）

1. 先调 `psc__demand_pool__list`，筛选 `status="待下达"` 定位待下达补库单。
2. 调 `psc__demand_pool__get` 核对补库单当前状态与字段。
3. 确认产能允许后，调 `psc__demand_pool__release`（可传 `promised_inbound`）。
4. ERP 执行生产并回传开工 → 调 `psc__demand_pool__on_workorder_started`。
5. ERP 回传入库 → 调 `psc__demand_pool__on_inbound`，补库单转为 `已完成` 闭环结束。

### 3. 需求消失取消

1. 调 `psc__demand_pool__list` 或 `psc__demand_pool__get` 定位目标补库单。
2. 确认补库需求已消失（库存已补 / 客户取消）且状态为 `待下达` 或 `已下达`。
3. 调 `psc__demand_pool__cancel`，补库单转为 `已取消`（终态）。

---

## 四、前置条件与注意事项

1. **创建前必须确认物料存在**
   - `create` 会调用 `md_material.get` 校验 `material_no`。
   - 若物料不存在，补库单不会创建。

2. **字段约束**
   - `material_no` 必填，禁止手工录入，必须引用 `md_material`。
   - `replenish_type` 仅限 `缺货补库` / `最低库存补库` / `安全库存补库` 三类。
   - `replenish_qty` 必须为正数（> 0）。
   - `required_inbound` 必填；`promised_inbound` 可选，在 `release` 时回填。

3. **补库单号由系统生成**
   - `replenish_no` 由 `demand_pool` 应用自动生成（`RP` + 日期 + 流水）。
   - Agent 不能指定 `replenish_no`；后续查询与流转都必须使用已存在的 `replenish_no`。

4. **三类补库优先级**
   - `缺货补库 > 最低库存补库 > 安全库存补库`，同一物料同时满足多个触发条件时按最高优先级处理。

5. **状态机约束（详见 §五）**
   - `待下达` 只能 `release` 或 `cancel`。
   - `已下达` 只能 `on_workorder_started` 或 `cancel`。
   - `生产中` 只能 `on_inbound`。
   - `已完成`、`已取消` 为终态，不可再流转。

6. **无手工新建 / 修改 / 删除服务**
   - 本应用不提供用户手工新建入口（`create` 为系统击穿触发）。
   - 本应用不提供修改补库数量、物料、类型的服务。
   - 本应用不提供删除补库单服务（作废走 `cancel`）。

7. **ERP 适配器为 stub**
   - `release` 调用的 `_dispatch_to_erp` 当前返回本地 stub 回执，真实接入时只换适配器实现，公共方法不变。

8. **权限由平台控制**
   - Agent 能否调用这些工具，由平台授权决定；应用本身不做鉴权。

---

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `物料号不能为空` | `create` 传入的 `material_no` 为空或全是空白。 | 向用户索要有效物料号，或先查 `md_material` 列表取得有效编号。 |
| `补库类型仅支持缺货/最低库存/安全库存补库` | `create` 的 `replenish_type` 不在三类枚举内，或 `list` 的 `replenish_type` 筛选值非法。 | 将值改为 `缺货补库` / `最低库存补库` / `安全库存补库` 后重试。 |
| `补库数量必须为数字` | `create` 计算/传入的补货量不是数字。 | 传入合法数值，或补齐 `stock_on_hand` 与水位线参数让其按分档计算。 |
| `补库数量必须大于0` | 补货量 ≤ 0（如库存余额已 ≥ 目标水位），BR-09 不生成补库单。 | 说明该物料无需补库，不生成补库单；如确需补库，核对水位线参数与当前库存。 |
| `要求入库时间不能为空` | `create` 传入的 `required_inbound` 为空。 | 补传击穿时点（要求入库时间）后重试。 |
| `物料记录不存在` | `create` 时 `md_material.get` 未找到该物料。 | 先核对 `material_no`；必要时先在 `md_material` 创建物料主数据，确认存在后重试。 |
| `物料校验失败` | `create` 调用 `md_material.get` 出现系统异常。 | 稍后重试；若持续失败，提示人工介入或联系维护。 |
| `补库单号生成失败，请重试` | 系统生成 `replenish_no` 时连续冲突，极少发生。 | 直接重试 `create`；若多次失败，提示人工介入或联系维护。 |
| `补库单号不能为空` | `release` / `on_workorder_started` / `on_inbound` / `cancel` / `get` 传入的 `replenish_no` 为空或空白。 | 提供非空 `replenish_no`；若不知道编号，先调 `list` 查询。 |
| `补库单不存在` | 传入的 `replenish_no` 查不到补库单。 | 先调 `list` 或 `get` 核对编号；确认补库单存在后再执行操作。 |
| `当前状态不可下达` | 对非 `待下达` 的补库单执行了 `release`（状态机非法跳转）。 | 先 `get` 查看状态；仅 `待下达` 可下达；`已下达` 等其开工回传，`生产中`/`已完成`/`已取消` 不可下达。 |
| `当前状态不可开工回传` | 对非 `已下达` 的补库单执行了 `on_workorder_started`（如 `待下达` 或 `已完成`）。 | 先 `get` 查看状态；仅 `已下达` 可开工回传；若为 `待下达` 先 `release`，终态不可回传。 |
| `当前状态不可入库回传` | 对非 `生产中` 的补库单执行了 `on_inbound`（如 `待下达` 或 `已下达`）。 | 先 `get` 查看状态；仅 `生产中` 可入库回传；若为 `已下达` 先等开工回传。 |
| `当前状态不可取消` | 对 `生产中` 或 `已完成` 的补库单执行了 `cancel`（状态机非法跳转）。 | 先 `get` 查看状态；仅 `待下达` / `已下达` 可取消；`生产中`/`已完成` 不可取消。 |
| `状态筛选不合法` | `list` 传入的 `status` 不是 `待下达` / `已下达` / `生产中` / `已完成` / `已取消`。 | 只使用合法状态筛选，或省略 `status` 参数后重试。 |
| `分页参数不合法` | `list` 的 `page` / `size` 不是合法整数。 | 传正整数页码与每页条数后重试。 |
| `页码必须大于等于1` | `list` 的 `page` < 1。 | 将 `page` 改为 ≥ 1 后重试。 |
| `每页条数必须大于等于1` | `list` 的 `size` < 1。 | 将 `size` 改为 ≥ 1 后重试。 |
