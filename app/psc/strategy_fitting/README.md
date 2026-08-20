# strategy_fitting 应用 README（Agent 操作指南）

## 一、应用简介

- **应用组**：`psc`
- **应用名**：`strategy_fitting`
- **聚合根**：`StrategyFitting`（策略拟合）
- **主键**：`fit_version + material_no`（复合主键，同一物料同一拟合版本下仅一条记录）
- **同名库**：`strategy_fitting.db`
- **是否跨应用**：是。
  - `run` 跨应用调用 `md_material.get`（校验物料存在）。
  - `run_batch` 跨应用调用 `md_material.list`（取正常状态物料）。
  - `approve` / `rollback` 跨应用调用 `md_material.set_fit_params`（回填参数，带版本）。
  - `_load_sales_history` 为 ERP 外部适配器（当前 stub 返回空列表）。
- **引用关系**：`strategy_fitting.material_no` 是对 `md_material.material_no` 的**弱引用**，不建物理外键；拟合结果与回填分离，先落表、人工复核通过（已生效）才回填物料主数据。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `psc__strategy_fitting__run` | `material_no`：str，必填<br>`fit_version`：str，必填（YYYYMM） | 对指定物料发起一次策略拟合（预测拟合 + 库存拟合），结果落表 `status=待复核`，返回拟合结果记录。 |
| `psc__strategy_fitting__run_batch` | `fit_version`：str，必填（YYYYMM） | 按拟合版本对全部正常状态物料逐物料拟合，返回受理汇总（total/success/failed/errors）。 |
| `psc__strategy_fitting__get` | `fit_version`：str，必填<br>`material_no`：str，必填 | 查看单条拟合结果完整字段，返回拟合结果记录。 |
| `psc__strategy_fitting__list` | `material_no`：str \| None，选填（模糊匹配）<br>`fit_version`：str \| None，选填（精确）<br>`status`：str \| None，选填（待复核/已生效/已否决）<br>`abnormal_flag`：bool \| None，选填<br>`page`：int \| None，选填<br>`size`：int \| None，选填 | 分页列表，返回 `{"items": [...], "total": N}`。 |
| `psc__strategy_fitting__approve` | `fit_version`：str，必填<br>`material_no`：str，必填<br>`confirm`：bool \| None，选填，默认 false（异常记录二次确认标记） | 复核通过：`待复核 → 已生效`，回填物料主数据（带版本）。 |
| `psc__strategy_fitting__reject` | `fit_version`：str，必填<br>`material_no`：str，必填 | 否决：`待复核 → 已否决`，不回填物料主数据。 |
| `psc__strategy_fitting__rollback` | `fit_version`：str，必填<br>`material_no`：str，必填 | 回滚：`已生效 → 已否决`（本版作废），回填上一版参数。 |

---

## 三、标准工作流

### 1. 单物料拟合（run → approve / reject）

1. 先调用 `psc__strategy_fitting__run`，传入 `material_no`（来自 `md_material.list` 下拉，禁止手工编造）与 `fit_version`（YYYYMM）。
2. 从返回结果确认 `status=待复核`、`abnormal_flag=false`。
3. 复核决策：
   - 通过 → 调用 `psc__strategy_fitting__approve`，若 `abnormal_flag=true` 须传 `confirm=true` 二次确认；通过后 `status=已生效` 且物料主数据已回填。
   - 否决 → 调用 `psc__strategy_fitting__reject`，`status=已否决`，不回填。

### 2. 整批拟合（run_batch → list → approve / reject）

1. 调用 `psc__strategy_fitting__run_batch`，传入 `fit_version`，返回汇总回执。
2. 调用 `psc__strategy_fitting__list`，`status="待复核"` 筛选待复核记录。
3. 对每条记录调用 `psc__strategy_fitting__get` 查看详情，逐条 `approve` 或 `reject`。

### 3. 参数回滚（rollback）

1. 调用 `psc__strategy_fitting__get` 确认目标记录 `status=已生效`。
2. 调用 `psc__strategy_fitting__rollback`，物料主数据回填上一版参数，本记录 `status=已否决`。

### 4. 状态机

```
待复核 --approve--> 已生效
待复核 --reject --> 已否决
已生效 --rollback--> 已否决（回填上一版参数）
```

---

## 四、前置条件与注意事项

1. **物料必须先在 md_material 存在**
   - `run` 会调用 `md_material.get` 校验物料存在，`material_no` 不存在则拒绝。
   - `material_no` 来源 `md_material.list`，禁止手工编造。

2. **fit_version 格式**：必须为 6 位 YYYYMM（如 `202608`），月份 01~12。

3. **拟合结果先落表、复核通过才回填**
   - `run` / `run_batch` 完成后物料主数据**未被改动**，仅落表 `status=待复核`。
   - 只有 `approve` 成功才调用 `md_material.set_fit_params` 回填参数。

4. **同一 fit_version + material_no 唯一（幂等）**
   - 重复调用 `run` 会覆盖该记录并重置为 `待复核`，不产生重复行。

5. **状态机约束**
   - 仅 `待复核` 可 `approve` / `reject`。
   - 仅 `已生效` 可 `rollback`。
   - `已否决` 为终态，不可再流转。

6. **异常记录须二次确认**
   - `abnormal_flag=true` 时，`approve` 必须传 `confirm=true`，否则被拦截。

7. **回滚依赖上一版已生效记录**
   - `rollback` 回填同物料更早 `fit_version` 且 `status=已生效` 的参数；无上一版则拒绝。

8. **简化实现说明**
   - 预测拟合取默认方法「指数平滑」+ 默认参数，sMAPE 用历史均值差近似；库存拟合取默认组合（服务系数 1.65、组批窗口 28 天）。真实网格回测/约束优化待接入后替换 `_predict_fit` / `_inventory_fit`。
   - `_load_sales_history` 为 stub 返回空列表，真实 ERP 接入时只替换该适配器实现。

9. **权限由平台控制**：应用不做鉴权；approve/reject/rollback 仅拟合复核人可调用。

---

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `物料号不能为空` | 传入的 `material_no` 为空或全空白。 | 向用户索要物料号，或先调用 `md_material.list` 取得有效物料号。 |
| `拟合版本不能为空` | 传入的 `fit_version` 为空或全空白。 | 向用户索要拟合版本（YYYYMM）。 |
| `拟合版本格式必须为 YYYYMM` | `fit_version` 非 6 位数字或月份非法。 | 改为合法 YYYYMM（如 `202608`）后重试。 |
| `物料不存在` | `run` 时 `md_material.get` 未找到该物料。 | 先核对 `material_no`；必要时先创建物料主数据，确认存在后重新 `run`。 |
| `物料列表获取失败` | `run_batch` 时 `md_material.list` 调用失败。 | 核对 md_material 应用状态，稍后重试 `run_batch`。 |
| `拟合结果不存在` | 传入的 `fit_version + material_no` 查不到拟合结果。 | 先调用 `psc__strategy_fitting__list` 核对编号；确认记录存在后再操作。 |
| `仅待复核状态可生效` | 对非 `待复核` 记录调用了 `approve`。 | 先 `get` 查看当前状态；若已否决则不可生效，若已生效则无需重复通过。 |
| `参数跳变过大，需人工确认` | 记录 `abnormal_flag=true` 且 `approve` 未传 `confirm=true`。 | 向用户说明参数跳变风险，确认后再以 `confirm=true` 重新 `approve`。 |
| `仅待复核状态可否决` | 对非 `待复核` 记录调用了 `reject`。 | 先 `get` 查看当前状态；已否决/已生效均不可再否决。 |
| `仅已生效状态可回滚` | 对非 `已生效` 记录调用了 `rollback`。 | 先 `get` 查看当前状态；仅 `已生效` 可回滚。 |
| `无上一版参数可回滚` | 记录已生效但同物料无更早的已生效拟合记录。 | 无上一版可退回，向用户说明无法回滚。 |
| `状态筛选不合法` | `list` 的 `status` 不是 `待复核/已生效/已否决`。 | 只使用合法状态筛选，或省略 `status` 参数后重试。 |
| `分页参数不合法` | `list` 的 `page`/`size` 非整数。 | 传入合法整数分页参数后重试。 |
| `页码必须大于等于1` | `page < 1`。 | 改为 `page >= 1` 后重试。 |
| `每页条数必须大于等于1` | `size < 1`。 | 改为 `size >= 1` 后重试。 |
