# bullwhip_correction · Agent 操作指南

## 一、应用简介

牛鞭修正处理——发布前最后一道口径修正。下游派生需求 vs 终端消耗口径对比修正，锚定终端需求。

- **聚合根**：BullwhipCorrection
- **主键**：bw_no（BW-YYYYMM-NNN）
- **数据库**：bullwhip_correction.db（同名库，单表）
- **分层治理**：Tier1直供→简化确认；Tier2/3→强制修正分析
- **跨应用调用**：出站调 demand_processing.get_approved、common_parts_agg.get、vehicle_part_map.get_active_mapping；入站被 demand_release.create_draft 引用 final_qty

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `parts-fc__bullwhip_correction__create` | `part_no: str` 零件号，`period: str` 期间，`tier: str` Tier1直供/Tier2/Tier3，`derived_qty: float` 派生需求，`end_qty: float` 终端需求，`end_source: str` 终端来源（默认"结算"） | 创建处理单→自动计算amp_factor与判定 |
| `parts-fc__bullwhip_correction__get` | `bw_no: str` 处理单号 | 查看处理单详情（派生/终端/放大系数/修正动作） |
| `parts-fc__bullwhip_correction__list` | `part_no: str`（可选），`period: str`（可选），`tier: str`（可选），`status: str`（可选），`amp_verdict: str`（可选） | 条件筛选处理单列表 |
| `parts-fc__bullwhip_correction__maintain` | `bw_no: str` 处理单号 | 容忍内维持→状态→维持 |
| `parts-fc__bullwhip_correction__correct` | `bw_no: str` 处理单号，`corr_action: str` 修正机制+说明，`final_qty: float` 终端口径预测值 | 超阈修正→状态→已修正 |
| `parts-fc__bullwhip_correction__confirm` | `bw_no: str` 处理单号 | 确认→已确认（转发布），终端口径可被D09引用 |

## 三、标准工作流

### 流程 A：Tier1直供→简化确认

1. 总部计划调用 `create("8210001", "2026-09", "Tier1直供", derived_qty=990, end_qty=970, end_source="结算")`
2. 系统自动计算 amp_factor=1.02（<= θ_amp 1.10），amp_verdict="容忍内·维持"
3. Tier1直供+容忍内→自动进入"维持"状态，corr_action 自动填写"维持——Tier1直供，放大已由拆解先行完成"
4. 总部计划调用 `maintain(bw_no)` 确认维持
5. 总部计划调用 `confirm(bw_no)` → 已确认，供 D09 引用

### 流程 B：Tier2/3→超阈修正

1. 总部计划调用 `create("8220010", "2026-09", "Tier2", derived_qty=1350, end_qty=1000, end_source="结算")`
2. 系统自动计算 amp_factor=1.35（> θ_amp 1.10），amp_verdict="超阈·修正"，状态="待处理"
3. 总部计划审阅放大系数，从**六机制菜单**选择修正动作：
   - 终端需求可见 / 信息共享上传 / 按预测准确率分配 / 减小批量·平准化 / 安全库存协同 / 缩短提前期
4. 调用 `correct(bw_no, corr_action="切换终端需求口径 + 信息共享上传", final_qty=1000)`
   - **必须登记机制+说明**，禁止只改 final_qty 不选机制
5. 调用 `confirm(bw_no)` → 已确认

### 流程 C：容忍内维持（非Tier1场景）

1. create 后 amp_verdict="容忍内·维持"且非 Tier1场景
2. 调用 `maintain(bw_no)` 确认维持
3. 调用 `confirm(bw_no)` 确认

## 四、前置条件与注意事项

- **BR-01**：全覆盖分轨——Tier1直供简化确认，Tier2/3强制修正
- **BR-02**：终端来源优先级不可跳级：结算 > OEM消耗 > 外部映射 > 排产
- **BR-03**：θ_amp = 1.10（默认），amp_factor <= θ_amp → 维持，超阈 → 修正
- **BR-04**：修正必须登记所落机制与依据，禁止"无机制纯减数"
- **BR-05**：修正不改 D04 合理修订，D08 调的是口径锚
- **BR-07**：零件号×期间唯一，不可重复创建
- 六机制菜单为固定枚举：终端需求可见/信息共享上传/按预测准确率分配/减小批量·平准化/安全库存协同/缩短提前期
- derived_qty 通用件场景取 D07 修正总量（通过 common_parts_agg.get）
- 未确认的处理单不得被下游 D09 引用

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 应对策略 |
|---|---|---|
| "派生需求量（derived_qty）必填" / "终端需求量（end_qty）必填" | 缺少必传入参 | 索要缺失参数后重试 |
| "派生需求量必须大于零" / "终端需求量必须大于零" | 量纲为零 | 确认数据来源是否正确，传入正值 |
| "层级只能为：Tier1直供/Tier2/Tier3" | tier 不在枚举内 | 列出三个层级选项，请用户选择 |
| "终端来源只能为：结算/OEM消耗/外部映射/排产" | end_source 不在枚举内 | 列出四个来源，按优先级（结算最高）引导选择 |
| "零件...在...期间已存在牛鞭处理单" | BR-07 唯一性冲突 | 调用 list 查找已有处理单，如已存在则直接操作已有单 |
| "仅待处理状态可执行维持/修正" | 状态已变更 | 调用 get 查看当前状态和判定结果 |
| "当前判定为...不可维持，请走修正流程" | amp_verdict 为"超阈·修正" | 走修正流程，从六机制菜单选动作，调用 correct |
| "当前判定为...无需修正，请走维持流程" | amp_verdict 为"容忍内·维持" | 走维持流程，调用 maintain |
| "修正必须登记所落机制与依据，禁止无机制纯减数" | corr_action 为空 | 必须从六机制菜单中选择至少一项，填写修正说明 |
| "仅维持/已修正状态可确认" | 状态不是维持或已修正 | 先执行 maintain 或 correct，再确认 |
