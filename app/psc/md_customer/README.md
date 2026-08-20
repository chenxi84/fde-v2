# md_customer · 客户主数据

## 一、应用简介

- **聚合根**：`MdCustomer`（客户主数据），是客户编码（customer_no）的权威来源。
- **主键**：`customer_no`（文本，全局唯一，单字段主键，不可修改）。
- **数据存储**：本应用同名库 `md_customer.db`（平台管理，含平台自动追加的审计列）。
- **跨应用调用**：无。本应用不调用其他应用，属主数据层，被销售预测 / 库存策略 / 达成率等下游聚合以 `customer_no` 弱引用（本应用不感知、不维护）。
- **字段**：`customer_no`（客户编码）、`customer_name`（客户名称）、`credit_code`（统一社会信用代码，18 位，GB 32100-2015 校验位）、`settle_mode`（结算模式，字典值：现售 / 寄售，空值=未设置）、`line_stock_days`（线边库存天数，默认 0）、`transfer_lead_days`（调拨提前期）。

## 二、对外服务（工具）

工具名统一为 `psc__md_customer__<服务名>`。

| 工具名 | 参数（类型 / 必填 / 默认） | 说明 |
|---|---|---|
| `psc__md_customer__create` | `customer_no`(str,必填) · `customer_name`(str,必填) · `settle_mode`(str,选填,字典:现售/寄售) · `line_stock_days`(int,选填,默认0) · `transfer_lead_days`(int,选填) · `credit_code`(str,选填,18位统一社会信用代码) | 新建客户主数据，`customer_no` 全局唯一 |
| `psc__md_customer__get` | `customer_no`(str,必填) | 按客户编码查看单条详情 |
| `psc__md_customer__list` | `customer_no`(str,选填,模糊) · `customer_name`(str,选填,模糊) · `credit_code`(str,选填,模糊,自动大写化) · `page`(int,选填,默认1) · `size`(int,选填,默认20) | 分页列表，按 customer_no 升序；返回 `{"items":[...], "total":N}`，`total` 为切片前全量行数 |
| `psc__md_customer__update` | `customer_no`(str,必填) · `customer_name`(str,选填) · `settle_mode`(str,选填,字典:现售/寄售) · `line_stock_days`(int,选填) · `transfer_lead_days`(int,选填) · `credit_code`(str,选填,18位统一社会信用代码) | 更新客户主数据，`customer_no` 主键不可改，未传字段不更新 |
| `psc__md_customer__import_batch` | `rows`(list[dict],必填) | 批量 upsert：已存在 `customer_no` 更新，不存在新增；返回 `{"total":N,"success":N,"fail":N,"errors":[{row,field,message}]}` |

> `list` 的分页参数名是 `size`（不是 `page_size`）；`page` 与 `size` 都缺省时返回全部数据。

## 三、标准工作流

**新建客户**：先 `list`（按 customer_no 模糊）核对编码是否已存在 → 不存在则 `create` → 用返回的 `customer_no` 回 `get` 确认。

**查看 / 定位**：`list`（可按编码 / 名称模糊筛选、分页）→ 点击目标行 → `get` 查看完整字段。

**维护参数**：`list` / `get` 定位到目标客户 → `update` 修改 `customer_name` / `settle_mode` / `line_stock_days` / `transfer_lead_days` → 再次 `get` 确认生效。

**ERP 冗余同步（批量导入）**：用平台文件工具读取上传的导入文件并解析成 `rows`（每行一个 dict，键：`customer_no, customer_name, credit_code, settle_mode, line_stock_days, transfer_lead_days`）→ `import_batch(rows)` → 检查返回的 `success` / `fail` 与 `errors` 明细，把失败行反馈给用户或修正后重导。

## 四、前置条件与注意事项

- **必填**：`customer_no`、`customer_name` 必填，不可为空字符串。
- **唯一**：`customer_no` 全局唯一，创建时重复会报错；批量导入时重复主键执行**更新（upsert）**而非拒绝。
- **长度**：`customer_no` ≤ 50 字符，`customer_name` ≤ 100 字符。
- **数值约束**：`line_stock_days`、`transfer_lead_days` 有值时必须为非负整数；`line_stock_days` 未填默认 0；`transfer_lead_days` 未填存空（是否必填待业务方确认）。
- **结算模式字典**：`settle_mode` 字典值为 **现售 / 寄售**（2026-08 业务确认）；空值允许（未设置），非空必须命中字典，否则报「结算模式必须为字典值：现售 / 寄售」（create/update 抛错，import_batch 记入行级 errors）。
- **统一社会信用代码**：`credit_code` 选填；非空时必须为 18 位 GB 32100-2015 合法代码（字符集为数字+大写，不含 I/O/Z/S/V，末位为校验位）。录入自动转大写；长度错误报「统一社会信用代码必须为18位」，字符非法报「含非法字符」，校验位不符报「校验位不正确」。
- **主键不可改**：`update` 不能修改 `customer_no`；`customer_name` 不可更新为空。
- **无删除功能**：V1 只增不改删，避免预测链级联问题，请勿尝试删除客户记录。
- **无跨应用依赖**：本应用不调用其他应用；下游（sales_forecast / inventory_strategy / attainment）以 `customer_no` 弱引用，删除/改码会破坏下游，故主键不可变。
- **审计列由平台自动维护**：无需也不要在 DDL / DML 中手写 `created_at` 等审计字段。

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 应对 |
|---|---|---|
| 客户编码不能为空 | `customer_no` 未填或为空字符串 | 向用户索要客户编码后重试 |
| 客户编码不能超过50字符 | `customer_no` 超长 | 核对编码，缩短至 50 字符内重试 |
| 该客户编码已存在 | 创建时主键冲突 | 先 `list`/`get` 核对；若确为同一客户，改用 `update` 或 `import_batch`（upsert） |
| 客户名称不能为空 | `customer_name` 未填或为空字符串 | 向用户索要客户名称后重试 |
| 客户名称不能超过100字符 | `customer_name` 超长 | 缩短名称至 100 字符内重试 |
| 结算模式必须为字典值：现售 / 寄售 | `settle_mode` 非空但不在字典内 | 改为 现售 / 寄售 之一或留空后重试 |
| 统一社会信用代码必须为18位 | `credit_code` 长度不为 18 | 补齐 18 位后重试 |
| 统一社会信用代码含非法字符（仅数字与大写字母，不含 I/O/Z/S/V） | `credit_code` 字符集非法 | 核对代码（常见为小写自动转大写后仍含 I/O 等）后重试 |
| 统一社会信用代码校验位不正确 | `credit_code` 前 17 位与校验位不匹配 | 核对代码是否抄录错误后重试 |
| 线边库存天数必须为非负整数 | `line_stock_days` 非数字或为负 | 改为 0 或非负整数后重试 |
| 调拨提前期必须为非负整数 | `transfer_lead_days` 非数字或为负 | 改为非负整数或留空后重试 |
| 客户记录不存在 | `get`/`update` 目标 `customer_no` 不存在 | 先 `list` 核对编码，或先 `create` 该客户 |
| 导入数据必须为列表 | `import_batch` 入参不是 list | 确保传入 `list[dict]` 格式的 rows |

> `import_batch` 逐行校验，失败行**不抛异常**，而是写入返回值的 `errors` 数组（字段级 `message` 与上表同文案，另有「行数据格式非法」表示某行不是 dict）。合法行正常入库 / 更新，请依据 `errors` 逐条反馈并修正后重导。
