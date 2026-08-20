# sales_history · 历史台账

## 一、应用简介
- **聚合根**：`SalesHistory`（物料销售历史台账），粒度 = 物料 × 客户 × 月度期间。
- **主键**：`(material_no, customer_no, period)`；`period` 形如 `YYYY-MM`；`qty` 为干净需求（≥0）；`forecast_qty` 为对应期间 N+1 原始预测（可空，自动关联）。
- **数据来源类型**：自动参考创建——**无 create 服务**，前端无手工新建入口；数据由 ERP 经 `import_batch`（批量）/ `upsert`（单条）冗余回写。
- **定位**：取代 V1 的 `_load_sales_history` stub，为销售预测/库存策略/策略拟合提供真实历史干净需求。

## 二、对外服务
| 工具名 | 参数 | 说明 |
|---|---|---|
| `psc__sales_history__upsert` | material_no*, customer_no*, period*, qty* | ERP 单条幂等回写（存在覆盖/不存在插入），并自动拉取 N+1 原始预测写 forecast_qty |
| `psc__sales_history__import_batch` | rows* | 批量 upsert，返回 {total,success,fail,errors} |
| `psc__sales_history__attach_forecast` | material_no*, customer_no*, period*, qty 可选 | 预测侧推送 N+1 原始预测到 forecast_qty；实际行不存在则跳过（attached=false） |
| `psc__sales_history__sync_forecast` | — | 批量回填存量行 forecast_qty，返回 {updated} |
| `psc__sales_history__list` | material_no/customer_no/period/page/size 可选 | 精确 AND 筛选分页 {items,total} |
| `psc__sales_history__history_sequence` | material_nos(单物料或断点链)/customer_no/limit | 消费方投影：按 period 升序数量序列（链内多物料按期求和、缺期补 0、limit 取末尾 N 期） |
| `psc__sales_history__purchasing_customers` | material_no 可选 | 历史采购客户集（去重升序） |

## 三、消费端
- `sales_forecast`：`open_version`→purchasing_customers（清单客户维度）；`calc_baseline`/借用参考→history_sequence（基线）。
- `inventory_strategy.calc`→history_sequence（日需求/σ/响应窗口波动）。
- `strategy_fitting.run`→history_sequence（回测）。
- 各消费端保留「台账为空 → []」兜底，行为与 V1 一致。

## 四、注意事项
- period 必须 `YYYY-MM`，否则「期间格式必须为 YYYY-MM」；qty 负值拒绝。
- 同批次重复主键行按顺序 upsert，后行覆盖前行。
- 无 delete/update 服务（重导/upsert 覆盖即可）。
