# 销售预测看板 前端详设
> 来源：app/forecast/architecture.md（主链关系图）+ 各应用详设；产出供第⑦步编码 / 第⑧步测试用例
> 落位：`view/forecast/dashboard.js` + `view/forecast/dashboard.html`（组级页，key="dashboard"）

## 1. 页面元数据 PAGE_META
key=dashboard / name=首页看板 / ic=📊 / title=销售预测 · 工作台 / crumb=KPI · 主链管道 · 待办 / order=10

## 2. 区块构成

### 2.1 KPI 指标带
三列卡片行（frow，每卡 `.kpi`）：
| 指标 | svc 探测 | 说明 |
|------|---------|------|
| 活跃版本 | `md_fcst_version.get_active()` quiet | 显示当前活跃月度版本号 |
| 快照完成率 | `forecast_snapshot.get_version_status(fcst_version)` quiet | 已填行/总行 ×100% |
| 待核定加工行 | `forecast_processing.list_lines(prc_batch, chk_result='')` quiet | 未核定行数 |

### 2.2 主链管道（各应用状态分布）
四列卡片行：
| 管道段 | svc 探测 | 展示 |
|--------|---------|------|
| 快照 | `forecast_snapshot.list(fcst_version, page=1, page_size=5)` | 最近5条快照行（物料+期间+预测量+标记） |
| 基线 | `forecast_baseline.list(base_batch, page=1, page_size=5)` | 最近5条基线行（物料+基线值+路径+状态） |
| 加工 | `forecast_processing.list_batches(fcst_version, page=1, page_size=5)` | 最近批次（批次号+状态+行数） |
| 发布 | `demand_release.list(fcst_version, page=1, page_size=5)` | 发布单列表（单号+状态+行数） |

### 2.3 待办队列
| 待办项 | svc 探测 | 跳转目标 |
|--------|---------|---------|
| 未填快照行 | `forecast_snapshot.list(data_flag='OEM未提供')` quiet | `forecast:forecast_snapshot` |
| 预计算基线 | `forecast_baseline.list(status='预计算')` quiet | `forecast:forecast_baseline` |
| 进行中加工批次 | `forecast_processing.list_batches(status='进行中')` quiet | `forecast:forecast_processing` |
| 草稿发布单 | `demand_release.list(status='草稿')` quiet | `forecast:demand_release` |

## 3. svc 字面量清单（授权派生依据——必须字面量）

| 区块 | 调用（应用.服务） | 参数 | quiet | 说明 |
|------|-------------------|------|-------|------|
| KPI | `svc("md_fcst_version","get_active")` | `{}` | true | 活跃版本号 |
| KPI | `svc("forecast_snapshot","get_version_status")` | `{fcst_version}` | true | 快照完成率 |
| KPI | `svc("forecast_processing","list_lines")` | `{prc_batch, page:1, page_size:200}` | true | 待核定行数 |
| 管道-快照 | `svc("forecast_snapshot","list")` | `{fcst_version, page:1, page_size:5}` | true | 最近快照行 |
| 管道-基线 | `svc("forecast_baseline","list")` | `{base_batch, page:1, page_size:5}` | true | 最近基线行 |
| 管道-加工 | `svc("forecast_processing","list_batches")` | `{fcst_version, page:1, page_size:5}` | true | 最近批次 |
| 管道-发布 | `svc("demand_release","list")` | `{fcst_version, page:1, page_size:5}` | true | 发布单 |
| 待办-快照 | `svc("forecast_snapshot","list")` | `{fcst_version, data_flag:'OEM未提供', page:1, page_size:5}` | true | 未填行 |
| 待办-基线 | `svc("forecast_baseline","list")` | `{base_batch, status:'预计算', page:1, page_size:5}` | true | 未确认行 |
| 待办-加工 | `svc("forecast_processing","list_batches")` | `{status:'进行中', page:1, page_size:5}` | true | 进行中批次 |
| 待办-发布 | `svc("demand_release","list")` | `{status:'草稿', page:1, page_size:5}` | true | 草稿单 |

> 以上 11 处 svc 必须字面量逐项书写（可闭包），全部 quiet 探测 + 零值兜底。

## 4. 数据来源与下拉
- 活跃版本号：`md_fcst_version.get_active()` → 驱动全部 KPI/管道/待办的 fcst_version 参数
- 基线批次号：从活跃版本推导或取最新

## 5. 交互要点
1. **全部 quiet + 零值兜底**：任一探测失败不喷 toast，显示 "—" 或 "暂无数据"
2. **跳转**：KPI/管道/待办中的单号/批次号为 `.b-link`，点击 goto `#/<应用key>` 到对应应用页
3. **加载态**：初始显示骨架屏（`.loadbox`），全部探测完成后渲染

## 6. 验收关注点（供第⑧步）
1. 路由渲染：`#/dashboard` 挂载出 KPI 行 + 管道卡片 + 待办卡片
2. 看板页 **有 `.kpi`**（与逐应用页相反——看板页有 KPI 卡片，非看板页 `.kpi` 数为 0 防粘滞）
3. quiet 探测：无数据时零值兜底不报错
4. 受限用户恒显：菜单含 dashboard
