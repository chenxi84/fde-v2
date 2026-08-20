# bullwhip_correction 应用 · Agent 操作指南

## 一、应用简介
牛鞭修正处理表——发布前最后一道口径修正，派生需求锚定终端口径。聚合根 `BullwhipCorrection`，主键 `bw_no`（编码 BW-YYYYMM-HHMMSS），一行一零件一周期一 Tier。按 Tier 层级差异化处理：Tier1 直供（已拆解先行）容忍内自动维持；Tier2/3 超阈强制执行修正分析。系统自动计算放大系数 amp_factor = derived_qty / end_qty，与参数 θ_amp 比较判定修正必要性。跨应用调用：system_config（获取 θ_amp 阈值参数）。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `sales-forecast__bullwhip_correction__create` | part_no, period, tier, derived_qty, end_qty, end_source="结算" | 新建处理单；系统自动计算放大系数并判定 amp_verdict |
| `sales-forecast__bullwhip_correction__get` | bw_no | 获取处理单详情 |
| `sales-forecast__bullwhip_correction__list` | part_no="", period="", tier="", status="" | 按零件/周期/层级/状态筛选列表 |
| `sales-forecast__bullwhip_correction__set_correction` | bw_no, corr_action, final_qty | 执行修正（仅超阈·修正状态可用）；须登记所落机制与依据 |
| `sales-forecast__bullwhip_correction__maintain` | bw_no | 容忍内维持确认（状态→已确认） |
| `sales-forecast__bullwhip_correction__confirm` | bw_no | 已修正确认（状态→已确认，转入发布） |

## 三、标准工作流
1. **新建处理单**：`create(part_no, period, tier, derived_qty, end_qty)` → 系统自动计算 amp_factor，从 system_config 获取 θ_amp，判定 amp_verdict。
2. **Tier1 直供 + 容忍内**：自动维持，status=「维持」，final_qty=derived_qty，corr_action="维持——放大已由拆解先行完成"。
3. **容忍内**：status=「维持」，final_qty=derived_qty，等待 `maintain(bw_no)` 确认 → 「已确认」。
4. **超阈**：status=「待处理」，final_qty=end_qty（初始锚定终端），等待人工 `set_correction(bw_no, corr_action, final_qty)` → 「已修正」。
5. **转入发布**：已修正单调 `confirm(bw_no)` → 「已确认」，进入 D09 需求发布。

## 四、前置条件与注意事项
- `create` 时 `derived_qty` 和 `end_qty` 均为必填；`end_qty` 不能为 0（否则放大系数无意义）。
- **θ_amp 阈值**：从 `system_config.get_param("θ_amp")` 获取，默认 1.10。amp_factor <= θ_amp → "容忍内·维持"；amp_factor > θ_amp → "超阈·修正"。
- **Tier1 直供特殊逻辑**：当 tier="Tier1直供" 且 amp_factor <= θ_amp 时，自动维持并附带说明"放大已由拆解先行完成"。
- **修正必须有依据**：`set_correction` 的 corr_action 不可为空——"修正必须登记所落机制与依据，禁止无机制纯减数"。
- 仅 `amp_verdict == "超阈·修正"` 的处理单可调用 `set_correction`。
- `maintain` 仅对 status="维持" 的单有效；`confirm` 仅对 status="已修正" 的单有效。
- θ_amp 获取失败时降级使用默认值 1.10，不阻断流程。

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步 |
|---|---|---|
| 派生需求量和终端需求量均为必填 | derived_qty 或 end_qty 未传 | 从上游 D07/D04 获取对应数据后重试 |
| 终端需求量不能为0 | end_qty=0 | 确认终端需求数据来源是否正确 |
| 牛鞭处理单 {bw_no} 不存在 | 单号错误或已删除 | 用 list 按条件查找正确单号 |
| 仅超阈处理单可执行修正 | amp_verdict 非"超阈·修正" | 容忍内走 maintain 流程；或确认数据是否需要重新判定 |
| 修正必须登记所落机制与依据，禁止无机制纯减数 | corr_action 为空 | 要求用户提供修正机制与依据（如"锚定终端结算量，按客户函件折减 X%"） |
| 当前状态 {status}，不可维持 | 非「维持」状态 | get 确认当前状态：已确认无需操作，已修正走 confirm |
| 当前状态 {status}，不可确认 | 非「已修正」状态 | get 确认当前状态：维持走 maintain，待处理需先 set_correction |
