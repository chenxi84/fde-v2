# 前端详设：dashboard（sales-forecast 组级看板）

> 类型：组级页（无后端应用）| PAGE_META.key = `dashboard` | order = 10

## PAGE_META

```json
{
  "key": "dashboard",
  "name": "毛需求管理工作台",
  "order": 10,
  "icon": "📊",
  "group": "sales-forecast"
}
```

## 区块构成

### 1. KPI 指标带（`.kpi` 横排）

| 指标 | 取值来源 | 探测 svc | 跳转目标 |
|------|---------|---------|---------|
| 待拆解收集单 | demand_collection.list(status="草稿") count | `svc("demand_collection","list",status="草稿")` | demand_collection |
| 待修正行数 | demand_processing 中 submit_status="待提交" 的行数 | `svc("demand_processing","list",status="进行中")` | demand_processing |
| 待核对行数 | demand_processing 中待核对的行数 | 同上 | demand_processing |
| 已发布 R 版 | demand_release.list(status="已发布") 最近版本 | `svc("demand_release","list",status="已发布")` | demand_release |
| 生效事件数 | independent_event.list(status="生效") count | `svc("independent_event","list",status="生效")` | independent_event |
| 待确认事件 | independent_event.list(status="待确认") count | `svc("independent_event","list",status="待确认")` | independent_event |

### 2. 主链管道（各应用状态分布，`.pipe` 横排卡片）

| 管道段 | 应用 | 展示内容 | 探测 svc |
|-------|------|---------|---------|
| 收集 | demand_collection | 按状态计数：草稿/已拆解/已锁定 | `svc("demand_collection","list")` |
| 加工 | demand_processing | 按状态计数：进行中/全部核定/已锁定 | `svc("demand_processing","list")` |
| 汇总 | common_part_aggregation | 通用件待汇总/已修正/已确认计数 | `svc("common_part_aggregation","list")` |
| 牛鞭 | bullwhip_correction | 待处理/维持/已修正/已确认计数 | `svc("bullwhip_correction","list")` |
| 发布 | demand_release | 草稿/待发布/已发布计数 | `svc("demand_release","list")` |

### 3. 待办队列（按角色，`.todo`）

| 角色 | 待办项 | 来源 |
|------|-------|------|
| 一线销售 | 待修正行、核对质询待应答 | demand_processing submit_status |
| 总部计划 | 待拆解确认、待核对、疑似事件待确认、发布 checklist 待验证 | demand_collection/demand_processing/independent_event/demand_release |

## svc 字面量清单（逐项字面量）

```
svc("demand_collection", "list")
svc("demand_processing", "list")
svc("common_part_aggregation", "list")
svc("bullwhip_correction", "list")
svc("demand_release", "list")
svc("independent_event", "list")
svc("master_data", "list_customers")
svc("master_data", "list_parts")
```

全部 quiet 探测（`list()` 不传参），仅做计数展示。KPI 卡片点击跳转到对应应用页。

## 验收关注点
- 首次加载时 `.kpi` 数量 > 0（非看板页 KPI 数量为 0 即为粘滞 bug）
- 所有 svc 必须字面量（变量拼名扫不到 → 受限用户 403）
- dashboard key 固定 `dashboard`，order=10 居首
- KPI 卡片点击跳转目标正确
