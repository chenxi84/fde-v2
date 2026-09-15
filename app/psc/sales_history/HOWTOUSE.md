# sales_history 使用要点

**管什么**：历史台账——物料 × 客户 × 月度的**已发生**干净需求，以及按期间升序的历史序列。回答「过去卖了多少」用它。

## 标准工作流（按此顺序）

1. `sync_external_history` — **常规数据入口**：从外部历史台账接口整体拉取并落库（URL 与鉴权在 `/integration` 配置）
2. `import_batch` — 只有拿到一份台账明细要补录时才用，`rows` 批量 upsert，返回 `{total, success, fail, errors}`
3. `list` — 按 `material_no` / `customer_no` / `period` 精确筛选分页
4. `history_sequence` — 只要数量序列时用它（传单物料或断点链的 `material_nos` + `customer_no`）
5. `history_series` — 需要「**哪一期**多少量」时用它，返回 `[{period, qty}]`
6. `purchasing_customers` — 取某物料的历史采购客户集
7. `main_customer` — 取某物料的**主要客户**（历史出货量最大者；无历史返回 None）。库存策略批量算水位时靠它拿客户缓冲参数

## 前置条件与禁忌

- **本应用没有 create 服务**。数据是 ERP 同步进来的，不存在「手工新建一条历史」这回事；要补数只能 `import_batch` / `sync_external_history`。
- **单条回写类服务不在你的工具表里**：`upsert`（ERP 同步逐条回写）、`attach_forecast`（`sales_forecast` 推送 N+1 预测）、`sync_forecast`（`attainment` 批量回填）都不给你调，写入走上面两个批量入口。
- `period` 必须 `YYYY-MM`，`qty` 不能为负。**无 delete / update 服务**，重导或覆盖即可。
- 同批次里主键重复的行按顺序处理，**后行覆盖前行**；导入后记得看 `fail` / `errors`，别只看 `total`。
- 各消费端（销售预测基线、库存策略、策略拟合回测）都以「台账为空 → 空序列」兜底，查不到不报错、也不代表该物料没需求。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/sales_history", doc="README")` 读完整操作指南再处置。
