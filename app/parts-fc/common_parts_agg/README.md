# common_parts_agg · Agent 操作指南

## 一、应用简介

通用件汇总修正——总量层去重修正，对抗"公地悲剧"。仅通用件经过，专用件自动分流跳过。

- **聚合根**：CommonPartsAgg
- **主键**：agg_no（AGG-YYYYMM-NNN）
- **数据库**：common_parts_agg.db（同名库，头行结构：d07_header + d07_detail）
- **跨应用调用**：出站调 demand_processing.get_approved、baseline_borrowing.get_derived_qty；入站被 bullwhip_correction.create 引用修正总量

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `parts-fc__common_parts_agg__create` | `part_no: str` 通用件号，`period: str` 期间（YYYY-MM） | 创建汇总单→待汇总，自动取锚参照 |
| `parts-fc__common_parts_agg__add_detail` | `agg_no: str` 汇总单号，`oem_code: str` 客户编码，`owner: str` 责任销售，`approved_qty: float` D04核定值，`evidence_qty: float` 证据加码量（默认0），`oral_qty: float` 口头加码量（默认0） | 添加客户份额明细，自动更新 sum_qty |
| `parts-fc__common_parts_agg__get` | `agg_no: str` 汇总单号 | 查看汇总单全貌（头+明细+锚对照） |
| `parts-fc__common_parts_agg__list` | `part_no: str` 零件号（可选），`period: str` 期间（可选），`status: str` 状态（可选） | 条件筛选汇总单列表 |
| `parts-fc__common_parts_agg__revise` | `agg_no: str` 汇总单号，`dedup_qty: float` 修正后总量，`dedup_reason: str` 折减逻辑+依据，`split_qty: str` 拆回分配JSON（可选） | 去重修正→已修正 |
| `parts-fc__common_parts_agg__confirm` | `agg_no: str` 汇总单号 | 确认修正→已确认（转D08） |

## 三、标准工作流

### 流程 A：通用件汇总修正完整流程

1. 总部计划调用 `create("STD-M6", "2026-09")` 创建汇总单
2. 对每个客户份额调用 `add_detail` 录入核定值、证据加码量、口头加码量
   - 证据加码量（evidence_qty）：有函件/合同/促销支持的部分，参与证据保护不折减
   - 口头加码量（oral_qty）：口头/无书面证据的部分，参与折减
3. 系统自动计算 sum_qty 并填充锚参照；明细全部录入后自动流转→"待修正"
4. 总部计划审阅锚对照，调用 `revise(agg_no, dedup_qty, dedup_reason, split_qty?)` 执行差异化折减
   - dedup_qty 必须 >= 承诺量合计（evidence_qty 之和）
   - dedup_reason 必须含锚对照结论+证据清单+折减系数来源
5. 确认修正：调用 `confirm(agg_no)` → 已确认，D08 可引用该修正总量

### 流程 B：专用件自动分流

- 系统/Agent 应在 create 前判断零件类型，专用件直接跳过本应用，无需创建汇总单
- 通用件则进入上述流程 A

## 四、前置条件与注意事项

- **BR-01**：仅通用件进入本应用，专用件自动分流跳过
- **BR-02**：通用件号×期间唯一，同一零件同一期间不可重复创建汇总单
- **BR-03**：折减必有依据（锚参照+证据清单），无锚不得折减——先完成 create+add_detail 确保锚参照填充
- **BR-04**：承诺量保护——evidence_qty 不参与折减，dedup_qty >= Σ evidence_qty
- **BR-05**：总量层修正不回退个体 D04 核定值，只调总量
- sum_qty 由系统自动计算（= Σ approved_qty），不可手动编辑
- 汇总单为创建时 D04 核定值快照，后续 D04 变更不回溯

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 应对策略 |
|---|---|---|
| "该通用件...在...期间已存在汇总单" | BR-02 唯一性冲突 | 调用 list 查询已有汇总单，如果需重新汇总则先处理已有单 |
| "仅待汇总状态可添加明细" | 汇总单已不在待汇总/待修正状态 | 调用 get 查看当前状态 |
| "折减必须有依据..." | 未填写 dedup_reason 或锚参照不完整 | 先确认 create 已完成锚参照取数，再填写完整的折减逻辑和数据依据 |
| "折减后总量...低于已确认承诺量合计..." | dedup_qty < Σ evidence_qty 违反 BR-04 | 将 dedup_qty 调至不低于各客户 evidence_qty 之和，或说明为何承诺量需调整 |
| "仅已修正状态可确认" | 尚未执行 revise 或状态不对 | 先执行 revise 去重修正，再确认 |
| "修正总量必须大于零" | dedup_qty <= 0 | 传入有效的正数修正总量 |
