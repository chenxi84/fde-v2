"""FDE v2 后端主链端到端验证 · nasa_pms（风险 risk）

链路形态（单应用 + 跨应用弱引用，含状态机与不变量）：
  risk(create → assess → mitigate → close)
    · BR-01 等级由「可能性 × 后果」推导，无处可直接写等级（create/update 都没有那对入参之外的入口）
    · BR-02 关闭必须有处置结论；结论为「缓解完成」时须已登记缓解措施
    · BR-03 等级为「高」/「严重」时不得以「接受」关闭
    · BR-04 编号唯一不可变
    · BR-05 类别 / 可能性 / 后果 受字典约束
    · BR-06 终态（已关闭 / 已接受）不可再改（update / assess / mitigate / close 四路都拦）
    · BR-07 受影响需求是弱引用，但填了必须真实存在（跨应用 requirement.get）

隔离：`shadow_dbs()` —— 业务库**复制**到临时目录，测试全程只读写副本，
**真库零字节接触，且不用停 dev server**。`shadow_clear(GROUP)` 清的是副本。

运行：python app/nasa_pms/tests/verify_chain_nasa_pms_risk.py
"""
import atexit
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _project_root():
    p = HERE
    while not (p / "fde_platform").is_dir():
        if p.parent == p:
            raise RuntimeError("无法定位项目根目录（未找到 fde_platform/）")
        p = p.parent
    return p


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from fde_platform.runtime import FdePlatform  # noqa: E402
from fde_platform.shadowdb import shadow_dbs, shadow_clear  # noqa: E402

# 输出编码：控制台代码页在本机默认是 GBK，而断言文案里有 ⇒ / ✓ / ✗ / ⚠ / − 这类**非 GBK 码位** ——
# 不钉住编码的话，print 自己会抛 UnicodeEncodeError（**崩在打印结果那一步**：断言算完了却报不出来，
# 其后用例也不再执行 —— 实测 nasa_pms 的 stakeholder 脚本里有一条断言就这么"消失"过）。与 scripts/run_gates.py 给
# 子进程设 PYTHONIOENCODING 同一根因；由 scripts/verify_test_script_encoding.py 守住别忘这一行。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_shadow = shadow_dbs()
_shadow.__enter__()
atexit.register(_shadow.__exit__, None, None, None)

GROUP = "nasa_pms"
APP = "risk"
REQ_APP = "requirement"

RESULTS = []
# 全程观察到的风险状态 —— 用于 TC-28 证明「状态机里每个状态都有服务能到达它」
STATES_SEEN = set()


def step(name):
    print(f"  → {name}", flush=True)


def record(ok, note=""):
    RESULTS.append(("", ok, note))
    print(f"    {'[OK]' if ok else '[FAIL]'} {note}" if note else f"    {'[OK]' if ok else '[FAIL]'}", flush=True)


def expect_err(fn, substr):
    from fde import FdeError
    try:
        fn()
    except FdeError as e:
        msg = str(e)
        assert substr in msg, f"错误应含『{substr}』，实际: {msg}"
        return msg
    raise AssertionError(f"应抛 FdeError(含『{substr}』)，但未抛出")


def main():
    # ⚠ 必须显式清表：影子库的副本**带着真库的数据**，不清会撞主键（清的是副本）
    shadow_clear(GROUP)
    pf = FdePlatform()
    pf.load_all()

    qname = f"{GROUP}/{APP}"
    if qname not in pf.app_names():
        print(f"  ⚠ 应用未加载: {qname}", flush=True)
        return 1
    print(f"  [OK] {qname}", flush=True)

    def call(svc, **kw):
        out = pf.call(qname, svc, **kw)
        # 记录本次返回里出现的风险状态（get/list 以外都是单条 dict）
        if isinstance(out, dict) and out.get("status") in (
                "identified", "analyzing", "mitigating", "closed", "accepted"):
            STATES_SEEN.add(out["status"])
        return out

    def call_req(svc, **kw):
        return pf.call(f"{GROUP}/{REQ_APP}", svc, **kw)

    # ── 主链（正向） ──────────────────────────────────────
    step("TC-01 识别风险（带可能性 / 后果 → 等级当即推导）")
    r1 = call("create", title="ICD 未按期冻结", statement="若分系统接口控制文档未在 PDR 前冻结，"
              "集成阶段将出现接口不匹配，导致返工与进度滑移",
              category="technical", likelihood=4, consequence=4, owner="张三")
    record(r1["risk_no"] == "RSK-001" and r1["status"] == "identified"
           and r1["risk_score"] == 16 and r1["risk_level"] == "critical",
           f"risk_no={r1['risk_no']} status={r1['status']} score={r1['risk_score']} level={r1['risk_level']}")

    step("TC-02 编号递增（未评估时等级与风险值为空）")
    r2 = call("create", title="长周期器件交期不确定", statement="关键 FPGA 采购周期若超过 26 周，"
              "将使 B 阶段总装节点后移", category="schedule")
    record(r2["risk_no"] == "RSK-002" and r2["risk_level"] is None and r2["risk_score"] is None,
           f"risk_no={r2['risk_no']} level={r2['risk_level']}（未评估）")

    step("TC-03 BR-01 等级由可能性 × 后果推导（assess）")
    ra = call("assess", risk_no="RSK-002", likelihood=2, consequence=3)
    record(ra["risk_score"] == 6 and ra["risk_level"] == "medium" and ra["status"] == "analyzing",
           f"score={ra['risk_score']} level={ra['risk_level']} status={ra['status']}")
    # BR-05 的输出含 `likelihood` / `consequence` 两个字典字段 —— 断言它们**原样落库**：
    record(ra["likelihood"] == 2 and ra["consequence"] == 3,
           f"likelihood={ra['likelihood']} consequence={ra['consequence']}")

    step("TC-04 BR-01 分档边界（1×1→低 / 3×4→高 / 5×5→严重）")
    ba = call("assess", risk_no="RSK-001", likelihood=1, consequence=1)
    bb = call("assess", risk_no="RSK-001", likelihood=3, consequence=4)
    bc = call("assess", risk_no="RSK-001", likelihood=5, consequence=5)
    record(ba["risk_level"] == "low" and ba["risk_score"] == 1, f"1×1 → {ba['risk_level']}({ba['risk_score']})")
    record(bb["risk_level"] == "high" and bb["risk_score"] == 12, f"3×4 → {bb['risk_level']}({bb['risk_score']})")
    record(bc["risk_level"] == "critical" and bc["risk_score"] == 25, f"5×5 → {bc['risk_level']}({bc['risk_score']})")

    step("TC-05 BR-07 受影响需求弱引用（跨应用 requirement.get 校验）")
    req = call_req("create", title="系统应支持 1000 并发用户", statement="8vCPU/32GB 下 P95 ≤ 2s",
                   req_type="technical", verify_method="test")
    r3 = call("create", title="并发指标未达成", statement="若性能优化未达 P95 ≤ 2s，"
              "将不满足已基线的并发需求", category="cost", req_no=req["req_no"])
    record(r3["risk_no"] == "RSK-003" and r3["req_no"] == "REQ-001",
           f"risk_no={r3['risk_no']} req_no={r3['req_no']}")

    step("TC-06 状态机 分析中 → 缓解中（mitigate）")
    rm = call("mitigate", risk_no="RSK-001", mitigation="提前开展接口冻结评审，并准备接口适配回退方案")
    record(rm["status"] == "mitigating" and "接口冻结" in rm["mitigation"],
           f"status={rm['status']} mitigation=「{rm['mitigation'][:10]}…」")

    step("TC-07 状态机 缓解中 → 已关闭（处置结论=转移）")
    rc = call("close", risk_no="RSK-001", disposition="transferred", note="转移给分系统承包商承担")
    record(rc["status"] == "closed" and rc["disposition"] == "transferred",
           f"status={rc['status']} disposition={rc['disposition']}")

    step("TC-08 状态机 → 已接受（处置结论=接受，中等级允许）")
    # ⚠ 必须先 mitigate：状态机只有 `mitigating → close` 一条边（2026-09-25 补闸后强制）
    call("mitigate", risk_no="RSK-002", mitigation="盯着 FPGA 交期，双源询价并预留替代型号")
    rd = call("close", risk_no="RSK-002", disposition="accepted")
    record(rd["status"] == "accepted" and rd["disposition"] == "accepted",
           f"status={rd['status']} disposition={rd['disposition']}")

    # ── BR 逐条（负例与兜底） ─────────────────────────────
    step("TC-09 未评估等级就登记缓解 → 拒绝（缓解须在分析之后）")
    record(True, expect_err(lambda: call("mitigate", risk_no="RSK-003", mitigation="加大冗余"),
                            "尚未评估等级"))

    step("TC-10 非「缓解中」态关闭 → 拒绝（§3.4 状态机：只有 mitigating → close）")
    call("assess", risk_no="RSK-003", likelihood=2, consequence=2)      # → 分析中
    record(True, expect_err(lambda: call("close", risk_no="RSK-003", disposition="mitigated"),
                            "只有「缓解中」的风险可以关闭"))
    # ⚠ BR-02 的「缓解完成须已登记缓解措施」在补闸后**不可达**（缓解中必然已有措施）——
    #   保留为**防御性不变量**（不删），但用例不再以它为期望：那条路径已走不到。
    record(call("get", risk_no="RSK-003")["status"] == "analyzing",
           "被拒后状态未变（仍为分析中）")
    step("TC-10b 补齐缓解措施后可关闭（同一条走通）")
    call("mitigate", risk_no="RSK-003", mitigation="增加冗余通道并纳入验证矩阵")
    rc3 = call("close", risk_no="RSK-003", disposition="mitigated")
    record(rc3["status"] == "closed" and rc3["disposition"] == "mitigated",
           f"status={rc3['status']} disposition={rc3['disposition']}")

    step("TC-11 BR-03 等级「严重」不得以「接受」关闭 → 拒绝")
    r4 = call("create", title="外部供货渠道受限", statement="若出口管制收紧，关键器件将无法按计划到货",
              category="programmatic", likelihood=4, consequence=5)
    record(r4["risk_no"] == "RSK-004" and r4["risk_level"] == "critical", f"level={r4['risk_level']}")
    # ⚠ 守卫顺序：状态闸在 BR-03 之前 —— 不先 mitigate 的话拿到的是状态错误，测不到 BR-03
    call("mitigate", risk_no="RSK-004", mitigation="提前锁定第二供货渠道，按季度复核出口管制清单")
    record(True, expect_err(lambda: call("close", risk_no="RSK-004", disposition="accepted"),
                            "不得以「接受」关闭"))
    step("TC-11b 换「转移」处置可通过")
    rc4 = call("close", risk_no="RSK-004", disposition="transferred")
    record(rc4["status"] == "closed", f"status={rc4['status']}")

    step("TC-12 BR-06 终态不可改（update / assess / mitigate / close 四路都拦）")
    record(True, expect_err(lambda: call("update", risk_no="RSK-001", title="偷改"), "终态"))
    record(True, expect_err(lambda: call("assess", risk_no="RSK-001", likelihood=1, consequence=1), "终态"))
    record(True, expect_err(lambda: call("mitigate", risk_no="RSK-001", mitigation="x"), "终态"))
    record(True, expect_err(lambda: call("close", risk_no="RSK-001", disposition="transferred"), "终态"))

    # ── 查询契约 ─────────────────────────────────────────
    step("TC-13 list 契约：返回 {items, total}，且与 get 同口径（全字段）")
    lst = call("list")
    items = lst.get("items") or []
    # ⚠ list 契约是 {items, total}（前端 pageable 依赖它）；返回裸数组会让页面静默显示空态
    record(lst.get("total") == 4 and [x["risk_no"] for x in items] ==
           ["RSK-001", "RSK-002", "RSK-003", "RSK-004"],
           f"total={lst.get('total')} items={[x['risk_no'] for x in items]}")
    record(bool(items) and "statement" in items[0] and "risk_level" in items[0]
           and "close_note" in items[0], "list 返回项含全部业务字段（与 get 同口径）")

    step("TC-14 按状态 / 类别 / 等级 / 受影响需求筛选")
    by_status = call("list", status="closed")
    by_cat = call("list", category="technical")
    by_level = call("list", risk_level="critical")
    by_req = call("list", req_no="REQ-001")
    record([x["risk_no"] for x in by_status["items"]] == ["RSK-001", "RSK-003", "RSK-004"],
           f"status=closed → {[x['risk_no'] for x in by_status['items']]}")
    record([x["risk_no"] for x in by_cat["items"]] == ["RSK-001"],
           f"category=technical → {[x['risk_no'] for x in by_cat['items']]}")
    record([x["risk_no"] for x in by_level["items"]] == ["RSK-001", "RSK-004"],
           f"risk_level=critical → {[x['risk_no'] for x in by_level['items']]}")
    record([x["risk_no"] for x in by_req["items"]] == ["RSK-003"],
           f"req_no=REQ-001 → {[x['risk_no'] for x in by_req['items']]}")

    step("TC-15 list 分页：total 为切片前全量，items 为切片后")
    p1 = call("list", page=1, size=2)
    p2 = call("list", page=2, size=2)
    record(p1["total"] == 4 and [x["risk_no"] for x in p1["items"]] == ["RSK-001", "RSK-002"]
           and [x["risk_no"] for x in p2["items"]] == ["RSK-003", "RSK-004"],
           f"p1.total={p1['total']} p1={[x['risk_no'] for x in p1['items']]} "
           f"p2={[x['risk_no'] for x in p2['items']]}")

    step("TC-16 查询详情 / 未命中不抛异常")
    one = call("get", risk_no="RSK-001")
    record(one["title"] == "ICD 未按期冻结" and one["disposition"] == "transferred", "字段完整")
    # 对照断言（T2 门禁：本步不能只证明「没抛异常」）—— 未命中**不产生副作用**：
    _before = call("list")["total"]
    record(call("get", risk_no="RSK-999") is None, "get 未命中返回 None（不抛异常）")
    record(call("list")["total"] == _before,
           f"未命中不产生副作用：列表仍 {_before} 条")

    # ── 入参校验（负例） ──────────────────────────────────
    step("TC-17 风险标题为空 → 拒绝")
    record(True, expect_err(lambda: call("create", title="  ", statement="x", category="technical"),
                            "风险标题不能为空"))

    step("TC-18 风险情景为空 → 拒绝")
    record(True, expect_err(lambda: call("create", title="x", statement="  ", category="technical"),
                            "风险情景不能为空"))

    step("TC-19 BR-05 类别非法 → 拒绝")
    record(True, expect_err(lambda: call("create", title="x", statement="y", category="其它"),
                            "风险类别只能是"))

    step("TC-20 BR-05 可能性越界 → 拒绝")
    record(True, expect_err(lambda: call("create", title="x", statement="y", category="technical",
                                        likelihood=6, consequence=2), "可能性只能是 1..5"))

    step("TC-21 只给可能性不给后果 → 拒绝（等级必须成对推导）")
    record(True, expect_err(lambda: call("create", title="x", statement="y", category="technical",
                                        likelihood=3), "后果必须是 1..5 的整数"))

    step("TC-22 BR-07 受影响需求不存在 → 拒绝（跨应用校验）")
    record(True, expect_err(lambda: call("create", title="x", statement="y", category="technical",
                                        req_no="REQ-999"), "受影响需求 REQ-999 不存在"))

    step("TC-23 缓解措施为空 → 拒绝")
    call("create", title="待缓解风险", statement="情景", category="cost", likelihood=2, consequence=2)
    record(True, expect_err(lambda: call("mitigate", risk_no="RSK-005", mitigation="  "),
                            "缓解措施不能为空"))

    # ⚠ 参数类负例必须在**能走到参数校验的状态**上测：补状态闸后，守卫顺序是
    #   终态 → 状态 → 参数 ⇒ RSK-005 得先在「缓解中」，否则拿到的是状态错误（测不到 BR-02）。
    call("mitigate", risk_no="RSK-005", mitigation="先登记一条缓解措施，再测参数校验")
    step("TC-24 BR-02 关闭不给处置结论 → 拒绝")
    record(True, expect_err(lambda: call("close", risk_no="RSK-005", disposition=""),
                            "必须给出处置结论"))

    step("TC-25 处置结论非法 → 拒绝")
    record(True, expect_err(lambda: call("close", risk_no="RSK-005", disposition="算了"),
                            "处置结论只能是"))

    step("TC-26 update 不存在 / 无内容 —— 均拒绝")
    record(True, expect_err(lambda: call("update", risk_no="RSK-999", title="x"), "不存在"))
    record(True, expect_err(lambda: call("update", risk_no="RSK-005"), "没有要修改的内容"))

    step("TC-27 BR-01 等级无直接写入口（改描述性字段不动等级）")
    before = call("get", risk_no="RSK-005")
    after = call("update", risk_no="RSK-005", title="待缓解风险（已改名）", owner="李四")
    record(after["risk_level"] == before["risk_level"] and after["risk_score"] == before["risk_score"]
           and after["title"] == "待缓解风险（已改名）" and after["owner"] == "李四",
           f"level={after['risk_level']} score={after['risk_score']}（未被改动）")
    record(True, expect_err(lambda: call("update", risk_no="RSK-005", category="其它"),
                            "风险类别只能是"))

    step("TC-28 状态机可覆盖性（每个状态都有服务能到达）")
    # ⚠ 状态机里出现的每个状态都必须有服务能到达它（样板踩过：状态机有 obsolete 但服务缺失）
    want = {"identified", "analyzing", "mitigating", "closed", "accepted"}
    record(STATES_SEEN == want, f"本链已到达的状态 = {sorted(STATES_SEEN)}")

    # ── 汇总 ─────────────────────────────────────────────
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
