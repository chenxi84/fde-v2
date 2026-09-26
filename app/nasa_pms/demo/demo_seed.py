"""nasa_pms 演示数据 · 造数（**写入真库**，供演示/看板/知识库用）。

场景：**近地轨道遥感卫星 EO-3 项目**（Earth Observation 3）—— 一条从"用户方提出观测需求"
到"技术度量超阈值告警"的完整系统工程故事。11 个聚合根**每个状态档位都有样本**，
所以看板的状态分布、列表筛选、状态机动作在演示时都能点得动。

    python app/nasa_pms/demo/demo_seed.py            # 清空本组数据后重建
    python app/nasa_pms/demo/demo_seed.py --keep      # 不清空，直接追加（调试用）

设计要点（与 `app/psc` 的 `宣传/demo_seed.py` 同形态）：
  · **一律经服务造数**（`platform.call`），不直连 SQL —— 状态机、BR 校验、跨应用弱引用
    都走真实路径，所以造出来的数据**天生是合法的演示状态**；顺带也是一次端到端演练。
  · **幂等**：默认先清空本组 11 张表（保留 config/ 下的平台库与用户/角色）。
  · **跨应用顺序**按弱引用依赖排：stakeholder → requirement(基线) → tech_plan → configuration_item
    → change_request(审批到已批准) → 配置项发版(用该变更号) → verification → risk
    → technical_measure → review(引计划) → decision(引度量)。
  · 内容与《演示业务方案》无关的**平台侧事项**（技能库/定时任务/集成）不在本脚本，见 `demo_build.py`。
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _project_root() -> pathlib.Path:
    p = HERE
    while not (p / "fde_platform").is_dir():
        if p.parent == p:
            raise SystemExit("找不到项目根：向上未发现 fde_platform/")
        p = p.parent
    return p


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

try:                                    # 控制台代码页可能是 GBK（Windows）—— 别让 print 崩在输出那一步
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

GROUP = "nasa_pms"
APPS = ["stakeholder", "requirement", "tech_plan", "configuration_item", "change_request",
        "verification", "risk", "technical_measure", "review", "decision", "interface",
        "wbs", "activity"]


def clear():
    """清空本组各应用库的全部表（**只清数据、保留库文件**）。

    ⚠ 走 `FDE_DB_ROOT`（有则用它，没有就在仓库里找 `app/<组>/<应用>/<应用>.db`）——
    与链测试的 `clean()` 同口径；但注意**本脚本不是影子库**：它就是要写进真库。
    """
    cleared = 0
    for app in APPS:
        root = os.environ.get("FDE_DB_ROOT", "").strip()
        db = (pathlib.Path(root) / f"{app}.db") if root else (ROOT / "app" / GROUP / app / f"{app}.db")
        if not db.exists():
            continue
        conn = sqlite3.connect(str(db))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for t in tables:
            conn.execute(f'DELETE FROM "{t}"')
        conn.commit()
        conn.close()
        cleared += 1
    # 分母闸：一个库都没清到，说明布局与查找路径不一致 —— 别静默继续（那会撞主键）
    if cleared != len(APPS):
        raise SystemExit(f"清库只清到 {cleared}/{len(APPS)} 个 —— 库路径与布局不一致，已停下")


def seed(pf):
    """按故事线造数。返回一份"设计态"摘要，供 `verify_demo.py` 复用口径。"""
    def call(app, svc, **kw):
        return pf.call(f"{GROUP}/{app}", svc, **kw)

    # ── ① 利益相关者（主数据：外部同步来的，本系统只读引用）────────────────
    call("stakeholder", "upsert", sh_no="SH-001", name="国家遥感中心", sh_type="customer",
         duty="提观测需求与验收", org="自然资源部")
    call("stakeholder", "upsert", sh_no="SH-002", name="航天科技集团八院", sh_type="contractor",
         duty="整星研制与交付", org="航天科技集团", contact="型号办 021-8888xxxx")
    call("stakeholder", "upsert", sh_no="SH-003", name="有效载荷分系统", sh_type="internal_org",
         duty="相机与数传分系统研制")
    call("stakeholder", "upsert", sh_no="SH-004", name="总体设计部", sh_type="internal_org",
         duty="总体方案与指标分配")
    call("stakeholder", "upsert", sh_no="SH-005", name="地面应用系统", sh_type="customer",
         duty="数据接收与产品分发")

    call("stakeholder", "add_expectation", sh_no="SH-001",
         statement="重访周期不超过 3 天", kind="need", source="需求评审纪要 2026-03-11")
    call("stakeholder", "add_expectation", sh_no="SH-001",
         statement="影像地面分辨率优于 1.5 m", kind="moe", source="任务书 §3.2", committed=True,
         moe="以靶标成像判读 GSD ≤ 1.5 m 为成功判据")
    call("stakeholder", "add_expectation", sh_no="SH-004",
         statement="整星发射质量不超过 1200 kg（受运载能力约束）", kind="constraint",
         source="运载接口控制文件", committed=True)
    call("stakeholder", "add_expectation", sh_no="SH-005",
         statement="下行数据 24 小时内完成产品级分发", kind="objective", source="应用系统设计")

    # ── ② 需求（系统/接口/技术/派生）+ 基线 B1 ────────────────────────────
    call("requirement", "create", title="重访周期不超过 3 天",
         statement="在轨观测阶段，对同一目标区的重访间隔不超过 72 小时。",
         req_type="system", verify_method="analysis", owner="总体设计部")
    call("requirement", "create", title="地面分辨率优于 1.5 m",
         statement="星下点地面像元分辨率（GSD）优于 1.5 m。",
         req_type="system", verify_method="test", owner="载荷分系统")
    call("requirement", "create", title="整星发射质量不超过 1200 kg",
         statement="发射状态整星质量不超过 1200 kg（含推进剂）。",
         req_type="technical", verify_method="test", owner="总体设计部")
    call("requirement", "create", title="数传速率不低于 900 Mbps",
         statement="对地数传链路在仰角 10° 以上时速率不低于 900 Mbps。",
         req_type="technical", verify_method="test", owner="测控分系统")
    call("requirement", "create", title="相机分系统接口符合 ICD-001",
         statement="相机与星务计算机的机械/电气/数据接口与 ICD-001 一致。",
         req_type="interface", verify_method="inspection", owner="载荷分系统")
    call("requirement", "create", title="测控链路接口符合 ICD-002",
         statement="测控应答机与地面测控网的接口与 ICD-002 一致。",
         req_type="interface", verify_method="inspection", owner="测控分系统")
    call("requirement", "create", title="姿态稳定度优于 0.005°/s",
         statement="成像期间三轴姿态稳定度优于 0.005°/s（3σ）。",
         req_type="system", verify_method="test", owner="控制分系统")
    call("requirement", "create", title="星上存储容量不低于 2 Tbit",
         statement="星上固态存储有效容量不低于 2 Tbit（扣除校验开销）。",
         req_type="technical", verify_method="inspection", owner="星务分系统")
    call("requirement", "create", title="在轨寿命不低于 5 年",
         statement="设计寿命不低于 5 年（含推进剂余量）。",
         req_type="system", verify_method="analysis", owner="总体设计部")
    call("requirement", "create", title="成像任务可编排",
         statement="地面可上注观测任务序列并在轨自动执行。",
         req_type="system", verify_method="demonstration", owner="星务分系统")
    # 派生需求（BR-02：必须挂上游）
    call("requirement", "derive", source_req_no="REQ-001", title="单圈观测时长不低于 12 分钟",
         statement="派生自 REQ-001：单圈可观测时间不低于 12 分钟。",
         verify_method="analysis", owner="总体设计部")
    call("requirement", "derive", source_req_no="REQ-002", title="相机焦距不小于 6 m",
         statement="派生自 REQ-002：为满足 GSD，相机焦距不小于 6 m。",
         verify_method="analysis", owner="载荷分系统")
    # 基线 B1：先提交评审、再整批冻进基线（2026-09-25 起基线有**评审门**：草稿不能直接进）
    for no in ("REQ-001", "REQ-002", "REQ-003", "REQ-007"):
        call("requirement", "submit_review", req_no=no)
    call("requirement", "baseline", req_nos=["REQ-001", "REQ-002", "REQ-003", "REQ-007"],
         baseline_ver="B1")
    # 一条停在「待评审」（让看板的状态分布不是一条直线，也让该筛选项有内容）
    call("requirement", "create", title="月面成像模式待定",
         statement="是否支持月面成像待任务书补充（列待评审）。",
         req_type="system", verify_method="demonstration", owner="总体设计部")
    call("requirement", "submit_review", req_no="REQ-013")
    # 一条作废需求（让「已废弃」档与**作废理由**都有样本；BR-02：记录保留、派生链不悬空）
    call("requirement", "obsolete", req_no="REQ-012",
         reason="接口方案变更 —— 该派生需求随之作废（记录保留，便于回溯）")

    # ── ③ 技术计划（SEMP / 验证计划 / 集成计划 / 技术评估）────────────────
    call("tech_plan", "create", name="系统工程管理计划（SEMP）", plan_type="semp", phase="a",
         maturity="baseline", scope="全寿命周期技术管理活动与职责分工", owner="系统工程师")
    call("tech_plan", "submit", plan_no="PLAN-001")
    call("tech_plan", "approve", plan_no="PLAN-001", approver="技术副总师", note="首次批准")
    call("tech_plan", "create", name="验证与确认计划（V&V Plan）", plan_type="verification",
         phase="b", maturity="preliminary", scope="各阶段验证方法、判据与资源", owner="验证负责人")
    call("tech_plan", "submit", plan_no="PLAN-002")
    call("tech_plan", "create", name="集成与试验计划", plan_type="integration", phase="c",
         maturity="approach", scope="分系统集成顺序与试验矩阵", owner="集成负责人")
    call("tech_plan", "create", name="技术评估与转化计划", plan_type="technology_dev", phase="b",
         maturity="approach", scope="关键技术的成熟度评估与转化路径", owner="技术评估组")
    # PLAN-004 走完整条流转：提交 → 撤回 → 再提交 → 批准 → 修订（BR-06：只有已批准才能修订）
    call("tech_plan", "submit", plan_no="PLAN-004")
    call("tech_plan", "withdraw", plan_no="PLAN-004", reason="成熟度评定口径需与总体对齐")
    call("tech_plan", "submit", plan_no="PLAN-004")
    call("tech_plan", "approve", plan_no="PLAN-004", approver="技术副总师", note="口径已对齐")
    call("tech_plan", "revise", plan_no="PLAN-004", summary="补充成熟度评定口径（对齐总体）",
         phase="b", maturity="preliminary")

    # ── ④ 配置项（含发版 —— 发版须带已批准的变更号）───────────────────────
    call("configuration_item", "create", name="星务软件 v1", ci_type="software", owner="星务分系统")
    call("configuration_item", "create", name="系统规范", ci_type="document", owner="总体设计部")
    call("configuration_item", "create", name="相机仿真模型", ci_type="model", owner="载荷分系统")
    call("configuration_item", "create", name="在轨遥测数据集", ci_type="data", owner="星务分系统")
    call("configuration_item", "create", name="测控应答机", ci_type="hardware", owner="测控分系统")
    call("configuration_item", "create", name="接口控制文件 ICD-001", ci_type="document",
         owner="载荷分系统")
    for no in ("CI-001", "CI-002", "CI-005"):
        call("configuration_item", "control", ci_no=no)
    call("configuration_item", "assign_baseline", ci_no="CI-001", baseline="product",
         baseline_ver="B1")
    call("configuration_item", "assign_baseline", ci_no="CI-002", baseline="functional",
         baseline_ver="B1")

    # ── ⑤ 变更请求（CR-001 走到"已批准"，供配置项发版引用）─────────────────
    call("change_request", "create", title="星务软件时序调整（BR-01 影响范围必填）",
         requester="星务分系统", ci_nos=["CI-001"], req_nos=["REQ-010"],
         description="成像任务编排时序与数传窗口冲突，需调整软件时序")
    call("change_request", "analyze", cr_no="CR-001",
         impact_analysis="影响 CI-001（星务软件）与 REQ-010；需重跑集成测试 A 组")
    call("change_request", "submit_review", cr_no="CR-001")
    call("change_request", "approve", cr_no="CR-001", comment="影响面清楚，同意实施",
         approver="CCB 主任")
    # 配置项用这个已批准的变更号发版
    call("configuration_item", "release", ci_no="CI-001", change_no="CR-001")
    call("configuration_item", "release", ci_no="CI-002", change_no="CR-001")
    call("change_request", "implement", cr_no="CR-001", note="星务软件 v1 已按该变更发版")

    call("change_request", "create", title="增补数传误码率测试项", requester="测控分系统",
         ci_nos=["CI-005"], req_nos=["REQ-004"], description="地面测试覆盖不足，需增补测试项")
    call("change_request", "analyze", cr_no="CR-002", impact_analysis="仅影响测试用例集，不触发设计变更")
    call("change_request", "submit_review", cr_no="CR-002")
    call("change_request", "create", title="ICD-001 数据字段补充说明", requester="载荷分系统",
         ci_nos=["CI-006"], req_nos=["REQ-005"], description="补充相机遥测字段的量纲说明")

    # ── ⑥ 验证项（对已基线需求的验证矩阵行）───────────────────────────────
    call("verification", "create", req_no="REQ-001", method="analysis", phase="system_functional",
         criteria="轨道仿真连续 30 天，任两次过顶间隔 ≤ 72 h", owner="总体设计部")
    call("verification", "create", req_no="REQ-002", method="test", phase="box_environmental",
         criteria="靶标成像判读 GSD ≤ 1.5 m", owner="载荷分系统")
    call("verification", "create", req_no="REQ-003", method="test", phase="system_environmental",
         criteria="称重结果 ≤ 1200 kg", owner="总体设计部")
    call("verification", "create", req_no="REQ-007", method="test", phase="integrated_vehicle",
         criteria="三轴稳定度 ≤ 0.005°/s（3σ）", owner="控制分系统")
    call("verification", "start", ver_no="VER-001", owner="总体设计部")
    call("verification", "record_result", ver_no="VER-001", result="pass",
         evidence="TR-001 轨道仿真报告", follow_up="")
    call("verification", "close", ver_no="VER-001", note="结论一致，关闭")
    call("verification", "start", ver_no="VER-002", owner="载荷分系统")
    call("verification", "record_result", ver_no="VER-002", result="pass",
         evidence="TR-002 靶标成像判读报告", follow_up="")
    call("verification", "start", ver_no="VER-004", owner="控制分系统")
    call("verification", "record_result", ver_no="VER-004", result="fail",
         evidence="TR-004 稳定度测量报告", follow_up="控制参数重调后复测（已挂行动项）")

    # ── ⑦ 风险（六条覆盖 识别/分析中/缓解中/已关闭/已接受）────────────────
    call("risk", "create", title="长周期器件交期不确定", statement="星上存储器件交期可能推迟 8 周",
         category="schedule", owner="物资部")
    call("risk", "create", title="相机焦距指标受运载包络约束", statement="焦距增大与包络冲突",
         category="technical", req_no="REQ-012", owner="载荷分系统")
    call("risk", "create", title="数传误码率不达标", statement="高仰角条件下误码率可能超标",
         category="technical", req_no="REQ-004", owner="测控分系统")
    call("risk", "create", title="研制经费超支", statement="关键器件涨价导致经费超支风险",
         category="cost", owner="型号办")
    call("risk", "create", title="总装测试场地冲突", statement="与其他型号争用大型试验场地",
         category="programmatic", owner="试验中心")
    call("risk", "create", title="推进剂加注安全风险", statement="加注作业存在人员安全风险",
         category="safety", owner="试验中心")
    call("risk", "assess", risk_no="RSK-002", likelihood=3, consequence=4)     # → 高
    call("risk", "assess", risk_no="RSK-003", likelihood=5, consequence=5)     # → 严重
    call("risk", "assess", risk_no="RSK-004", likelihood=2, consequence=3)     # → 中
    call("risk", "assess", risk_no="RSK-005", likelihood=1, consequence=2)     # → 低
    call("risk", "assess", risk_no="RSK-006", likelihood=2, consequence=2)     # → 低
    call("risk", "mitigate", risk_no="RSK-003", mitigation="提前开展误码率摸底试验并锁定均衡参数")
    call("risk", "mitigate", risk_no="RSK-005", mitigation="提前锁定场地并签互不冲突协议")
    call("risk", "close", risk_no="RSK-005", disposition="mitigated", note="场地已锁定")
    call("risk", "mitigate", risk_no="RSK-006",
         mitigation="按作业规程加注并做双人复核（低等级，走缓解登记后接受）")
    call("risk", "close", risk_no="RSK-006", disposition="accepted", note="低等级，作业规程已覆盖")

    # ── ⑧ 技术度量（含一条超阈值 → 自动开告警；一条已纠正）────────────────
    call("technical_measure", "create", name="数传误码率", category="tpm", direction="lower",
         target_value=1e-7, threshold_value=1e-6, unit="—", req_no="REQ-004", owner="测控分系统")
    call("technical_measure", "create", name="整星质量", category="tpm", direction="lower",
         target_value=1150, threshold_value=1200, unit="kg", req_no="REQ-003", owner="总体设计部")
    call("technical_measure", "create", name="地面分辨率", category="mop", direction="lower",
         target_value=1.2, threshold_value=1.5, unit="m", req_no="REQ-002", owner="载荷分系统")
    call("technical_measure", "create", name="成像任务完成率", category="kpp", direction="higher",
         target_value=0.95, threshold_value=0.85, unit="—", req_no="REQ-010", owner="星务分系统")
    for no in ("TPM-001", "TPM-002", "TPM-003"):
        call("technical_measure", "baseline", tpm_no=no, baseline_ver="B1")
    call("technical_measure", "record", tpm_no="TPM-001", period="2026-Q1", measured_value=8.5e-7,
         note="首轮测试")
    call("technical_measure", "record", tpm_no="TPM-002", period="2026-Q1", measured_value=1225,
         note="初样称重（复材舱板未换）")          # > 阈值 1200 → 超阈值 + open 告警
    call("technical_measure", "record", tpm_no="TPM-003", period="2026-Q1", measured_value=1.6,
         note="初样靶标成像")                       # > 1.5 → 超阈值
    call("technical_measure", "correct", tpm_no="TPM-003",
         corrective_action="更换相机主镜支撑材料并复测（已回到 1.4 m）")
    call("technical_measure", "record", tpm_no="TPM-003", period="2026-Q2", measured_value=1.4,
         note="纠正后复测")
    call("technical_measure", "close", tpm_no="TPM-003", note="复测达标，关闭该度量")

    # ── ⑨ 评审（SRR 已关闭 / PDR 行动项跟踪中 / CDR 计划中）────────────────
    call("review", "create", title="系统需求评审（SRR）", review_type="srr", phase="a",
         subject="系统需求与验证方法完备性", plan_no="PLAN-001", owner="系统工程师")
    call("review", "add_item", review_no="RV-001", item="REQ-001 重访周期可验证", criterion="有验证方法与判据")
    call("review", "add_item", review_no="RV-001", item="REQ-003 质量约束可测量", criterion="有判据与责任人")
    call("review", "start", review_no="RV-001")
    call("review", "conclude", review_no="RV-001", conclusion="pass",
         minutes="需求基线 B1 通过评审，无遗留问题", actions=[])
    call("review", "close", review_no="RV-001", note="无行动项，直接关闭")

    call("review", "create", title="初步设计评审（PDR）", review_type="pdr", phase="b",
         subject="初步设计与接口定义", plan_no="PLAN-002", owner="总体设计部")
    call("review", "add_item", review_no="RV-002", item="ICD-001 字段完备", criterion="数据字典逐项对照")
    call("review", "start", review_no="RV-002")
    call("review", "conclude", review_no="RV-002", conclusion="conditional",
         minutes="设计基本可行，需补充数传链路余量分析",
         actions=[{"content": "补充数传链路余量分析报告", "owner": "测控分系统",
                   "due_date": "2026-05-30"},
                  {"content": "更新 ICD-001 量纲说明", "owner": "载荷分系统",
                   "due_date": "2026-05-15"}])
    call("review", "close_action", review_no="RV-002", seq=2, note="ICD-001 已更新并入库")

    call("review", "create", title="关键设计评审（CDR）", review_type="cdr", phase="c",
         subject="详细设计冻结前评审", plan_no="PLAN-002", owner="总体设计部")

    # ── ⑩ 决策（一条按最高分、一条按依据选非最高分、一条权衡中）────────────
    call("decision", "create", topic="星上存储方案选型", eval_method="weighted_matrix",
         measure_no="TPM-001", issue="存储器件交期与容量冲突，需在两条路线中选一条",
         owner="星务分系统")
    call("decision", "add_criterion", dec_no="DC-001", criterion="容量余量", weight=3)
    call("decision", "add_criterion", dec_no="DC-001", criterion="交期风险", weight=2)
    call("decision", "add_option", dec_no="DC-001", name="方案A：进口大容量存储",
         description="容量 3 Tbit，交期 28 周")
    call("decision", "add_option", dec_no="DC-001", name="方案B：国产存储阵列",
         description="容量 2.4 Tbit，交期 12 周")
    call("decision", "start", dec_no="DC-001")
    call("decision", "score_option", dec_no="DC-001", seq=1, score=90, note="容量优")
    call("decision", "score_option", dec_no="DC-001", seq=2, score=75, note="容量略低")
    call("decision", "conclude", dec_no="DC-001", chosen_seq=1, rationale="容量余量优先，交期风险可控",
         risk_note="需并行落实进口器件替代预案", dissent="物资部倾向方案B")
    call("decision", "implement", dec_no="DC-001", note="已按方案A下单")

    call("decision", "create", topic="数传频段选择", eval_method="trade_study", measure_no="TPM-001",
         issue="X 频段与 Ka 频段权衡", owner="测控分系统")
    call("decision", "add_criterion", dec_no="DC-002", criterion="带宽", weight=2)
    call("decision", "add_criterion", dec_no="DC-002", criterion="地面站适配成本", weight=3)
    call("decision", "add_option", dec_no="DC-002", name="X 频段", description="地面站现成，带宽低")
    call("decision", "add_option", dec_no="DC-002", name="Ka 频段", description="带宽高，需改造地面站")
    call("decision", "start", dec_no="DC-002")
    call("decision", "score_option", dec_no="DC-002", seq=1, score=80, note="成本低")
    call("decision", "score_option", dec_no="DC-002", seq=2, score=70, note="需改造")
    call("decision", "conclude", dec_no="DC-002", chosen_seq=2, rationale="数传速率指标倒逼带宽，接受地面改造",
         risk_note="改造窗口须与地面站计划对齐", dissent="")

    call("decision", "create", topic="推进剂加注方案", eval_method="cost_benefit",
         issue="加注场地与窗口安排", owner="试验中心")
    call("decision", "add_criterion", dec_no="DC-003", criterion="安全裕度", weight=3)
    call("decision", "add_option", dec_no="DC-003", name="方案A：本场加注", description="节省转运")
    call("decision", "start", dec_no="DC-003")

    # ── ⑪ 接口（ICD-001 已发布 / ICD-002 已冻结 / 一条定义中）──────────────
    call("interface", "create", if_name="相机—星务数据接口", if_type="icd",
         provider="相机分系统", consumer="星务分系统",
         icd_content="LVDS 差分；帧周期 20 ms；遥测字段 32 项", ci_no="CI-006",
         owner="载荷分系统")
    call("interface", "release", if_no="IF-001")
    call("interface", "create", if_name="测控应答机—地面测控网接口", if_type="icd",
         provider="测控分系统", consumer="地面测控网",
         icd_content="上行 2 kbps 遥控；下行 8 kbps 遥测；测距体制统一 S 频段", owner="测控分系统")
    call("interface", "release", if_no="IF-002")
    call("interface", "freeze", if_no="IF-002", note="随初步设计冻结，后续变更须走 CR")
    call("interface", "create", if_name="数传—地面接收站接口", if_type="ird",
         provider="数传分系统", consumer="地面应用系统",
         icd_content="Ka 频段；下行 900 Mbps；数据格式 CCSDS", owner="测控分系统")
    call("interface", "create", if_name="整星—运载接口", if_type="icp",
         provider="总体设计部", consumer="运载火箭", icd_content="包络 2.2 m × 3.6 m；质量 ≤ 1200 kg",
         owner="总体设计部")

    # ── ⑩ 工作分解结构（产品树 + 使能性工作 + 变更中 + 已收口）─────────────
    # 先备一条**已批准**的变更（只有「已批准」能被 wbs.change 接受，BR-05）
    call("change_request", "create", title="WBS 载荷分系统子项调整", requester="载荷分系统",
         ci_nos=["CI-001"], description="载荷分系统下需调整子项划分，按配置控制流程走变更")
    call("change_request", "analyze", cr_no="CR-004",
         impact_analysis="仅影响 WBS 分解与工作包归属，不触发设计变更")
    call("change_request", "submit_review", cr_no="CR-004")
    call("change_request", "approve", cr_no="CR-004", comment="分解合理，同意实施",
         approver="项目经理")

    # 一棵三层的产品树；子号由系统按规则分配（**不手写**）
    call("wbs", "create", wbs_no="400000", title="遥感卫星系统", scope_ref="SOW §3 整星范围",
         owner="总体设计部", description="EO-3 遥感卫星，按产品分解")
    call("wbs", "add_child", parent_no="400000", title="星务分系统", owner="星务分系统")
    call("wbs", "add_child", parent_no="400000", title="载荷分系统", owner="载荷分系统")
    # 使能性工作：不是产品，但计入了批准范围（材料 §3.2 图 3-2）；**故意不给范围出处**，
    # 于是停在草稿 —— 演示"没有范围出处不得基线"（BR-03）
    call("wbs", "add_child", parent_no="400000", title="地面支持系统", kind="enabling",
         owner="总体设计部")
    call("wbs", "add_child", parent_no="400000.01", title="星务计算机", owner="星务分系统")
    call("wbs", "add_child", parent_no="400000.01.01", title="星务软件", kind="wp",
         owner="星务分系统")
    # 范围出处与需求覆盖（交叉引用矩阵的 X，材料 §3.3.3）
    call("wbs", "update", wbs_no="400000.01", scope_ref="SOW §3.2 星务范围", req_nos="REQ-010")
    call("wbs", "update", wbs_no="400000.02", scope_ref="SOW §3.3 载荷范围", req_nos="REQ-002")
    call("wbs", "update", wbs_no="400000.01.01", scope_ref="SOW §3.2.1")
    call("wbs", "update", wbs_no="400000.01.01.01", scope_ref="SOW §3.2.1.1")
    # **自顶向下**基线（父未基线时子会被拒，BR-02）
    for no in ("400000", "400000.01", "400000.02", "400000.01.01", "400000.01.01.01"):
        call("wbs", "baseline", wbs_no=no)
    # 变更中：已基线的元素用 CR-004 发起修订（改动挂上变更号，尚未落实）
    call("wbs", "change", wbs_no="400000.02", change_no="CR-004",
         note="载荷分系统子项划分调整，待落实")

    # 另一棵小树：走完 基线 → 逐级收口（已关闭是终态）
    call("wbs", "create", wbs_no="500000", title="地面站配套", scope_ref="SOW §4 地面段",
         owner="地面站")
    call("wbs", "add_child", parent_no="500000", title="天线阵")
    call("wbs", "update", wbs_no="500000.01", scope_ref="SOW §4.1")
    call("wbs", "baseline", wbs_no="500000")
    call("wbs", "baseline", wbs_no="500000.01")
    call("wbs", "close", wbs_no="500000.01", note="天线阵交付完成")
    call("wbs", "close", wbs_no="500000", note="地面站配套整枝收口")

    # ── ⑪ 进度活动（活动网络 + 基线 + 实绩；挂在 WBS **叶子**上）──────────
    # 一条单链网络：起始里程碑 → 编写 → 单元测试 → 完成里程碑（都在「星务软件」工作包下）
    call("activity", "add_milestone", name="星务软件开工", wbs_no="400000.01.01.01",
         phase="start", owner="星务分系统")
    call("activity", "create", name="编写星务软件", wbs_no="400000.01.01.01",
         duration_days=10, predecessors="ACT-001", owner="星务分系统")
    call("activity", "create", name="星务软件单元测试", wbs_no="400000.01.01.01",
         duration_days=5, predecessors="ACT-002", owner="测试组")
    call("activity", "add_milestone", name="星务软件交付", wbs_no="400000.01.01.01",
         predecessors="ACT-003", phase="finish")
    # 另一条挂到「载荷分系统」叶子：**故意不连逻辑链** —— 演示"开口端"（体检会报出来）
    call("activity", "create", name="载荷相机标定", wbs_no="400000.02",
         duration_days=4, owner="载荷分系统")
    # 基线：**显式给 project_start**，免得基线随"今天"漂（BR-07 的基准要可复现）
    call("activity", "baseline", act_nos=["ACT-001", "ACT-002", "ACT-003", "ACT-004"],
         project_start="2026-10-05")
    # 一条**并行支线**：用 SS + 滞后 + 理由（演示四种关系模型，材料 §5.5.8.2）；挂另一个叶子、不参与主线
    call("activity", "create", name="星务软件文档编写", wbs_no="400000.01.01.01",
         duration_days=6, predecessors="ACT-003:SS:3:与单元测试并行，文档随代码走",
         owner="星务分系统")
    # 日历：假日表放**十二月**（不影响上面按十月冻结的基线，只让"跳过非工作日"看得见）
    call("activity", "update_calendar", cal_no="CAL-001", add_holiday="2026-12-25")
    # 实绩：一条已完成（演示 BR-08：基线不动）、一条进行中
    call("activity", "record_progress", act_no="ACT-001", percent_complete=100,
         actual_start="2026-10-05", actual_finish="2026-10-05")
    call("activity", "record_progress", act_no="ACT-002", percent_complete=60,
         actual_start="2026-10-06")

    return {
        "stakeholder": 5, "expectations": 4,
        "requirement": 13, "baselined": 4, "baseline_ver": "B1",
        "tech_plan": 4, "configuration_item": 6, "released_ci": 2,
        "change_request": 3, "cr_implemented": 1, "cr_approved": 1,
        "verification": 4, "ver_closed": 1, "ver_failed": 1,
        "risk": 6, "risk_closed": 2, "risk_accepted": 1,
        "technical_measure": 4, "tpm_exceeded": 1, "tpm_closed": 1,
        "review": 3, "review_closed": 1, "review_tracking": 1,
        "decision": 3, "decision_decided": 2, "decision_implemented": 1,
        "interface": 4, "if_frozen": 1, "if_released": 2,
        # WBS（2026-09-26 并入）：8 个元素 —— 已基线 4 / 变更中 1 / 已关闭 2 / 草稿 1
        "wbs": 8, "wbs_baselined": 4, "wbs_in_change": 1, "wbs_closed": 2, "wbs_draft": 1,
        # 进度活动（2026-09-26 并入）：5 条 —— 已基线 4 / 已完成 1 / 进行中 1 / 计划 3
        "activity": 6, "activity_baselined": 4, "activity_completed": 1,
        "activity_in_progress": 1,
    }


def main():
    ap = argparse.ArgumentParser(description="nasa_pms 演示数据造数（写入真库）")
    ap.add_argument("--keep", action="store_true", help="不清空，直接追加（调试用）")
    args = ap.parse_args()

    from fde_platform.runtime import FdePlatform

    if not args.keep:
        sys.stdout.write("① 清空本组 %d 个应用库的表…\n" % len(APPS))
        clear()
    sys.stdout.write("② 按故事线造数（经真实服务）…\n")
    pf = FdePlatform()
    pf.load_all()
    for app in APPS:
        assert pf.handle(f"{GROUP}/{app}") is not None, f"{app} 未加载"
    want = seed(pf)

    sys.stdout.write("\n③ 设计态摘要（与 verify_demo.py 同一口径）\n")
    for k, v in want.items():
        sys.stdout.write(f"   {k:20s} {v}\n")
    sys.stdout.write("\n✓ 造数完成。建议接着跑：python app/%s/demo/verify_demo.py\n" % GROUP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
