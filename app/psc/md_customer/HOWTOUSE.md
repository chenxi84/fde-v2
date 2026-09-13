# md_customer 使用要点

**管什么**：客户档案主数据——客户编码/名称、结算模式、线边库存天数、调拨提前期、统一社会信用代码。

## 标准工作流（按此顺序）

1. `list` — 按 `customer_no` / `customer_name` / `credit_code` 模糊查重，拿 `items` 与 `total`
2. `create` — 单条建档（`customer_no` + `customer_name` 必填）
3. `get` — 用返回的 `customer_no` 回读确认
4. `update` — 维护参数时先 `get` 回填，只传要改的字段，改完再 `get` 确认
5. `import_batch` — 批量同步：整理 `rows`（每行一个 dict）→ 调用 → 读 `success` / `fail` / `errors`

## 前置条件与禁忌

- **`customer_no` 全局唯一、不可修改**。`create` 撞主键报「该客户编码已存在」——先 `list`/`get` 核对；确为同一客户就改用 `update`，或整批走 `import_batch`（批量是 upsert，同主键更新而非拒绝）。
- **没有删除服务**。下游（销售预测 / 库存策略 / 达成率）按号弱引用，别尝试删除客户记录。
- **`import_batch` 逐行校验、不抛异常**：失败行落进返回值的 `errors`，合法行照常入库。别只看 `fail` 计数，必须读 `errors` 逐条反馈、修正后重导。
- 字典与格式：`settle_mode` 非空时必须是 **现售 / 寄售**；`credit_code` 非空时必须是 18 位合法统一社会信用代码；`line_stock_days` / `transfer_lead_days` 非负整数。
- **分页参数名是 `size`，不是 `page_size`**；`page` / `size` 都省略时返回全量。
- 这个应用只回答「客户是谁、参数是多少」。问「某客户报得准不准」属达成率与置信度，不要在这里答。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/md_customer", doc="README")` 读完整操作指南再处置。
