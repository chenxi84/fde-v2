# 项目信息台账（project_ledger）

## 一、应用简介

项目信息台账是 parts-fc 组的主数据底座应用之一。以 **project_no + part_no（联合业务键）** 标识一条台账记录，记录项目x零件的六维属性（客户、产品、车型/平台、量纲口径、生命周期节点、项目责任人）。

- **聚合根**：ProjectLedger
- **数据存储**：`project_ledger.db`（平台自动管理），含主表 `prj_ledger` 与子表 `prj_change_log`
- **跨应用调用**：无发出（纯主数据，被其他应用引用）。usage/share 字段为引用展示，权威源在 vehicle_part_map
- **阶段状态机**：待定点 -> 定点中 -> 进行中 -> EOP关闭（各阶段可因商务变化回退，须附原因）
- **变更日志**：每次 update/set_stage 自动写入 `prj_change_log`，记录字段/前值/后值/原因/日期/操作人，不可删除

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `parts-fc__project_ledger__create` | `project_no: str`(必填), `part_no: str`(必填), `stage: str`(默认"待定点"), `oem_code: str`(必填), `plant_code: str`(必填), `veh_model: str`(必填), `part_kind: str`(默认"专用"), `sop: str`(必填), `owner: str`(必填), `award_prob: float`(可选), `platform: str`(可选), `usage: float`(默认0), `share: float`(默认0), `eop: str`(可选), `lc_shape: str`(可选) | 新建项目-零件台账行，自动登记首条变更日志（"创建"） |
| `parts-fc__project_ledger__get` | `project_no: str`(必填), `part_no: str`(必填) | 取项目详情（含完整变更日志列表 `change_log`） |
| `parts-fc__project_ledger__list` | `stage: str`(可选), `oem_code: str`(可选), `owner: str`(可选), `part_kind: str`(可选), `veh_model: str`(可选), `page: int`(可选), `page_size: int`(可选) | 按条件筛选项目列表，支持分页 |
| `parts-fc__project_ledger__update` | `project_no: str`(必填), `part_no: str`(必填), `**kwargs`(可选字段: stage/award_prob/oem_code/plant_code/veh_model/platform/part_kind/usage/share/sop/eop/lc_shape/owner) | 更新项目属性，仅变更字段生成变更日志 |
| `parts-fc__project_ledger__set_stage` | `project_no: str`(必填), `part_no: str`(必填), `new_stage: str`(必填), `reason: str`(必填) | 阶段迁移，须附原因，变更日志自动登记 |
| `parts-fc__project_ledger__get_active_projects` | `oem_code: str`(可选) | 取进行中（stage=进行中）项目清单，供 D03 录入校验 |
| `parts-fc__project_ledger__get_change_log` | `project_no: str`(必填), `part_no: str`(必填) | 单独取变更日志列表 |

## 三、标准工作流

### 3.1 新建与维护台账

1. **新建**：调用 `create`，传入完整六维属性 → 台账行写入 `prj_ledger`，stage 初始为"待定点"，首条变更日志自动登记
2. **查询**：调用 `get` 按 project_no + part_no 获取详情及变更历史
3. **筛选**：调用 `list` 按阶段/客户/责任人等条件遍历台账
4. **属性更新**：调用 `update` 修改属性字段 → 系统自动比对变更字段，仅变更字段写入 `prj_change_log`

### 3.2 阶段迁移

1. 调用 `set_stage`，传入 project_no、part_no、new_stage、reason（必填）
2. 系统校验状态机合法性后更新 stage，变更日志登记 `stage/旧阶段/新阶段/reason/日期`

### 3.3 下游消费

- `get_active_projects` 供 demand_collection.create 在 D03 录入时校验项目是否处于可录入状态

## 四、前置条件与注意事项

1. **引用完整性**：oem_code/plant_code 必须在客户主数据中存在；part_no 必须在物料主数据中存在；veh_model 必须在车型主数据中存在（弱引用，不硬阻断但应确保引用有效）
2. **stage 枚举**：仅限 待定点 / 定点中 / 进行中 / EOP关闭
3. **part_kind 枚举**：仅限 专用 / 通用。通用件应关联 >=2 客户或标记单一客户通用
4. **lc_shape 枚举**：仅限 传统 / 上市高后下滑，或为空
5. **award_prob 范围**：0~100，仅在 stage=待定点 或 定点中 时有业务意义
6. **sop < eop**：SOP 日期必须早于 EOP 日期
7. **usage/share 不可直接修改**：本表仅引用展示，权威源在 vehicle_part_map。量纲变更须通过 vehicle_part_map.set_usage/set_share 同步
8. **变更日志只追加不可删除**：prj_change_log 永久保留，支持审计回溯
9. **维护分工**：销售维护客户/阶段/责任人维度，计划维护产品/生命周期维度（业务约定，技术上不做硬阻断）

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 应对策略 |
|---------------|------|----------------|
| 项目号和零件号必填 | project_no 或 part_no 为空 | 从上游单据/用户输入中补齐 project_no 和 part_no 后再试 |
| 项目号与零件号组合已存在，不可重复登记 | 联合主键冲突 | 告知用户该组合已存在；建议先调用 `get` 确认，如需更新则调用 `update` |
| 客户编码必填 | oem_code 缺失 | 向用户索要客户编码（oem_code） |
| 工厂编码必填 | plant_code 缺失 | 向用户索要工厂编码（plant_code） |
| 车型必填 | veh_model 缺失 | 向用户索要车型（veh_model） |
| SOP必填 | sop 缺失 | 向用户索要 SOP 日期 |
| 责任销售必填 | owner 缺失 | 向用户索要责任销售人员 |
| 定点概率取值范围为 0~100 | award_prob 非法 | 要求用户提供 0~100 之间的百分比值 |
| 阶段只能为：待定点/定点中/进行中/EOP关闭 | stage 不在枚举范围 | 告知用户合法取值，请其修正 |
| 零件类别只能为：专用/通用 | part_kind 不在枚举范围 | 告知用户合法取值（专用/通用），请其修正 |
| 生命周期形态只能为：传统/上市高后下滑 | lc_shape 不在枚举范围 | 告知用户合法取值（传统/上市高后下滑），或留空 |
| SOP 必须早于 EOP | 日期约束违反 | 告知用户 SOP 必须早于 EOP，请其调整日期 |
| 项目 {X} 零件 {Y} 不存在 | 查询/更新目标记录不存在 | 先调用 `list` 确认正确的 project_no + part_no，或先调用 `create` 新建 |
| 阶段迁移原因必填 | set_stage 未传 reason | 向用户索要阶段迁移原因（如"客户确认立项"、"产品生命周期结束"等） |
| 阶段 {X} 不可迁移至 {Y} | 状态机约束违反 | 告知用户当前阶段和目标阶段，解释可允许的目标阶段列表 |
| 分页参数非法 | page/page_size 非有效整数 | 使用默认分页（page=1, page_size=50），或请用户提供合法数字 |
