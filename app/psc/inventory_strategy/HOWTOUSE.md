# inventory_strategy 使用要点

**管什么**：每个物料 × 月度版本的三层水位（最低 A / 安全 C / 组批 B）、对冲工具判定与水位带（下限 A+C、上限 A+C+B）。

## 标准工作流（按此顺序）

1. `calc_batch` — 整版本批量算水位，物料范围取 `md_material.list(status="正常")`；**单个物料失败不中断其余**，返回 `{total, success, fail, errors}`
2. 看 `fail` 与 `errors`：对失败物料定位原因（多为主数据参数缺失或历史不足）
3. `calc` — 对失败物料单独重算（`version_no + material_no`，**覆盖更新，不新增行**）

辅助：`list`（按版本 / 物料模糊 / 对冲工具筛）→ `get`（看三层水位、服务系数、设定依据）；下游取数用 `get_water_level`。

## 前置条件与禁忌

- **没有 create 服务**，水位是计算派生值。要新增/修正只能 `calc` / `calc_batch` 重算，不要找「新建水位」的接口。
- **参数一律来自主数据，禁止手工录入**：物料参数来自 `md_material`，客户缓冲参数来自 `md_customer`。参数不对就回主数据改，再重算。
- **历史干净需求经 `md_material.history_chain`（前序链 ∪ 断点链）取链 → `sales_history.history_sequence` 取近 12 期**——**新料自有历史不足靠前序链补足**。报「历史需求数据缺失」时先看 `history_chain` 是否为空：空 = 该料确实无可用历史，非空 = 台账未覆盖近 12 期。
- `service_level` 仅支持 90% / 95% / 98% / 99%；`version_no` 必须 `YYYYMM`。
- `hedge_tool` 仅 `库存`/`速度`；多客户物料缺省按缓冲 0 计算，仅在显式传 `customer_no` 时按该客户扣减。
- 报「库存策略记录不存在」= 该版本还没算过，先 `calc` 再取数。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/inventory_strategy", doc="README")` 读完整操作指南再处置。
