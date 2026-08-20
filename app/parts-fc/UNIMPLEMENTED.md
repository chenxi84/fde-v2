# parts-fc 未实现功能清单

> 基于 BRD《毛需求管理详设》对照分析，生成于 2026-08-08

## 缺失的公共方法（6 个）

| # | 应用 | 方法 | BRD 出处 |
|---|------|------|------|
| 1 | project_ledger | `get_active_projects` | §2.11 |
| 2 | vehicle_part_map | `get_active_mapping` | §2.12 |
| 3 | demand_collection | `get_true_qty` | §2.1.8 |
| 4 | demand_processing | `get_approved` | §2.3.5 |
| 5 | strategy_fitting | `refit` | §2.10.6 |
| 6 | strategy_fitting | `shadow_compare` | §2.10.6 |

## 未生效的跨应用调用（11 个）

| # | 调用方 | 应调 | 服务 | BRD 出处 |
|---|------|------|------|------|
| 7 | D03.create | D01 | get_active_projects | §2.1.7 |
| 8 | D03.create | D02 | get_active_mapping | §2.1.7 |
| 9 | D04.generate_baseline | D05 | get_derived_qty | §2.3.3 d |
| 10 | D04.submit_adjustment | D06 | list | §2.3.5 c |
| 11 | D07.create | D04 | get_approved | §2.6.4 |
| 12 | D07.create | D05 | get_derived_qty | §2.6.4 |
| 13 | D08.create | D04 | get_approved | §2.7.3 |
| 14 | D08.create | D07 | get | §2.7 |
| 15 | D08.create | D02 | get_active_mapping | §2.7.3 |
| 16 | D09.create_draft | D04/D06/D07/D08 | 汇总调用 | §2.8.6 |
| 17 | D10 | D05 | 模板库/类比库沉淀 | §2.10.6 |

## 缺失/简化的业务规则（8 个）

| # | 应用 | 规则 | BRD 出处 |
|---|------|------|------|
| 18 | D03 | 录入一致性校验 | §2.1.7.3 |
| 19 | D03 | 合理性提示 | §2.1.7.4 |
| 20 | D04 | 双路径基线生成 | §2.3.3 c |
| 21 | D04 | 修正权限校验 | §2.3.4 g |
| 22 | D04 | 退回 2 轮升级 | §2.3.5 e |
| 23 | D05 | 自动提示切换自产策略 | §2.5.6.4 |
| 24 | D07 | 自动判定专用/通用件分流 | §2.6.6.1 |
| 25 | D09 | checklist 真实跨应用校验 | §2.8.3 |

## 缺失的状态机（1 个）

| # | 应用 | 问题 | BRD 出处 |
|---|------|------|------|
| 26 | D12 | 缺 status 字段 | §2.9.4 |

## 缺失的算法实现（2 个）

| # | 应用 | 问题 | BRD 出处 |
|---|------|------|------|
| 27 | D04 | 基线生成未做真正时序外推 | §2.3.3 |
| 28 | D10 | 回测打分为固定值 | §2.10.3 |
