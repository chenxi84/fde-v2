# forecast 模块契约速查（自动生成 · 视图生成参照）

> 字段以此文件与 `app/forecast/<应用>/<应用>.py` 源码为准；list 示例取自库中现有数据（无数据项以源码为准；造数级样例经平台⑧契约冻结任务生成）。


## attainment

### 服务契约
```
compute(oem_code*, period*)
    — 按月+客户计算达成率与置信系数
compute_batch(fcst_version*)
    — 批量计算（月度闭环触发）：对全部客户计算最新期间的达成率
get(oem_code*, period*)
get_conf_factor(oem_code*, period*)
    — 取置信系数（供加工表使用），默认 1.0
list(oem_code=None:string, period=None:string, horizon=None:string, page=None:integer, page_size=None:integer)
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）


## demand_release

### 服务契约
```
add_onetime_item(rel_no*, part_no*, period*, onetime_adj*, reason*)
    — 月中附加一次性调整
apply_part_adj(rel_no*, part_no*, period*, adj_qty*, func_type*, basis*)
    — 应用零件级处理量到发布单明细行
create_draft(prc_batch*)
    — 从已锁定加工批次创建发布草稿：汇总→初步毛需求
get(rel_no*)
    — 取单头+全部明细
get_diff(rel_no*)
    — R_n vs R_n−1 差异视图
get_line(rel_no*, line_no*)
list(fcst_version=None:string, part_no=None:string, period=None:string, status=None:string, page=None:integer, page_size=None:integer)
publish(rel_no*)
    — 发布：状态→已发布；联动锁定快照V版与月度版本
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "rel_no": "REL-202608-001",
 "fcst_version": "202608",
 "base_period": "202608",
 "prev_rel_no": "",
 "publisher": "demo",
 "published_at": "2026-08-12 00:14:28",
 "status": "已发布"
}
```


## forecast_baseline

### 服务契约
```
confirm(base_batch*, oem_code*, plant_code*, part_no*, period*)
    — 计划确认单行
confirm_batch(base_batch*)
    — 计划确认整批
generate(base_batch*, fcst_version*)
    — 按月生成基线行集：从快照行集展开，基于历史结算量计算基线值
get(base_batch*, oem_code*, plant_code*, part_no*, period*)
get_batch_status(base_batch*)
list(base_batch=None:string, oem_code=None:string, plant_code=None:string, part_no=None:string, period=None:string, status=None:string, base_path=None:string, page=None:integer, page_size=None:integer)
update_method(base_batch*, oem_code*, plant_code*, part_no*, period*, base_method*)
    — 调整方法/参数（须登记依据）
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "base_batch": "B202608",
 "oem_code": "OEM-A",
 "plant_code": "PLT-A1",
 "part_no": "8210001",
 "period": "2026-09",
 "fcst_version": "202608",
 "project_no": "PRJ-001",
 "veh_model": "",
 "base_qty": 956.99,
 "base_path": "时序外推",
 "base_method": "指数平滑 α=0.3（近12期）",
 "cross_chk": "",
 "generator": "demo",
 "status": "已确认"
}
```


## forecast_processing

### 服务契约
```
add_onetime_line(prc_batch*, oem_code*, plant_code*, part_no*, period*, onetime_adj*, onetime_reason*, onetime_tag=None:string)
    — 月中附加一次性行（当期行，基线值为空）
create_batch(base_batch*, fcst_version*)
    — 创建加工批次并自动生成明细行（从基线行集展开）
fill_line(prc_batch*, oem_code*, plant_code*, part_no*, period*, conf_adj=None:number, conf_reason=None:string, trend_adj=None:number, trend_reason=None:string, onetime_adj=None:number, onetime_reason=None:string, onetime_tag=None:string)
    — 填写调整
finalize(prc_batch*)
    — 全部核定→锁定。前置：全部行通过方可锁定
get(prc_batch*)
    — 取单头+全部明细
get_line(prc_batch*, oem_code*, plant_code*, part_no*, period*)
list_batches(fcst_version=None:string, status=None:string, page=None:integer, page_size=None:integer)
list_lines(prc_batch*, oem_code=None:string, plant_code=None:string, part_no=None:string, period=None:string, chk_result=None:string, page=None:integer, page_size=None:integer)
review_line(prc_batch*, oem_code*, plant_code*, part_no*, period*, chk_result*, chk_comment=None:string)
    — 核定/退回单行
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）


## forecast_snapshot

### 服务契约
```
fill(fcst_version*, oem_code*, plant_code*, part_no*, period*, orig_qty*, data_flag=None:string, source_channel=None:string)
    — 填/更新预测量（orig_qty 首次录入后即冻结）
get(fcst_version*, oem_code*, plant_code*, part_no*, period*)
get_version_status(fcst_version*)
    — 取版本状态：行数/未提供行数/接收渠道分布
list(fcst_version=None:string, oem_code=None:string, plant_code=None:string, part_no=None:string, period=None:string, data_flag=None:string, page=None:integer, page_size=None:integer)
lock_version(fcst_version*)
    — R版发布联动锁定——将快照行标记为已锁定（通过版本状态体现）
open_version(fcst_version*)
    — 月度 opening：按活跃零件集自动生成 N+1~N+3 三行（均标记"未提供"）
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "fcst_version": "202608",
 "oem_code": "OEM-A",
 "plant_code": "PLT-A1",
 "part_no": "8210001",
 "period": "2026-09",
 "offset": "M+1",
 "project_no": "PRJ-001",
 "veh_model": "",
 "orig_qty": 1150.0,
 "data_flag": "正常",
 "source_channel": "销售转录",
 "recv_date": "2026-08-12",
 "collector": "demo"
}
```


## md_customer

### 服务契约
```
create(oem_code*, oem_name*, plant_code*, plant_name*, settle_mode*)
get(oem_code*, plant_code*)
import_batch(rows*)
list(oem_code=None:string, plant_code=None:string, settle_mode=None:string, page=None:integer, page_size=None:integer)
update(oem_code*, plant_code*, oem_name=None:string, plant_name=None:string, settle_mode=None:string)
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "oem_code": "OEM-A",
 "plant_code": "PLT-A1",
 "oem_name": "主机厂A",
 "plant_name": "一工厂",
 "settle_mode": "寄售"
}
```


## md_fcst_version

### 服务契约
```
create(fcst_version*, base_period*, periods*, opening_date=None:string)
get(fcst_version*)
get_active()
    — 取当前活跃版本
list(page=None:integer, page_size=None:integer)
set_linked(fcst_version*, rel_no=None:string)
    — R版发布联动锁定
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "fcst_version": "202608",
 "base_period": "2026-08",
 "periods": [
  "2026-09",
  "2026-10",
  "2026-11"
 ],
 "opening_date": "2026-08-01",
 "status": "锁定",
 "linked_batch": "REL-202608-001"
}
```


## md_material

### 服务契约
```
create(part_no*, part_name*, uom=None:string, mat_type=None:string)
get(part_no*)
import_batch(rows*)
list(part_no=None:string, part_name=None:string, mat_type=None:string, page=None:integer, page_size=None:integer)
update(part_no*, part_name=None:string, uom=None:string, mat_type=None:string)
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "part_no": "8210001",
 "part_name": "前保险杠总成",
 "uom": "件",
 "mat_type": "成品"
}
```


## md_part_replace

### 服务契约
```
create(rel_no*, rel_type*, old_part*, new_part*, switch_date=None:string, ecn_no=None:string)
disable(rel_no*)
get(rel_no*)
list(rel_type=None:string, old_part=None:string, new_part=None:string, status=None:string, page=None:integer, page_size=None:integer)
update(rel_no*, rel_type=None:string, old_part=None:string, new_part=None:string, switch_date=None:string, ecn_no=None:string, status=None:string)
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "rel_no": "ECN-A-118",
 "rel_type": "替换",
 "old_part": "8210001",
 "new_part": "8210001-B",
 "switch_date": "",
 "ecn_no": "ECN-A-118",
 "status": "生效"
}
```


## md_project

### 服务契约
```
create(project_no*, project_name*, stage*, oem_code*, plant_code*, veh_model=None:string, platform=None:string, sop=None:string, eop=None:string, owner=None:string)
get(project_no*)
list(project_no=None:string, stage=None:string, oem_code=None:string, plant_code=None:string, page=None:integer, page_size=None:integer)
list_active()
    — 取进行中项目——活跃行集定义来源，供快照 opening 用
update(project_no*, project_name=None:string, stage=None:string, veh_model=None:string, platform=None:string, sop=None:string, eop=None:string, owner=None:string)
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "project_no": "PRJ-001",
 "project_name": "车型A项目",
 "stage": "进行中",
 "oem_code": "OEM-A",
 "plant_code": "PLT-A1",
 "veh_model": "",
 "platform": "",
 "sop": "",
 "eop": "",
 "owner": ""
}
```


## md_project_part

### 服务契约
```
create(project_no*, part_no*, veh_model=None:string, usage=None:number, share=None:number, eff_from=None:string, eff_to=None:string)
get(project_no*, part_no*)
list(project_no=None:string, part_no=None:string, veh_model=None:string, page=None:integer, page_size=None:integer)
list_active()
    — 取进行中项目的全部零件映射（供快照 opening 用）
list_by_part(part_no*)
    — 按零件查所有项目映射（通用件识别：同 part_no 出现在 ≥2 个不同客户的项目中）
update(project_no*, part_no*, veh_model=None:string, usage=None:number, share=None:number, eff_from=None:string, eff_to=None:string)
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "project_no": "PRJ-001",
 "part_no": "8210001",
 "veh_model": "",
 "usage": 1.0,
 "share": 1.0,
 "eff_from": "",
 "eff_to": ""
}
```


## part_level_adj

### 服务契约
```
create_breakpoint_adj(fcst_version*, period*, old_part*, new_part*, old_adj*, new_adj*, ecn_no*)
    — 断点成对调整：旧件截断负量 + 新件启动正量
create_generic_merge(fcst_version*, period*, part_no*, adj_qty*, basis*)
    — 通用件合并调整
create_replace_merge(fcst_version*, period*, part_no*, adj_qty*, basis*)
    — 替换件合并调整
get(adj_no*)
list(fcst_version=None:string, func_type=None:string, part_no=None:string, period=None:string, page=None:integer, page_size=None:integer)
summarize(fcst_version*)
    — 汇总：按物料×期间聚合全部 delta
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "adj_no": "PAD-202608-001",
 "func_type": "通用件合并",
 "part_no": "STD-M6",
 "fcst_version": "202608",
 "period": "2026-09",
 "adj_qty": -1600.0,
 "basis": "口头加码按历史系数0.65折减",
 "pair_no": "",
 "owner": "demo",
 "created_at": "2026-08-12 00:14:28"
}
```
