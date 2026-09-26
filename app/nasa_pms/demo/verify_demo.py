"""nasa_pms 演示环境**体检**（是不是「能开演的状态」）。

**为什么需要一个「是不是演示环境」的哨兵**（这条是从 `scripts/verify_agent_quality.py` 学来的，
那段 docstring 把它写得很清楚）：
> 环境没造好时最坏的失败模式是：agent 说"没有要处理的"、ground truth 也是"没有" ——
> **两边一致地错，测试照样绿**。

所以调用方（人、或将来给 nasa_pms 写的智能体质量场景）**先跑本脚本**：它按**身份**校验
（不是按数量 —— 数量变了可能是"环境更完整了"），任何一个关键对象缺失就明确报"不是演示环境，
请先跑 `demo_build.py`"，而不是把环境问题当成「业务上确实没有」。

    python app/nasa_pms/demo/verify_demo.py        # rc=0 是演示环境；rc=2 不是（照 PSC 的 eval 口径）

校验一律经**服务**（`platform.call`）—— 顺带也是一次只读的接口冒烟。
"""
from __future__ import annotations

import os
import pathlib
import sys


def _project_root() -> pathlib.Path:
    p = pathlib.Path(__file__).resolve().parent
    while not (p / "fde_platform").is_dir():
        if p.parent == p:
            raise SystemExit("找不到项目根：向上未发现 fde_platform/")
        p = p.parent
    return p


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

GROUP = "nasa_pms"

# 设计态的**关键对象**（按身份校验）：(应用.服务/入参, 期望) —— 全都来自 `demo_seed.py` 的故事线
CHECKS = [
    # (调用, 比的字段, 期望值, 为什么) —— **一律按身份校验**，不比数量
    ("stakeholder.get(sh_no=SH-001)", "name", "国家遥感中心", "主数据 5 条之一"),
    ("requirement.get(req_no=REQ-001)", "status", "baselined", "需求基线 B1 已建立"),
    ("requirement.get(req_no=REQ-012)", "req_type", "derived", "派生需求挂着上游（BR-02）"),
    ("requirement.get(req_no=REQ-013)", "status", "pending_review", "有一条停在「待评审」（评审门的入口服务存在）"),
    ("tech_plan.get(plan_no=PLAN-001)", "status", "approved", "SEMP 已批准"),
    ("tech_plan.get(plan_no=PLAN-004)", "status", "revised", "有「已修订」的计划（版本台账两条）"),
    ("configuration_item.get(ci_no=CI-001)", "status", "released", "已发布配置项（发版带变更号）"),
    ("change_request.get(cr_no=CR-001)", "status", "implemented", "变更请求走到已实施"),
    ("change_request.get(cr_no=CR-002)", "status", "reviewing", "有「审批中」的变更（审批链可演示）"),
    ("verification.get(ver_no=VER-001)", "status", "closed", "验证项走完规划→通过→关闭"),
    ("verification.get(ver_no=VER-004)", "status", "failed", "有「不通过」的验证项（覆盖读数用）"),
    ("risk.get(risk_no=RSK-003)", "status", "mitigating", "严重风险在缓解中"),
    ("risk.get(risk_no=RSK-006)", "status", "accepted", "低等级风险已接受关闭"),
    ("technical_measure.get(tpm_no=TPM-002)", "status", "exceeded", "超阈值度量（告警已开）"),
    ("technical_measure.get(tpm_no=TPM-003)", "status", "closed", "已纠正并关闭的度量"),
    ("review.get(review_no=RV-001)", "status", "closed", "评审已关闭"),
    ("review.get(review_no=RV-002)", "status", "tracking", "行动项跟踪中的评审"),
    ("decision.get(dec_no=DC-001)", "status", "implemented", "决策已实施"),
    ("decision.get(dec_no=DC-003)", "status", "weighing", "有权衡中的决策"),
    ("interface.get(if_no=IF-002)", "status", "frozen", "接口已冻结"),
    # WBS（2026-09-26 并入）：四个状态档位各有样本，且**父子关系**可查
    ("wbs.get(wbs_no=400000)", "status", "baselined", "整星 WBS 已基线（受配置控制）"),
    ("wbs.get(wbs_no=400000.02)", "status", "in_change", "有一条挂在变更中的元素（变更号 CR-004）"),
    ("wbs.get(wbs_no=400000.03)", "kind", "enabling", "有使能性工作样本（非产品但计入范围）"),
    ("wbs.get(wbs_no=400000.03)", "status", "draft", "它没有范围出处 → 停在草稿（BR-03）"),
    ("wbs.get(wbs_no=400000.01.01.01)", "kind", "wp", "最低层是工作包（第三层）"),
    ("wbs.get(wbs_no=500000)", "status", "closed", "另一棵树走完基线→收口（终态）"),
    # 进度活动（2026-09-26 并入）：三态齐，且**基线冻在派生日期上**、实绩没改基线
    ("activity.get(act_no=ACT-001)", "status", "completed", "起始里程碑回填 100% → 已完成"),
    ("activity.get(act_no=ACT-002)", "status", "in_progress", "有一条进行中的活动（60%）"),
    ("activity.get(act_no=ACT-003)", "status", "planned", "有一条还没开工的活动"),
    ("activity.get(act_no=ACT-004)", "kind", "milestone", "完成里程碑（工期恒 0）"),
    ("activity.get(act_no=ACT-001)", "baseline_start", "2026-10-05",
     "基线冻在**派生日期**上（不是手填的）"),
    ("activity.get(act_no=ACT-005)", "baseline_start", None,
     "有一条未基线的活动（它还是开口端）"),
    ("activity.get(act_no=ACT-004)", "predecessors", "ACT-003",
     "主线是完成→开始（默认关系）"),
    ("activity.get(act_no=ACT-006)", "predecessors", "ACT-003:SS:3:与单元测试并行，文档随代码走",
     "另有一条 **SS + 滞后 + 理由**（§5.5.8.2 的四种关系模型）"),
    ("interface.get(if_no=IF-001)", "status", "released", "接口已发布"),
]
COUNT_CHECKS = [
    ("stakeholder", "list", {}, 5, "利益相关者"),
    ("requirement", "list", {}, 13, "需求"),
    ("risk", "list", {}, 6, "风险"),
    ("technical_measure", "list", {}, 4, "技术度量"),
    ("wbs", "list", {}, 8, "WBS 元素"),
    ("activity", "list", {}, 6, "进度活动"),
]


def main() -> int:
    from fde_platform.runtime import FdePlatform

    pf = FdePlatform()
    pf.load_all()

    def call(app, svc, **kw):
        try:
            return pf.call(f"{GROUP}/{app}", svc, **kw)
        except Exception as e:                              # noqa: BLE001
            return {"__error__": f"{type(e).__name__}: {e}"}

    problems = []
    sys.stdout.write("nasa_pms 演示环境体检（按身份校验，不看数量）\n" + "-" * 62 + "\n")
    for spec, field, want, why in CHECKS:
        app, rest = spec.split(".", 1)
        svc, arg = rest.split("(", 1)
        key, val = arg.rstrip(")").split("=")
        got = call(app, svc, **{key: val})
        actual = got.get(field) if isinstance(got, dict) else got
        ok = actual == want
        sys.stdout.write(f"  {'✓' if ok else '✗'} {spec:34s} {field}={actual}（期望 {want}；{why}）\n")
        if not ok:
            problems.append(f"{spec}：{field} 期望 {want}，实际 {actual}")

    for app, svc, kw, want, label in COUNT_CHECKS:
        got = call(app, svc, **kw)
        n = got.get("total") if isinstance(got, dict) else None
        ok = n == want
        sys.stdout.write(f"  {'✓' if ok else '✗'} {app}.{svc} 的 {label}条数 → {n}（期望 {want}）\n")
        if not ok:
            problems.append(f"{app}.{svc}.total：期望 {want}，实际 {n}")

    # 作废理由必须**落库**（`obsolete(reason=…)` → `void_reason`；2026-09-25 起留痕）
    ob = call("requirement", "get", req_no="REQ-012")
    ok_ob = isinstance(ob, dict) and ob.get("status") == "obsolete" and bool((ob.get("void_reason") or "").strip())
    sys.stdout.write(f"  {'✓' if ok_ob else '✗'} REQ-012 作废理由已落库 → "
                     f"{(ob.get('void_reason') if isinstance(ob, dict) else ob)!r}\n")
    if not ok_ob:
        problems.append("REQ-012：作废理由未落库（void_reason 为空）")

    if problems:
        sys.stdout.write("\n✗ **不是演示环境**（或演示环境已被改动）：\n")
        for p in problems:
            sys.stdout.write(f"    · {p}\n")
        sys.stdout.write("\n请先重建：python app/nasa_pms/demo/demo_build.py\n"
                         "（rc=2 是本脚本约定的「环境未就绪」，与 PSC 的 `verify_agent_quality.py` 同口径）\n")
        return 2
    sys.stdout.write("\n✓ 是演示环境：关键对象按身份齐全，状态分布覆盖各档。\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
