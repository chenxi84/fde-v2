# 毛需求加工（demand_processing）

## 一、应用简介

毛需求加工（`DemandProcessing`）是 parts-fc 组中最复杂的聚合根，承载需求链的核心加工环节。
它将 D03 产出的真实消耗（true_qty）加工为"核定毛需求"（消耗口径），
作为 D07/D08/D09 的唯一消耗量输入。

- **聚合根编号**：4
- **主键**：`proc_batch`（PRC-YYYYMM-NNN）
- **数据存储**：`demand_processing.db` 同名 SQLite 库
- **五层同事务**：加工单头（d04_header）、基线明细（d04_baseline）、修正明细（d04_adjust）、核对明细（d04_check）、调整登记（d04_log）同属一个加工批次的事务边界，不可拆分
- **核心理念**：通过"基线锚定 + 三件套强制登记 + 多因素核对 + 退回返工循环"四道机制，保证每一次数值调整可追溯、可归因、可衡量 FVA
- **跨应用依赖**：strategy_fitting、baseline_borrowing、demand_collection、project_ledger、vehicle_part_map、independent_event

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `parts-fc__demand_processing__create_batch` | `oem_code: str`（必填）、`plant_code: str`（必填）、`fcst_version: str`（必填） | 创建加工批次，绑定客户x工厂xV版本。同一客户+工厂+V版本不可重复创建 |
| `parts-fc__demand_processing__generate_baseline` | `proc_batch: str`（必填） | 系统预计算双路径基线（路径A时序外推 + 路径B因果推演）。内部调用 strategy_fitting、baseline_borrowing、demand_collection、vehicle_part_map、project_ledger、independent_event。仅"进行中"批次可执行 |
| `parts-fc__demand_processing__get_baseline` | `proc_batch: str`（必填）、`part_no: str`（可选）、`veh_model: str`（可选）、`period: str`（可选） | 查询基线明细，可按零件/车型/期间筛选 |
| `parts-fc__demand_processing__submit_adjustment` | `proc_batch: str`（必填）、`part_no: str`（必填）、`veh_model: str`（必填）、`period: str`（必填）、`adj_qty: float`（必填）、`adj_reason_cat: str`（必填）、`adj_evidence: str`（可选，默认""） | 销售提交修正值。三件套强制（原因类别+数据依据+责任人缺一不可）；|修正幅度率| > 20% 时 adj_evidence 强制非空；owner 校验（仅责任销售可修正）；自动写入 D04-L 调整日志 |
| `parts-fc__demand_processing__review` | `proc_batch: str`（必填）、`part_no: str`（必填）、`veh_model: str`（必填）、`period: str`（必填）、`chk_result: str`（必填，"通过"或"退回"）、`chk_reason: str`（可选，默认""）、`chk_adj_qty: float`（可选，默认 None） | 核对销售修正：通过则落定 approved_qty（消耗口径），退回须附书面理由（视角+所需证据）。2 轮退回触发升级抛 FdeError。核对人调数同样登记三件套（双向约束） |
| `parts-fc__demand_processing__get_approved` | `proc_batch: str`（必填）、`part_no: str`（可选）、`veh_model: str`（可选）、`period: str`（可选） | 查询核定毛需求（消耗口径），仅返回 chk_result="通过"的行，供 D07/D08/D09 取数 |
| `parts-fc__demand_processing__get_status` | `proc_batch: str`（必填） | 查询批次整体状态及各行状态汇总统计（总计/待修正/待核对/已核定/退回/升级/逾期） |
| `parts-fc__demand_processing__lock` | `proc_batch: str`（必填） | 锁定加工批次。仅"全部核定"状态可锁定。由 D09 demand_release.publish 联动调用 |

## 三、标准工作流

### 3.1 完整加工流程（从批次创建到全部核定）

1. D03 拆解确认后，调用 `create_batch(oem_code, plant_code, fcst_version)` 创建加工批次
2. 调用 `generate_baseline(proc_batch)` 生成双路径基线（自动跨应用取 D10 策略 / D05 借用 / D03 真实消耗 / D02 量纲 / D01 份额）
3. 总部计划审核基线（通过偏差率判断是否需要人工确认）
4. 一线销售调用 `submit_adjustment(proc_batch, part_no, veh_model, period, adj_qty, adj_reason_cat, adj_evidence)` 提交修正值
5. 总部计划核对人调用 `review(proc_batch, part_no, veh_model, period, chk_result, chk_reason?, chk_adj_qty?)` 执行核对
6. 若退回：销售补充证据后重新调用 `submit_adjustment`（轮次+1，D04-L 新记录）
7. 若通过：approved_qty 落定，行状态 = "已核定"
8. 全部行核定后，批次自动推进为"全部核定"状态
9. D09 发布后调用 `lock(proc_batch)` 三层同锁

### 3.2 退回返工循环

1. 核对人调用 `review(..., chk_result="退回", chk_reason="水位视角：...+情报视角：...")` —— chk_reason 必须包含"哪个视角不通过 + 需要什么证据/调整"
2. 销售查看退回理由（五个要素：轮次/视角/所需证据/核对人/时间）
3. 销售补充证据或调整修正值后重新调用 `submit_adjustment`
4. 核对人再核 —— 若仍退回且 chk_round >= 2，系统抛 FdeError 建议升级产销平衡会

## 四、前置条件与注意事项

- **批次唯一性**：同一客户+工厂+V版本只能有一个加工批次，重复创建会抛 FdeError
- **状态前置**：generate_baseline / submit_adjustment / review 均要求批次状态 = "进行中"
- **基线前置**：submit_adjustment 要求目标零件x车型x期间的基线已在 D04-B 中存在
- **修正前置**：review 要求目标修正行的 submit_status = "已提交"
- **三件套强制**：submit_adjustment 的 adj_reason_cat 不可为空；|adj_pct| > 20% 时 adj_evidence 不可为空——服务端强制校验，不可绕过
- **Owner 校验**：submit_adjustment 通过 project_ledger 交叉验证当前操作人是否为该零件责任销售——非责任销售提交会抛 FdeError 拒绝
- **核定口径**：approved_qty 为消耗口径，不含独立事件加项（脉冲/断点）。事件在 D09 发布单上汇合（叠加结构），防止重复计入
- **上市高后下滑形态**：generate_baseline 会自动检测生命周期形态——若为"上市高后下滑"且 D10 策略使用简单移动平均/线性外推，会抛 FdeError 拒绝生成，要求使用衰减模型
- **断点截断**：generate_baseline 会自动跳过断点期内旧件的基线生成
- **脉冲不进基线**：基线输入为 true_qty（已拆解剥离脉冲），事件量不进基线计算
- **2轮升级**：同一零件x期间第 2 次退回时，review 会写入退回记录后立即抛 FdeError，由调用方捕获后升级处理
- **跨应用调用容错**：generate_baseline 中的跨应用调用（strategy_fitting / baseline_borrowing / vehicle_part_map 等）均有 try/except 兜底，单个外部服务不可用不阻塞整体流程，但会影响对应路径的数据质量
- **锁定不可逆**：lock 后所有五层数据只读，改数必须走新批次（版本修订）

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步该怎么做 |
|---------------|------|---------------------|
| 客户{oem_code}工厂{plant_code}的V版本{fcst_version}已存在加工批次，不可重复创建 | 唯一性冲突 | 先调用 get_status 或 get_baseline 检查是否已有该批次的加工单；若有则复用已有 proc_batch，不要重复创建 |
| 加工批次 {proc_batch} 不存在 | 批次号无效 | 先调用 create_batch 创建批次，或让用户确认批次号是否正确 |
| 仅"进行中"批次可生成基线 | 批次状态不是"进行中" | 调用 get_status 确认当前状态；若已锁定则告知用户须走新批次 |
| 获取收集数据失败：{详情} | demand_collection 不可用或 collect_no 无效 | 检查 D03 收集单是否已完成拆解并确认；确认 demand_collection 应用是否在线 |
| 收集单无明细数据，无法生成基线 | D03 收集单无明细行 | 提示用户先在 D03 收集单中录入明细并完成拆解确认 |
| 零件{part_no}车型{veh_model}生命周期形态为"上市高后下滑"，策略...为禁止的线性外推方法，必须使用衰减模型 | 基线方法不匹配生命周期形态 | 提示用户到 D10 strategy_fitting 重新拟合，为对应零件选择 Gompertz 或指数衰减等衰减模型 |
| 修正值不得为负数 | 输入合法性校验 | 提示用户修正值应为非负数，检查输入 |
| 零件{...}车型{...}期间{...}基线未生成，无法修正 | 基线缺失 | 先调用 generate_baseline 生成基线，或在 get_baseline 中确认该行是否存在 |
| 原因类别不可为空（三件套强制） | 三件套校验不通过 | 提示用户必须选择原因类别枚举值（客户侧情报/份额量纲/生命周期/节奏/外部验证背离/水位校准/其他） |
| 修正幅度率 {pct} 超过20%阈值，必须附数据依据（客户函件/邮件记录/数据截图）方可提交 | 分级举证触发 | 提示用户补充 adj_evidence 参数：上传或粘贴客户函件/邮件记录/数据截图等举证材料 |
| 零件{...}的责任销售不是您/为{owner}，无权修正 | Owner 校验失败 | 告知用户仅该零件的登记责任销售可提交修正；若需变更责任销售，先到 D01 project_ledger 更新 owner |
| 核对结论必须为"通过"或"退回" | 输入值不在枚举中 | 提示用户 chk_result 仅接受"通过"或"退回"两个值 |
| 零件{...}修正行不存在，无法核对 | 修正行缺失 | 提示用户该零件x期间尚未提交修正，先让销售调用 submit_adjustment |
| 修正行状态为...，非"已提交"不可核对 | 行状态不符合前置条件 | 调用 get_status 或 get_baseline 确认该行当前状态；若为"待提交"则催销售提交，若"已核定"则无需再核对 |
| 退回必须附书面理由——须包含"哪个视角不通过"和"需要什么证据/调整" | chk_reason 不符合规范 | 提示核对人填写完整的退回理由，格式要求：明确指出具体哪个视角不通过 + 需要销售提供什么证据或如何调整 |
| 零件{...}已退回{chk_round}轮，2轮无共识——建议升级至产销平衡会或总部仲裁 | 升级机制触发 | 告知用户该行已达升级阈值，暂停线上核对流程，转产销平衡会线下裁决；裁决后可通过 review 重新录入结论 |
| 批次状态为...，非"全部核定"不可锁定 | 锁定前置校验 | 调用 get_status 确认批次状态；若存在未核定行，先完成所有核对流程；若为"已锁定"则告知用户已锁定 |
