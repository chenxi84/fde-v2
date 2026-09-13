# strategy_fitting 使用要点

**管什么**：按物料做滚动回测选最优预测方法与参数（MASE、预测值、预测区间）与库存拟合，以及复核 / 否决 / 回滚。回答「这个料该用哪个模型」「拟合结果如何」用它。

## 标准工作流（按此顺序）

1. `run_batch` — 整批拟合（按 `fit_version` 覆盖全部正常状态物料）；单物料用 `run`。结果**只落表**，`status=待复核`
2. `list(status="待复核")` — 取待复核清单（配 `abnormal_flag` 可只看异常行）
3. `get` — 逐条看完整字段；**不知道版本号时用 `get_latest`**（取该物料最新一版），别硬猜 `fit_version`
4. `approve` — 复核通过（`待复核 → 已生效`，**此时才回填物料主数据**）；否决用 `reject`
5. `rollback` — 对已生效记录回滚，回填同物料上一版已生效参数（无上一版则被拒）

## 前置条件与禁忌

- **拟合不改物料主数据**：`run` / `run_batch` 只落表待复核，只有 `approve` 成功才回填；跑完别指望下游立刻看到新参数。
- **回填用的 `md_material.set_fit_params` 不在你的工具表里**（由 `approve` / `rollback` 内部调用）。改某物料的拟合参数就走「拟合 → 复核 → 生效」这条链，绕过去直接改会让复核失去意义。
- **异常记录必须二次确认**：数据不足（常规方法 < 12 期、间歇方法 < 4 期）或 **MASE ≥ 1** 时 `abnormal_flag=true`，此时 `approve` 不带 `confirm=true` 会被拦。要先向用户说明异常原因，得到确认后再带 `confirm=true` 重发。
- **状态机**：仅 `待复核` 可 `approve` / `reject`；仅 `已生效` 可 `rollback`；`已否决` 是终态。
- **幂等**：同一 `fit_version + material_no` 重复 `run` 会覆盖并把状态重置回 `待复核`（已生效的记录会被打回）。
- `material_no` 取自 `md_material.list`（`run` 会校验存在性），`fit_version` 必须 6 位 `YYYYMM`。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/strategy_fitting", doc="README")` 读完整操作指南再处置。
