# outbound_plan 使用要点

**管什么**：对客户的出库计划——手工登记客户/物料/数量/计划出库日期，以及延期、到期关闭、删除。回答「有哪些出库计划」或要新增/改一条，用它。

## 标准工作流（按此顺序）

1. `create` — 登记一笔计划（`customer_no`、`material_no`、`qty`、`out_date`，可带 `actual_out_no`）
2. `update` — 实际出库后回填 `actual_out_no`；**延期也用它**改 `out_date`
3. `list` / `get` — 按物料 / 客户 / 状态查询（读取时自动结算到期关闭）
4. `close_expired` — 需要显式批量关闭时用（幂等，返回 `{closed: N}`）

## 前置条件与禁忌

- **主数据引用铁律**：`customer_no` 必须存在于 `md_customer`、`material_no` 必须存在于 `md_material`，创建/编辑时后端校验，凭空写会被拒。
- **到期关闭是惰性的**：`out_date` 早于今日的计划在下一次 `list` / `get` 读取时置 `已关闭`，没有常驻定时器。所以别为「帮用户关闭到期计划」专门跑一轮——正常读一次就已经结算了；`close_expired` 只是显式触发同一逻辑。
- **已关闭计划仍可 `update` 延期**：把 `out_date` 改到今日及以后，状态自动恢复 `待出库` 并重新进入库存推移表的预计出库量。这是让一条到期计划继续执行的**唯一**路径。
- **只有 `待出库` 可 `delete`**。已关闭的记录是历史留痕，后端拦截删除；用户说要删一条已关闭计划时，先解释并改走延期。
- `qty` 必须 > 0；`out_date` 用 `YYYY-MM-DD`（兼容 `YYYYMMDD` 输入，自动规范化）。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/outbound_plan", doc="README")` 读完整操作指南再处置。
