# parts-fc 模块契约速查（自动生成 · 视图生成参照）

> 字段以此文件与 `app/parts-fc/<应用>/<应用>.py` 源码为准；list 示例取自库中现有数据（无数据项以源码为准；造数级样例经平台⑧契约冻结任务生成）。


## baseline_borrowing

### 服务契约
```
calibrate(jy_no*, calibration_data*)
    — 早期校准更新——有自身历史数据后修正借用参数。
close(jy_no*, reason*)
    — 关闭借用单——历史转充足后切换自产策略，或不再使用该借用。
create(part_no*, veh_model*, hist_months*, borrow_method*, borrow_source*, source_params*, derived_qty*, proc_batch*, calibration=None:string)
    — 新建基线借用单。
get(jy_no*)
    — 获取借用单详情。
get_derived_baseline(jy_no*)
    — 获取推导基线值——返回 derived_qty 中各期基线数据。
list(part_no=None:string, status=None:string, borrow_method=None:string)
    — 按条件列表查询。
review(jy_no*, approved*, comment*)
    — 审核借用单——通过或驳回。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "jy_no": "JY-202608-012",
 "part_no": "PART-003-BB18",
 "veh_model": "MODEL-A",
 "hist_months": 0,
 "borrow_method": "先导指标",
 "borrow_source": "V2026-08 OEM滚动预测",
 "source_params": "{}",
 "calibration": null,
 "derived_qty": "{\"2026-08\":440}",
 "proc_batch": "BATCH-BB18",
 "status": "待审核",
 "reviewer": null,
 "review_date": null,
 "created_at": "2026-08-08 12:07:37",
 "updated_at": "2026-08-08 12:07:37",
 "created_by": "demo",
 "updated_by": "demo"
}
```


## bullwhip_correction

### 服务契约
```
confirm(bw_no*)
    — 确认（已修正→已确认，转入发布）
create(part_no*, period*, tier*, derived_qty=None:number, end_qty=None:number, end_source='结算':string)
    — 新建处理单。系统自动计算放大系数。
get(bw_no*)
list(part_no=None:string, period=None:string, tier=None:string, status=None:string)
maintain(bw_no*)
    — 容忍内维持
set_correction(bw_no*, corr_action*, final_qty*)
    — 执行修正（超阈场景）
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "bw_no": "BW-202608-08120730734124",
 "part_no": "PART-001",
 "period": "2026-09",
 "tier": "Tier1直供",
 "derived_qty": 990.0,
 "end_qty": 970.0,
 "end_source": "结算",
 "amp_factor": 1.0206185567010309,
 "amp_verdict": "容忍内·维持",
 "corr_action": "维持——放大已由拆解先行完成",
 "final_qty": 990.0,
 "checker": "demo",
 "chk_date": "2026-08-08",
 "status": "已确认",
 "created_at": "2026-08-08 12:07:30",
 "updated_at": "2026-08-08 12:07:30",
 "created_by": "demo",
 "updated_by": "demo"
}
```


## common_parts_agg

### 服务契约
```
add_detail(agg_no*, oem_code*, owner_sales*, approved_qty*, evidence_qty=0:number, verbal_qty=0:number)
    — 添加客户份额明细
confirm(agg_no*)
    — 确认转D08
create(part_no*, period*)
    — 新建汇总单，拉取各客户D04核定值。
get(agg_no*)
list(part_no=None:string, period=None:string, status=None:string)
set_dedup(agg_no*, dedup_qty*, dedup_reason*, anchor_ref=None:object)
    — 去重修正：差异化折减
set_split(agg_no*, split_detail*)
    — 拆回分配：修正总量落回客户维度
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "agg_no": "AGG-202608-08120730666267",
 "part_no": "PART-STD",
 "period": "2026-09",
 "sum_qty": 32000.0,
 "anchor_ref": "{}",
 "dedup_qty": 30500.0,
 "dedup_pct": -0.046875,
 "dedup_reason": "口头加码2400按历史实际用量折减约1500",
 "split_qty": null,
 "status": "已确认",
 "reviser": "demo",
 "revise_time": "2026-08-08 12:07:30",
 "created_at": "2026-08-08 12:07:30",
 "updated_at": "2026-08-08 12:07:30",
 "created_by": "demo",
 "updated_by": "demo"
}
```


## demand_collection

### 服务契约
```
add_lines(collect_no*, lines*)
    — 批量录入明细。lines=[{part_no, project_no, veh_model, period, orig_qty, ...}]
cancel(collect_no*, reason*)
    — 作废收集单
confirm_decompose(collect_no*)
    — 拆解确认：恒等式 + 噪声守恒校验后冻结版本。脉冲确认→生成D06事件。
create(oem_code*, plant_code*, fcst_version*, base_period*, demand_type='月度滚动预测':string, source_channel='':string, recv_date='':string, remark='':string)
    — 新建收集单头。客户+工厂+版本唯一。
decompose(collect_no*, line_no*, period*, noise_adj*, pulse_qty*, method*, basis*)
    — 记录单行拆解结果。true_qty = orig_qty - pulse_qty - noise_adj（系统强制）。
get(collect_no*)
    — 获取收集单全貌（单头+明细+拆解快照）
list(oem_code=None:string, fcst_version=None:string, status=None:string)
lock(collect_no*)
    — 锁定版本（由D09发布联动触发）
supersede(collect_no*, new_collect_no*)
    — 版本替代
version_diff(collect_no*)
    — 版本比对：当前版本 vs 上一版本逐零件×期间差异
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "collect_no": "COL-202608-08120733056513",
 "oem_code": "OEM-A",
 "plant_code": "PLANT-1",
 "fcst_version": "V2026-08-TC02",
 "base_period": "2026-08",
 "demand_type": "月度滚动预测",
 "source_channel": "EDL/EDI",
 "recv_date": "2026-08-08",
 "collector": "demo",
 "status": "草稿",
 "prev_version": "COL-202608-08120733018944",
 "remark": "",
 "created_at": "2026-08-08 12:07:33",
 "updated_at": "2026-08-08 12:07:33",
 "created_by": "demo",
 "updated_by": "demo"
}
```


## demand_processing

### 服务契约
```
confirm_baseline(proc_batch*, part_no*, veh_model*, period*, base_qty=None:number, deviation_reason=None:string)
    — 人工确认/裁决基线
create_batch(fcst_version*, oem_code*, plant_code*)
    — 创建加工批次。由拆解确认后触发。
generate_baseline(proc_batch*)
    — 系统预计算双路径基线。从D03取true_qty，从D10/D05取策略。
get(proc_batch*)
    — 获取批次全貌
get_status(proc_batch*, part_no*, veh_model*, period*)
    — 查看行级状态
list(oem_code=None:string, status=None:string)
lock(proc_batch*)
    — 锁定批次（D09发布联动触发）
review(proc_batch*, part_no*, veh_model*, period*, chk_result*, chk_reason='':string, chk_adj_qty=None:number)
    — 核对：通过/退回。退回须附书面理由。
submit_adjustment(proc_batch*, part_no*, veh_model*, period*, adj_qty*, adj_reason_cat*, adj_evidence='':string)
    — 销售提交修正值。三件套强制。超θ_rev(20%)强制举证。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "proc_batch": "PRC-202608-08120730285855",
 "oem_code": "OEM-A",
 "plant_code": "PLANT-1",
 "fcst_version": "V2026-08",
 "status": "进行中",
 "start_time": "2026-08-08 12:07:30",
 "finish_time": null,
 "created_at": "2026-08-08 12:07:30",
 "updated_at": "2026-08-08 12:07:30",
 "created_by": "demo",
 "updated_by": "demo"
}
```


## demand_release

### 服务契约
```
add_line(rel_no*, part_no*, veh_model*, period*, cons_qty*, event_items*, basis*, lineage*, split_qty=None:object)
    — 添加发布明细行。rel_qty = cons_qty + Σ事件量（系统强制）。
checklist_verify(rel_no*)
    — 发布前 checklist 五项校验。
create_draft(base_period*)
    — 生成发布草稿：汇总D04/D06/D07/D08结果。
get(rel_no*)
    — 获取发布单全貌
list(rel_version=None:string, status=None:string)
publish(rel_no*)
    — 正式发布。联动锁定D04批次+D03 V版。
revise(rel_no*, reason*)
    — 版本修订——产生子版本
version_diff(rel_no*)
    — 版本比对 R_n vs R_{n-1}
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "rel_no": "REL-202608-08120737716247",
 "rel_version": "R202608.4",
 "base_period": "2026-08",
 "prev_version": null,
 "status": "草稿",
 "publisher": null,
 "publish_date": null,
 "created_at": "2026-08-08 12:07:37",
 "updated_at": "2026-08-08 12:07:37",
 "created_by": "demo",
 "updated_by": "demo"
}
```


## forecast_assessment

### 服务契约
```
add_record(fa_no*, part_no*, veh_model*, period*, fcst_qty*, actual_qty*, settle_qty*, base_qty*, adj_qty*)
    — 添加单零件考核记录并自动计算指标
attribute(fa_no*, part_no*, period*, attribution*, result*, evidence='':string)
    — 归因认定
calculate(period*)
    — 批量计算考核期指标（从D09/D04取快照）
create(period*)
    — 创建考核期批次。从D09取发布快照计算指标。
get(fa_no*)
get_fva_view(part_no*, period*)
    — FVA视图：基线误差 vs 核定误差
get_trust_discount(oem_code*)
    — 供D04调用：返回客户信任折扣
list(part_no=None:string, period=None:string, result=None:string)
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "fa_no": "FA-202608-08120730941305",
 "part_no": "PART-001",
 "veh_model": "MODEL-A",
 "period": "2026-08",
 "fcst_qty": 1200.0,
 "actual_qty": 1190.0,
 "conv_rate": 0.9916666666666667,
 "dev_qty": -10.0,
 "settle_qty": 1195.0,
 "base_qty": 1180.0,
 "adj_qty": 1200.0,
 "attribution": "容忍区间内|偏差-10在±10%容忍区间内",
 "result": "计入考核",
 "cycle": "2026-08",
 "assessor": "demo",
 "created_at": null,
 "updated_at": "2026-08-08 12:07:30",
 "created_by": null,
 "updated_by": "demo"
}
```


## independent_event

### 服务契约
```
cancel(event_no*, close_basis*)
    — 取消事件——误判/误登记时使用。状态→已取消，close_basis 记录复盘结论。
close(event_no*, close_basis*)
    — 关闭事件——已回落/生效→已关闭。close_basis 必填。
confirm(event_no*)
    — 确认事件——待确认→生效。仅总部计划可操作。
create(event_type*, part_no*, period*, event_qty*, source_basis*, oem_code='':string, veh_model='':string, source_ref=None:string, bp_batch=None:string, bp_date=None:string)
    — 新建独立事件。
create_bp_pair(old_part_no*, new_part_no*, bp_date*, old_qty*, new_qty*, oem_code*, veh_model*, period*, source_basis='设变通知':string, source_ref=None:string)
    — 创建成对断点——旧件截断+新件启动，同 bp_batch 关联。
get(event_no*)
    — 获取事件详情。
list(part_no=None:string, event_type=None:string, status=None:string, period=None:string)
    — 按条件列表查询。
mark_subsided(event_no*, close_basis*)
    — 标记已回落——生效→已回落（水位达标）。close_basis 必填，记录水位达标证明。
mark_sustained(event_no*)
    — 标记持续中——生效→持续中（水位脉冲未达标，不重复登记）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）


## project_ledger

### 服务契约
```
create(project_no*, part_no*, stage='待定点':string, oem_code='':string, plant_code='':string, veh_model='':string, part_kind='专用':string, sop='':string, owner_sales='':string, award_prob=None:number, platform=None:string, usage=0:number, share=0:number, eop=None:string, lc_shape=None:string)
    — 新建项目-零件关联记录。
get(project_no*, part_no*)
    — 获取项目-零件详情。
get_change_log(project_no*, part_no*)
    — 获取变更日志列表。
list(stage=None:string, oem_code=None:string, owner_sales=None:string)
    — 按条件列表查询。
set_stage(project_no*, part_no*, new_stage*, reason*)
    — 阶段迁移——记录变更日志后更新阶段。
update(project_no*, part_no*, kwargs*)
    — 更新项目-零件属性，记录变更日志。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "project_no": "PRJ-001",
 "part_no": "PART-001",
 "stage": "进行中",
 "award_prob": null,
 "oem_code": "OEM-A",
 "plant_code": "PLANT-1",
 "veh_model": "MODEL-A",
 "platform": null,
 "part_kind": "专用",
 "usage": 0.0,
 "share": 0.0,
 "sop": "2024-03",
 "eop": "2027-06",
 "lc_shape": "传统",
 "owner_sales": "S001",
 "created_at": "2026-08-08 12:07:29",
 "updated_at": "2026-08-08 12:07:29",
 "created_by": "demo",
 "updated_by": "demo"
}
```


## strategy_fitting

### 服务契约
```
add_candidate(fit_no*, strategy*, inv_policy*)
    — 添加候选策略
create(part_no*, veh_model*, demand_shape*, data_range=None:string)
    — 新建拟合任务
get(fit_no*)
get_strategy(part_no*, veh_model*)
    — 供D04调用：获取当前生效策略
list(part_no=None:string, status=None:string)
run_backtest(fit_no*)
    — 执行滚动回测（简化：实际需历史数据+时间序列回测引擎）
select_strategy(fit_no*, cand_no*)
    — 选定策略
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "fit_no": "D10-2026Q3-081207",
 "part_no": "PART-001",
 "veh_model": "MODEL-A",
 "demand_shape": "稳定",
 "data_range": "2025-01~2026-06",
 "backtest_spec": null,
 "status": "生效中",
 "fitter": "demo",
 "fit_date": "2026-08-08",
 "created_at": "2026-08-08 12:07:30",
 "updated_at": "2026-08-08 12:07:30",
 "created_by": "demo",
 "updated_by": "demo"
}
```


## vehicle_part_map

### 服务契约
```
create(part_no*, veh_model*, platform=None:string, usage=0:number, share=0:number, lc_stage='':string, lc_shape='传统':string, sop='':string, eop=None:string, source='':string, status='生效':string)
    — 新建车型-零件映射。
disable(part_no*, veh_model*, reason='':string)
    — 停用映射——设变替代或EOP。
get(part_no*, veh_model*)
    — 获取映射详情。
get_usage_history(part_no*, veh_model*)
    — 查询量纲历史版本（用量+份额）。
list(part_no=None:string, veh_model=None:string, lc_stage=None:string, status=None:string)
    — 按条件列表查询。
set_share(part_no*, veh_model*, new_share*, effective_date*, basis*)
    — 变更供应份额——生成历史版本。
set_usage(part_no*, veh_model*, new_usage*, effective_date*, basis*)
    — 变更单车用量——生成历史版本，旧版本按生效期间保留。
update(part_no*, veh_model*, kwargs*)
    — 更新映射属性（不含量纲字段；量纲变更必须走 set_usage/set_share）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "part_no": "PART-001",
 "veh_model": "MODEL-A",
 "platform": "P1",
 "usage": 2.0,
 "share": 100.0,
 "lc_stage": "成熟",
 "lc_shape": "传统",
 "sop": "2024-03",
 "eop": "2027-06",
 "status": "生效",
 "source": "BOM",
 "created_at": "2026-08-08 12:07:29",
 "updated_at": "2026-08-08 12:07:36",
 "created_by": "demo",
 "updated_by": "demo"
}
```
