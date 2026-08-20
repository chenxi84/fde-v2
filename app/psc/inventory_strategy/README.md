# inventory_strategy 应用 README（Agent 操作指南）

## 一、应用简介

- **应用名**：`inventory_strategy`
- **所属应用组**：`psc`
- **聚合根**：`InventoryStrategy`
- **业务主键**：`version_no + material_no`（复合主键）
- **同名库**：`inventory_strategy.db`
- **数据来源类型**：自动参考创建——水位为系统按物料参数 + 客户缓冲参数 + 历史干净需求自动计算的派生值，**无 `create` 服务**，前端只提供查看 + 计算/重算。
- **是否跨应用调用**：
  - `calc` 调用 `md_material.get(material_no=...)`、`md_customer.get(customer_no=...)`（`customer_no` 缺省时按缓冲 0 处理）。
  - `calc_batch` 调用 `md_material.list(status="正常")` 确定物料范围。
  - 历史干净需求经 `_load_sales_history` 适配器取数（当前为 stub，真实接入 ERP 时替换实现）。

本应用为每个物料×月度版本计算三层水位——最低库存 A、安全库存 C、组批库存 B，并判定品种分层对冲工具（库存/速度），产出水位带（下限 A+C、上限 A+C+B），供毛需求叠加与库存推移表对照水位线。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `psc__inventory_strategy__calc` | `version_no: str`，必填，无默认<br>`material_no: str`，必填，无默认<br>`customer_no: str`，可选，默认 `None` | 计算单物料库存策略。取物料参数（生产/物流时间、满足率目标、组批窗口、价值分类）与客户缓冲参数（缺省 0），按三层水位公式计算并落库。同版本同物料重复计算即覆盖更新（重算）。返回完整策略记录（含水位带派生值）。 |
| `psc__inventory_strategy__calc_batch` | `version_no: str`，必填，无默认 | 整版本批量计算。取 `md_material.list(status="正常")` 的物料范围，逐物料计算；单个物料失败不中断其余。返回 `{total, success, fail, errors}`，`errors` 列出失败物料号与原因。 |
| `psc__inventory_strategy__get` | `version_no: str`，必填，无默认<br>`material_no: str`，必填，无默认 | 查看单物料库存策略详情，含三层水位、对冲工具、服务系数、响应窗口波动、组批窗口、设定依据，及水位带下限/上限派生值。 |
| `psc__inventory_strategy__list` | `version_no: str`，可选，默认 `None`（精确匹配）<br>`material_no: str`，可选，默认 `None`（模糊匹配）<br>`hedge_tool: str`，可选，默认 `None`（精确匹配，仅 `库存`/`速度`）<br>`page: int`，可选，默认 `None`<br>`size: int`，可选，默认 `None` | 按版本/物料/对冲工具筛选查看列表（条件 AND 关系），默认按 `material_no` 升序。返回 `{"items": [...], "total": N}`；`page`/`size` 均缺省时返回全部。 |
| `psc__inventory_strategy__get_water_level` | `version_no: str`，必填，无默认<br>`material_no: str`，必填，无默认 | 跨应用接口，返回三层水位 `{min_level, safety_level, batch_level, lower, upper}`，供毛需求合成与库存推移表对照水位线。 |

---

## 三、标准工作流

### 1. 计算单物料库存策略

前置：物料主数据（`md_material`）已具备生产/物流时间、满足率目标、组批窗口、价值分类；历史干净需求可取数。

推荐顺序：

1. 先调 `psc__inventory_strategy__calc(version_no="202608", material_no="8210001")` 触发计算/重算。
2. 计算成功返回完整记录；如需确认落库，再调 `psc__inventory_strategy__get(version_no="202608", material_no="8210001")`。

示例顺序：

```text
psc__inventory_strategy__calc(version_no="202608", material_no="8210001")
psc__inventory_strategy__get(version_no="202608", material_no="8210001")
```

若客户有明确稳定缓冲协议（需扣减可用缓冲天数），传入 `customer_no`：

```text
psc__inventory_strategy__calc(version_no="202608", material_no="8210001", customer_no="C1001")
```

### 2. 整版本批量计算库存策略

推荐顺序：

1. 先调 `psc__inventory_strategy__calc_batch(version_no="202608")` 一次性生成整张策略表。
2. 检查返回的 `fail` 与 `errors`：对失败物料逐条定位原因（多为历史数据缺失或参数缺失）。
3. 补齐主数据/历史数据后，可对该物料单独重算 `psc__inventory_strategy__calc`。

示例顺序：

```text
psc__inventory_strategy__calc_batch(version_no="202608")
psc__inventory_strategy__calc(version_no="202608", material_no="失败物料号")
```

### 3. 查看库存策略列表与详情

推荐顺序：

1. 先调 `psc__inventory_strategy__list(version_no="202608", material_no="8210")` 定位候选记录。
2. 从列表取目标 `material_no`，再调 `psc__inventory_strategy__get` 查看完整参数与设定依据。
3. 可按 `hedge_tool="库存"` 或 `"速度"` 筛选品种分层。

示例顺序：

```text
psc__inventory_strategy__list(version_no="202608", material_no="8210")
psc__inventory_strategy__get(version_no="202608", material_no="8210001")
```

### 4. 下游应用取三层水位

下游应用（毛需求/库存推移表）直接调用：

```text
psc__inventory_strategy__get_water_level(version_no="202608", material_no="8210001")
```

返回 `min_level`/`safety_level`/`batch_level` 及水位带 `lower`/`upper`；若报「库存策略记录不存在」，应先触发 `calc` 再取数。

---

## 四、前置条件与注意事项

1. **无 create 服务**
   - 水位为系统计算派生值，本应用不提供手工录入/新建水位的服务。
   - 需新增/修正水位时，只能通过 `calc` / `calc_batch` 重新计算。

2. **复合主键与重算覆盖**
   - `version_no + material_no` 唯一；同一物料同版本重复 `calc` 是**覆盖更新**（重算），不新增行。

3. **主数据引用铁律（禁止手工录入参数）**
   - 生产时间 `prod_days`、物流时间 `logistics_days`、满足率目标 `service_level`、组批窗口 `batch_window`、价值分类 `value_class` 等均来自 `md_material`。
   - 可用缓冲天数 `line_stock_days`、调拨提前期 `transfer_lead_days` 来自 `md_customer`。
   - 历史干净需求经 `_load_sales_history` 适配器取数（当前 stub 返回空列表，**真实接入 ERP 前 `calc`/`calc_batch` 会因历史数据缺失而失败**，接入时只需替换 `_load_sales_history` 实现）。

4. **版本号格式**
   - `version_no` 必须为 `YYYYMM`（6 位数字，月 01~12），否则报错。

5. **满足率目标取值**
   - `service_level` 仅支持 90% / 95% / 98% / 99%（对应服务系数 1.28 / 1.65 / 2.05 / 2.33）；`md_material` 中以 0~1 存储（如 `0.95`），也兼容百分数（如 `95`）。

6. **品种分层对冲工具**
   - `hedge_tool` 仅 `库存`/`速度`。判定：价值分类为「高」且（生产时间+物流时间 ≤ 线边库存天数+调拨提前期）→ `速度`（安全库存 C=0、组批 B=0）；否则 `库存`。
   - 多客户物料的客户缓冲取值默认按 0 处理（业务待确认），仅在显式传入 `customer_no` 时按该客户参数扣减。

7. **跨应用依赖**
   - `calc` 依赖 `md_material.get`、`md_customer.get`；`calc_batch` 依赖 `md_material.list(status="正常")`。
   - 依赖服务抛出的 `FdeError`（如「物料记录不存在」）会原样传播，`calc_batch` 会将其记入 `errors`。

8. **弱引用风险**
   - 物料/客户被其他应用弱引用；本应用不删除主数据，正常业务路径下不会出现因主数据删除导致的引用悬空。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `月度版本不能为空` | 调用 `calc`/`calc_batch`/`get`/`get_water_level` 时未提供有效 `version_no`。 | 向用户索要月度版本号（YYYYMM）；确认非空后重新调用。 |
| `版本号格式必须为 YYYYMM` | `version_no` 不是 6 位数字或月份不在 01~12。 | 请用户提供合法版本号，如 `202608`；修正后重新调用。 |
| `物料号不能为空` | 调用 `calc`/`get`/`get_water_level` 时未提供有效 `material_no`。 | 向用户索要物料号；确认非空后重新调用。 |
| `生产时间不能为负` | `md_material` 中该物料 `prod_days` 为负。 | 引导用户先在 `md_material` 修正生产时间（≥0）后重算。 |
| `物流时间不能为负` | `md_material` 中该物料 `logistics_days` 为负。 | 引导用户先在 `md_material` 修正物流时间（≥0）后重算。 |
| `组批窗口不能为负` | `md_material` 中该物料 `batch_window` 为负。 | 引导用户先在 `md_material` 修正组批窗口（≥0）后重算。 |
| `满足率目标不能为空` | `md_material` 中该物料未配置 `service_level`。 | 引导用户先在 `md_material` 补全满足率目标后重算。 |
| `满足率目标格式非法` | `service_level` 非数字。 | 请用户在 `md_material` 中改为数字（如 `0.95`）后重算。 |
| `满足率目标仅支持 90%/95%/98%/99%` | `service_level` 不在支持值内。 | 请用户将满足率目标改为 90%/95%/98%/99% 之一后重算。 |
| `物料 ... 历史需求数据缺失，无法计算库存策略` | `_load_sales_history` 未取到该物料近 N 期干净需求（stub 阶段恒为此结果）。 | 确认历史需求是否已接入；若为 stub，提示需接入真实 ERP 历史数据后再计算。 |
| `数值参数非法` | `md_material`/`md_customer` 的数值字段为非法值。 | 引导用户先修正对应主数据的数值字段后重算。 |
| `库存策略记录不存在` | 调用 `get`/`get_water_level` 时目标物料×版本尚无策略记录。 | 先调 `psc__inventory_strategy__calc` 计算该物料；或先 `list` 核对 `version_no`/`material_no` 是否正确。 |
| `对冲工具筛选不合法` | 调用 `list` 时 `hedge_tool` 不是 `库存`/`速度`。 | 将 `hedge_tool` 改为 `库存` 或 `速度`；不需要该过滤时可省略或传 `None`。 |
| `分页参数非法` | 调用 `list` 时 `page`/`size` 非正整数。 | 将 `page`/`size` 改为正整数；或省略以返回全部数据。 |
| `物料 ... 不存在`（来自 `md_material.get`） | 该物料号未在物料主数据中登记。 | 引导用户先在 `md_material` 建立该物料主数据，再触发 `calc`。 |
| `客户 ... 不存在`（来自 `md_customer.get`） | 传入的 `customer_no` 未在客户主数据中登记。 | 引导用户先在 `md_customer` 建立该客户主数据；或省略 `customer_no` 按缓冲 0 计算。 |
