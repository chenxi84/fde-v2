# parts-fc 组级看板 前端详设
> 来源：app/parts-fc/_contracts.md（冻结契约）+ app/parts-fc/architecture.md（聚合关系图/主链）+ 各应用详设状态机摘录；产出供第⑦步编码 / 第⑧步测试用例
> 落位：组级看板无对应后端应用，前端视图落 `app/parts-fc/前端详设/dashboard.md`；工厂 `export default function pageDashboard()`；组件通过 shell 注册为首页/概览页
> 注意：看板全量 svc 调用均为 `quiet:true` 探测——失败不喷 toast，零值兜底，不阻断页面渲染

## 1. 页面元数据 PAGE_META

| 字段 | 值 | 说明 |
|---|---|---|
| key | `dashboard` | 组级看板固定 key，page_id 为 `parts-fc:dashboard` |
| name | 需求预测总览 | 侧栏菜单名（首页/概览入口） |
| ic | 📊 | 菜单图标字 |
| title | 需求预测工作台 | 主区页面头 |
| crumb | 总览 · KPI · 主链管道 · 待办队列 | 头部副题 |
| order | 10 | 最小 order 居首，其余应用按 10 步长递增 |

- 页面零鉴权：无任何权限判断；菜单按页面授权渲染在 shell，数据范围由后端闸门执法，401 由 api.js 自动跳登录。
- 看板**不包含任何写操作 svc**——全部调用均为 `quiet:true` 只读探测。KPI 点击、待办点击均跳转至对应应用页面。

## 2. 区块构成

看板区块结构不同于单据型页面，划分为四大区域：KPI 指标带 / 主链管道 / 待办队列 / 快捷入口。

### 2.1 KPI 指标带

**用途**：顶部一行 `.kpi` 磁贴，展示全组关键业务指标计数，每项可点击跳转至对应应用页。

| KPI 磁贴 | svc 来源 | 指标口径 | 跳转目标 |
|---|---|---|---|
| 待收集 | `svc("demand_collection","list")` `{status:"草稿"}` | D03 收集单 status=草稿 count | `#/demand_collection` |
| 待修正 | `svc("demand_processing","list")` `{status:"进行中"}` | D04 加工批次 status=进行中 count（含待提交/待核对行） | `#/demand_processing` |
| 待核对 | `svc("demand_processing","list")` | 遍历批次 get_status 汇总待核对行数 | `#/demand_processing` |
| 已发布 R 版 | `svc("demand_release","list")` `{status:"已发布"}` | D09 发布单 status=已发布 count | `#/demand_release` |
| 生效事件 | `svc("independent_event","list")` `{status:"生效"}` | D06 事件 status=生效 count | `#/independent_event` |
| 生效映射 | `svc("vehicle_part_map","list")` `{status:"生效"}` | D02 映射 status=生效 count | `#/vehicle_part_map` |

- 每块 KPI 渲染为数字大字 + 标签小字；数据加载中显示 `—` 占位，quiet 失败显示 `—`（不喷 toast）。
- 点击跳转使用 `navigateTo(appKey)` 或 hash 路由，目标页打开后自带对应过滤条件（如跳转 D03 时默认 status=草稿）。

### 2.2 主链管道

**用途**：按 architecture.md 主链顺序展示 D03→D04→D07→D08→D09 五节点流程状态分布，以进度条/分段指示器呈现各阶段单据在各状态下的数量分布。

**主链节点（按加工链顺序）**：

| 节点 | 应用 | svc 来源 | 状态分布 | 展示形式 |
|---|---|---|---|---|
| ① 收集 | `demand_collection` | `svc("demand_collection","list")` | 草稿 / 已拆解 / 已锁定 / 已替代 / 已作废 | 分段横条，各状态宽度按 count 比例 |
| ② 加工 | `demand_processing` | `svc("demand_processing","list")` | 进行中 / 全部核定 / 已锁定 | 分段横条 + 进行中批次数 |
| ③ 通用件汇总 | `common_parts_agg` | `svc("common_parts_agg","list")` | 待汇总 / 待修正 / 已修正 / 已确认 | 分段横条 |
| ④ 牛鞭修正 | `bullwhip_correction` | `svc("bullwhip_correction","list")` | 待处理 / 维持 / 已修正 / 已确认 | 分段横条 |
| ⑤ 发布 | `demand_release` | `svc("demand_release","list")` | 草稿 / 待发布 / 已发布 / 已替代 | 分段横条 + 已发布版本号列表 |

- 每节点为一行 `.pipeline-node`，包含：节点序号 + 应用名（可点击跳转） + 状态分布条 + 总计数。
- 节点间用箭头连接符（`→`）串联，形成可视化主链流程。
- 状态分布条使用 `hue()` 色系：灰（草稿/待处理）、蓝（进行中/已拆解）、绿（已确认/已发布/已核定）、红（已作废/异常）。

### 2.3 待办队列

**用途**：按角色（销售 / 计划）分组展示当前待处理事项清单，每项可点击跳转至对应应用页面执行操作。

#### 2.3.1 销售待办

| 待办项 | svc 来源 | 业务语义 | 跳转目标 |
|---|---|---|---|
| 待录入收集明细 | `svc("demand_collection","list")` `{status:"草稿"}` | D03 收集单 status=草稿，销售需补录明细行 | `#/demand_collection` |
| 待提交修正 | `svc("demand_processing","list")` `{status:"进行中"}` | D04 加工批次进行中，销售需提交修正值 | `#/demand_processing` |
| 退回待重报 | `svc("demand_processing","list")` `{status:"进行中"}` | D04 核对退回行，销售需重新修正提交 | `#/demand_processing` |

#### 2.3.2 计划待办

| 待办项 | svc 来源 | 业务语义 | 跳转目标 |
|---|---|---|---|
| 待拆解确认 | `svc("demand_collection","list")` `{status:"草稿"}` | D03 收集单待计划执行拆解并确认 | `#/demand_collection` |
| 待核对 | `svc("demand_processing","list")` `{status:"进行中"}` | D04 销售已提交修正，计划需核对 | `#/demand_processing` |
| 通用件待修正 | `svc("common_parts_agg","list")` `{status:"待修正"}` | D07 通用件汇总待计划去重修正 | `#/common_parts_agg` |
| 牛鞭待处理/修正 | `svc("bullwhip_correction","list")` `{status:"待处理"}` + `{status:"已修正"}` | D08 牛鞭待处理或已修正待确认 | `#/bullwhip_correction` |
| 待发布确认 | `svc("demand_release","list")` `{status:"待发布"}` | D09 发布单待发布确认 | `#/demand_release` |
| 借用单待审核 | `svc("baseline_borrowing","list")` `{status:"待审核"}` | D05 借用单待计划审核 | `#/baseline_borrowing` |
| 事件待确认 | `svc("independent_event","list")` `{status:"待确认"}` | D06 独立事件待计划确认 | `#/independent_event` |

- 每项待办展示：标签 + 计数徽章；点击跳转。
- 零值时显示 `0` 或隐藏该项（保留标签但计数为 0）。
- 所有待办 svc 均为 quiet 探测，失败时显示 `—`。

### 2.4 快捷入口（辅助应用面板）

**用途**：列出主数据底座与支撑应用入口，供快速导航。

| 入口 | 应用 | 跳转目标 |
|---|---|---|
| 项目信息台账 | `project_ledger` | `#/project_ledger` |
| 车型零件映射 | `vehicle_part_map` | `#/vehicle_part_map` |
| 基线借用 | `baseline_borrowing` | `#/baseline_borrowing` |
| 独立事件 | `independent_event` | `#/independent_event` |
| 策略拟合 | `strategy_fitting` | `#/strategy_fitting` |
| 预测考核 | `forecast_assessment` | `#/forecast_assessment` |

- 每个入口为图标 + 应用名卡片，quiet 探测对应 `list` 服务获取记录总数展示在卡片右下角。

## 3. svc 字面量清单（授权派生依据——必须字面量 svc("应用","服务")）

> 所有调用均为 `quiet:true` 探测；参数中空条件传 `undefined` 不带。

### 3.1 KPI 指标带

| 区块 | 调用（应用.服务） | 参数 | quiet | 说明 |
|---|---|---|---|---|
| KPI·待收集 | `svc("demand_collection","list")` | `{status:"草稿", page:1, page_size:1}` | true | 取 D03 草稿计数 |
| KPI·待修正 | `svc("demand_processing","list")` | `{status:"进行中", page:1, page_size:1}` | true | 取 D04 进行中计数 |
| KPI·待核对 | `svc("demand_processing","list")` | `{status:"进行中", page:1, page_size:100}` | true | 取全部进行中批次后遍历 get 统计行级待核对 |
| KPI·待核对（批次行） | `svc("demand_processing","get")` | `{proc_batch}` | true | 取批次全貌（含基线/修正/核对子表），汇总待核对行数 |
| KPI·已发布 | `svc("demand_release","list")` | `{status:"已发布", page:1, page_size:1}` | true | 取 D09 已发布计数 |
| KPI·生效事件 | `svc("independent_event","list")` | `{status:"生效", page:1, page_size:1}` | true | 取 D06 生效计数 |
| KPI·生效映射 | `svc("vehicle_part_map","list")` | `{status:"生效", page:1, page_size:1}` | true | 取 D02 生效映射计数 |

### 3.2 主链管道

| 区块 | 调用（应用.服务） | 参数 | quiet | 说明 |
|---|---|---|---|---|
| 管道·D03 收集 | `svc("demand_collection","list")` | `{page:1, page_size:200}` | true | 取全部收集单统计状态分布 |
| 管道·D04 加工 | `svc("demand_processing","list")` | `{page:1, page_size:200}` | true | 取全部加工批次统计状态分布 |
| 管道·D07 通用件 | `svc("common_parts_agg","list")` | `{page:1, page_size:200}` | true | 取全部汇总单统计状态分布 |
| 管道·D08 牛鞭 | `svc("bullwhip_correction","list")` | `{page:1, page_size:200}` | true | 取全部处理单统计状态分布 |
| 管道·D09 发布 | `svc("demand_release","list")` | `{page:1, page_size:200}` | true | 取全部发布单统计状态分布 |

### 3.3 待办队列

| 区块 | 调用（应用.服务） | 参数 | quiet | 说明 |
|---|---|---|---|---|
| 销售·待录入 | `svc("demand_collection","list")` | `{status:"草稿", page:1, page_size:200}` | true | D03 草稿列表（销售补明细） |
| 销售·待提交修正 | `svc("demand_processing","list")` | `{status:"进行中", page:1, page_size:200}` | true | D04 进行中批次（销售提交修正） |
| 计划·待拆解 | `svc("demand_collection","list")` | `{status:"草稿", page:1, page_size:200}` | true | D03 草稿列表（计划拆解） |
| 计划·待核对 | `svc("demand_processing","list")` | `{status:"进行中", page:1, page_size:200}` | true | D04 进行中批次（计划核对） |
| 计划·通用件待修正 | `svc("common_parts_agg","list")` | `{status:"待修正", page:1, page_size:200}` | true | D07 待修正汇总单 |
| 计划·牛鞭待处理 | `svc("bullwhip_correction","list")` | `{status:"待处理", page:1, page_size:200}` | true | D08 待处理单 |
| 计划·牛鞭待确认 | `svc("bullwhip_correction","list")` | `{status:"已修正", page:1, page_size:200}` | true | D08 已修正待确认 |
| 计划·待发布确认 | `svc("demand_release","list")` | `{status:"待发布", page:1, page_size:200}` | true | D09 待发布单 |
| 计划·借用单待审核 | `svc("baseline_borrowing","list")` | `{status:"待审核", page:1, page_size:200}` | true | D05 待审核借用单 |
| 计划·事件待确认 | `svc("independent_event","list")` | `{status:"待确认", page:1, page_size:200}` | true | D06 待确认事件 |

### 3.4 快捷入口计数

| 区块 | 调用（应用.服务） | 参数 | quiet | 说明 |
|---|---|---|---|---|
| 入口·项目台账 | `svc("project_ledger","list")` | `{page:1, page_size:1}` | true | 全量计数 |
| 入口·车型映射 | `svc("vehicle_part_map","list")` | `{page:1, page_size:1}` | true | 全量计数 |
| 入口·基线借用 | `svc("baseline_borrowing","list")` | `{page:1, page_size:1}` | true | 全量计数 |
| 入口·独立事件 | `svc("independent_event","list")` | `{page:1, page_size:1}` | true | 全量计数 |
| 入口·策略拟合 | `svc("strategy_fitting","list")` | `{page:1, page_size:1}` | true | 全量计数 |
| 入口·预测考核 | `svc("forecast_assessment","list")` | `{page:1, page_size:1}` | true | 全量计数 |

### 3.5 全量应用探测（完整性兜底——所有 11 个应用的 list/get 服务全覆盖）

| # | 调用（应用.服务） | quiet | 说明 |
|---|---|---|---|
| 1 | `svc("project_ledger","list")` | true | 项目台账列表探测 |
| 2 | `svc("project_ledger","get")` | true | 项目台账详情探测（需 project_no + part_no，看板仅做连通性探测，不实际取详情） |
| 3 | `svc("vehicle_part_map","list")` | true | 车型映射列表探测 |
| 4 | `svc("vehicle_part_map","get")` | true | 车型映射详情探测（连通性，不实际调用） |
| 5 | `svc("demand_collection","list")` | true | 需求收集列表探测 |
| 6 | `svc("demand_collection","get")` | true | 需求收集详情探测（连通性） |
| 7 | `svc("demand_processing","list")` | true | 需求加工列表探测 |
| 8 | `svc("demand_processing","get")` | true | 需求加工详情探测（连通性） |
| 9 | `svc("demand_processing","get")` | true | 需求加工批次全貌探测（含基线/修正/核对子表） |
| 10 | `svc("baseline_borrowing","list")` | true | 基线借用列表探测 |
| 11 | `svc("baseline_borrowing","get")` | true | 基线借用详情探测（连通性） |
| 12 | `svc("independent_event","list")` | true | 独立事件列表探测 |
| 13 | `svc("independent_event","get")` | true | 独立事件详情探测（连通性） |
| 14 | `svc("common_parts_agg","list")` | true | 通用件汇总列表探测 |
| 15 | `svc("common_parts_agg","get")` | true | 通用件汇总详情探测（连通性） |
| 16 | `svc("bullwhip_correction","list")` | true | 牛鞭修正列表探测 |
| 17 | `svc("bullwhip_correction","get")` | true | 牛鞭修正详情探测（连通性） |
| 18 | `svc("demand_release","list")` | true | 需求发布列表探测 |
| 19 | `svc("demand_release","get")` | true | 需求发布详情探测（连通性） |
| 20 | `svc("strategy_fitting","list")` | true | 策略拟合列表探测 |
| 21 | `svc("strategy_fitting","get")` | true | 策略拟合详情探测（连通性） |
| 22 | `svc("forecast_assessment","list")` | true | 预测考核列表探测 |
| 23 | `svc("forecast_assessment","get")` | true | 预测考核详情探测（连通性） |

> 以上 23 处必须在 view.js 中以字面量逐项书写（可包在闭包里），**勿用变量拼名**——这是页面授权隐式放行派生扫描的唯一来源。其中仅连通行探测（get）不实际传参调用，仅声明字面量用于授权派生；实际数据拉取依赖上方 list 调用。

## 4. 数据来源与下拉

**看板无下拉控件**：所有数据均来自后端 svc list/get quiet 探测，不涉及前端主数据下拉。

**契约 payload → 区块字段映射**：

| 来源 | payload 字段 | 去向 |
|---|---|---|
| `demand_collection.list` 项 | collect_no, oem_code, plant_code, fcst_version, base_period, status, collector, created_at | KPI 计数 + 主链 D03 状态分布 + 销售/计划待办 |
| `demand_processing.list` 项 | proc_batch, oem_code, plant_code, fcst_version, status, start_time, finish_time | KPI 计数 + 主链 D04 状态分布 + 待办队列 |
| `common_parts_agg.list` 项 | agg_no, part_no, period, sum_qty, dedup_qty, status | 主链 D07 状态分布 + 计划待办 |
| `bullwhip_correction.list` 项 | bw_no, part_no, period, tier, amp_factor, amp_verdict, final_qty, status | 主链 D08 状态分布 + 计划待办 |
| `demand_release.list` 项 | rel_no, rel_version, base_period, status, publisher, publish_date | KPI 计数 + 主链 D09 状态分布 + 计划待办 |
| `independent_event.list` 项 | event_no, event_type, part_no, period, event_qty, status | KPI 计数 + 计划待办 |
| `vehicle_part_map.list` 项 | part_no, veh_model, usage, share, lc_stage, status | KPI 计数 + 快捷入口计数 |
| `baseline_borrowing.list` 项 | jy_no, part_no, veh_model, borrow_method, status | 计划待办 + 快捷入口计数 |
| `project_ledger.list` 项 | project_no, part_no, stage, oem_code, owner_sales | 快捷入口计数 |
| `strategy_fitting.list` 项 | fit_no, part_no, veh_model, demand_shape, status | 快捷入口计数 |
| `forecast_assessment.list` 项 | fa_no, part_no, veh_model, period, conv_rate, result | 快捷入口计数 |

## 5. 交互要点

1. **全局 quiet 探测**：所有 svc 调用均为 `quiet:true`——任一 svc 失败不喷 toast，对应区块显示 `—` 占位或 `0` 兜底，不阻断页面整体渲染。
2. **并行加载**：KPI 指标带、主链管道、待办队列三大区块的 svc 调用并行发起（Promise.all 或等效），不串行等待；各区块独立 loading 态。
3. **KPI 点击跳转**：每块 KPI 磁贴为可点击区域，跳转至对应应用页并携带默认过滤条件（通过 hash query 参数或页面间状态传递）。
4. **待办点击跳转**：每项待办标签为可点击按钮，跳转至对应应用页。
5. **主链管道无点击**：主链节点名称（应用名）可点击跳转，状态分布条为只读展示。
6. **自动刷新**：页面挂载时全量拉取，不设定时轮询（避免后端压力）；用户可通过浏览器刷新或看板内刷新按钮手动刷新。
7. **空态兜底**：所有区块在数据为空时展示空态文案（如"暂无进行中的加工批次"），不喷 toast。
8. **展示工具**：`hue()` 用于状态徽章色系映射（草稿→灰 / 进行中→蓝 / 已确认/已发布→绿 / 已作废/异常→红）；`fmtTime()` 用于时间字段；数字计数用 `fmt()` 千分位。
9. **加载骨架**：大区块（主链管道、待办队列）加载中展示骨架屏（skeleton），KPI 磁贴加载中展示 `—` 占位。
10. **看板无表单、无模态、无写操作**：纯展示页。

## 6. 验收关注点（供第⑧步前端测试用例）

1. **路由渲染**：`#/dashboard` 挂载出四大区块（KPI 指标带 + 主链管道 + 待办队列 + 快捷入口），菜单「📊 需求预测总览」按 order=10 居首。
2. **KPI 磁贴计数正确**：造 D03 草稿 3 条、D04 进行中 2 批、D09 已发布 1 版、D06 生效 2 条 → 看板各 KPI 磁贴数字与造数一致；quiet 失败时磁贴显示 `—`。
3. **主链管道状态分布正确**：造 D03 草稿×2 + 已拆解×1 → D03 节点分段横条草稿 2 宽、已拆解 1 宽，总计数 3；各节点状态颜色正确。
4. **待办队列角色分组正确**：销售待办仅展示销售相关项（待录入/待提交修正）；计划待办展示计划相关项（待拆解/待核对/通用件待修正/牛鞭/发布/借用审核/事件确认）；待办计数与造数一致。
5. **跳转连通**：点击 KPI「待收集」跳转至 `#/demand_collection`；点击待办「待核对」跳转至 `#/demand_processing`；快捷入口卡片点击跳转至对应应用页。
6. **并行加载不阻塞**：页面加载时各区块独立渲染，任一 svc 超时/失败不影响其他区块。
7. **干净控制台**：全程 0 console error / 0 pageerror / 0 HTTP≥400（quiet 探测的 4xx 为预期行为，不输出到控制台；non-quiet 的 4xx 需查明）。
