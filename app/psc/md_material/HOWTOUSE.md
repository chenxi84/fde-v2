# md_material 使用要点

**管什么**：物料主数据与代际谱系——基础参数、预测方法参数、库存策略参数，以及前序料号链与统一历史链。

## 标准工作流（按此顺序）

1. `import_batch` — 建账/同步首选，`rows` 为行对象数组，主键已存在则更新，失败行在 `errors`
2. `create` — 只对确实缺失的单个物料本地补录（`material_no` + `material_name` 必填）
3. `list` — 用 `status=正常` 取预测范围物料，按号或名模糊定位；再 `get` 看完整参数
4. `update` — 只传要改的字段，`material_no` 仅作定位
5. `predecessor_chain` / `history_chain` — 追前序料号 / 取「前序链 ∪ 断点链」的统一物料号链，新料自有历史不足时靠它补
6. `sync_external_material` — 从 ERP/PLM 整体拉取落库（URL 与鉴权在 `/integration` 配置）

## 前置条件与禁忌

- **`set_fit_params` 不在你的工具表里**。它是复核通过后的回填入口，由 `strategy_fitting.approve` 调用；你直接调会绕过「建议→复核→生效」。要定预测方法与参数，走 `strategy_fitting` 回测 + 复核。
- **`status` 只读**：取值限 正常/EOP/停用，但由外部主数据接口维护，`update` 改它会报「状态由外部维护」；唯一例外是 `import_batch`（ERP/PLM 冗余同步，status 随同步走）。
- **`material_no` 全局唯一且不可修改**，无删除服务——它被全链十余个聚合弱引用。
- **`base_params` 必须与 `base_method` 匹配**，否则报「基线参数与基线方法不匹配」：移动平均需 `window`(3~12)、指数平滑需 `alpha`(0~1)、阶跃检测需 `threshold`(0~1)、借用参考需 `ref_material`（须是已存在的物料号）。
- **那 6 个统计模型（AutoTheta / AutoARIMA / AutoETS / SeasonalNaive / CrostonOptimized / TSB）不要手工指定**——它们由策略拟合产出、复核后回填；手工指定只用于批量导入与历史遗留。
- 数值约束：`unit_value` / `change_cost` / `prod_days` / `logistics_days` ≥ 0；`service_level` ∈ [0,1]；`batch_window` > 0。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/md_material", doc="README")` 读完整操作指南再处置。
