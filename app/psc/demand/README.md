# 毛需求与净需求（demand）

## 一、应用简介

- **聚合根**：毛需求与净需求 `Demand`，标识 `version_no + material_no + rolling_month`（复合主键）。
- **数据存储**：同名库 `demand.db`（平台自动创建），表 `demand` 存每个物料 × 滚动月度（N+1/N+2/N+3）的需求行。
- **核心公式**：
  - `gross_qty = forecast_qty + inventory_qty`（库存策略水位只加期末 N+3，不逐期分摊）。
  - `net_qty = gross_qty + open_order_qty − onhand_qty − in_transit_qty`，各层非负（结果为负时置 0）。
- **状态机**：本应用无独立状态列，随 `md_monthly_version.lock_status` 流转：`草稿 → 发布（锁定）→ 冻结`。
- **跨应用调用**：`sales_forecast`、`inventory_strategy`、`md_part_replace`、`md_breakpoint`、`md_monthly_version`；ERP 执行数据（未发/库存/在途）经 `_load_*` 适配器访问（当前为 stub，返回空）。

## 二、对外服务（工具）

| 工具名 | 参数（类型 / 必填 / 默认） | 说明 |
|---|---|---|
| `psc__demand__build_gross` | `version_no: str`（必填，YYYYMM） | 合成毛需求：替换件/断点合并 + 叠加库存策略水位，幂等重算更新 |
| `psc__demand__publish` | `version_no: str`（必填） | 发布冻结毛需求，联动月度版本草稿→发布（锁定） |
| `psc__demand__calc_net` | `version_no: str`（必填） | 运算净需求（叠加未发、扣库存与在途，各层非负），联动版本发布→冻结 |
| `psc__demand__get` | `version_no: str`、`material_no: str`、`rolling_month: str`（均必填） | 取单行详情（forecast/inventory/gross/open_order/onhand/in_transit/net 分层拆解） |
| `psc__demand__list` | `version_no: str=None`、`material_no: str=None`、`rolling_month: str=None`、`page: int=None`、`size: int=None`（均选填） | 按版本/物料/滚动月度筛选分页列表，返回 `{"items": [...], "total": N}` |
| `psc__demand__export_net` | `version_no: str`（必填） | 导出某版本净需求清单（version_no/material_no/rolling_month/net_qty） |

> `rolling_month` 取值仅限 `N+1` / `N+2` / `N+3`。

## 三、标准工作流

Agent 应按以下顺序调用（一步不成，后续不推进）：

1. **`psc__demand__build_gross`**：合成毛需求（前置：月度版本已建且为草稿、销售预测已汇总、库存策略已计算）。
2. **`psc__demand__publish`**：核对无误后发布冻结毛需求（前置：已 build_gross）。
3. **`psc__demand__calc_net`**：对已发布版本运算净需求（前置：已 publish，ERP 执行数据可取到）。
4. **`psc__demand__export_net`**：导出净需求清单，交线下产能平衡（前置：已 calc_net）。

辅助流程：

- 核对需求结果：`psc__demand__list`（按版本/物料筛选）→ `psc__demand__get`（看单行分层拆解）。

## 四、前置条件与注意事项

- **版本状态**：build_gross 仅草稿版本可执行；publish 要求已合成；calc_net 仅发布（锁定）版本可执行；export_net 仅冻结版本可导出。
- **合成口径**：
  - 通用件合并：`sales_forecast.get_summary` 返回物料级合计，即已完成通用件合并，本应用无需额外处理。
  - 替换件合并：`md_part_replace.list(status=生效)` 有 `old_material_no → new_material_no` 关系时，把 old 的预测全额加到 new。
  - 断点处理：`md_breakpoint.list` 有切换关系时按 `switch_time` 归属——切换后需求归新件、切换前保留旧件（物料级口径；精确转移口径与客户维度待业务确认）。
  - 库存策略水位只加期末 N+3（总量口径），不逐期分摊。
- **幂等**：重复 build_gross 只更新已有行（按复合主键 upsert），不重复插入。
- **不可改**：publish 后毛需求行禁止修改（状态随 md_monthly_version 锁定）。
- **ERP 适配器**：`_load_open_order / _load_inventory / _load_in_transit` 当前返回空（净需求按 0 处理），真实接入时只换适配器实现、不改公共方法。
- **弱引用**：material_no 引用 `md_material`，version_no 引用 `md_monthly_version`，不跨库强约束，不级联删除。

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 下一步该怎么做 |
|---|---|---|
| 月度版本号不能为空 | 未传 version_no | 向用户索要月度版本号（YYYYMM） |
| 版本不存在 | version_no 未在 md_monthly_version 中登记 | 先调用 `md_monthly_version` 相关工具创建/核对版本号 |
| 版本已发布，不可合成 | 版本非草稿（已发布/已冻结） | 换草稿版本重试，或告知用户该版本毛需求已定型 |
| 销售预测汇总取数失败 | sales_forecast 未汇总或汇总不可用 | 先完成 `sales_forecast` 的决策与汇总（summarize），再回来合成 |
| 毛需求未合成，请先执行合成 | publish 前未 build_gross | 先调 `psc__demand__build_gross` |
| 版本已发布，不可重复发布 | 版本已处于发布/冻结态 | 停止重复发布；如需重做请换新版本 |
| 毛需求未发布冻结，不可运算净需求 | calc_net 前版本仍为草稿 | 先依次 `build_gross` → `publish`，再运算净需求 |
| 版本已冻结，不可重复运算净需求 | 版本已冻结（终态） | 净需求已定型，无需重复运算；如需调整换新版本 |
| 记录不存在 | get 的目标行不存在 | 先 `psc__demand__list` 核对 version_no/material_no/rolling_month |
| 滚动月度只能为 N+1/N+2/N+3 | rolling_month 取值非法 | 改用 N+1 / N+2 / N+3 之一 |
| 分页参数不合法 | page/size 非正整数 | 传正整数（page≥1、size≥1）或省略 |
| 净需求未运算 | export_net 前版本未冻结（未 calc_net） | 先调 `psc__demand__calc_net` 完成净需求运算 |
