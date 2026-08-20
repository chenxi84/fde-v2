# 销售预测应用组 · 架构设计覆盖度检查报告

> 产出时间：2026-08-12
> 依据：app/forecast/brd/销售预测详设.md（全部 566 行）
> 检查对象：app/forecast/architecture.md

---

## 一、BRD 业务单据覆盖度

| BRD 单据/表 | BRD 位置 | architecture.md 对应 | 状态 |
|------------|---------|---------------------|------|
| 预测快照表 | §8.1 | 聚合根 forecast_snapshot | ✅ |
| 基线表 | §8.2 | 聚合根 forecast_baseline | ✅ |
| 预测加工表（单头+明细） | §8.3 | 聚合根 forecast_processing | ✅ |
| 初步毛需求表 | §8.4 | 不独立成聚合：demand_release.create_draft 内置计算步骤（决策 D1） | ✅ 明确排除 |
| 零件级处理 | §8.5 | 聚合根 part_level_adj | ✅ |
| 毛需求发布单（单头+明细） | §8.6 | 聚合根 demand_release | ✅ |
| 客户主数据 M1 | §9.3 | 聚合根 md_customer | ✅ |
| 物料主数据 M2 | §9.3 | 聚合根 md_material | ✅ |
| 项目台账 M3 | §9.3 | 聚合根 md_project | ✅ |
| 项目-零件映射 M4 | §9.3 | 聚合根 md_project_part | ✅ |
| 替换关系表 M5 | §9.3 | 聚合根 md_part_replace | ✅ |
| 模板/类比库 M6 | §9.3 | V1 不建模（决策 D2） | ✅ 明确排除 |
| 外部数据台账 M7 | §9.3 | V1 不建模（决策 D3） | ✅ 明确排除 |
| 月度版本主数据 M8 | §9.3 | 聚合根 md_fcst_version | ✅ |
| 寄售结算 H1 | §9.4 | 外部系统，不建聚合（决策 D4） | ✅ 明确排除 |
| 出货台账 H2 | §9.4 | 外部系统，不建聚合（决策 D4） | ✅ 明确排除 |
| 达成率/置信度 H3 | §9.4 | 聚合根 attainment | ✅ |

**BRD 业务单据覆盖度 = 17/17 = 100%** ✅

---

## 二、BRD 主流程覆盖度

| BRD 主流程 | BRD 位置 | architecture.md 关系图对应链路 | 状态 |
|-----------|---------|------------------------------|------|
| 月度版本 opening → 自动生成快照行 | §1.1/§8.1 | FS.open_version → MFV.get + MPP.list_active | ✅ |
| 销售填预测 | §1.1/§8.1 | FS.fill | ✅ |
| 基线生成（历史→外推/借用） | §2 | FB.generate → FS.list + AT.list | ✅ |
| 计划确认基线 | §2 | FB.confirm / confirm_batch | ✅ |
| 加工：基线→置信度调整→趋势调整→一次性调整→独立需求 | §3/§8.3 | FP.create_batch → FB.list + FS.list；FP.fill_line → AT.get_conf_factor | ✅ |
| 加工核定与锁定 | §8.3 | FP.review_line + finalize | ✅ |
| 初步毛需求汇总（物料级） | §8.4 | DR.create_draft → FP.get（内置汇总） | ✅ |
| 零件级处理：通用件合并 | §4.1/§8.5 | PLA.create_generic_merge → MPP.list_by_part | ✅ |
| 零件级处理：替换件合并 | §4.2/§8.5 | PLA.create_replace_merge → MPR.get | ✅ |
| 零件级处理：断点调整 | §4.3/§8.5 | PLA.create_breakpoint_adj → MPR.get | ✅ |
| 毛需求发布 | §5/§8.6 | DR.publish → FS.lock_version + MFV.set_linked | ✅ |
| 月度闭环：达成率计算 | §7 | AT.compute → FS.list | ✅ |
| 月度闭环：复盘与回校 | §7.2 | AT.compute_batch → 各应用 BR 参数回校通道 | ✅ |

**BRD 主流程覆盖度 = 14/14 = 100%** ✅

---

## 三、BRD 角色职责覆盖度

| BRD 角色 | BRD 位置 | architecture.md 聚合根卡职责描述 | 状态 |
|---------|---------|-------------------------------|------|
| 一线销售 | §6 | FS：预测收集（及时性）、客户侧信息；collector 字段记录 | ✅ |
| 总部计划 | §6 | FB：基线生成与确认；FP：置信度/趋势/一次性调整确认、合并总量把控；DR：发布决策 | ✅ |

**BRD 角色覆盖度 = 2/2 = 100%** ✅

---

## 四、总体结论

| 维度 | 覆盖度 | 判定 |
|------|--------|------|
| 业务单据 | 17/17 = 100% | ✅ 通过 |
| 主流程 | 14/14 = 100% | ✅ 通过 |
| 角色职责 | 2/2 = 100% | ✅ 通过 |
| **总体** | **100%** | **✅ 通过，可进入第④步（Step ②）** |

> 注：3 项明确排除（初步毛需求/模板库/外部数据台账）均有排除理由记录在决策 D1-D3。
> 2 项外部系统依赖（H1/H2）按 CONVENTION §12.2 经适配器访问、不建聚合。
