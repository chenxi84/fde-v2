# nasa_pms 模块契约速查（自动生成 · 视图生成参照）

> 字段以此文件与 `app/nasa_pms/<应用>/<应用>.py` 源码为准；list 示例取自库中现有数据（无数据项以源码为准；造数级样例经平台⑧契约冻结任务生成）。


## activity

### 服务契约
```
add_milestone(name*, wbs_no*, predecessors=None:string, owner=None:string, phase=None:string, note=None:string)
    — 建里程碑（工期恒 0 的便捷入口 —— 里程碑是**事件**不是工作，§5.5.7.1）。
baseline(act_nos*, project_start=None:string, calendar_no=None:string)
    — 建立进度基线：把**派生日期**冻进 `baseline_start` / `baseline_finish`。
change(act_no*, change_no*, note=None:string)
    — 对已基线的活动发起修订：挂上**已批准**的变更号（跨应用只读校验 `change_request.get`）。
check_network()
    — 网络体检：返回**图论与格式可判**的问题 + 两类跨应用问题（挂靠非叶子 / 叶子无活动）。
create(name*, wbs_no*, duration_days=1:integer, kind='activity':string, predecessors=None:string, owner=None:string, phase=None:string, note=None:string)
    — 建一个活动（或汇总活动）。编号系统生成；`wbs_no` 必须是 **WBS 的叶子元素**。
create_calendar(name*, unit='days':string, holidays=None:string, is_default=False:boolean)
    — 建一个工作日历。`unit` 是**项目级口径**：`days`（工作日，跳过周末与假日）/ `edays`（日历天）。
critical_path(project_start=None:string, calendar_no=None:string)
    — 只取关键路径（浮时为 0 的活动，按最早开始排序）。
get(act_no*)
    — 按编号查活动（带回 `pred_list` 结构化逻辑链与当前日历口径）；未命中返回 None。
get_calendar(cal_no*)
    — 按编号取日历；未命中返回 None。
link(act_no*, predecessor_no*, rel_type='FS':string, lag_days=0:integer, reason=None:string)
    — 给活动加一条前置关系（默认 **完成→开始（FS）、无滞后**）。
list(status=None:string, kind=None:string, wbs_no=None:string, owner=None:string, baselined=None:string, keyword=None:string, page=None:integer, size=None:integer)
    — 按状态 / 类型 / 挂靠元素 / 责任方 / 是否已基线 / 关键词筛选，**分页返回 `{items,total}`**。
list_calendars()
    — 全部日历（默认的排前面）。
record_progress(act_no*, percent_complete=None:integer, actual_start=None:string, actual_finish=None:string, note=None:string)
    — 回填实绩：实际开始 / 完成 / 完成百分比。
schedule_view(project_start=None:string, calendar_no=None:string)
    — **派生排程**：按四种关系 + 滞后正推最早日期、逆推最晚日期、算浮时、标关键路径。
unlink(act_no*, predecessor_no*)
    — 断掉一条前置。已基线的活动同样要走变更流程（BR-07）。
update(act_no*, name=None:string, duration_days=None:integer, predecessors=None:string, wbs_no=None:string, owner=None:string, note=None:string, change_no=None:string)
    — 改**计划字段**（名称 / 工期 / 逻辑链 / 挂靠元素 / 责任方 / 备注）。
update_calendar(cal_no*, name=None:string, unit=None:string, holidays=None:string, add_holiday=None:string, remove_holiday=None:string, is_default=None:boolean)
    — 改日历（名称 / 工期口径 / 假日表）。`add_holiday` / `remove_holiday` 是单条增删的便捷入口。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "act_no": "ACT-001",
 "name": "星务软件开工",
 "kind": "milestone",
 "phase": "start",
 "wbs_no": "400000.01.01.01",
 "duration_days": 0,
 "predecessors": null,
 "owner": "星务分系统",
 "status": "completed",
 "percent_complete": 100,
 "actual_start": "2026-10-05",
 "actual_finish": "2026-10-05",
 "baseline_start": "2026-10-05",
 "baseline_finish": "2026-10-05",
 "change_no": null,
 "note": "",
 "pred_list": []
}
```


## change_request

### 服务契约
```
analyze(cr_no*, impact_analysis*)
    — 登记影响分析：`submitted → analyzing`（提交 → 影响分析）。
approve(cr_no*, comment*, approver=None:string)
    — 批准：`reviewing → approved`（审批中 → 已批准）。
create(title*, requester*, ci_nos=None:string, req_nos=None:string, description=None:string, project_no=None:string)
    — 提交一条变更请求（落库为 `submitted`「已提交」）。
get(cr_no*)
    — 按变更请求编号查询；未命中返回 None，不抛异常。
implement(cr_no*, note=None:string)
    — 实施：`approved → implemented`（已批准 → 已实施，**终态**）。
list(status=None:string, requester=None:string, ci_no=None:string, req_no=None:string, page=None:integer, size=None:integer)
    — 按状态 / 申请方 / 影响的配置项 / 影响的需求筛选，**分页返回 `{items, total}`**，
reject(cr_no*, comment*, approver=None:string)
    — 拒绝：`reviewing → rejected`（审批中 → 已拒绝，**终态**）。
submit_review(cr_no*)
    — 提交审批：`analyzing → reviewing`（影响分析 → 审批中）。
update(cr_no*, title=None:string, requester=None:string, ci_nos=None:string, req_nos=None:string, description=None:string)
    — 修改变更请求内容（标题 / 申请方 / 影响范围 / 变更说明）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "cr_no": "CR-001",
 "title": "星务软件时序调整（BR-01 影响范围必填）",
 "requester": "星务分系统",
 "ci_nos": [
  "CI-001"
 ],
 "req_nos": [
  "REQ-010"
 ],
 "description": "成像任务编排时序与数传窗口冲突，需调整软件时序",
 "impact_analysis": "影响 CI-001（星务软件）与 REQ-010；需重跑集成测试 A 组",
 "decision_note": "影响面清楚，同意实施",
 "approver": "CCB 主任",
 "implement_note": "星务软件 v1 已按该变更发版",
 "status": "implemented",
 "project_no": ""
}
```


## configuration_item

### 服务契约
```
archive(ci_no*, reason=None:string)
    — 归档：已发布 → 已归档（`released → archived`，状态机终态）。
assign_baseline(ci_no*, baseline*, baseline_ver=None:string)
    — 把配置项纳入某条基线（材料 §6.5.1.2.2 的四条基线之一）。
bump_version(ci_no*, new_version*, change_no*)
    — 版本变更：把当前版本升到 `new_version`，状态回落为「受控」。
control(ci_no*, owner=None:string)
    — 提交受控：草稿 → 受控（`draft → controlled`）。
create(name*, ci_type*, owner=None:string, project_no=None:string)
    — 新建一个配置项，落库为草稿状态，初始版本恒为 v1（新配置项从第一版开始）。
get(ci_no*)
    — 按配置项编号查询；未命中返回 None，不抛异常。
list(ci_type=None:string, status=None:string, baseline=None:string, page=None:integer, size=None:integer)
    — 按类型 / 状态 / 所属基线筛选，**分页返回 `{items, total}`**，默认按编号升序。
release(ci_no*, change_no=None:string)
    — 发版：受控 → 已发布（`controlled → released`），把当前版本冻结为已发布版本。
update(ci_no*, name=None:string, ci_type=None:string, owner=None:string, change_no=None:string)
    — 修改配置项内容（名称 / 类型 / 责任人）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "ci_no": "CI-001",
 "name": "星务软件 v1",
 "ci_type": "software",
 "version": 1,
 "released_ver": 1,
 "baseline": "product",
 "baseline_ver": "B1",
 "status": "released",
 "owner": "星务分系统"
}
```


## decision

### 服务契约
```
add_criterion(dec_no*, criterion*, weight=1:string)
    — 往评价准则清单里加一条准则（提出 / 权衡中都可加，已决策后冻结，BR-06）。
add_option(dec_no*, name*, description=None:string)
    — 往备选方案清单里加一个方案（提出 / 权衡中都可加，已决策后冻结，BR-06）。
conclude(dec_no*, chosen_seq*, rationale=None:string, risk_note=None:string, dissent=None:string)
    — 作决策：权衡中 → 已决策（`weighing → decided`）。
create(topic*, eval_method='weighted_matrix':string, measure_no=None:string, issue=None:string, owner=None:string, project_no=None:string)
    — 新建一个决策议题，落库为「提出」状态，编号自动生成（`DC-001` 起）。
get(dec_no*)
    — 按决策编号查询（含评价准则 `criteria` 与备选方案 `options`）；未命中返回 None，不抛异常。
implement(dec_no*, note=None:string)
    — 实施：已决策 → 已实施（`decided → implemented`，**硬终态**）。
list(eval_method=None:string, status=None:string, owner=None:string, page=None:integer, size=None:integer)
    — 按评价方法 / 状态 / 责任人筛选，**分页返回 `{items, total}`**，默认按编号升序。
score_option(dec_no*, seq*, score*, note=None:string)
    — 给一个备选方案打评价得分（仅「权衡中」；`score` 为 0~100 的整数，BR-08）。
start(dec_no*)
    — 开始权衡：提出 → 权衡中（`proposed → weighing`）。
update(dec_no*, topic=None:string, eval_method=None:string, measure_no=None:string, issue=None:string, owner=None:string, project_no=None:string)
    — 修改决策的议题性内容（议题 / 议题说明 / 评价方法 / 来源度量 / 责任人 / 所属项目）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "dec_no": "DC-001",
 "topic": "星上存储方案选型",
 "issue": "存储器件交期与容量冲突，需在两条路线中选一条",
 "measure_no": "TPM-001",
 "eval_method": "weighted_matrix",
 "status": "implemented",
 "chosen_seq": 1,
 "chosen_name": "方案A：进口大容量存储",
 "rationale": "容量余量优先，交期风险可控",
 "risk_note": "需并行落实进口器件替代预案",
 "dissent": "物资部倾向方案B",
 "implement_note": "已按方案A下单",
 "owner": "星务分系统",
 "project_no": "",
 "criterion_total": 2,
 "option_total": 2,
 "scored_total": 2,
 "top_seq": 1,
 "top_score": 90
}
```


## interface

### 服务契约
```
create(if_name*, if_type*, provider*, consumer*, icd_content=None:string, ci_no=None:string, owner=None:string, project_no=None:string)
    — 定义一条接口，落库为「定义中」状态，编号自动生成（`IF-001` 起）；**此时尚无版本**。
freeze(if_no*, note=None:string)
    — 冻结接口：已发布 → 已冻结（`released → frozen`，硬终态）。
get(if_no*)
    — 按接口编号查询（含版本变更通知记录 `changes`）；未命中返回 None，不抛异常。
list(if_type=None:string, status=None:string, provider=None:string, consumer=None:string, ci_no=None:string, page=None:integer, size=None:integer)
    — 按类型 / 状态 / 提供方 / 使用方 / 关联配置项筛选，**分页返回 `{items, total}`**，
list_changes(if_no=None:string, party=None:string, action=None:string, page=None:integer, size=None:integer)
    — **跨接口的版本变更通知台账**（查询视图 —— 卡片 9 只有「通知记录并入本聚合」，
release(if_no*)
    — 发布接口 —— **首次发布**：定义中 → 已发布（`defined → released`），定版为 `A`；
revise(if_no*, new_version*, reason*, icd_content=None:string)
    — 发起版本变更：已发布 → 变更中（`released → changing`），改版本号并**通知两端**。
update(if_no*, if_name=None:string, if_type=None:string, provider=None:string, consumer=None:string, icd_content=None:string, ci_no=None:string, owner=None:string, project_no=None:string)
    — 修改接口的描述性内容（名称 / 类型 / 责任人 / 所属项目 / 关联配置项…）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "if_no": "IF-001",
 "if_name": "相机—星务数据接口",
 "if_type": "icd",
 "provider": "相机分系统",
 "consumer": "星务分系统",
 "icd_content": "LVDS 差分；帧周期 20 ms；遥测字段 32 项",
 "version": "A",
 "status": "released",
 "ci_no": "CI-006",
 "freeze_note": null,
 "owner": "载荷分系统",
 "project_no": "",
 "change_total": 2
}
```


## requirement

### 服务契约
```
baseline(req_nos*, baseline_ver*)
    — 把一批需求冻结为一个基线版本 —— **全或无**：任一条不满足 BR-01 则整批拒绝。
create(title*, statement*, req_type*, verify_method*, source_req_no=None:string, owner=None:string, project_no=None:string)
    — 新建一条需求，落库为草稿状态。
derive(source_req_no*, title*, statement*, verify_method*, owner=None:string)
    — 从上游需求派生一条新需求（派生的便捷入口，等价于 create 且类型为 derived）。
get(req_no*)
    — 按需求编号查询；未命中返回 None，不抛异常。
list(req_type=None:string, status=None:string, source_req_no=None:string, page=None:integer, size=None:integer)
    — 按类型 / 状态 / 上游需求筛选，**分页返回 `{items, total}`**，默认按编号升序。
obsolete(req_no*, reason=None:string)
    — 作废一条需求（状态机允许任意状态转 obsolete）。
submit_review(req_no*)
    — 把草稿提交评审：`draft` → `pending_review`（2026-09-25 补）。
update(req_no*, title=None:string, statement=None:string, verify_method=None:string, owner=None:string, change_no=None:string)
    — 修改需求内容。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "req_no": "REQ-001",
 "title": "重访周期不超过 3 天",
 "statement": "在轨观测阶段，对同一目标区的重访间隔不超过 72 小时。",
 "req_type": "system",
 "verify_method": "analysis",
 "source_req_no": "",
 "status": "baselined",
 "owner": "总体设计部",
 "project_no": "",
 "baseline_ver": "B1",
 "change_no": null,
 "void_reason": null
}
```


## review

### 服务契约
```
add_item(review_no*, item*, criterion=None:string)
    — 往评审项清单里加一条评审项（计划 / 进行中都可加，已结论后冻结，BR-06）。
close(review_no*, note=None:string)
    — 关闭评审：已结论 / 行动项跟踪中 → 已关闭（`→ closed`，硬终态）。
close_action(review_no*, seq*, note=None:string)
    — 完成一条行动项：未完成 → 已完成（`open → done`）。
conclude(review_no*, conclusion*, minutes=None:string, actions=None:string)
    — 出结论：进行中 → 已结论 / 行动项跟踪中（`in_progress → concluded | tracking`）。
create(title*, review_type*, phase*, subject*, plan_no=None:string, owner=None:string, project_no=None:string)
    — 新建一次评审，落库为「计划」状态，编号自动生成（`RV-001` 起）。
get(review_no*)
    — 按评审编号查询（含评审项清单 `items` 与行动项清单 `actions`）；未命中返回 None，不抛异常。
list(review_type=None:string, phase=None:string, status=None:string, conclusion=None:string, plan_no=None:string, page=None:integer, size=None:integer)
    — 按类型 / 阶段 / 状态 / 结论 / 依据计划筛选，**分页返回 `{items, total}`**，默认按编号升序。
list_actions(review_no=None:string, owner=None:string, status=None:string, page=None:integer, size=None:integer)
    — **跨评审的行动项汇总**（卡片「并入说明」明确它是**查询视图**，不是独立聚合）。
start(review_no*)
    — 启动评审：计划 → 进行中（`planned → in_progress`）。
update(review_no*, title=None:string, review_type=None:string, phase=None:string, subject=None:string, plan_no=None:string, owner=None:string)
    — 修改评审的描述性内容（标题 / 类型 / 阶段 / 评审对象 / 依据计划 / 责任人）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "review_no": "RV-001",
 "title": "系统需求评审（SRR）",
 "review_type": "srr",
 "phase": "a",
 "subject": "系统需求与验证方法完备性",
 "plan_no": "PLAN-001",
 "status": "closed",
 "conclusion": "pass",
 "minutes": "需求基线 B1 通过评审，无遗留问题",
 "close_note": "无行动项，直接关闭",
 "owner": "系统工程师",
 "project_no": "",
 "action_total": 0,
 "action_open": 0
}
```


## risk

### 服务契约
```
assess(risk_no*, likelihood*, consequence*)
    — 重评风险等级：写入可能性 / 后果，等级**由二者推导**，状态推进到「分析中」。
close(risk_no*, disposition*, note=None:string)
    — 关闭风险：必须给出**处置结论**（缓解完成 / 转移 / 接受），结论与终态同事务落库。
create(title*, statement*, category*, likelihood=None:integer, consequence=None:integer, req_no=None:string, owner=None:string, project_no=None:string)
    — 识别一条风险，落库为「识别」状态。
get(risk_no*)
    — 按风险编号查询；未命中返回 None，不抛异常。
list(category=None:string, status=None:string, risk_level=None:string, req_no=None:string, page=None:integer, size=None:integer)
    — 按类别 / 状态 / 等级 / 受影响需求筛选，**分页返回 `{items, total}`**，默认按编号升序。
mitigate(risk_no*, mitigation*)
    — 登记缓解措施，状态推进到「缓解中」。
update(risk_no*, title=None:string, statement=None:string, category=None:string, req_no=None:string, owner=None:string)
    — 修改风险描述性内容。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "risk_no": "RSK-001",
 "title": "长周期器件交期不确定",
 "statement": "星上存储器件交期可能推迟 8 周",
 "category": "schedule",
 "likelihood": null,
 "consequence": null,
 "risk_score": null,
 "risk_level": null,
 "mitigation": null,
 "req_no": "",
 "owner": "物资部",
 "status": "identified",
 "disposition": null,
 "close_note": null,
 "project_no": ""
}
```


## stakeholder

### 服务契约
```
add_expectation(sh_no*, statement*, kind*, source*, moe=None:string, committed=None:string, note=None:string)
    — 登记一条期望（期望并入本聚合，无独立标识 —— 卡片 I-1）。
get(sh_no*)
    — 按相关方编号查询（含期望清单 `expectations`）；未命中返回 None，不抛异常。
list(sh_type=None:string, keyword=None:string, project_no=None:string, page=None:integer, size=None:integer)
    — 按类型 / 关键字 / 所属项目筛选，**分页返回 `{items, total}`**，默认按编号升序。
update_expectation(sh_no*, seq*, statement=None:string, kind=None:string, source=None:string, moe=None:string, committed=None:string, note=None:string)
    — 维护一条期望（改陈述 / 类别 / 来源 / 度量口径 / 承诺 / 备注）。
upsert(sh_no*, name*, sh_type*, duty=None:string, org=None:string, contact=None:string, project_no=None:string)
    — **外部同步落库**：`sh_no` 已存在则更新，不存在则新增（幂等）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "sh_no": "SH-001",
 "name": "国家遥感中心",
 "sh_type": "customer",
 "duty": "提观测需求与验收",
 "org": "自然资源部",
 "contact": null,
 "project_no": null,
 "expectation_total": 2,
 "committed_total": 1
}
```


## tech_plan

### 服务契约
```
approve(plan_no*, approver*, note=None:string)
    — 批准：审批中 → 已批准（`in_review → approved`）。**I-1 的「生效唯一」面落在这里。**
coverage(phase=None:string, plan_type=None:string, page=None:integer, size=None:integer)
    — **阶段 × 计划类型的覆盖矩阵**（查询视图，不是独立聚合）—— 卡片 I-1「每个阶段至少
create(name*, plan_type*, phase*, maturity=None:string, scope=None:string, owner=None:string, project_no=None:string)
    — 建一份技术计划，落库为「草稿」状态、版本 `V1`，编号自动生成（`PLAN-001` 起）。
get(plan_no*)
    — 按计划编号查询（含版本台账 `versions`）；未命中返回 None，不抛异常。
list(plan_type=None:string, phase=None:string, status=None:string, owner=None:string, page=None:integer, size=None:integer)
    — 按计划类型 / 覆盖阶段 / 状态 / 责任人筛选，**分页返回 `{items, total}`**，默认按编号升序。
revise(plan_no*, summary*, phase=None:string, maturity=None:string)
    — 修订（阶段推进的唯一入口）：已批准 → 已修订（`approved → revised`），**版本递增**。
submit(plan_no*)
    — 提交审批：草稿 / 已修订 → 审批中（`draft|revised → in_review`）。
update(plan_no*, name=None:string, plan_type=None:string, phase=None:string, maturity=None:string, scope=None:string, owner=None:string, project_no=None:string)
    — 修改计划的内容（名称 / 类型 / 覆盖阶段 / 成熟度 / 范围 / 责任人 / 所属项目）。
withdraw(plan_no*, reason=None:string)
    — 撤回审批：审批中 → 回到**提交前的状态**（`in_review → draft | revised`）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "plan_no": "PLAN-001",
 "name": "系统工程管理计划（SEMP）",
 "plan_type": "semp",
 "phase": "a",
 "maturity": "baseline",
 "version": 1,
 "status": "approved",
 "scope": "全寿命周期技术管理活动与职责分工",
 "revise_note": null,
 "owner": "系统工程师",
 "project_no": "",
 "version_total": 1,
 "latest_approved_ver": 1,
 "latest_approver": "技术副总师"
}
```


## technical_measure

### 服务契约
```
baseline(tpm_no*, baseline_ver=None:string)
    — 基线化：定义 → 度量中（`defined → measuring`）。
close(tpm_no*, note=None:string)
    — 关闭度量：度量中 / 已纠正 → 已关闭（`→ closed`，硬终态）。
correct(tpm_no*, corrective_action*)
    — 纠正：超阈值 → 已纠正（`exceeded → corrected`）。
create(name*, category*, direction*, target_value*, threshold_value*, unit=None:string, req_no=None:string, owner=None:string, project_no=None:string)
    — 定义一条技术度量（TPM/MOP/KPP），落库为「定义」状态，编号自动生成（`TPM-001` 起）。
get(tpm_no*)
    — 按度量编号查询（含实测值序列 `readings` 与告警台账 `alerts`）；未命中返回 None，不抛异常。
list(category=None:string, status=None:string, direction=None:string, req_no=None:string, page=None:integer, size=None:integer)
    — 按类别 / 状态 / 优化方向 / 关联需求筛选，**分页返回 `{items, total}`**，默认按编号升序。
list_alerts(tpm_no=None:string, status=None:string, category=None:string, page=None:integer, size=None:integer)
    — **跨度量的告警汇总**（查询视图，不是独立聚合）。
rebaseline(tpm_no*, target_value*, threshold_value*, change_no*, direction=None:string)
    — 重设基线：改写判定口径（目标值 / 阈值 / 优化方向）的**唯一**入口（卡片 I-2 / BR-02）。
record(tpm_no*, period*, measured_value*, note=None:string)
    — 记一期实测值：度量中 / 已纠正 → 度量中（在阈内）或 超阈值（出阈）。
update(tpm_no*, name=None:string, category=None:string, unit=None:string, req_no=None:string, owner=None:string, direction=None:string, target_value=None:string, threshold_value=None:string)
    — 修改度量的描述性内容（名称 / 类别 / 计量单位 / 关联需求 / 责任人）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "tpm_no": "TPM-001",
 "name": "数传误码率",
 "category": "tpm",
 "direction": "lower",
 "unit": "—",
 "target_value": 1e-07,
 "threshold_value": 1e-06,
 "baseline_ver": "B1",
 "change_no": null,
 "current_value": 8.5e-07,
 "current_period": "2026-Q1",
 "req_no": "REQ-004",
 "owner": "测控分系统",
 "status": "measuring",
 "close_note": null,
 "project_no": "",
 "reading_total": 1,
 "alert_total": 0,
 "alert_open": 0
}
```


## verification

### 服务契约
```
close(ver_no*, note=None:string)
    — 关闭验证项：**已判定**（通过 / 不通过）→ 关闭（终态）。
create(req_no*, method*, phase*, criteria=None:string, owner=None:string, project_no=None:string)
    — 规划一条验证项（验证矩阵的一行），落库为「规划」状态。
get(ver_no*)
    — 按验证项编号查询；未命中返回 None，不抛异常。
list(req_no=None:string, method=None:string, status=None:string, phase=None:string, page=None:integer, size=None:integer)
    — 按对应需求 / 验证方法 / 状态 / 验证阶段筛选，**分页返回 `{items, total}`**，默认按编号升序。
record_result(ver_no*, result*, evidence*, follow_up=None:string)
    — 记录判定结果：执行中 → 通过 / 不通过。
start(ver_no*, owner=None:string)
    — 开始执行：规划 → 执行中（`planned → executing`）。
update(ver_no*, method=None:string, phase=None:string, criteria=None:string, owner=None:string)
    — 修改验证项的规划信息（验证方法 / 验证阶段 / 成功判据 / 责任人）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "ver_no": "VER-001",
 "req_no": "REQ-001",
 "method": "analysis",
 "phase": "system_functional",
 "status": "closed",
 "result": "pass",
 "evidence": "TR-001 轨道仿真报告",
 "follow_up": "",
 "close_note": "结论一致，关闭",
 "criteria": "轨道仿真连续 30 天，任两次过顶间隔 ≤ 72 h",
 "owner": "总体设计部",
 "project_no": ""
}
```


## wbs

### 服务契约
```
add_child(parent_no*, title*, kind='product':string, description=None:string, scope_ref=None:string, owner=None:string, req_nos=None:string)
    — 在父元素下**按规则自动分配子号**并建立子元素（`parent.01` / `parent.02`…）。
baseline(wbs_no*)
    — 纳入基线（`draft → baselined`）或**落实变更**（`in_change → baselined`，版次 +1）。
change(wbs_no*, change_no*, note=None:string)
    — 对已基线的元素发起修订（`baselined → in_change`）。
close(wbs_no*, note=None:string)
    — 关闭元素（`baselined → closed`，终态）。
coverage()
    — 需求覆盖对账：返回**两侧缺口**（材料 §3.3.3 的交叉引用矩阵）。
create(wbs_no*, title*, kind='product':string, parent_no=None:string, description=None:string, scope_ref=None:string, owner=None:string, req_nos=None:string)
    — 建立一个元素（顶层或指定父元素）。落库为草稿状态，版次 0。
get(wbs_no*)
    — 按元素编号查询字典条目（全字段）；未命中返回 None，不抛异常。
list(status=None:string, kind=None:string, parent_no=None:string, owner=None:string, keyword=None:string, page=None:integer, size=None:integer)
    — 按状态 / 类型 / 父元素 / 责任方 / 关键词筛选，**分页返回 `{items, total}`**，默认按编号升序。
tree(root=None:string)
    — 返回嵌套树（`children` 递归）；`root` 为空时返回全部顶层。
update(wbs_no*, title=None:string, description=None:string, scope_ref=None:string, spec_no=None:string, spec_title=None:string, charge_code=None:string, owner=None:string, req_nos=None:string, change_no=None:string)
    — 修改字典字段（**编号不在可改字段里** —— BR-07）。
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "wbs_no": "400000",
 "title": "遥感卫星系统",
 "parent_no": null,
 "level": 1,
 "kind": "product",
 "description": "EO-3 遥感卫星，按产品分解",
 "scope_ref": "SOW §3 整星范围",
 "spec_no": null,
 "spec_title": null,
 "charge_code": null,
 "owner": "总体设计部",
 "req_nos": null,
 "rev_no": 0,
 "rev_authorization": null,
 "change_no": null,
 "status": "baselined",
 "close_note": null
}
```
