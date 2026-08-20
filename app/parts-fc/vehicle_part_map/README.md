# 车型—零件映射（vehicle_part_map）

## 一、应用简介

车型—零件映射是 parts-fc 组的主数据底座应用之一。以 **part_no + veh_model（联合业务键）** 标识一条映射记录，是车型级数据到零件级的桥接，单车用量（usage）与供应份额（share）的权威源。

- **聚合根**：VehiclePartMap
- **数据存储**：`vehicle_part_map.db`（平台自动管理），含主表 `veh_part_map` 与子表 `usage_history`
- **跨应用调用**：无发出（纯主数据，被 D03/D04/D05/D08/D10 引用）。`get_active_mapping` 是最重要的跨应用调用入口
- **状态机**：生效 -> 停用（停用不可逆）
- **量纲历史版本**：每次 set_usage/set_share 自动将旧值写入 `usage_history`（生效起止期间/旧值/变更依据），保证"当时的口径"可回溯
- **单一权威原则**：单价用量与供应份额以本表为准，project_ledger 仅引用展示

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `parts-fc__vehicle_part_map__create` | `part_no: str`(必填), `veh_model: str`(必填), `usage: float`(默认0), `share: float`(默认0), `lc_stage: str`(必填), `lc_shape: str`(默认"传统"), `sop: str`(必填), `source: str`(必填), `platform: str`(可选), `eop: str`(可选), `status: str`(默认"生效") | 新建零件-车型映射行 |
| `parts-fc__vehicle_part_map__get` | `part_no: str`(必填), `veh_model: str`(必填) | 取映射详情（含量纲历史版本列表 `usage_history`） |
| `parts-fc__vehicle_part_map__list` | `part_no: str`(可选), `veh_model: str`(可选), `lc_stage: str`(可选), `status: str`(可选), `page: int`(可选), `page_size: int`(可选) | 按条件筛选映射列表，支持分页 |
| `parts-fc__vehicle_part_map__update` | `part_no: str`(必填), `veh_model: str`(必填), `**kwargs`(可选字段: platform/lc_stage/lc_shape/sop/eop/status/source) | 更新映射一般属性（不含 usage/share） |
| `parts-fc__vehicle_part_map__set_usage` | `part_no: str`(必填), `veh_model: str`(必填), `new_usage: float`(必填), `effective_date: str`(必填), `basis: str`(必填) | 变更单车用量，旧值写入 usage_history 后更新主表 |
| `parts-fc__vehicle_part_map__set_share` | `part_no: str`(必填), `veh_model: str`(必填), `new_share: float`(必填), `effective_date: str`(必填), `basis: str`(必填) | 变更供应份额，旧值写入 usage_history 后更新主表 |
| `parts-fc__vehicle_part_map__get_usage_history` | `part_no: str`(必填), `veh_model: str`(必填) | 单独查询量纲历史版本列表 |
| `parts-fc__vehicle_part_map__disable` | `part_no: str`(必填), `veh_model: str`(必填), `reason: str`(必填) | 停用映射（status 改为"停用"），停用原因必填 |
| `parts-fc__vehicle_part_map__get_active_mapping` | `part_no: str`(必填) | 取零件当前生效（status=生效）的车型映射列表，供跨应用调用 |

## 三、标准工作流

### 3.1 新建映射与量纲登记

1. **新建映射**：调用 `create`，传入 part_no、veh_model 及完整量纲/生命周期属性 → 映射行写入 `veh_part_map`，status 默认"生效"
2. **查询详情**：调用 `get` 按 part_no + veh_model 获取映射全貌，含 usage_history 历史版本
3. **筛选列表**：调用 `list` 按零件号/车型/状态/生命周期阶段等条件遍历

### 3.2 量纲变更（用量/份额）

1. 调用 `set_usage` 或 `set_share`
2. 系统自动：关闭旧历史版本的 effective_to -> 将旧值写入 usage_history -> 更新主表为新值
3. basis（变更依据）必填，应附设变通知号或商务函件号

### 3.3 映射停用

1. 调用 `disable`，传入 reason（必填，如"设变替代"、"EOP"）
2. status 更新为"停用"，之后 `get_active_mapping` 不再返回该行

### 3.4 下游消费（跨应用）

- `get_active_mapping(part_no)` 是最重要的跨应用入口，被以下应用调用：
  - demand_collection（D03）：量纲校验
  - demand_processing（D04）：因果路径量纲转换
  - baseline_borrowing（D05）：生命周期形态/相似车型选源
  - bullwhip_correction（D08）：外部映射终端需求取数
  - strategy_fitting（D10）：需求形态分类输入

## 四、前置条件与注意事项

1. **引用完整性**：part_no 必须在物料主数据中存在；veh_model 必须在车型主数据中存在（弱引用，不硬阻断）
2. **lc_stage 枚举**：仅限 爬坡 / 成熟 / 衰退 / EOP临近
3. **lc_shape 枚举**：仅限 传统 / 上市高后下滑。标注"上市高后下滑"驱动基线使用衰减模型
4. **status 枚举**：仅限 生效 / 停用。新建默认为"生效"，停用不可逆
5. **source 枚举**：仅限 BOM / 设变通知 / 商务确认
6. **usage >= 0**：单车用量必须 >= 0（值为 0 为占位映射，量纲尚未确定）
7. **share 0~100**：供应份额百分比，0 表示退出供应，100 表示独家供应
8. **sop < eop**：SOP 日期必须早于 EOP 日期
9. **usage/share 不可直接 update**：量纲变更必须走 set_usage/set_share 专用方法，直接 update 会被拦截
10. **量纲变更 basis 必填**：每次变更须附设变通知号或商务函件号
11. **usage_history 只追加不可删除**：历史版本永久保留，支持 FVA 复盘与基线校准

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 应对策略 |
|---------------|------|----------------|
| 零件号和车型必填 | part_no 或 veh_model 为空 | 从上游单据/用户输入中补齐 part_no 和 veh_model 后再试 |
| 零件 {X} 车型 {Y} 映射已存在 | 联合主键冲突 | 告知用户该映射已存在；先调用 `get` 确认，如需变更量纲则调用 `set_usage`/`set_share` |
| 生命周期阶段必填 | lc_stage 缺失 | 向用户索要生命周期阶段（爬坡/成熟/衰退/EOP临近） |
| SOP必填 | sop 缺失 | 向用户索要 SOP 日期 |
| 映射依据必填（BOM/设变通知/商务确认） | source 缺失 | 向用户索要映射依据来源 |
| 映射依据只能为：BOM/设变通知/商务确认 | source 不在枚举范围 | 告知用户合法取值，请其修正 |
| 单车用量必须 >= 0 | usage 为负数 | 请用户提供 >=0 的值 |
| 供应份额必须在 0~100 之间 | share 超出范围 | 请用户提供 0~100 之间的百分比 |
| SOP 必须早于 EOP | 日期约束违反 | 告知用户 SOP 必须早于 EOP，请其调整 |
| 生命周期阶段只能为：爬坡/成熟/衰退/EOP临近 | lc_stage 不在枚举范围 | 告知用户合法取值，请其修正 |
| 生命周期形态只能为：传统/上市高后下滑 | lc_shape 不在枚举范围 | 告知用户合法取值（传统/上市高后下滑），或留空 |
| 状态只能为：生效/停用 | status 不在枚举范围 | 告知用户合法取值（生效/停用），或使用默认值 |
| usage 变更必须通过 set_usage 方法生成历史版本，不可直接覆盖 | 在 update 中传了 usage | 改用 `set_usage` 方法，提供 effective_date 和 basis |
| share 变更必须通过 set_share 方法生成历史版本，不可直接覆盖 | 在 update 中传了 share | 改用 `set_share` 方法，提供 effective_date 和 basis |
| 量纲变更依据必填（设变通知/商务函件号） | set_usage/set_share 未传 basis | 向用户索要变更依据（设变通知号/商务函件号） |
| 份额变更依据必填（设变通知/商务函件号） | set_share 未传 basis | 向用户索要份额变更依据 |
| 零件 {X} 车型 {Y} 映射不存在 | 查询/操作的目标记录不存在 | 先调用 `list` 确认正确的 part_no + veh_model，或先调用 `create` 新建 |
| 停用原因必填 | disable 未传 reason | 向用户索要停用原因（如"设变替代"、"EOP"等） |
| 该映射已处于停用状态，不可重复停用 | 重复停用 | 告知用户该映射已停用，无需重复操作 |
| 分页参数非法 | page/page_size 非有效整数 | 使用默认分页（page=1, page_size=50），或请用户提供合法数字 |
