# 独立事件登记（independent_event）

## 一、应用简介

独立事件登记表（D06）是叠加结构中"事件项"的唯一载体。毛需求 = 消耗驱动预测量 + 一次性水位脉冲 + 其他独立事件（断点等），框架确立"趋势归趋势、事件归事件"原则：预测引擎只对消耗建模外推，脉冲与断点属"事件驱动"的独立加项——当期计入、必须履约，但不进趋势外推。

**聚合根**：IndependentEvent
**主键**：event_no（格式 EVT-YYYYMMDDHHMMSS，时间戳）
**数据库**：independent_event.db（单表）

**表结构**：
- `indep_event`：独立事件主表（PK event_no）

**承载三类事件**：
- 水位脉冲：D03 拆解产出 → D06 登记 → 跟踪生命周期（待确认→生效→持续中→已回落→已关闭）
- 断点（ECN/零件切换）：成对登记（旧件截断+新件启动），共用 bp_batch 关联
- 其他一次性事件：人工登记+举证确认 → 计入当期毛需求

**系统常量（不可通过参数修改）**：
- `in_demand` 恒为 1（计入当期毛需求）
- `in_trend` 恒为 0（不进趋势外推）

**跨应用调用**：
- `create` 被 `demand_collection.decompose` 调用（脉冲确认后生成事件）
- `get_active_events` 被 `demand_release.create_draft` 调用（发布加项取数）
- `list` 被 `demand_processing.submit_adjustment` 调用（防重校验）

**水位脉冲状态机**：待确认 → 生效 → 持续中(水位未补足) / 已回落(水位达标) → 已关闭
**断点状态机**：登记 → 生效 → 已关闭
**其他事件状态机**：待确认 → 生效 → 已关闭

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `parts-fc__independent_event__create` | event_type: str, part_no: str, period: str, event_qty: float, source_basis: str, oem_code: str="", veh_model: str="", source_ref: str=None, bp_batch: str=None, bp_date: str=None | 新建独立事件。in_demand 恒=1，in_trend 恒=0。断点类必须通过 create_bp_pair。水位脉冲自动防重 |
| `parts-fc__independent_event__get` | event_no: str | 获取事件详情 |
| `parts-fc__independent_event__list` | part_no: str=None, event_type: str=None, status: str=None, period: str=None | 按条件筛选事件列表 |
| `parts-fc__independent_event__confirm` | event_no: str | 确认事件：待确认→生效。仅总部计划可操作 |
| `parts-fc__independent_event__mark_sustained` | event_no: str | 标记持续中：生效→持续中。水位未补足时使用，防止重复登记 |
| `parts-fc__independent_event__mark_subsided` | event_no: str, close_basis: str | 标记已回落：生效/持续中→已回落。close_basis 必填（水位达标证明） |
| `parts-fc__independent_event__close` | event_no: str, close_basis: str | 关闭事件。close_basis 必填。已关闭/已取消不可操作 |
| `parts-fc__independent_event__cancel` | event_no: str, close_basis: str | 取消事件（误判留痕）。仅待确认状态可取消。close_basis 记录复盘结论 |
| `parts-fc__independent_event__get_active_events` | part_no: str=None, period: str=None | 取生效事件清单。筛选 status=生效 AND in_demand=1。供 D09 发布加项取数 |
| `parts-fc__independent_event__create_bp_pair` | old_part_no: str, new_part_no: str, bp_date: str, old_qty: float, new_qty: float, oem_code: str, veh_model: str, period: str, source_basis: str="设变通知", source_ref: str=None | 成对登记断点——旧件截断+新件启动，共用 bp_batch。断点禁止单边登记 |

## 三、标准工作流

### 流程 1：水位脉冲全生命周期（系统生成 → 人工确认 → 跟踪 → 关闭）

1. **系统生成（D03 调用）**：D03 decompose 检测到脉冲后自动调用 `create(event_type="水位脉冲", ...)` 创建事件，status="待确认"。
2. **审查确认**：总部计划审查拆解结果，确认脉冲判定正确后调用 `confirm(event_no)` → status="生效"，事件量进入 D09 加项池。
3. **持续跟踪**：后续版本发现水位未补足时调用 `mark_sustained(event_no)` → status="持续中"，防止重复登记。
4. **回落标记**：水位达标后调用 `mark_subsided(event_no, close_basis)` → status="已回落"，close_basis 记录水位证明。**不得登记为新的负向脉冲**。
5. **归档关闭**：回落确认后调用 `close(event_no, close_basis)` → status="已关闭"，事件归档。

### 流程 2：断点事件全生命周期（成对登记 → 跟踪切换 → 关闭）

1. **成对登记**：收到设变通知后调用 `create_bp_pair(old_part_no, new_part_no, bp_date, old_qty, new_qty, ...)` 一次性创建两条事件，共用 bp_batch。返回 bp_batch + old_event + new_event。
2. **跟踪切换**：通过 `get(event_no)` 查看旧件/新件事件状态，跟踪切换进度。
3. **切换完成**：旧件尾量清零后调用 `close(old_event_no, close_basis)`，新件排产稳定后调用 `close(new_event_no, close_basis)`。

### 流程 3：误判取消

1. 总部计划判定待确认事件为误判（如外生证据否定脉冲），调用 `cancel(event_no, close_basis)` → status="已取消"，close_basis 记录复盘结论（如"θ_step 阈值偏敏感，建议上调"）。
2. 已生效事件不可取消，应走 `close` 流程。

### 流程 4：下游取数（D09 视角）

1. D09 create_draft 调用 `get_active_events(part_no, period)` 获取生效事件清单。
2. 仅 status="生效" AND in_demand=1 的事件被返回；待确认/已回落/已关闭/已取消均不出现在结果中。

## 四、前置条件与注意事项

1. **in_demand 恒 1、in_trend 恒 0**：系统常量，不可通过参数修改。这是叠加结构"趋势归趋势、事件归事件"的数据层落锁。
2. **断点必须成对登记**：event_type 含"断点"时，单条 create 会校验 bp_batch 非空（防止单边登记）。正确做法是使用 `create_bp_pair` 一次性创建。
3. **脉冲回落不等于新负脉冲**：水位达标后调用 `mark_subsided` 在原事件上标记，不得创建新的负向脉冲事件。
4. **脉冲持续中期间不重复登记**：create 水位脉冲时会做防重校验（同 part_no + period + 生效/持续中）。
5. **人工登记必须附依据**：source_basis 为"人工登记+说明"时，source_basis 本身即包含说明，若为空则拒绝。
6. **系统生成须计划确认**：source_basis 为"阶跃检测"/"发运-结算倒推"时，初始 status="待确认"，须经 confirm 后生效。
7. **close_basis 必填**：close、cancel、mark_subsided 操作的 close_basis 参数不可为空。
8. **事件量只计入归属期间**：event_qty 只计入其 period，不自动滚动、不进外推。
9. **create_bp_pair 在同一事务中**：旧件截断+新件启动两条记录同时写入。
10. **bp_batch 格式**：BP-YYYYMMDDHHMMSS（时间戳），断点对的两行共用同一 bp_batch。

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对策略 |
|----------|------|--------------|
| 零件号必填 | 缺必填字段 | 要求用户提供 part_no |
| 归属期间必填 | 缺必填字段 | 要求用户提供 period（YYYY-MM 格式） |
| 来源依据必填 | 缺必填字段 | 要求用户提供 source_basis（阶跃检测/发运-结算倒推/设变通知/人工登记+说明） |
| 来源依据只能为：... | source_basis 值不合法 | 告知用户合法的来源依据选项，让其选择 |
| 客户编码必填 | 缺必填字段 | 要求用户提供 oem_code |
| 车型编码必填 | 缺必填字段 | 要求用户提供 veh_model |
| 断点类事件必须通过 create_bp_pair 成对登记 | 单边创建被拦截 | 改用 create_bp_pair 一次性创建旧件截断+新件启动 |
| 零件 {part_no} 期间 {period} 已存在持续中的水位脉冲 | 脉冲防重 | 告知用户该零件+期间已有生效/持续中脉冲，无需重复登记。可先 get 查看现有事件 |
| 事件 {event_no} 不存在 | event_no 无效 | 先调 list 查询可用事件，让用户选择正确的 event_no |
| 仅待确认事件可确认 | 状态不允许 | 告知用户当前事件状态，只有"待确认"可以 confirm |
| 仅生效事件可标记持续中 | 状态不允许 | 告知用户只有"生效"状态的脉冲可标记持续中 |
| 仅生效/持续中事件可标记回落 | 状态不允许 | 告知用户只有"生效"或"持续中"可标记回落 |
| 回落依据必填 | 缺 close_basis | 要求用户提供回落依据（如"8月水位达标3.5天"） |
| 关闭依据必填 | 缺 close_basis | 要求用户提供关闭依据 |
| 事件已关闭，不可重复关闭 | 重复操作 | 告知用户事件已关闭 |
| 已取消事件不可关闭 | 状态不允许 | 告知用户已取消事件不可关闭，如需恢复请重新创建 |
| 取消原因必填 | 缺 close_basis | 要求用户提供取消原因（复盘结论） |
| 已关闭事件不可取消 | 状态不允许 | 告知用户已关闭事件不可取消 |
| 事件已取消 | 重复操作 | 告知用户该事件已被取消 |
| 新旧零件号均必填 | 缺必填字段 | 要求用户同时提供 old_part_no 和 new_part_no |
| 断点时点必填 | 缺必填字段 | 要求用户提供 bp_date（切换生效日，YYYY-MM-DD 格式） |
| 事件类型只能为：... | event_type 不合法 | 告知用户合法类型：水位脉冲/断点·旧件截断/断点·新件启动/其他 |
| 事件编号生成失败 | 系统异常 | 提示用户重试，如持续失败联系管理员 |
| 断点批次号生成失败 | 系统异常 | 提示用户重试，如持续失败联系管理员 |
