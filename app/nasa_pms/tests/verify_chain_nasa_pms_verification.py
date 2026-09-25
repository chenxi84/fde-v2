"""FDE v2 后端主链端到端验证 · nasa_pms（验证项 verification）

链路形态（单应用 + **跨应用强关联**，含完整状态机与两条不变量）：
  verification(create → start → record_result → close)
    · BR-01 验证项必须挂在一条需求上，且该需求必须真实存在（跨应用 requirement.get）
    · BR-02 判定必须有证据；判定「不通过」必须同时记录后续处置（聚合根卡 6 的 I-2）
    · BR-03 判定不可重复；已判定不得改写验证方法 / 阶段；已关闭为终态
    · BR-04 编号唯一且不可变（update 字段白名单里没有 ver_no）
    · BR-05 验证方法 / 验证阶段受字典约束
    · BR-06 状态机守卫：只有规划能开始执行、只有执行中能判定、只有已判定能关闭

隔离：`shadow_dbs()` —— 业务库**复制**到临时目录，测试全程只读写副本，
**真库零字节接触，且不用停 dev server**。`shadow_clear(GROUP)` 清的是副本。

运行：python app/nasa_pms/tests/verify_chain_nasa_pms_verification.py
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
APP = "verification"
REQ_APP = "requirement"

RESULTS = []
# 全程观察到的验证项状态 —— 用于 TC-28 证明「状态机里每个状态都有服务能到达它」
STATES_SEEN = set()


def step(name):
    print(f"  → {name}", flush=True)


def record(ok, note=""):
    RESULTS.append((ok, note))
    print(f"    {'[OK]' if ok else '[FAIL]'} {note}" if note else f"    {'[OK]' if ok else '[FAIL]'}",
          flush=True)


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
        if isinstance(out, dict) and out.get("status") in (
                "planned", "executing", "passed", "failed", "closed"):
            STATES_SEEN.add(out["status"])
        return out

    def call_req(svc, **kw):
        return pf.call(f"{GROUP}/{REQ_APP}", svc, **kw)

    # ── 前置：需求（验证项的强关联上游）────────────────────
    req1 = call_req("create", title="系统应支持 1000 并发用户",
                    statement="8vCPU/32GB 下 P95 响应 ≤ 2s", req_type="technical",
                    verify_method="test")
    req2 = call_req("create", title="星上存储器容量不小于 2Tb",
                    statement="在轨工作 5 年内不出现容量不足", req_type="system",
                    verify_method="analysis")
    step("前置：已录入需求 REQ-001 / REQ-002（供跨应用强关联校验）")
    record(req1["req_no"] == "REQ-001" and req2["req_no"] == "REQ-002",
           f"{req1['req_no']} / {req2['req_no']}")

    # ── 主链（正向） ──────────────────────────────────────
    step("TC-01 规划验证项（验证矩阵的一行：需求 × 验证方法 × 阶段）")
    r1 = call("create", req_no="REQ-001", method="test", phase="system_functional",
              criteria="P95 ≤ 2s，连续 30 分钟无错误", owner="张三")
    record(r1["ver_no"] == "VER-001" and r1["status"] == "planned" and r1["result"] is None
           and r1["req_no"] == "REQ-001" and r1["method"] == "test",
           f"ver_no={r1['ver_no']} status={r1['status']} req_no={r1['req_no']} result={r1['result']}")

    step("TC-02 编号递增（同一需求可挂多条验证项，多轮验证各占一行）")
    r2 = call("create", req_no="REQ-002", method="analysis", phase="box_functional",
              owner="李四")
    r3 = call("create", req_no="REQ-001", method="inspection", phase="end_to_end")
    record(r2["ver_no"] == "VER-002" and r3["ver_no"] == "VER-003",
           f"{r2['ver_no']} / {r3['ver_no']}")

    step("TC-03 BR-01 对应需求不存在 → 拒绝（跨应用 requirement.get）")
    record(True, expect_err(lambda: call("create", req_no="REQ-999", method="test",
                                        phase="on_orbit"), "对应需求 REQ-999 不存在"))

    step("TC-04 BR-01 对应需求为空 → 拒绝（强关联：没有需求就没有矩阵行）")
    record(True, expect_err(lambda: call("create", req_no="  ", method="test",
                                        phase="on_orbit"), "对应需求不能为空"))

    step("TC-05 BR-05 验证方法字典校验")
    record(True, expect_err(lambda: call("create", req_no="REQ-001", method="",
                                        phase="on_orbit"), "验证方法不能为空"))
    record(True, expect_err(lambda: call("create", req_no="REQ-001", method="猜",
                                        phase="on_orbit"), "验证方法只能是"))

    step("TC-06 BR-05 验证阶段字典校验")
    record(True, expect_err(lambda: call("create", req_no="REQ-001", method="test",
                                        phase=""), "验证阶段不能为空"))
    record(True, expect_err(lambda: call("create", req_no="REQ-001", method="test",
                                        phase="出厂前"), "验证阶段只能是"))

    step("TC-07 状态机 规划 → 执行中（start）")
    rs = call("start", ver_no="VER-001")
    record(rs["status"] == "executing", f"status={rs['status']}")

    step("TC-08 重复开始执行 → 拒绝")
    record(True, expect_err(lambda: call("start", ver_no="VER-001"), "已在执行中"))

    step("TC-09 BR-06 规划中的验证项不能直接判定（须先执行）")
    record(True, expect_err(lambda: call("record_result", ver_no="VER-003", result="pass",
                                        evidence="抽查记录"), "请先开始执行"))

    step("TC-10 BR-02 判定没有证据 → 拒绝")
    record(True, expect_err(lambda: call("record_result", ver_no="VER-001", result="pass",
                                        evidence="  "), "判定必须有证据"))

    step("TC-11 BR-05 判定结果字典校验")
    record(True, expect_err(lambda: call("record_result", ver_no="VER-001", result="maybe",
                                        evidence="某报告 §3"), "判定结果只能是"))

    step("TC-12 BR-02 判定「不通过」却没给后续处置 → 拒绝（I-2）")
    record(True, expect_err(lambda: call("record_result", ver_no="VER-001", result="fail",
                                        evidence="某报告 §3", follow_up="  "),
                            "必须同时记录后续处置"))

    step("TC-13 判定通过（执行中 → 通过，证据与判定同事务落库）")
    rp = call("record_result", ver_no="VER-001", result="pass",
              evidence="性能测试报告 TR-001 §4.2：P95 = 1.4s")
    record(rp["status"] == "passed" and rp["result"] == "pass"
           and "TR-001" in rp["evidence"],
           f"status={rp['status']} result={rp['result']}")

    step("TC-14 BR-03 重复判定 → 拒绝（需重新验证请另建验证项）")
    record(True, expect_err(lambda: call("record_result", ver_no="VER-001", result="fail",
                                        evidence="x", follow_up="y"), "不能重复判定"))

    step("TC-15 判定不通过（带后续处置）")
    call("start", ver_no="VER-002")
    rf = call("record_result", ver_no="VER-002", result="fail",
              evidence="热真空试验报告 TR-002：-40℃ 下写入失败 3 次",
              follow_up="更换存储器件型号后复验（复验项另建）")
    record(rf["status"] == "failed" and rf["result"] == "fail"
           and "更换存储器件" in rf["follow_up"],
           f"status={rf['status']} follow_up=「{rf['follow_up'][:8]}…」")

    step("TC-16 BR-06 只有已判定的验证项才能关闭（规划 / 执行中都拒绝）")
    record(True, expect_err(lambda: call("close", ver_no="VER-003"),
                            "只有已判定的验证项才能关闭"))
    call("start", ver_no="VER-003")
    record(True, expect_err(lambda: call("close", ver_no="VER-003"),
                            "只有已判定的验证项才能关闭"))

    step("TC-17 判定通过（第三条）—— 供后续 BR-03 用例")
    rp3 = call("record_result", ver_no="VER-003", result="pass",
               evidence="外观检验记录 IN-001：标识齐全、无机械损伤")
    record(rp3["status"] == "passed", f"status={rp3['status']}")

    step("TC-18 BR-03 已判定不得改写验证方法 / 验证阶段；成功判据与责任人仍可补")
    record(True, expect_err(lambda: call("update", ver_no="VER-003", method="test"),
                            "不能改写验证方法与验证阶段"))
    record(True, expect_err(lambda: call("update", ver_no="VER-003", phase="on_orbit"),
                            "不能改写验证方法与验证阶段"))
    ru = call("update", ver_no="VER-003", criteria="标识与外观符合图样要求", owner="王五")
    record(ru["criteria"] == "标识与外观符合图样要求" and ru["owner"] == "王五"
           and ru["method"] == "inspection",
           f"criteria 已补，method 仍为 {ru['method']}")

    step("TC-19 关闭验证项（已判定 → 关闭，终态）")
    rc = call("close", ver_no="VER-001", note="结论已纳入验证矩阵报告")
    # TC-19b **关闭说明留痕**（2026-09-25 起 `note` 落库到 `close_note`）
    record(call("get", ver_no="VER-001")["close_note"] == "结论已纳入验证矩阵报告",
           f"close_note={call('get', ver_no='VER-001')['close_note']!r}")
    record(rc["status"] == "closed" and rc["result"] == "pass", f"status={rc['status']}")

    step("TC-20 重复关闭 → 拒绝")
    record(True, expect_err(lambda: call("close", ver_no="VER-001"), "已经是关闭状态"))

    step("TC-21 BR-03 终态（已关闭）：修改 / 再判定 / 再关闭全部拒绝")
    record(True, expect_err(lambda: call("update", ver_no="VER-001", owner="偷改"),
                            "已关闭（终态）"))
    record(True, expect_err(lambda: call("record_result", ver_no="VER-001", result="fail",
                                        evidence="x", follow_up="y"), "已关闭（终态）"))
    record(True, expect_err(lambda: call("close", ver_no="VER-001"), "已经是关闭状态"))

    step("TC-22 BR-06 只有规划状态能开始执行（已判定的拒绝）")
    record(True, expect_err(lambda: call("start", ver_no="VER-003"),
                            "只有规划状态才能开始执行"))

    step("TC-23 BR-04 编号不可变（update 字段白名单里没有 ver_no）+ 编号为空 → 拒绝")
    record(True, expect_err(lambda: call("start", ver_no=""), "验证项编号不能为空"))
    record(True, expect_err(lambda: call("update", ver_no="  ", owner="x"),
                            "验证项编号不能为空"))

    step("TC-24 改不存在的验证项 / 无内容修改 → 均拒绝")
    record(True, expect_err(lambda: call("update", ver_no="VER-999", owner="x"), "不存在"))
    record(True, expect_err(lambda: call("update", ver_no="VER-002"), "没有要修改的内容"))

    # ── 查询契约 ─────────────────────────────────────────
    step("TC-25 list 契约：返回 {items, total}，且与 get 同口径（全字段）")
    lst = call("list")
    items = lst.get("items") or []
    # ⚠ list 契约是 {items, total}（前端 pageable 依赖它）；返回裸数组会让页面静默显示空态
    record(lst.get("total") == 3 and [x["ver_no"] for x in items] ==
           ["VER-001", "VER-002", "VER-003"],
           f"total={lst.get('total')} items={[x['ver_no'] for x in items]}")
    record(bool(items) and "evidence" in items[0] and "follow_up" in items[0]
           and "criteria" in items[0], "list 返回项含全部业务字段（与 get 同口径）")

    step("TC-26 按对应需求 / 验证方法 / 状态 / 阶段筛选，以及分页")
    by_req = call("list", req_no="REQ-001")
    by_method = call("list", method="analysis")
    by_status = call("list", status="failed")
    by_phase = call("list", phase="end_to_end")
    record([x["ver_no"] for x in by_req["items"]] == ["VER-001", "VER-003"],
           f"req_no=REQ-001 → {[x['ver_no'] for x in by_req['items']]}")
    record([x["ver_no"] for x in by_method["items"]] == ["VER-002"],
           f"method=analysis → {[x['ver_no'] for x in by_method['items']]}")
    record([x["ver_no"] for x in by_status["items"]] == ["VER-002"],
           f"status=failed → {[x['ver_no'] for x in by_status['items']]}")
    record([x["ver_no"] for x in by_phase["items"]] == ["VER-003"],
           f"phase=end_to_end → {[x['ver_no'] for x in by_phase['items']]}")
    p1 = call("list", page=1, size=2)
    p2 = call("list", page=2, size=2)
    record(p1["total"] == 3 and [x["ver_no"] for x in p1["items"]] == ["VER-001", "VER-002"]
           and [x["ver_no"] for x in p2["items"]] == ["VER-003"],
           f"p1.total={p1['total']} p1={[x['ver_no'] for x in p1['items']]} "
           f"p2={[x['ver_no'] for x in p2['items']]}")

    step("TC-27 查询详情 / 未命中不抛异常")
    one = call("get", ver_no="VER-001")
    record(one["req_no"] == "REQ-001" and one["status"] == "closed"
           and one["result"] == "pass" and one["phase"] == "system_functional",
           f"req_no={one['req_no']} status={one['status']} phase={one['phase']}")
    record(one["criteria"] == "P95 ≤ 2s，连续 30 分钟无错误", "成功判据落库")
    # 对照断言（T2 门禁：本步不能只证明「没抛异常」）—— 未命中**不产生副作用**：
    _before = call("list")["total"]
    record(call("get", ver_no="VER-999") is None, "get 未命中返回 None（不抛异常）")
    record(call("list")["total"] == _before,
           f"未命中不产生副作用：列表仍 {_before} 条")

    step("TC-28 状态机可覆盖性（每个状态都有服务能到达）")
    # ⚠ 状态机里出现的每个状态都必须有服务能到达它（样板踩过：状态机有状态但服务缺失）
    want = {"planned", "executing", "passed", "failed", "closed"}
    record(STATES_SEEN == want, f"本链已到达的状态 = {sorted(STATES_SEEN)}")

    # ── 汇总 ─────────────────────────────────────────────
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
