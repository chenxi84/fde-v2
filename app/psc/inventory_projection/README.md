# inventory_projection 应用 README（Agent 操作指南）

## 一、应用简介

- **应用组**：`psc`
- **应用名**：`inventory_projection`
- **聚合根**：`InventoryProjection`（库存推移表）
- **主键**：复合主键 `material_no + biz_date`
- **同名库**：`inventory_projection.db`（平台自动创建，应用不自建连接）
- **数据来源类型**：自动参考创建——由系统逐日刷新推演生成，**前端只读**，不提供创建 / 编辑 / 删除入口。
- **是否跨应用**：是。
  - `refresh` 调用 `master_plan.get_latest` + `demand_pool.list`（取预计入库量）、`outbound_plan.list`（取预计出库量）、`inventory_strategy.get_water_level`（取三层水位 A/C/B）；
  - `refresh_batch` 调用 `md_material.list`（取「正常」状态物料范围）；
  - `scan_alert` 调用 `inventory_strategy.get_water_level`（对照水位线）、`demand_pool.create`（击穿时生成补库单）。
- **外部系统**：ERP 库存经应用内 `_load_inventory` 适配器接入（当前为 stub，真实接入只换适配器实现）。
- **引用关系**：`material_no` 对 `md_material` 为**弱引用**（不建物理外键，不做级联），主数据引用铁律——物料号来自 `md_material`，禁止手工录入。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `psc__inventory_projection__refresh` | `material_no`：str，必填<br>`biz_date`：str，必填（YYYY-MM-DD）<br>`opening_stock`：float \| None，可选，默认 `None`（缺省取 ERP 库存） | 对单物料逐日推演未来 3 个月（90 自然日）库存水位并落盘，返回逐日记录列表与起始库存、版本号。 |
| `psc__inventory_projection__refresh_batch` | `biz_date`：str \| None，可选，默认当天（YYYY-MM-DD）<br>`material_nos`：list \| None，可选，默认 `None`（缺省取 `md_material` 正常状态物料全量） | 整批刷新推移表，刷新成功后逐物料联动 `scan_alert`（击穿水位**自动创建**需求池补库单）；返回 `{total, success, fail, success_materials, errors, replenishments}`。 |
| `psc__inventory_projection__get` | `material_no`：str，必填<br>`biz_date`：str，必填 | 按物料号 + 日期查询单日推移明细（入库/出库/余额/预警类型）。 |
| `psc__inventory_projection__list` | `material_no`：str \| None，可选，精确匹配<br>`biz_date`：str \| None，可选，精确匹配<br>`alert_type`：str \| None，可选，精确匹配（无/缺货/击穿最低/击穿安全/呆滞/超储）<br>`page`：int \| None，可选，默认 `None`（None 返回全部）<br>`size`：int \| None，可选，默认 `None` | 按物料/日期/预警类型筛选推移表列表，默认按 `biz_date` 升序（从早到晚）且只显示当日及以后（BR-11 历史隐藏；选定具体历史日期可回看），返回 `{"items": [...], "total": N}`。 |
| `psc__inventory_projection__scan_alert` | `material_no`：str，必填<br>`version_no`：str \| None，可选，默认 `None`（缺省由该物料最早推移日期推断） | 对照水位线扫描某物料推移表，回填 `alert_type`；击穿水位（缺货/最低/安全）触发 `demand_pool.create` 生成补库单。 |

---

## 三、标准工作流

### 1. 查看某物料的水位走势与预警时点

1. 先调 `psc__inventory_projection__list`，传 `material_no="<物料号>"`（可加 `alert_type` 筛选），取得逐日推移记录。
2. 命中预警的行（`alert_type ≠ 无`）即预警时点；需看某日明细时，调 `psc__inventory_projection__get`，传 `material_no` + `biz_date`。
3. 对缺货/击穿行，跟进需求池补库单；对超储/呆滞行，跟进降储治理。

### 2. 单物料刷新推演

1. 确认 `material_no` 来自 `md_material`（主数据引用铁律）。
2. 调 `psc__inventory_projection__refresh`，传 `material_no`、`biz_date`（推演起始日，如 `2026-08-14`）；如需指定起始库存可传 `opening_stock`，否则系统取 ERP 库存。
3. 刷新后如需生成补库单，再调 `psc__inventory_projection__scan_alert`。

### 3. 整批刷新 + 预警联动（每日 0 点定时）

1. 调 `psc__inventory_projection__refresh_batch`（可不传参：自动当天 + 全量正常物料）。
2. 系统内部先逐物料 `refresh`，再对刷新成功的物料逐个 `scan_alert`（击穿时自动 `demand_pool.create`）。
3. 从返回的 `errors` 关注失败物料，从 `replenishments` 关注新生成的补库单。

---

## 四、前置条件与注意事项

1. **物料号引用主数据（主数据引用铁律）**
   - `material_no` 必须来自 `md_material`；`refresh_batch` 的物料范围取自 `md_material.list(status="正常")`。
   - 单物料 `refresh` 不单独校验物料存在性，调用方须保证 `material_no` 有效。

2. **跨应用依赖须先就绪**
   - `refresh` 依赖 `master_plan.get_latest(version_no, material_no)` 提供预计入库量（主计划月度需求 + 最迟入库日期）。
   - `scan_alert` 依赖 `inventory_strategy.get_water_level(version_no, material_no)` 提供三层水位 A（最低）/ C（安全）/ B（组批）；无策略记录时无法预警。
   - `scan_alert` 击穿时调用 `demand_pool.create` 生成补库单，故 `demand_pool` 应用须已就绪。

3. **推演口径**
   - 起始库存 = ERP 自有仓成品库存（`_load_inventory`）；逐日递推 `balance(t) = balance(t-1) + 入库(t) - 出库(t)`。
   - 预计入库 = 主计划月度需求（集中记在 `latest_inbound_date` 当天）+ 需求池「已下达 / 生产中」补库单（`demand_pool.list`，按承诺/要求入库日）。
   - 预计出库 = 「待出库」出库计划按计划出库日期合计（`outbound_plan.list`）。
   - 推演窗口 = 未来 3 个月（90 自然日），首日 balance 锚定 ERP 库存（首日通常无流量）。

4. **预警水位线判定（BR-08）**
   - `balance < 0` → 缺货；`0 ≤ balance < A` → 击穿最低；`A ≤ balance < A+C` → 击穿安全；`balance > B` → 超储；其余 → 无。
   - 「呆滞」的触发阈值 BRD 未定义（待确认），当前代码不产出「呆滞」，仅保留枚举取值。

5. **已结束日期隐藏不删除（BR-11）**
   - `refresh` 只重算当前 90 天窗口，历史（已结束）日期的记录保留在库，仅由前端隐藏。

6. **补库量口径**
   - `scan_alert` 计算补库量 = 补回触发水位线的缺口（产能紧张基线：缺货补回 0、最低补到 A、安全补到 A+C）。
   - 产能富余时「补到组批 B」的分档规则属 `demand_pool` 聚合（本应用仅触发 create）。

7. **去重策略待确认**
   - `scan_alert` 幂等：可重复执行；但同一物料持续击穿时，每次执行都可能重复触发 `demand_pool.create`。连续多日击穿的补库单去重策略待业务方确认。

---

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `物料号不能为空` | `refresh` / `get` / `scan_alert` 传入的 `material_no` 为空或空白。 | 向用户索要物料号，或先调 `md_material` 工具查询有效物料号。 |
| `推演起始日期格式非法，应为 YYYY-MM-DD` | `refresh` / `refresh_batch` 的 `biz_date` 不是合法日期。 | 改用 `YYYY-MM-DD` 格式（如 `2026-08-14`）重新调用。 |
| `日期不能为空` | `get` 的 `biz_date` 为空或空白。 | 提供非空日期；若不知道具体日期，先调 `list` 查询。 |
| `预警类型筛选不合法` | `list` 的 `alert_type` 不是 无/缺货/击穿最低/击穿安全/呆滞/超储 之一。 | 改用合法枚举值，或省略 `alert_type` 参数后重试。 |
| `分页参数不合法` | `list` 的 `page` / `size` 无法解析为整数。 | 传入正整数页码与条数；不需要分页时省略 `page` / `size`。 |
| `推移记录不存在` | `get` 按物料号+日期查不到记录。 | 先调 `list` 确认该物料是否有推移记录；必要时先调 `refresh` 生成。 |
| `该物料暂无库存推移记录，请先执行刷新` | `scan_alert` 时该物料还没有推移记录。 | 先调 `refresh`（或 `refresh_batch`）生成推移记录，再执行 `scan_alert`。 |
| `库存策略记录不存在，无法扫描预警` | `scan_alert` 时该物料+版本无库存策略水位（A/C/B）。 | 先调 `inventory_strategy` 工具为对应版本计算水位，再重新 `scan_alert`。 |
| `无可推演物料，请先确认物料主数据` | `refresh_batch` 未取得「正常」状态物料（或 `material_nos` 为空）。 | 先确认 `md_material` 中存在正常状态物料，或显式传入 `material_nos` 列表。 |
| `推移记录日期格式非法` | 库中已有推移记录的日期无法解析（数据异常）。 | 提示人工排查该物料历史推移记录；必要时重新 `refresh` 覆盖当前窗口。 |
