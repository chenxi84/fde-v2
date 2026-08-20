# psc 模块契约速查（自动生成 · 视图生成参照）

> 字段以此文件与 `app/psc/<应用>/<应用>.py` 源码为准；list 示例取自库中现有数据（无数据项以源码为准；造数级样例经平台⑧契约冻结任务生成）。


## attainment

### 服务契约
```
get(customer_no*, material_no*)
    — 按客户+物料查询该组合的 MAPE/bias；未命中返回 None，不抛异常。
list(customer_no=None:string, material_no=None:string, page=None:integer, size=None:integer)
    — 按客户/物料（AND 关系，可选）筛选达成率列表，分页返回 {items, total}。
upsert(customer_no*, material_no*, mape*, bias*)
    — ERP 统计回写 MAPE/bias：同客户+物料存在则覆盖更新，不存在则插入（幂等）。
compute(months=None:integer)
    — 口径A 单表计算 MAPE/bias 并回写：直接读 sales_history 行内 forecast_qty(F) 与 qty(A)，无需 join 销售预测；
      默认滚动 6 个月，窗口内有效样本<3 或 Σ实际=0 跳过。返回 {computed, skipped}。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "customer_no": "C001",
 "material_no": "M1",
 "mape": 0.1,
 "bias": 0.05
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
list(version_no=None:string, material_no=None:string, rolling_month=None:string, page=None:string, size=None:string)
    — 按版本/物料/滚动月度筛选毛需求与净需求分页列表。
publish(version_no*)
    — 发布冻结毛需求：校验已合成，并联动 md_monthly_version.publish 锁定版本。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "version_no": "202608",
 "material_no": "M1",
 "rolling_month": "N+1",
 "forecast_qty": 950.0,
 "inventory_qty": 0.0,
 "gross_qty": 950.0,
 "open_order_qty": 0.0,
 "onhand_qty": 0.0,
 "in_transit_qty": 0.0,
 "net_qty": 950.0
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
list(material_no=None:string, replenish_type=None:string, status=None:string, page=None:string, size=None:string)
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
 "replenish_no": "RP202608140001",
 "material_no": "M1",
 "replenish_type": "缺货补库",
 "replenish_qty": 100.0,
 "required_inbound": "2026-08-20",
 "promised_inbound": "2026-08-20",
 "status": "已完成"
}
```


## inventory_projection

### 服务契约
```
get(material_no*, biz_date*)
    — 按物料号 + 日期查询单日推移明细。
list(material_no=None:string, biz_date=None:string, alert_type=None:string, page=None:integer, size=None:integer)
    — 按物料号 / 日期 / 预警类型筛选推移表列表，支持分页；默认 biz_date 升序（从早到晚），
      未选日期时仅返回当日及以后（BR-11 历史隐藏），选定具体日期（含历史）精确回看。
refresh(material_no*, biz_date*, opening_stock=None:string)
    — 对单个物料逐日推演未来 3 个月库存水位并落盘（含预警标记）。
      预计入库量 = master_plan.get_latest + demand_pool.list（已下达/生产中）；
      预计出库量 = outbound_plan.list（status=待出库，按计划出库日期合计）。
refresh_batch(biz_date=None:string, material_nos=None:string)
    — 整批刷新推移表（biz_date 缺省=当天，material_nos 缺省=全量正常物料），
      刷新后逐物料联动预警扫描（击穿水位自动创建需求池补库单）；
      返回 {total, success, fail, success_materials, errors, replenishments}。
scan_alert(material_no*, version_no=None:string)
    — 对照水位线扫描某物料推移表，回填 alert_type，击穿水位触发需求池补库。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "material_no": "M1",
 "biz_date": "2026-08-15",
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
 "version_no": "202608",
 "material_no": "M1",
 "hedge_tool": "库存",
 "min_level": 0,
 "service_factor": 1.65,
 "resp_volatility": 0,
 "safety_level": 0,
 "batch_window": 28,
 "batch_level": 0,
 "basis": "物料M1：生产10天+物流5天，满足率95%，组批窗口28天，近0期月均干净需求0件，对冲工具库存（无历史数据，水位按 0）",
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
 "material_no": "M1",
 "version_no": "202608",
 "rolling_month": "N+1",
 "plan_version": 1,
 "plan_qty": 950.0,
 "latest_inbound_date": "2026-09-30"
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
    — 取某新物料的断点切换时间（可按客户收窄）；无断点返回 None。供销售预测 calc_baseline 回填处理表 switch_time。
list(customer_no=None:string, old_material_no=None:string, new_material_no=None:string, page=None:string, size=None:string)
    — 按客户/原物料号/新物料号（精确）筛选分页列表，默认不含已停用记录，按切换时间降序。
trace(new_material_no*)
    — 沿断点向上追溯原物料号链，返回从最上游原物料号到给定新物料号的序列（无断点返回自身）。
upcoming(days=60:integer)
    — 即将切换的断点关系：switch_time 在 [今天, 今天+days] 且未停用，供销售预测/库存策略/流程总览做「即将切换」预警。
update(bp_id*, customer_no=None:string, old_material_no=None:string, new_material_no=None:string, switch_time=None:string, ecn_no=None:string)
    — 更新断点的切换时间/变更单号等字段，重新校验物料引用、原≠新、组合唯一。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "bp_id": 1,
 "customer_no": "C001",
 "old_material_no": "M3",
 "new_material_no": "M4",
 "switch_time": "2026-09-01",
 "ecn_no": "ECN-002",
 "disabled": 0
}
```


## md_customer

### 服务契约
```
create(customer_no*, customer_name*, settle_mode=None:string, line_stock_days=None:integer, transfer_lead_days=None:integer, credit_code=None:string)
    — 新建客户主数据，customer_no 全局唯一；settle_mode 字典 现售/寄售；credit_code 18 位统一社会信用代码（GB 32100-2015 校验位）。
get(customer_no*)
    — 按客户编码查看单条客户主数据详情。
import_batch(rows*)
    — 批量导入/更新（upsert）：已存在 customer_no 更新，不存在则新增。
list(customer_no=None:string, customer_name=None:string, credit_code=None:string, page=None:integer, size=None:integer)
    — 按客户编码/名称/统一社会信用代码模糊筛选的分页列表（credit_code 自动大写化），按 customer_no 升序。
update(customer_no*, customer_name=None:string, settle_mode=None:string, line_stock_days=None:integer, transfer_lead_days=None:integer, credit_code=None:string)
    — 更新客户主数据（customer_no 主键不可改）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "customer_no": "C001",
 "customer_name": "客户A",
 "credit_code": "91110000710931000M",
 "settle_mode": "寄售",
 "line_stock_days": 0,
 "transfer_lead_days": 3
}
```


## md_material

### 服务契约
```
create(material_no*, material_name*, status='正常':string, unit_value=None:number, value_class=None:string, change_cost=None:number, prod_days=None:number, logistics_days=None:number, change_risk=None:string, service_level=None:number, batch_window=None:number, base_method=None:string, base_params=None:string)
    — 新建物料主数据记录，material_no 全局唯一。
get(material_no*)
    — 查询单个物料的完整主数据与参数。
import_batch(rows*)
    — 批量导入/更新（upsert）：逐行校验，成功行入库，失败行返回错误明细。
list(material_no=None:string, material_name=None:string, status=None:string, page=None:integer, size=None:integer)
    — 按物料号/名称模糊、状态精确筛选的分页列表。
set_fit_params(material_no*, base_method*, base_params*, batch_window*, service_level*, fit_version*)
    — 拟合参数回填（被 strategy_fitting 调用），更新方法/参数并记录版本快照。
update(material_no*, material_name=None:string, status=None:string, unit_value=None:number, value_class=None:string, change_cost=None:number, prod_days=None:number, logistics_days=None:number, change_risk=None:string, service_level=None:number, batch_window=None:number, base_method=None:string, base_params=None:string)
    — 更新物料名称与各参数；material_no（主键）与 status（只读）不可修改。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "material_no": "M1",
 "material_name": "物料A更新",
 "status": "正常",
 "value_class": null,
 "change_risk": null,
 "base_method": null
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
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "version_no": "202609",
 "anchor_period": "2026-09",
 "opening_date": "2026-09-01",
 "lock_status": "草稿"
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
list(old_material_no=None:string, new_material_no=None:string, status=None:string, page=None:string, size=None:string)
    — 按原物料号/替换物料号（模糊）、状态（精确）筛选分页列表。
update(rel_no*, old_material_no*, new_material_no*, ecn_no=None:string)
    — 更新替换关系的原/替换物料号与 ECN 依据，重新校验物料引用、原≠替换与组合唯一。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "rel_no": "R544623FABE0647B2AAF9836410177B51",
 "old_material_no": "M3",
 "new_material_no": "M4",
 "ecn_no": "ECN-001",
 "status": "失效"
}
```


## md_project

### 服务契约
```
create(project_no*, project_name*, owner*, stage=None:string, sop_date=None:string, eop_date=None:string)
    — 新建项目台账。project_no 全局唯一，stage 默认「进行中」。
get(project_no*)
    — 按项目号查询项目台账详情。
import_batch(rows*)
    — 批量导入/更新项目台账（upsert）。已存在主键行更新，新行新增；逐行校验，失败行记录错误明细。
list(project_no=None:string, project_name=None:string, stage=None:string, page=None:integer, size=None:integer)
    — 按项目号（模糊）、项目名称（模糊）、阶段（精确）筛选项目台账，支持分页。
update(project_no*, project_name=None:string, stage=None:string, sop_date=None:string, eop_date=None:string, owner=None:string)
    — 更新项目台账（project_no 为主键不可修改）。stage 遵循单向流转，禁止跳级/回退。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "project_no": "PRJ-1",
 "project_name": "项目1",
 "stage": "SOP",
 "sop_date": "2026-01-01",
 "eop_date": "2027-12-31",
 "owner": "S001"
}
```


## md_project_part

### 服务契约
```
create(project_no*, material_no*, usage*)
    — 新建项目×物料映射，校验项目/物料引用存在与单车用量范围；车型/供应份额不入库（项目级信息，前端关联 md_project 显示）。
get(project_no*, material_no*)
    — 按复合主键查看单条映射。
import_batch(rows*)
    — 批量导入/更新（upsert）：逐行校验，失败行返回错误明细，不阻断其余行。
list(project_no=None:string, material_no=None:string, page=None:integer, size=None:integer)
    — 按项目号/物料号模糊筛选的分页列表。
list_by_material(material_no*)
    — 按物料号查询其全部项目映射（不分页，供量纲折算/预测分摊跨应用调用）。
update(project_no*, material_no*, usage=None:string)
    — 更新映射的单车用量；project_no+material_no 不可修改。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "project_no": "PRJ-1",
 "material_no": "M1",
 "usage": 1.0
}
```


## outbound_plan

### 服务契约
```
close_expired()
    — 关闭到期计划：待出库且计划出库日期早于今日的计划自动关闭（幂等），返回 {closed: N}。
create(customer_no*, material_no*, qty*, out_date*, actual_out_no=None:string)
    — 手工新建出库计划：校验主数据引用，按日期判定初始状态（今日及以后=待出库，早于今日=已关闭）。
delete(plan_no*)
    — 删除出库计划：仅「待出库」可删；已关闭为历史留痕，不可删除。
get(plan_no*)
    — 按出库计划号查看单条计划详情（读取前先惰性关闭到期计划）。
list(material_no=None:string, customer_no=None:string, status=None:string, page=None:integer, size=None:integer)
    — 按物料 / 客户 / 状态筛选出库计划分页列表（读取前先惰性关闭到期计划），按 out_date 降序。
update(plan_no*, customer_no=None:string, material_no=None:string, qty=None, out_date=None:string, actual_out_no=None:string)
    — 编辑出库计划（已关闭亦可编辑延期）：传入字段覆盖，状态按最终日期重算（延期到今日及以后恢复待出库）。
```

### 跨应用依赖
- create / update 调用 `md_material.get`、`md_customer.get` 校验主数据存在性（主数据引用铁律）。
- 被 `inventory_projection.refresh` 消费：`list(status=待出库)` 生成推移表预计出库量。

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "plan_no": "OB202608200001",
 "customer_no": "C001",
 "material_no": "M1",
 "qty": 300.0,
 "out_date": "2026-09-20",
 "actual_out_no": null,
 "status": "待出库"
}
```


## sales_forecast

### 服务契约
```
adjust_event(version_no*, material_no*, customer_no*, rolling_month*, event_analysis=None:string, event_adj=0:string)
    — 填写事件分析/事件调整量，重算基线和事件合计量（只作用归属期，不外推）。
calc_baseline(version_no*, material_no*, customer_no*, rolling_month*)
    — 断点追溯前置 + 按物料基线方法/参数作用于历史干净需求，得到基线数量。
calc_baseline_batch(version_no*, material_no=None:string, customer_no=None:string)
    — 批量算基线：遍历版本内全部处理行（可按物料/客户收窄）逐行 calc_baseline，单行失败跳过。
      返回 {version_no, computed, failed}。仅草稿版本可执行。
create(version_no*, material_no*, customer_no=None:string)
    — 手工新建物料×客户组合（客户可空），覆盖 open_version 未生成的组合；拆 N+1/N+2/N+3 三行进处理表。
      组合已存在 / 物料或客户不存在 / 版本非草稿均拒绝。
import_orig_qty(version_no*, rows*)
    — 批量导入客户原始预测：逐行 fill_customer 写 orig_qty（自动算 adj、N+1 关联历史台账），单行失败跳过。
      rows 项 {material_no, customer_no, rolling_month, orig_qty}。返回 {total, success, fail, errors}。仅草稿版本。
decide_batch(version_no*, material_no=None:string, customer_no=None:string)
    — 批量决策：遍历版本内全部处理行（可按物料/客户收窄）逐行 decide（物料级 base vs adj_sum 判异常），单行失败跳过。
      返回 {version_no, computed, failed, abnormal}。仅草稿版本。
decide(version_no*, material_no*, customer_no*, rolling_month*)
    — 按 MAPE 与偏离率自动标记异常并给出最终预测建议（异常行不自动填写）。
fill_customer(version_no*, material_no*, customer_no*, rolling_month*, orig_qty=None:string, adj_qty=None:string)
    — 填写客户原始预测数量，系统按 bias 自动算调整后需求（人工可调）。
get(version_no*, material_no*, customer_no*, rolling_month*)
    — 按主键取处理表单行全部字段。
get_summary(version_no*, material_no=None:string)
    — 取指定版本（可指定物料）的汇总行，供毛需求合成。
list(version_no=None:string, material_no=None:string, customer_no=None:string, rolling_month=None:string, abnormal_flag=None:string, page=None:string, size=None:string)
    — 按版本/物料/客户/滚动月度/异常标记筛选分页查询处理表。
open_version(version_no*)
    — 开启月度版本：按正常状态物料 × 该物料的历史采购客户生成清单并拆 N+1/N+2/N+3 进处理表；
      某物料无历史采购记录时客户字段为空、仅初始化一行（避免 300 客户 × 3 月铺满）。
set_final(version_no*, material_no*, customer_no*, rolling_month*, final_qty*)
    — 异常行人工填写最终预测量（非异常行拒绝人工覆盖）。
summarize(version_no*)
    — 按物料 × 滚动月度合计所有客户最终预测量，刷新汇总表。
customer_forecast_history(material_no*, customer_no*, months=None:integer)
    — 历史客户预测投影（口径A 达成率用）：rolling=N+1 且 orig_qty 非空，期间=版本月+1，
      返回 [{period, orig_qty}] 升序；months 取末尾 N 个月。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "version_no": "202608",
 "material_no": "M1",
 "customer_no": "C001",
 "rolling_month": "N+1",
 "orig_qty": 1000.0,
 "mape": 0.1,
 "bias": 0.05,
 "adj_qty": 950.0,
 "base_method": "移动平均",
 "base_params": "{\"window\": 6}",
 "base_qty": null,
 "event_analysis": null,
 "event_adj": 0.0,
 "base_event_qty": null,
 "bp_material_no": null,
 "switch_time": null,
 "abnormal_flag": 0,
 "final_qty": 950.0,
 "created_at": "2026-08-14 18:57:32",
 "updated_at": "2026-08-14 18:57:33",
 "created_by": "demo",
 "updated_by": "demo"
}
```


## sales_history

### 服务契约
```
upsert(material_no*, customer_no*, period*, qty*)
    — ERP 单条幂等回写：同 物料+客户+期间 覆盖 qty，否则插入；并自动拉取 N+1 原始预测写入 forecast_qty。period 须 YYYY-MM，qty≥0。
import_batch(rows*)
    — 批量导入（upsert 语义）：逐行校验，返回 {total, success, fail, errors}。
attach_forecast(material_no*, customer_no*, period*, qty=None)
    — 预测侧推送：把 N+1 原始预测写入对应台账行 forecast_qty；实际行不存在则跳过（attached=false）。
sync_forecast()
    — 批量回填存量台账行 forecast_qty（按 物料+客户 拉销售预测 N+1 按期对齐）。返回 {updated}。
list(material_no=None:string, customer_no=None:string, period=None:string, page=None:integer, size=None:integer)
    — 按物料/客户/期间（精确、AND）筛选分页列表 {items, total}。
history_sequence(material_nos=None, customer_no=None:string, limit=None:integer)
    — 消费方投影：按 period 升序返回数量序列（数字列表）；material_nos 支持单物料或断点链（多物料按期求和、缺期补 0）；limit 取末尾 N 期。
purchasing_customers(material_no=None:string)
    — 历史采购客户集（去重升序，可按物料收窄）。
```

### list 返回项示例
```json
{
 "material_no": "M1",
 "customer_no": "C001",
 "period": "2026-01",
 "qty": 900.0,
 "forecast_qty": 910.0
}
```


## strategy_fitting

### 服务契约
```
approve(fit_version*, material_no*, confirm=False:string)
    — 复核通过：待复核 → 已生效，并回填物料主数据（带版本）。
get(fit_version*, material_no*)
    — 查看单条拟合结果完整字段。
list(material_no=None:string, fit_version=None:string, status=None:string, abnormal_flag=None:string, page=None:string, size=None:string)
    — 按物料号（模糊）/拟合版本/状态/异常标记筛选分页列表。
reject(fit_version*, material_no*)
    — 否决：待复核 → 已否决，不回填物料主数据。
rollback(fit_version*, material_no*)
    — 回滚：已生效 → 已否决（本版作废），并回填上一版参数。
run(material_no*, fit_version*)
    — 对指定物料发起一次策略拟合（预测拟合 + 库存拟合），结果落表（待复核）。
run_batch(fit_version*)
    — 整批拟合：按 fit_version 对全部正常状态物料逐物料拟合（简化同步实现）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "material_no": "M1",
 "fit_version": "202609",
 "pred_method": "指数平滑",
 "pred_params": "{\"alpha\": 0.3, \"trend\": false}",
 "smape": 0.0,
 "service_factor": 1.65,
 "safety_level": 0.0,
 "batch_window": 28.0,
 "fulfill_rate": 0.95,
 "inv_days": 0.0,
 "changeover_cnt": 0,
 "abnormal_flag": false,
 "status": "待复核"
}
```
