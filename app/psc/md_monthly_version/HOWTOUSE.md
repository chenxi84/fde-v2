# md_monthly_version 使用要点

**管什么**：月度版本本身——版本号、锚定期间、锁定状态（草稿/发布/冻结），以及「当前活跃版本是哪个」。

## 标准工作流（按此顺序）

1. `get_active` — 先查当前有无活跃版本（返回 `null` 表示无，不是错误）
2. `list` — 核对拟建版本号是否已被占用
3. `create` — 建版本，传 `version_no`（YYYYMM）、`anchor_period`、`opening_date`（YYYY-MM-DD）；初始必为 `草稿`
4. `publish` — `草稿` → `发布（锁定）`，锁定后下游即可引用该版本
5. `freeze` — `发布（锁定）` → `冻结`（归档）
6. `unfreeze` — `冻结` → `草稿`（解冻，前提是无其他活跃版本）
7. `get` — 按版本号看详情；批量筛选用 `list(version_no=…, lock_status=…)`

## 前置条件与禁忌

- **同一时刻只能有一个非冻结版本**：存在 `草稿` 或 `发布（锁定）` 的版本时，`create` 和 `unfreeze` 都会被拒（报「已存在活跃版本」）。要开新版，必须先把当前活跃版本 `publish`（若是草稿）再 `freeze` 推到冻结。
- **状态机单向、禁跳级**：`publish` 仅对 `草稿` 有效，`freeze` 仅对 `发布（锁定）` 有效，`unfreeze` 仅对 `冻结` 有效。**没有删除服务**，冻结就是归档终态。
- **动版本前先 `get` 看状态**：`demand.publish` / `demand.calc_net` 会联动调用本应用的 `publish` / `freeze`——跑需求链时版本可能已被别人锁过，别凭记忆猜状态。
- `version_no` 必须 6 位 `YYYYMM`（`202608`）且全局唯一；`opening_date` 必须 `YYYY-MM-DD`；`anchor_period` 只做非空校验。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/md_monthly_version", doc="README")` 读完整操作指南再处置。
