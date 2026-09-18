# psc 模块契约速查（自动生成 · 视图生成参照）

> 字段以此文件与 `app/psc/<应用>/<应用>.py` 源码为准；list 示例取自库中现有数据（无数据项以源码为准；造数级样例经平台⑧契约冻结任务生成）。


## attainment

### 服务契约
```
compute(months=6:string)
    — 口径A 单表计算 MAPE/bias 并回写：直接读 sales_history 行内
get(customer_no*, material_no*)
    — 按客户+物料查询该组合的 MAPE/bias；未命中返回 None，不抛异常。
list(customer_no=None:string, material_no=None:string, page=None:integer, size=None:integer)
    — 按客户/物料（AND 关系，可选）筛选达成率列表，分页返回 {items, total}。
upsert(customer_no*, material_no*, mape*, bias*)
    — ERP 统计回写 MAPE/bias：同客户+物料存在则覆盖更新，不存在则插入（幂等）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "customer_no": "AITO",
 "material_no": "M9-BEAM",
 "mape": 0.08,
 "bias": 0.03
}
```


## demand

### 服务契约
```
build_gross(version_no*)
    — 合成毛需求：替换件/断点合并加工 + 叠加库存策略水位（期末 N+3）。幂等重算更新。
calc_net(version_no*)
    — 运算净需求：net = gross + 未发 − 库存 − 在途，各层非负；联动 freeze 冻结版本。
export_net(version_no*)
    — 导出某版本净需求清单（物料号/滚动月度/net_qty），供线下产能平衡。
get(version_no*, material_no*, rolling_month*)
    — 按 version_no + material_no + rolling_month 取单条毛需求/净需求详情（分层拆解）。
list(version_no=None:string, material_no=None:string, rolling_month=None:string, page=None:integer, size=None:integer)
    — 按版本/物料/滚动月度筛选毛需求与净需求分页列表。
publish(version_no*)
    — 发布冻结毛需求：校验已合成，并联动 md_monthly_version.publish 锁定版本。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "version_no": "202610",
 "material_no": "BYD-HAN-BRK",
 "rolling_month": "N+1",
 "forecast_qty": 1629.6,
 "inventory_qty": 0.0,
 "gross_qty": 1629.6,
 "open_order_qty": 0.0,
 "onhand_qty": 0.0,
 "in_transit_qty": 0.0,
 "net_qty": 1629.6
}
```


## demand_pool

### 服务契约
```
cancel(replenish_no*)
    — 需求消失作废：待下达 / 已下达 -> 已取消（终态）。
create(material_no*, replenish_type*, replenish_qty*, required_inbound*, stock_on_hand=None:string, min_level_a=None:string, safety_level_c=None:string, batch_level_b=None:string, capacity_tight=None:string)
    — 库存推移表击穿触发自动生成补库单（数据来源类型：自动参考创建，非手工新建）。
get(replenish_no*)
    — 按补库单号查看单条补库单详情。
list(material_no=None:string, replenish_type=None:string, status=None:string, page=None:integer, size=None:integer)
    — 按物料号 / 补库类型 / 状态（精确）筛选分页列表，默认按要求入库时间升序。
on_inbound(replenish_no*)
    — ERP 回传入库：生产中 -> 已完成（终态）。
on_workorder_started(replenish_no*)
    — ERP 回传工单开工：已下达 -> 生产中。
release(replenish_no*, promised_inbound=None:string)
    — 下达生产：待下达 -> 已下达，经 _dispatch_to_erp 适配器下发生产计划给 ERP。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "replenish_no": "RP202609170002",
 "material_no": "BYD-HAN-FB25",
 "replenish_type": "最低库存补库",
 "replenish_qty": 70.53,
 "required_inbound": "2026-10-01",
 "promised_inbound": null,
 "status": "待下达"
}
```


## inventory_projection

### 服务契约
```
get(material_no*, biz_date*)
    — 按物料号 + 日期查询单日推移明细。
list(material_no=None:string, biz_date=None:string, alert_type=None:string, page=None:integer, size=None:integer)
    — 按物料号 / 日期 / 预警类型筛选推移表列表，支持分页。
refresh(material_no*, biz_date*, opening_stock=None:number)
    — 对单个物料逐日推演未来 3 个月库存水位并落盘（含预警标记）。
refresh_batch(biz_date=None:string, material_nos=None:string)
    — 整批刷新全量物料推移表，并在刷新后联动预警扫描（击穿自动创建需求池补库单）。
scan_alert(material_no*, version_no=None:string)
    — 对照水位线扫描某物料推移表，回填 alert_type，击穿水位触发需求池补库。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "material_no": "BYD-HAN-BRK",
 "biz_date": "2026-10-01",
 "inbound_qty": 0.0,
 "outbound_qty": 0.0,
 "balance": 0.0,
 "alert_type": "无"
}
```


## inventory_strategy

### 服务契约
```
calc(version_no*, material_no*, customer_no=None:string)
    — 计算单物料库存策略（三层水位+对冲工具），同物料同版本重复计算即覆盖更新。
calc_batch(version_no*)
    — 整版本批量计算库存策略，逐物料计算，单个物料失败不中断其余物料。
get(version_no*, material_no*)
    — 查看单物料库存策略详情（含水位带下限/上限派生值）。
get_water_level(version_no*, material_no*)
    — 取三层水位（供下游应用对照水位线），返回 A/C/B 及水位带上下限。
list(version_no=None:string, material_no=None:string, hedge_tool=None:string, page=None:integer, size=None:integer)
    — 按版本/物料/对冲工具筛选查看库存策略列表，支持分页。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "version_no": "202610",
 "material_no": "BYD-HAN-BRK",
 "hedge_tool": "速度",
 "min_level": 0,
 "service_factor": 1.65,
 "resp_volatility": 5.99,
 "safety_level": 0,
 "batch_window": 0,
 "batch_level": 0,
 "basis": "物料BYD-HAN-BRK：生产2天+物流1天，满足率95%，组批窗口0天，近12期月均干净需求1516.42件，对冲工具速度",
 "lower": 0,
 "upper": 0
}
```


## master_plan

### 服务契约
```
get(plan_version*, material_no*, rolling_month*)
    — 按主键（plan_version + material_no + rolling_month）查询单行主计划。
get_latest(version_no*, material_no*)
    — 取某物料在指定月度版本下、每个滚动月度最大 plan_version 的行（供库存推移表取预计入库量）。
import_from_net(version_no*, material_nos=None:string, rolling_month='N+1':string, latest_inbound_date=None:string)
    — 「原样通过」导入：把净需求清单里的指定行原样转成主计划行（FUNC-05）。
import_plan(version_no*, rows*)
    — 导入线下产能平衡结果：逐行校验，合法行落新版本（plan_version +1），返回导入摘要。
list(version_no=None:string, material_no=None:string, page=None:integer, size=None:integer)
    — 分页查询主计划，支持按月度版本、物料号筛选，默认按 plan_version 降序。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "material_no": "BYD-HAN-WIR",
 "version_no": "202610",
 "rolling_month": "N+1",
 "plan_version": 2,
 "plan_qty": 8516.52,
 "latest_inbound_date": "2026-10-31"
}
```


## md_breakpoint

### 服务契约
```
create(customer_no*, old_material_no*, new_material_no*, switch_time*, ecn_no=None:string)
    — 新建断点：校验物料存在、原≠新、切换时间非空、组合唯一后入库。
disable(bp_id*)
    — 停用断点记录（软失效，不参与 trace 追溯与列表默认展示）。
get(bp_id*)
    — 按断点标识查询单条断点记录（含已停用记录）。
get_switch_time(new_material_no*, customer_no=None:string)
    — 取某新物料的断点切换时间（可按客户收窄）；无断点返回 None。
list(customer_no=None:string, old_material_no=None:string, new_material_no=None:string, page=None:integer, size=None:integer)
    — 按客户/原物料号/新物料号（精确）筛选分页列表，默认不含已停用记录，按切换时间降序。
trace(new_material_no*)
    — 沿断点向上追溯原物料号链，返回从最上游原物料号到给定新物料号的序列（无断点返回自身）。
upcoming(days=60:integer)
    — 即将切换的断点关系：switch_time 在 [今天, 今天+days] 且未停用。
update(bp_id*, customer_no=None:string, old_material_no=None:string, new_material_no=None:string, switch_time=None:string, ecn_no=None:string)
    — 更新断点的切换时间/变更单号等字段，重新校验物料引用、原≠新、组合唯一。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "bp_id": 29,
 "customer_no": "BYD",
 "old_material_no": "BYD-HAN-FB25",
 "new_material_no": "BYD-HAN-FB26",
 "switch_time": "2026-07-01",
 "ecn_no": "ECN-2026-0451",
 "disabled": 0
}
```


## md_customer

### 服务契约
```
create(customer_no*, customer_name*, settle_mode=None:string, line_stock_days=None:integer, transfer_lead_days=None:integer, credit_code=None:string)
    — 新建客户主数据，customer_no 全局唯一。
get(customer_no*)
    — 按客户编码查看单条客户主数据详情。
import_batch(rows*)
    — 批量导入/更新（upsert）：已存在 customer_no 更新，不存在则新增。
list(customer_no=None:string, customer_name=None:string, credit_code=None:string, page=None:integer, size=None:integer)
    — 按客户编码/名称/统一社会信用代码模糊筛选的分页列表，按 customer_no 升序。
update(customer_no*, customer_name=None:string, settle_mode=None:string, line_stock_days=None:integer, transfer_lead_days=None:integer, credit_code=None:string)
    — 更新客户主数据（customer_no 主键不可改）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "customer_no": "AITO",
 "customer_name": "赛力斯汽车有限公司",
 "credit_code": "915000007094891941",
 "settle_mode": "寄售",
 "line_stock_days": 3,
 "transfer_lead_days": 2
}
```


## md_material

### 服务契约
```
create(material_no*, material_name*, status='正常':string, unit_value=None:number, value_class=None:string, change_cost=None:number, prod_days=None:number, logistics_days=None:number, change_risk=None:string, service_level=None:number, batch_window=None:number, base_method=None:string, base_params=None:string, predecessor_material_no=None:string)
    — 新建物料主数据记录，material_no 全局唯一。
get(material_no*)
    — 查询单个物料的完整主数据与参数。
history_chain(material_no*)
    — 统一历史链：前序链 ∪ 断点链（md_breakpoint.trace）去重，供 history_sequence 取历史。
import_batch(rows*)
    — 批量导入/更新（upsert）：逐行校验，成功行入库，失败行返回错误明细。
list(material_no=None:string, material_name=None:string, status=None:string, page=None:integer, size=None:integer)
    — 按物料号/名称模糊、状态精确筛选的分页列表。返回全字段，供列表自选显示列。
predecessor_chain(material_no*)
    — 递归追溯前序物料链，返回 [最老前序, …, 直接前序, 本物料]（最老在前）。
set_fit_params(material_no*, base_method*, base_params*, batch_window=None:number, service_level=None:number, fit_version=None:string, model_blob=None:string, sigma_l=None:number)
    — 拟合参数回填（被 strategy_fitting 调用），更新方法/参数并记录版本快照。
sync_external_material()
    — 对外服务：从外部（ERP / PLM）拉取物料主数据并经 import_batch 落库。
update(material_no*, material_name=None:string, status=None:string, unit_value=None:number, value_class=None:string, change_cost=None:number, prod_days=None:number, logistics_days=None:number, change_risk=None:string, service_level=None:number, batch_window=None:number, base_method=None:string, base_params=None:string, predecessor_material_no=None:string)
    — 更新物料名称与各参数；material_no（主键）与 status（只读）不可修改。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "material_no": "BYD-HAN-BRK",
 "material_name": "汉2026款制动踏板总成",
 "predecessor_material_no": null,
 "status": "正常",
 "unit_value": 2600.0,
 "value_class": "高",
 "change_cost": 8000.0,
 "prod_days": 2.0,
 "logistics_days": 1.0,
 "change_risk": "高",
 "service_level": 0.95,
 "batch_window": 28.0,
 "base_method": "AutoTheta",
 "base_params": "{\"season_length\": 12}",
 "fit_version": "202610",
 "fit_effective_at": "2026-09-15 14:50:42",
 "model_blob": null,
 "sigma_l": 5.9852
}
```


## md_monthly_version

### 服务契约
```
create(version_no*, anchor_period*, opening_date*)
freeze(version_no*)
get(version_no*)
get_active()
list(version_no=None:string, lock_status=None:string, page=None:integer, size=None:integer)
publish(version_no*)
unfreeze(version_no*)
    — 冻结版本回退到草稿（解冻）：供计划员修正误冻结的版本后重新编辑。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "version_no": "202610",
 "anchor_period": "2026-10",
 "opening_date": "2026-10-01",
 "lock_status": "冻结"
}
```


## md_part_replace

### 服务契约
```
create(old_material_no*, new_material_no*, ecn_no=None:string)
    — 新建替换关系：校验原/替换物料存在、原≠替换、组合唯一后入库，status 默认「生效」。
disable(rel_no*)
    — 将替换关系设为「失效」（幂等：已失效直接返回）。
get(rel_no*)
    — 查看单条替换关系详情。
list(old_material_no=None:string, new_material_no=None:string, status=None:string, page=None:integer, size=None:integer)
    — 按原物料号/替换物料号（模糊）、状态（精确）筛选分页列表。
update(rel_no*, old_material_no*, new_material_no*, ecn_no=None:string)
    — 更新替换关系的原/替换物料号与 ECN 依据，重新校验物料引用、原≠替换与组合唯一。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）


## md_project

### 服务契约
```
create(project_no*, project_name*, owner*, stage=None:string, sop_date=None:string, eop_date=None:string, veh_model=None:string, share=None:string)
    — 新建项目台账。project_no 全局唯一，stage 默认「进行中」。
get(project_no*)
    — 按项目号查询项目台账详情。
import_batch(rows*)
    — 批量导入/更新项目台账（upsert）。已存在主键行更新，新行新增；逐行校验，失败行记录错误明细。
list(project_no=None:string, project_name=None:string, stage=None:string, page=None:integer, size=None:integer)
    — 按项目号（模糊）、项目名称（模糊）、阶段（精确）筛选项目台账，支持分页。
update(project_no*, project_name=None:string, stage=None:string, sop_date=None:string, eop_date=None:string, owner=None:string, veh_model=None:string, share=None:string)
    — 更新项目台账（project_no 为主键不可修改）。stage 遵循单向流转，禁止跳级/回退。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "project_no": "BYD-HAN-25",
 "project_name": "比亚迪·汉 2025 款",
 "stage": "EOP",
 "sop_date": "2024-09-01",
 "eop_date": "2026-08-31",
 "owner": "王振",
 "veh_model": "比亚迪·汉",
 "share": 1.0
}
```


## md_project_part

### 服务契约
```
create(project_no*, material_no*, usage*)
    — 新建项目×物料映射，校验项目/物料引用存在与单车用量范围。车型/份额由项目关联，不入库。
get(project_no*, material_no*)
    — 按复合主键查看单条映射。
import_batch(rows*)
    — 批量导入/更新（upsert）：逐行校验，失败行返回错误明细，不阻断其余行。
list(project_no=None:string, material_no=None:string, page=None:integer, size=None:integer)
    — 按项目号/物料号模糊筛选的分页列表。
list_by_material(material_no*)
    — 按物料号查询其全部项目映射（不分页，供量纲折算/预测分摊跨应用调用）。
update(project_no*, material_no*, usage=None:string)
    — 更新映射的单车用量；project_no+material_no 不可修改。车型/份额由项目关联，不入库。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "project_no": "BYD-HAN-25",
 "material_no": "BYD-HAN-FB25",
 "usage": 1
}
```


## outbound_plan

### 服务契约
```
close_expired()
    — 关闭到期计划：待出库且计划出库日期早于今日的计划自动关闭（幂等）。
create(customer_no*, material_no*, qty*, out_date*, actual_out_no=None:string)
    — 手工新建出库计划：校验主数据引用，按日期判定初始状态。
delete(plan_no*)
    — 删除出库计划：仅「待出库」可删；已关闭为历史留痕，不可删除。
get(plan_no*)
    — 按出库计划号查看单条计划详情。
list(material_no=None:string, customer_no=None:string, status=None:string, page=None:integer, size=None:integer)
    — 按物料 / 客户 / 状态筛选出库计划分页列表（读取前先惰性关闭到期计划）。
update(plan_no*, customer_no=None:string, material_no=None:string, qty=None:string, out_date=None:string, actual_out_no=None:string)
    — 编辑出库计划（已关闭亦可编辑延期）：传入字段覆盖，状态按最终日期重算。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "plan_no": "OB202609150003",
 "customer_no": "BYD",
 "material_no": "BYD-HAN-SPARM",
 "qty": 129.8545,
 "out_date": "2026-10-10",
 "actual_out_no": null,
 "status": "待出库"
}
```


## sales_forecast

### 服务契约
```
adjust_event(version_no*, material_no*, customer_no*, rolling_month*, event_analysis=None:string, event_adj=0:number)
    — 填写事件分析/事件调整量，重算基线和事件合计量（只作用归属期，不外推）。
calc_baseline(version_no*, material_no*, customer_no*, rolling_month*)
    — 断点追溯前置 + 按物料基线方法/参数作用于历史干净需求，得到基线数量。
calc_baseline_batch(version_no*, material_no=None:string, customer_no=None:string)
    — 批量算基线：遍历版本内全部处理行（可按物料/客户收窄）逐行 calc_baseline，
create(version_no*, material_no*, customer_no=None:string)
    — 手工新建物料×客户组合（客户可空），覆盖 open_version 未生成的组合。
customer_forecast_history(material_no*, customer_no*, months=None:integer)
    — 历史客户预测投影（供达成率计算，口径A）：取 rolling=N+1 且 orig_qty 非空的行，
decide(version_no*, material_no*, customer_no*, rolling_month*)
    — 按 MAPE 与偏离率自动标记异常并给出最终预测建议（异常行不自动填写）。
decide_batch(version_no*, material_no=None:string, customer_no=None:string)
    — 批量决策：遍历版本内全部处理行（可按物料/客户收窄）逐行 decide，单行失败跳过。
fill_customer(version_no*, material_no*, customer_no*, rolling_month*, orig_qty=None:number, adj_qty=None:number)
    — 填写客户原始预测数量，系统按 bias 自动算调整后需求（人工可调）。
get(version_no*, material_no*, customer_no*, rolling_month*)
    — 按主键取处理表单行全部字段。
get_summary(version_no*, material_no=None:string)
    — 取指定版本（可指定物料）的汇总行，供毛需求合成。
import_orig_qty(version_no*, rows*)
    — 批量导入客户原始预测：逐行调 fill_customer 写 orig_qty（自动算 adj、N+1 关联历史台账），
list(version_no=None:string, material_no=None:string, customer_no=None:string, rolling_month=None:string, abnormal_flag=None:boolean, page=None:integer, size=None:integer)
    — 按版本/物料/客户/滚动月度/异常标记筛选分页查询处理表。
open_version(version_no*)
    — 开启月度版本：按正常状态物料 × 该物料的历史采购客户生成清单并拆 N+1/N+2/N+3 进处理表。
set_final(version_no*, material_no*, customer_no*, rolling_month*, final_qty*)
    — 异常行人工填写最终预测量（非异常行拒绝人工覆盖）。
summarize(version_no*)
    — 按物料 × 滚动月度合计所有客户最终预测量，刷新汇总表。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "version_no": "202610",
 "material_no": "BYD-HAN-BRK",
 "customer_no": "BYD",
 "rolling_month": "N+1",
 "orig_qty": 1680.0,
 "mape": 0.09,
 "bias": 0.03,
 "adj_qty": 1629.6,
 "base_method": "AutoTheta",
 "base_params": "{\"season_length\": 12}",
 "base_qty": 1623.6435,
 "event_analysis": null,
 "event_adj": 0.0,
 "base_event_qty": 1623.6435,
 "bp_material_no": null,
 "switch_time": null,
 "abnormal_flag": 0,
 "final_qty": 1629.6,
 "created_at": "2026-09-15 14:50:31",
 "updated_at": "2026-09-15 22:03:20",
 "created_by": "demo",
 "updated_by": "demo"
}
```


## sales_history

### 服务契约
```
attach_forecast(material_no*, customer_no*, period*, qty*)
    — 预测侧推送：把 N+1 原始预测写入对应台账行的 forecast_qty。
history_sequence(material_nos=None:string, customer_no=None:string, limit=None:integer)
    — 消费方投影：按 period 升序返回干净需求数量序列（数字列表）。
history_series(material_nos=None:string, customer_no=None:string, limit=None:integer)
    — 与 history_sequence 同口径，但返回 [{period, qty}]（含期间标签）。
import_batch(rows*)
    — 批量导入（upsert 语义）：逐行校验，合法行入库，失败行返回错误明细，不阻断其余行。
list(material_no=None:string, customer_no=None:string, period=None:string, page=None:integer, size=None:integer)
    — 按物料/客户/期间（精确、AND、可选）筛选台账分页列表 {items, total}。
main_customer(material_no*)
    — 该物料历史出货量最大的客户（无历史返回 None）。
purchasing_customers(material_no=None:string)
    — 历史采购客户集（去重升序，可按物料收窄），供销售预测清单客户维度。
sync_external_history()
    — 对外服务：拉取外部历史台账接口并经 import_batch 落库（供定时任务 / Agent 调用）。
sync_forecast()
    — 批量回填 forecast_qty：按 (物料,客户) 拉销售预测 N+1 原始预测，按期对齐更新存量台账行。
upsert(material_no*, customer_no*, period*, qty*)
    — ERP 单条回写：同 物料+客户+期间 存在则覆盖 qty，不存在则插入（幂等）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "material_no": "BYD-HAN-BRK",
 "customer_no": "BYD",
 "period": "2024-09",
 "qty": 1426.0,
 "forecast_qty": null
}
```


## strategy_fitting

### 服务契约
```
approve(fit_version*, material_no*, confirm=False:boolean)
    — 复核通过：待复核 → 已生效，并回填物料主数据（带版本）。
get(fit_version*, material_no*)
    — 查看单条拟合结果完整字段。
get_latest(material_no*)
    — 取某物料最新一版拟合结果（按 fit_version 降序）。无拟合返回 None（不抛错）。
list(material_no=None:string, fit_version=None:string, status=None:string, abnormal_flag=None:boolean, page=None:integer, size=None:integer)
    — 按物料号（模糊）/拟合版本/状态/异常标记筛选分页列表。
reject(fit_version*, material_no*)
    — 否决：待复核 → 已否决，不回填物料主数据。
rollback(fit_version*, material_no*)
    — 回滚：已生效 → 已否决（本版作废），并回填上一版参数。
run(material_no*, fit_version*)
    — 对指定物料发起一次策略拟合（预测拟合 + 库存拟合），结果落表（待复核）。
run_batch(fit_version=None:string)
    — 整批拟合：按 fit_version 对全部正常状态物料逐物料拟合（简化同步实现）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "material_no": "BYD-HAN-BRK",
 "fit_version": "202610",
 "pred_method": "AutoTheta",
 "pred_params": "{\"season_length\": 12}",
 "smape": 0.0391,
 "mase": 0.8112,
 "pred_qty": 1623.64,
 "pred_lo": 1543.6,
 "pred_hi": 1706.36,
 "sigma_l": 5.9852,
 "detail_json": "{\"candidates\": [{\"method\": \"AutoTheta\", \"params\": {\"season_length\": 12}, \"mase\": 0.8112, \"smape\": 0.0391, \"steps\": [{\"period\": \"2024-09\", \"actual\": 1426.0, \"pred\": -22705.26}, {\"period\": \"2024-10\", \"actual\": 1516.0, \"pred\": -120.0}, {\"period\": \"2024-11\", \"actual\": 1506.0, \"pred\": 1414.69}, {\"period\": \"2024-12\", \"actual\": 1515.0, \"pred\": 1503.89}, {\"period\": \"2025-01\", \"actual\": 1402.0, \"pred\": 1518.04}, {\"period\": \"2025-02\", \"actual\": 1365.0, \"pred\": 1413.21}, {\"period\": \"2025-03\", \"actual\": 1393.0, \"pred\": 1371.85}, {\"period\": \"2025-04\", \"actual\": 1379.0, \"pred\": 1395.4}, {\"period\": \"2025-05\", \"actual\": 1359.0, \"pred\": 1383.81}, {\"period\": \"2025-06\", \"actual\": 1440.0, \"pred\": 1364.35}, {\"period\": \"2025-07\", \"actual\": 1458.0, \"pred\": 1438.9}, {\"period\": \"2025-08\", \"actual\": 1555.0, \"pred\": 1460.53}, {\"period\": \"2025-09\", \"actual\": 1513.0, \"pred\": 1552.69}, {\"period\": \"2025-10\", \"actual\": 1545.0, \"pred\": 1519.3}, {\"period\": \"2025-11\", \"actual\": 1626.0, \"pred\": 1547.1}, {\"period\": \"2025-12\", \"actual\": 1533.0, \"pred\": 1624.69}, {\"period\": \"2026-01\", \"actual\": 1483.0, \"pred\": 1542.64}, {\"period\": \"2026-02\", \"actual\": 1509.0, \"pred\": 1490.58}, {\"period\": \"2026-03\", \"actual\": 1462.0, \"pred\": 1511.57}, {\"period\": \"2026-04\", \"actual\": 1401.0, \"pred\": 1468.94}, {\"period\": \"2026-05\", \"actual\": 1466.0, \"pred\": 1409.12}, {\"period\": \"2026-06\", \"actual\": 1520.0, \"pred\": 1466.1}, {\"period\": \"2026-07\", \"actual\": 1512.0, \"pred\": 1520.29}, {\"period\": \"2026-08\", \"actual\": 1627.0, \"pred\": 1516.29}]}, {\"method\": \"AutoETS\", \"params\": {\"season_length\": 12}, \"mase\": 0.8133, \"smape\": 0.0392, \"steps\": [{\"period\": \"2024-09\", \"actual\": 1426.0, \"pred\": 1429.24}, {\"period\": \"2024-10\", \"actual\": 1516.0, \"pred\": 1426.18}, {\"period\": \"2024-11\", \"actual\": 1506.0, \"pred\": 1510.89}, {\"period\": \"2024-12\", \"actual\": 1515.0, \"pred\": 1506.28}, {\"period\": \"2025-01\", \"actual\": 1402.0, \"pred\": 1514.5}, {\"period\": \"2025-02\", \"actual\": 1365.0, \"pred\": 1408.41}, {\"period\": \"2025-03\", \"actual\": 1393.0, \"pred\": 1367.47}, {\"period\": \"2025-04\", \"actual\": 1379.0, \"pred\": 1391.55}, {\"period\": \"2025-05\", \"actual\": 1359.0, \"pred\": 1379.71}, {\"period\": \"2025-06\", \"actual\": 1440.0, \"pred\": 1360.18}, {\"period\": \"2025-07\", \"actual\": 1458.0, \"pred\": 1435.46}, {\"period\": \"2025-08\", \"actual\": 1555.0, \"pred\": 1456.72}, {\"period\": \"2025-09\", \"actual\": 1513.0, \"pred\": 1549.4}, {\"period\": \"2025-10\", \"actual\": 1545.0, \"pred\": 1515.07}, {\"period\": \"2025-11\", \"actual\": 1626.0, \"pred\": 1543.3}, {\"period\": \"2025-12\", \"actual\": 1533.0, \"pred\": 1621.29}, {\"period\": \"2026-01\", \"actual\": 1483.0, \"pred\": 1538.03}, {\"period\": \"2026-02\", \"actual\": 1509.0, \"pred\": 1486.13}, {\"period\": \"2026-03\", \"actual\": 1462.0, \"pred\": 1507.7}, {\"period\": \"2026-04\", \"actual\": 1401.0, \"pred\": 1464.6}, {\"period\": \"2026-05\", \"actual\": 1466.0, \"pred\": 1404.62}, {\"period\": \"2026-06\", \
  …（已截断）
```
