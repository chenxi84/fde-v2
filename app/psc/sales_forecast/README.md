# sales_forecast 应用 README（Agent 操作指南）

## 一、应用简介

- **应用组**：`psc`（产销协同）
- **应用名**：`sales_forecast`
- **聚合根**：`SalesForecast`（销售预测）
- **主表**：`sales_forecast_line`（处理表），主键为复合键 `version_no + material_no + customer_no + rolling_month`
- **汇总表**：`sales_forecast_summary`（处理表派生合计，禁止独立编辑），主键 `version_no + material_no + rolling_month`
- **同名库**：`sales_forecast.db`
- **是否跨应用**：是。写操作与决策会跨应用调用 `md_monthly_version`、`md_material`、`md_customer`、`md_breakpoint`、`attainment`，并通过 `_load_sales_history` 适配器直连 ERP（stub 空列表，真实接入换实现）。
- **状态机**：本应用无独立状态列，随 `md_monthly_version.lock_status` 流转——**草稿**可执行全部写操作；发布（锁定）/冻结后只读，任何写操作被拒绝。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `psc__sales_forecast__open_version` | `version_no`：str，必填 | 开启月度版本：按「正常状态物料 × 该物料的历史采购客户」生成清单并拆 N+1/N+2/N+3 进处理表；某物料无历史采购记录时客户字段为空、仅初始化一行。返回 `{version_no, list_rows, line_rows}`。 |
| `psc__sales_forecast__create` | `version_no`：str，必填<br>`material_no`：str，必填<br>`customer_no`：str，可选（留空 = 空客户组合） | 手工新建物料×客户组合，覆盖 `open_version` 未生成的组合；拆 N+1/N+2/N+3 三行进处理表。组合已存在 / 物料或客户不存在 / 版本非草稿均拒绝。返回 `{version_no, material_no, customer_no, line_rows}`。 |
| `psc__sales_forecast__fill_customer` | `version_no`：str，必填<br>`material_no`：str，必填<br>`customer_no`：str，必填<br>`rolling_month`：str，必填（N+1/N+2/N+3）<br>`orig_qty`：float，可选<br>`adj_qty`：float，可选 | 填写客户原始预测数量。系统按 `bias` 自动算 `adj_qty = orig_qty × (1 − bias)`（人工可调）；`orig_qty` 可留空。返回该行全字段。 |
| `psc__sales_forecast__calc_baseline` | `version_no`：str，必填<br>`material_no`：str，必填<br>`customer_no`：str，必填<br>`rolling_month`：str，必填 | 断点追溯前置 + 按物料 `base_method`/`base_params` 作用于历史干净需求算 `base_qty`，并算 `base_event_qty = base_qty + event_adj`。返回该行全字段。 |
| `psc__sales_forecast__adjust_event` | `version_no`：str，必填<br>`material_no`：str，必填<br>`customer_no`：str，必填<br>`rolling_month`：str，必填<br>`event_analysis`：str，可选<br>`event_adj`：float，可选，默认 0 | 填写事件分析/调整量，重算 `base_event_qty`。事件调整只作用归属期、不外推。返回该行全字段。 |
| `psc__sales_forecast__decide` | `version_no`：str，必填<br>`material_no`：str，必填<br>`customer_no`：str，必填<br>`rolling_month`：str，必填 | 按 MAPE 与偏离率自动标记异常并给出最终预测建议（异常行不自动填 `final_qty`）。返回该行全字段。 |
| `psc__sales_forecast__set_final` | `version_no`：str，必填<br>`material_no`：str，必填<br>`customer_no`：str，必填<br>`rolling_month`：str，必填<br>`final_qty`：float，必填 | 异常行人工填写最终预测量（仅 `abnormal_flag=1` 的行可填）。返回该行全字段。 |
| `psc__sales_forecast__summarize` | `version_no`：str，必填 | 按物料 × 滚动月度合计所有客户 `final_qty`，刷新汇总表。返回 `{version_no, summary_rows}`。 |
| `psc__sales_forecast__get` | `version_no`：str，必填<br>`material_no`：str，必填<br>`customer_no`：str，必填<br>`rolling_month`：str，必填 | 按主键取处理表单行全部字段。 |
| `psc__sales_forecast__list` | `version_no`：str，可选<br>`material_no`：str，可选<br>`customer_no`：str，可选<br>`rolling_month`：str，可选<br>`abnormal_flag`：bool，可选<br>`page`：int，可选<br>`size`：int，可选 | 按条件筛选分页查询处理表。返回 `{"items": [...], "total": N}`。 |
| `psc__sales_forecast__get_summary` | `version_no`：str，必填<br>`material_no`：str，可选 | 取指定版本（可指定物料）的汇总行，供毛需求合成。返回汇总行列表。 |

---

## 三、标准工作流

### 1. 完整预测闭环（标准顺序，务必按此推进）

1. **开启版本**：调用 `psc__sales_forecast__open_version`，传入草稿版本号 `version_no`，生成清单与处理表行（每组合拆 N+1/N+2/N+3）。
2. **填客户预测**：对每个「物料 × 客户 × 滚动月度」行调用 `psc__sales_forecast__fill_customer`，传入 `orig_qty`（可留空），系统自动算 `adj_qty`。
3. **基线计算**：对每行调用 `psc__sales_forecast__calc_baseline`（先断点追溯，再按物料方法/参数算 `base_qty`）。
4. **事件调整**：对需要调整的行调用 `psc__sales_forecast__adjust_event`，传入 `event_analysis`/`event_adj`。
5. **决策**：对每行调用 `psc__sales_forecast__decide`，系统自动标记异常并给出 `final_qty`。
6. **异常收口**：对 `abnormal_flag=1` 的行调用 `psc__sales_forecast__set_final` 人工填 `final_qty`。
7. **汇总**：调用 `psc__sales_forecast__summarize` 生成/刷新汇总表。
8. **交付**：下游经 `psc__sales_forecast__get_summary(version_no, material_no=None)` 取汇总结果。

### 2. 双源分歧人工介入

1. `psc__sales_forecast__decide` 发现偏离率 > 5% → `abnormal_flag=1`，`final_qty` 不自动填。
2. 线下与销售核对原因后，调用 `psc__sales_forecast__set_final` 人工填写 `final_qty`。
3. 再次调用 `psc__sales_forecast__summarize`，人工值计入 `final_qty_sum`。

### 3. 查询核对

1. 用 `psc__sales_forecast__list` 按版本/物料/客户/滚动月度/异常标记筛选浏览。
2. 用 `psc__sales_forecast__get` 按主键取单行全字段核对。

---

## 四、前置条件与注意事项

1. **版本必须草稿**
   - 所有写操作（`open_version`/`fill_customer`/`calc_baseline`/`adjust_event`/`decide`/`set_final`/`summarize`）前都会校验 `md_monthly_version.lock_status` 为「草稿」。
   - 版本发布（锁定）或冻结后，任何写操作都会被拒绝。

2. **开版顺序与唯一性**
   - `open_version` 依赖 `md_material` 中存在「正常」状态物料，以及 `sales_history.purchasing_customers(material_no)` 按物料返回的历史采购客户集；某物料无历史时客户为空、仅一行。
   - 同一版本只能开启一次，重复开启被拒绝。

3. **处理表行必须先开版**
   - `fill_customer`/`calc_baseline`/`adjust_event`/`decide`/`set_final`/`get` 都以 `version_no + material_no + customer_no + rolling_month` 定位，行不存在时报「处理表行不存在」。
   - 主键字段 `material_no`/`customer_no` 分别标注来源 `md_material`/`md_customer`，非手工录入。

4. **客户预测调整口径（BR-11）**
   - `adj_qty = orig_qty × (1 − bias)`，其中 `bias` 来自 `attainment.get`（多报为正、少报为负）。
   - `orig_qty` 可留空（客户不填报）；留空时 `adj_qty` 为空，后续决策走「默认信基线」路径。

5. **基线计算前提（BR-17）**
   - `calc_baseline` 要求物料已配置 `base_method`（移动平均/指数平滑/阶跃检测/借用参考）与 `base_params`；未配置报「物料未配置基线方法」。
   - 断点追溯（`md_breakpoint.trace`）只拼接「原件历史 + 新件历史」（量比固定 1.0），与「借用参考」不同。

6. **决策阈值可配置（BR-16）**
   - MAPE 阈值 `0.20`、偏离率阈值 `0.05` 为类常量（`MAPE_THRESHOLD`/`DEVIATION_THRESHOLD`），调优改常量不改业务逻辑。

7. **汇总表派生、禁止独立编辑（BR-03）**
   - `sales_forecast_summary.final_qty_sum` 只能由 `summarize` 重算，每次覆盖旧值；无独立的汇总表写服务。

8. **异常行最终预测不自动填（BR-26）**
   - `decide` 对偏离率 > 5% 的行置 `abnormal_flag=1` 且 `final_qty` 留空，必须经 `set_final` 人工填写；非异常行调 `set_final` 会被拒绝。

9. **`abnormal_flag` 存储为 0/1**
   - 返回结果中 `abnormal_flag` 为 `0`（非异常）或 `1`（异常）；`list` 的 `abnormal_flag` 筛选参数接受 `true/false`、`1/0`、`是/否` 等。

10. **权限由平台控制**
    - 本应用不做鉴权，仅读 `self.ctx`；能否调用由平台授权决定。

---

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `版本号不能为空` | `version_no` 为空或全空白。 | 向用户索要有效版本号（YYYYMM），重新调用。 |
| `物料号不能为空` | `material_no` 为空或全空白。 | 向用户索要有效物料号，或先查 `md_material` 列表核对。 |
| `客户编号不能为空` | `customer_no` 为空或全空白。 | 向用户索要有效客户编号，或先查 `md_customer` 列表核对。 |
| `滚动月度不能为空` | `rolling_month` 为空。 | 传入 `N+1`、`N+2` 或 `N+3`。 |
| `滚动月度只能为 N+1 / N+2 / N+3` | `rolling_month` 不在枚举内。 | 改为 `N+1`、`N+2`、`N+3` 之一后重试。 |
| `月度版本不存在` | 目标 `version_no` 在 `md_monthly_version` 中不存在。 | 先核对版本号；必要时先在 `md_monthly_version` 创建该版本。 |
| `版本已锁定，不可开启预测` | 对已发布（锁定）/冻结的版本执行 `open_version`。 | 确认版本状态；若已锁定则不可再开版，改用只读查询。 |
| `版本已锁定，预测不可修改` | 对已发布（锁定）/冻结的版本执行写操作。 | 确认版本状态为「草稿」后再操作；已锁定版本只能读。 |
| `该版本已开启预测，不可重复开启` | 对该版本重复执行 `open_version`。 | 用 `list`/`get` 核对已生成的行，无需重复开版。 |
| `获取物料主数据失败，请稍后重试` | `open_version` 调用 `md_material.list` 失败。 | 检查 `md_material` 应用是否可用，稍后重试。 |
| `处理表行不存在` | 定位键对应的处理表行不存在。 | 先 `open_version` 生成行，或用 `list` 核对定位键。 |
| `物料不存在` | `fill_customer`/`calc_baseline` 的 `material_no` 在 `md_material` 中不存在。 | 先查 `md_material` 核对物料号；必要时先建物料。 |
| `客户不存在` | `fill_customer` 的 `customer_no` 在 `md_customer` 中不存在。 | 先查 `md_customer` 核对客户编号；必要时先建客户。 |
| `原始需求数量不合法` | `orig_qty` 非数字。 | 传入合法数字或省略（留空）后重试。 |
| `调整后需求不合法` | `adj_qty` 非数字。 | 传入合法数字或省略（让系统按 bias 自动算）后重试。 |
| `物料未配置基线方法` | `calc_baseline` 时物料无 `base_method`。 | 先在 `md_material` 配置该物料的 `base_method`/`base_params`。 |
| `借用参考缺少参考物料号` | `base_method=借用参考` 但 `base_params.ref_material` 缺失。 | 在 `md_material.base_params` 中补 `ref_material` 后重试。 |
| `未知基线方法` | `base_method` 不在「移动平均/指数平滑/阶跃检测/借用参考」内。 | 修正 `md_material.base_method` 后重试。 |
| `事件调整量不合法` | `event_adj` 非数字。 | 传入合法数字（默认 0）后重试。 |
| `该行非异常行，无需人工填写` | 对 `abnormal_flag=0` 的行执行 `set_final`。 | 该行已自动填 `final_qty`，无需人工覆盖。 |
| `最终预测量不合法` | `set_final` 的 `final_qty` 非数字。 | 传入合法数字后重试。 |
| `最终预测量不能为空` | `set_final` 的 `final_qty` 为空。 | 提供非空数值后重试。 |
| `异常标记筛选不合法` | `list` 的 `abnormal_flag` 无法解析为布尔。 | 用 `true`/`false` 或 `1`/`0` 后重试。 |
| `分页参数不合法` | `list` 的 `page`/`size` 非正整数。 | 传入 ≥1 的整数 `page`/`size` 或省略后重试。 |
