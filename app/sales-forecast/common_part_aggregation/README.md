# common_part_aggregation 应用 · Agent 操作指南

## 一、应用简介
通用件汇总修正表——总量层去重修正，对抗公地悲剧。聚合根 `CommonPartAggregation`，主键 `agg_no`（编码 AGG-YYYYMM-HHMMSS），仅通用件经过此环节。各客户独立预测同一通用件时存在重复计算，本应用汇总各 OEM 客户核定值 → 去重折减修正 → 拆回客户维度。跨应用调用：demand_processing（获取 D04 客户核定值）。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `sales-forecast__common_part_aggregation__create` | part_no, period | 新建汇总单，创建 d07_header，返回 agg_no |
| `sales-forecast__common_part_aggregation__add_detail` | agg_no, oem_code, owner_sales, approved_qty, evidence_qty=0, verbal_qty=0 | 添加客户份额明细（含承诺量/口头量），自动更新合计 |
| `sales-forecast__common_part_aggregation__get` | agg_no | 获取汇总单全貌（header + 所有 details） |
| `sales-forecast__common_part_aggregation__list` | part_no="", period="", status="" | 按零件/周期/状态筛选列表 |
| `sales-forecast__common_part_aggregation__set_dedup` | agg_no, dedup_qty, dedup_reason, anchor_ref | 去重修正：差异化折减，低于承诺量保护拒绝 |
| `sales-forecast__common_part_aggregation__set_split` | agg_no, split_detail | 拆回分配：修正总量落回各客户维度 |
| `sales-forecast__common_part_aggregation__confirm` | agg_no | 确认转 D08（状态→已确认） |

## 三、标准工作流
1. **新建汇总单**：`create(part_no, period)` → 状态「待汇总」。
2. **拉取客户核定值**：从 demand_processing 获取各 OEM 客户的 D04 核定值，逐客户调用 `add_detail` 填入 approved_qty/evidence_qty/verbal_qty。
3. **去重修正**：`set_dedup(agg_no, dedup_qty, dedup_reason, anchor_ref)` → 计算折减比例，状态→「已修正」。承诺量保护：修正总量不得低于 evidence_qty 合计。
4. **拆回分配**：`set_split(agg_no, split_detail)` → 将修正结果分配回各 OEM 客户维度。
5. **确认转入牛鞭**：`confirm(agg_no)` → 状态「已确认」，进入 D08 牛鞭修正环节。

## 四、前置条件与注意事项
- 本应用**仅通用件**经过，专用件跳过此环节直接进入牛鞭修正。
- `add_detail` 仅在「待汇总」状态可调用；已执行去重修正后不可再添加明细。
- **承诺量保护**：`set_dedup` 的修正总量不得低于所有明细的 evidence_qty 合计（"汇总函件加码部分，确保不低于承诺量"），否则抛错。
- **折减必须有依据**：dedup_reason 不可为空——"无锚、无证据清单不得拍脑袋折减"。
- `set_split` 仅在「已修正」状态可调用；`confirm` 仅在「已修正」状态可调用。
- anchor_ref 可记录锚定参考（如 OEM 预测版本/平台层级对比），为可选参数。
- approved_qty 为客户核定值，evidence_qty 为有证据支撑量，verbal_qty 为口头沟通量，三者共同构成汇总基础。

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步 |
|---|---|---|
| 汇总单 {agg_no} 不存在 | 单号错误或已删除 | 用 list 按条件查找正确单号 |
| 仅待汇总状态可添加明细 | 已进入后续环节 | get 确认当前状态：已修正需新建汇总单 |
| 仅待汇总状态可修正 | 已修正或已确认 | 如需重新修正，新建汇总单 |
| 仅已修正状态可拆回分配 | 未执行去重修正 | 先调 set_dedup 完成修正 |
| 仅已修正状态可确认 | 未执行去重修正 | 先调 set_dedup 完成修正 |
| 折减必须有依据（无锚、无证据清单不得拍脑袋折减） | dedup_reason 为空 | 向用户索要去重依据（如 anchor_ref/OEM 重叠分析） |
| 修正总量 {dedup_qty} 低于已承诺量 {total_evidence}，违反承诺量保护 | 折减过度 | 提高 dedup_qty 至不低于 evidence_qty 合计，或与客户重新确认承诺量 |
