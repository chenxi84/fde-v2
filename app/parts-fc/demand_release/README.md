# demand_release · Agent 操作指南

## 一、应用简介

毛需求发布单——加工链终点。消耗驱动量（D08终端口径）+ 独立事件加项（D06）的最终合成与冻结发布（R版），净需求/S&OP 唯一输入。

- **聚合根**：DemandRelease
- **主键**：rel_no（REL-YYYYMM-NNN）
- **发布版本**：rel_version（R+YYYYMM.x）
- **数据库**：demand_release.db（同名库，头行结构：d09_header + d09_detail）
- **跨应用调用**：出站调 demand_processing.get_approved、bullwhip_correction.get、common_parts_agg.get、independent_event.get_active_events（create_draft时）；调 demand_processing.lock、demand_collection.lock（publish时）

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `parts-fc__demand_release__create_draft` | `base_period: str` 锚定期间（YYYY-MM） | 生成发布草稿（自动汇总上游） |
| `parts-fc__demand_release__add_line` | `rel_no: str` 发布单号，`part_no: str` 零件号，`veh_model: str` 车型，`period: str` 期间，`cons_qty: float` 消耗驱动量，`event_items: list` 事件加项，`basis: str` 主要依据，`lineage: dict` 链路线索，`split_qty: dict` 拆回分配（可选） | 添加发布明细行 |
| `parts-fc__demand_release__get` | `rel_no: str` 发布单号 | 查看发布单全貌（含构成列示+链路线索） |
| `parts-fc__demand_release__list` | `status: str`（可选），`base_period: str`（可选） | 条件筛选发布单列表 |
| `parts-fc__demand_release__run_checklist` | `rel_no: str` 发布单号 | 执行发布前五项校验→通过则状态→待发布 |
| `parts-fc__demand_release__publish` | `rel_no: str` 发布单号 | 正式发布→R版冻结+联动锁定D04/D03 |
| `parts-fc__demand_release__revise` | `rel_no: str` 发布单号，`reason: str` 修订原因，`adjustments: str` 调整说明（可选） | 版本修订→旧版已替代，新版草稿 |
| `parts-fc__demand_release__get_version_diff` | `rel_no: str` 发布单号 | R_n vs R_{n-1} 版本差异比对 |

## 三、标准工作流

### 流程 A：毛需求发布完整流程

1. **生成草稿**：总部计划调用 `create_draft("2026-08")` 创建发布草稿
   - 系统自动汇总上游数据（D04核定值/D08终端口径/D07通用件总量/D06生效事件）
2. **填充明细**：对每个零件×期间调用 `add_line` 录入：
   - cons_qty = D08 final_qty（消耗驱动量）
   - event_items = [{event_no, qty}]（仅生效事件，**不含待确认/疑似事件**）
   - rel_qty 由系统强制计算 = cons_qty + Σevent_items.qty（**不可手动修改**）
   - lineage = {proc_batch, agg_no?, bw_no}（链路线索）
   - basis = 基线来源+修正/核对要点+客户对齐结论
3. **checklist 校验**：调用 `run_checklist(rel_no)` 执行五项校验
   - ① D04核定齐套 ② D08全结论 ③ D06事件齐备 ④ 客户对齐完成 ⑤ 版本差异完整
   - **五项全部通过** → status → "待发布"
   - 任一项 FAIL → 修复后重新 run_checklist
4. **正式发布**：调用 `publish(rel_no)` → status → "已发布"
   - 系统自动联动锁定 D04 加工批次 + D03 收集版本
   - R版永久保留，不可回退修改
5. **（如需修订）版本修订**：调用 `revise(rel_no, reason)` →
   - 旧版 → "已替代"（永久保留）
   - 新版 → "草稿"（重新走 checklist → publish 流程）

### 流程 B：版本差异比对

1. 调用 `get_version_diff(new_rel_no)` 获取逐零件×期间差异
2. 输出：旧值/新值/差异量/变更类型（新增/删除/变更）

## 四、前置条件与注意事项

- **BR-01**：唯一入口——净需求/S&OP 只消费已发布 R 版，草稿口径不得外流
- **BR-02**：构成加和强制——rel_qty = cons_qty + Σ event_items.qty，**系统强制计算，禁止手工修改**
- **BR-03**：疑似不发布——待确认/疑似事件不得进入 event_items，只计入 D06 生效事件
- **BR-06**：发布即冻结——R版发布后 D04/D03 一起锁定，不可回退，只能走 revise
- **BR-07**：版本永久保留——旧版标记"已替代"但数据不删除
- **BR-09**：checklist 五项全部通过方可发布，任何一项 FAIL 则状态保持"草稿"
- 客户对齐结论（basis 栏）为总部计划手工填写，系统只校验非空
- 首次发布无 prev_version 时第5项（版本差异）自动 PASS
- publish 操作不可逆，需确认后再执行

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 应对策略 |
|---|---|---|
| "锚定期间（base_period）必填" | 未传入 base_period | 索要锚定期间（如 2026-08） |
| "仅草稿状态可添加明细" | 发布单已不在草稿状态 | 调用 get 查看当前状态；如已发布则需 revise 生成新版本 |
| "零件号必填" / "期间必填" / "主要依据必填" | add_line 缺少必填字段 | 逐项索要：part_no、period、basis（基线来源+修正/核对要点+客户对齐结论） |
| "发布量不得为负" | cons_qty + event_items < 0 | 核对 cons_qty 和事件量的符号，调整后重试 |
| "仅草稿状态可执行 checklist" | 状态已变更 | 调用 get 查看状态；如已是"待发布"则直接 publish |
| "当前状态...须先通过 checklist 五项校验至'待发布'" | publish 前置条件不满足 | 先调用 run_checklist 完成五项校验 |
| "仅已发布版本可修订" | revise 要求状态="已发布" | 确认当前版本是否已发布；如是草稿则直接修改 |
| "修订原因不可为空" | revise 缺少 reason | 索要修订原因（如"断点ECN-A-119新增"或"OEM需求塌方"） |
| "无上一版本，无法比对差异" | 首次发布无 prev_version | 告知用户这是首个版本，无差异可比对 |
