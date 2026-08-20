# 主机厂原始需求收集（demand_collection）

## 一、应用简介

主机厂原始需求收集表（D03）是毛需求加工链的入口应用。OEM（主机厂）每期向零部件供应商发布滚动预测，本应用提供统一的收集入口，支持版本化收集与信号拆解（滤噪声/剥脉冲/留真实消耗）。

**聚合根**：DemandCollection
**主键**：collect_no（格式 COL-YYYYMMDDHHMMSS，时间戳）
**数据库**：demand_collection.db（三层结构）

**三层表结构**：
- `d03_header`：收集单头（PK collect_no）
- `d03_detail`：收集明细（PK collect_no + line_no），纵表存储零件x期间需求量
- `d03_snapshot`：拆解快照（PK collect_no + line_no + period），1:1 对明细行

**跨应用调用**：
- `decompose` 调用 `independent_event.create` 生成水位脉冲事件
- `lock` 被 `demand_release.publish` 调用（D09 发布联动锁定）
- `get_true_qty` 被 `demand_processing.generate_baseline` 调用（基线取数）

**状态机**：草稿 → 已拆解 → 已锁定 / 已作废

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `parts-fc__demand_collection__create` | oem_code: str, plant_code: str, fcst_version: str, base_period: str, demand_type: str="月度滚动预测", source_channel: str="", recv_date: str="", remark: str="" | 新建收集单头。客户+工厂+版本唯一，collect_no 自动生成，prev_version 自动带出 |
| `parts-fc__demand_collection__add_lines` | collect_no: str, lines: list | 批量录入明细行。lines 每项含 {part_no, project_no, veh_model, period, orig_qty, proj_stage?, uom?, data_flag?, is_consignment?}。仅草稿状态可录入 |
| `parts-fc__demand_collection__get` | collect_no: str | 获取收集单全貌（单头+明细+拆解快照） |
| `parts-fc__demand_collection__list` | oem_code: str=None, fcst_version: str=None, status: str=None | 按条件筛选收集单列表（仅单头摘要） |
| `parts-fc__demand_collection__decompose` | collect_no: str, decompositions: list | 批量信号拆解。decompositions 每项含 {line_no, period, noise_adj, pulse_qty, method, basis}。非寄售件自动免拆解。has_pulse 时自动调用 independent_event.create |
| `parts-fc__demand_collection__confirm_decompose` | collect_no: str | 拆解确认与版本冻结。校验恒等式（true_qty = orig_qty - pulse_qty - noise_adj）与噪声守恒（Σnoise_adj≈0）。状态→已拆解 |
| `parts-fc__demand_collection__lock` | collect_no: str | 锁定版本（由 D09 发布联动触发）。仅已拆解状态可锁定。状态→已锁定 |
| `parts-fc__demand_collection__cancel` | collect_no: str, reason: str | 作废收集单。须填写原因，仅草稿状态可作废。状态→已作废 |
| `parts-fc__demand_collection__get_version_diff` | collect_no: str | 版本比对：V_n vs V_{n-1} 逐零件x期间差异。prev_version 为空时返回"首版，无对比基线" |
| `parts-fc__demand_collection__get_true_qty` | collect_no: str, part_no: str=None, period: str=None | 取真实消耗量。仅已拆解/已锁定状态可返回，草稿状态拒绝。供 D04 基线取数 |

## 三、标准工作流

### 流程 1：月度滚动预测收集全流程

1. **创建收集单**：调用 `create(oem_code, plant_code, fcst_version, base_period, ...)` 创建收集单头，获得 `collect_no`。检查返回的 collect_no，确认状态为"草稿"。
2. **录入明细**：调用 `add_lines(collect_no, lines)` 批量录入 OEM 原始需求量。OEM 未提供的期间设置 `data_flag="OEM未提供"`，非寄售件设置 `is_consignment=0`。
3. **查看确认**：调用 `get(collect_no)` 查看收集单全貌，确认明细正确。
4. **执行拆解**：调用 `decompose(collect_no, decompositions)` 批量执行信号拆解。对寄售件传入 noise_adj/pulse_qty，非寄售件自动免拆解。检查返回的 results 中 has_pulse 行是否成功生成事件号。
5. **拆解确认**：调用 `confirm_decompose(collect_no)` 确认并冻结版本。如校验不通过（恒等式/守恒），根据错误信息修正 decompositions 后重试步骤 4。
6. **等待锁定**：版本已拆解后，等待 D09 发布联动调用 `lock` 锁定。

### 流程 2：版本比对

1. 调用 `get_version_diff(collect_no)` 获取当前版本与上一版本的逐期差异。
2. 若返回"首版，无对比基线"，说明当前为首期收集，无历史可对比。

### 流程 3：下游取数（D04 视角）

1. 调用 `get_true_qty(collect_no, part_no, period)` 取已拆解/已锁定版本的 true_qty 用于基线生成。
2. 草稿状态的收集单调用此方法会被拒绝，需等待拆解确认完成。

## 四、前置条件与注意事项

1. **客户+工厂+版本唯一**：同一客户+工厂+版本只能有一份收集单，重复创建会报错。
2. **orig_qty 不可变**：录入后不可直接修改，任何改动只能创建新版本。
3. **仅草稿状态可编辑**：add_lines、decompose、cancel 均要求 status="草稿"。
4. **OEM 未提供需显式标记**：设置 data_flag="OEM未提供"，禁止隐式补 0。
5. **非寄售件免拆解**：is_consignment=0 的零件，decompose 自动设置 true_qty=orig_qty，noise_adj=0，pulse_qty=0。
6. **噪声守恒**：拆解窗口内所有期间的 Σnoise_adj 必须约等于 0（容忍 ±0.1），违反则 confirm_decompose 不通过。
7. **恒等式强制**：true_qty = orig_qty - pulse_qty - noise_adj，系统强制校验。
8. **lock 仅限已拆解**：草稿/已作废状态不可锁定。
9. **cancel 仅限草稿**：已拆解/已锁定须走版本替代流程。
10. **跨应用依赖**：decompose 中 has_pulse 时会调用 independent_event.create，事件创建失败不阻断拆解（静默跳过）。
11. **通用件不汇总**：通用件按客户分别收集，汇总去重是 common_parts_agg 的职责。

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对策略 |
|----------|------|--------------|
| 客户 {oem_code} 工厂 {plant_code} 版本 {fcst_version} 已存在收集单 | 重复创建 | 告知用户该组合已有收集单，提供已有 collect_no 供用户确认是否需要复用或作废重建 |
| 收集单 {collect_no} 不存在 | collect_no 无效 | 先用 list 查询可用的收集单列表，让用户选择正确的 collect_no |
| 仅草稿状态可录入明细 | 状态不允许 | 告知用户当前收集单状态（非草稿），如需修改请创建新版本 |
| 仅草稿状态可执行拆解 | 状态不允许 | 告知用户拆解仅限草稿状态，已拆解/已锁定不可重新拆解 |
| 仅草稿状态可确认拆解 | 状态不允许 | 告知用户当前状态不可确认，检查是否已确认过 |
| 明细行 {collect_no}/{line_no} 不存在 | line_no 无效 | 先调 get 查看明细列表，确认正确的 line_no |
| 无明细数据，无法确认拆解 | 明细为空 | 先调用 add_lines 录入至少一行明细 |
| 明细行 {line_no} 期间 {period} 缺少拆解快照 | 未完成拆解 | 先调用 decompose 对该行执行拆解，再确认 |
| 行{line_no}期间{period}拆解恒等式不成立 | 数值不一致 | 检查 noise_adj/pulse_qty 设置，确保 true_qty = orig_qty - pulse_qty - noise_adj |
| 噪声调整跨期总额不守恒 | Σnoise_adj 不为 0 | 调整各期 noise_adj 使总和归零（平滑只改形状、不改总量） |
| 当前状态 {status} 不可锁定 | 锁定前置条件不满足 | 仅已拆解可锁定，告知用户先完成拆解确认 |
| 当前状态 {status} 不可作废 | 作废前置条件不满足 | 仅草稿可作废，已拆解/已锁定须走版本替代 |
| 作废必须填写原因 | 缺必填字段 | 要求用户提供作废原因（如"OEM撤回预测"） |
| 收集单尚未完成拆解确认，true_qty 不可用 | 下游取数时机不对 | 告知下游等待拆解确认完成后再取数，或改用 orig_qty 做参考 |
