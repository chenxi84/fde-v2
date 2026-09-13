# inventory_projection 使用要点

**管什么**：库存推移表——逐日推演未来 3 个月（90 自然日）的库存水位，带缺货/击穿最低/击穿安全/超储预警，并联动生成补库单。

## 标准工作流（按此顺序）

1. `refresh_batch` — **整批刷新**推移表；缺省 = 当天 + `md_material` 全部「正常」物料，可用 `biz_date` / `material_nos` 收窄。**刷新成功后逐物料联动预警扫描，击穿水位会自动创建需求池补库单**；返回含 `errors` 与 `replenishments`
2. 从 `errors` 关注失败物料，从 `replenishments` 关注新生成的补库单
3. `scan_alert` — 只在需要单独补扫某物料预警时调
4. 查读数：`list`（按物料 / 日期 / 预警类型筛）→ `get`（某日明细）

## 前置条件与禁忌

- **用 `refresh_batch`，不要用单物料版 `refresh`**——后者是界面逐物料刷新用的，**不在你的工具表里**；逐物料调既慢，又容易只刷一半。
- **依赖须先就绪**：预警扫描依赖 `inventory_strategy.get_water_level` 提供 A/C/B 水位，**无策略记录无法预警**（报「库存策略记录不存在，无法扫描预警」→ 先去算水位）；推演依赖 `master_plan.get_latest` 提供预计入库量。
- **预警判定**：`balance < 0` 缺货；`0 ≤ balance < A` 击穿最低；`A ≤ balance < A+C` 击穿安全；`balance > B` 超储。「呆滞」阈值未定义，当前不产出。
- `list` 默认只显示当日及以后（历史记录隐藏不删除；指定具体历史日期可回看）。
- 重复 `scan_alert` 幂等，但同一物料持续击穿时每次都可能重复触发补库单——**去重策略待业务确认，不要自作主张去重**。
- `material_no` 必须来自 `md_material`。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/inventory_projection", doc="README")` 读完整操作指南再处置。
