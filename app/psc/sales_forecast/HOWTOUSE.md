# sales_forecast 使用要点

**管什么**：月度版本内的销售预测清单——客户填报 → 调整 → 基线 → 决策 → 汇总，以及客户原始预测导入。

## 标准工作流（按此顺序）

1. `open_version` — 开版，按「正常物料 × 历史采购客户」生成 N+1/N+2/N+3 处理行
2. `import_orig_qty` — **整批**导入客户原始预测；系统按 bias 自动算 `adj_qty = orig_qty × (1 − bias)`
3. `calc_baseline_batch` — 批量算基线（先断点追溯，再套物料 `base_method`）
4. `adjust_event` — 只有需要事件调整的行才调（**无批量版**，逐行）
5. `decide_batch` — 批量决策，标记异常并给建议值；**已人工定稿的行会被跳过**，返回里的 `settled_skipped`/`settled_rows` 报出跳了哪几行
6. `set_final` — 对 `abnormal_flag=1` 的行人工定稿（**逐行**，这是人工动作）
7. `summarize` — 按物料 × 滚动月度刷新汇总表
8. `get_summary` — 交付给下游（毛需求合成）

## 前置条件与禁忌

- **版本必须是草稿态**。发布/冻结后所有写操作被拒。做不了时先确认是否该开新版本。
- **处理行必须先开版**：`import_orig_qty` / `calc_baseline_batch` 等都以 `version_no + material_no + customer_no + rolling_month` 定位，行不存在直接报错。
- **用批量接口，不要逐行调**。单行版 `fill_customer` / `calc_baseline` / `decide` 只给界面用，**不在你的工具表里**；要填就整批导，要算就整批算。
- **异常行的 `final_qty` 不自动填**：`decide_batch` 只标记 `abnormal_flag=1`，须 `set_final` 定稿；非异常行调 `set_final` 会被拒。
- **人工定稿不会被覆盖**：`set_final` 定过的行会在定稿台账留痕，之后 `decide`/`decide_batch` **跳过**它（见 BR-27）——所以界面上点「批量决策」不会清掉你刚定的稿。想改就再 `set_final` 一次。
- `material_no` / `customer_no` 必须来自 `md_material` / `md_customer`，不要凭空写。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/sales_forecast", doc="README")` 读完整操作指南再处置。
