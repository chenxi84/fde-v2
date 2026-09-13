# attainment 使用要点

**管什么**：客户 × 物料的预测达成率与偏差——MAPE（报得多不准）与 bias（习惯性报高还是报低）。回答「这个客户报的预测准不准」用它，不要去翻客户主数据或销售预测。

## 标准工作流（按此顺序）

1. `compute` — **你唯一能写数据的入口**。按口径 A 滚动重算 MAPE/bias 并回写，默认 `months=6`；窗口内有效样本 < 3 或 Σ实际 = 0 的行跳过
2. `list` — 按 `customer_no` / `material_no` 筛选查看（AND 关系，都不传返回全部）
3. `get` — 已知客户 + 物料时取单条，未命中返回 `None`（不是错误）

## 前置条件与禁忌

- **`upsert` 不在你的工具表里**。它是 ERP 达成率统计同步任务的回写入口（幂等覆盖），由系统驱动、不由你发起；要刷新达成率就用 `compute`。
- **没有 create / update / delete**，本应用是「自动参考创建」，写入只经 `compute` 或 ERP 同步。不要试图调用不存在的写工具。
- `customer_no` / `material_no` 是联合主键，必填；`mape` 非负、`bias` 可正可负（多报为正、少报为负）。
- 本应用**不校验**客户/物料在 `md_customer` / `md_material` 是否存在，别再拿主数据缺失去解释这里的空结果。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/attainment", doc="README")` 读完整操作指南再处置。
