"""FDE v2 后端主链端到端验证 · nasa_pms（需求 requirement）

链路形态（单应用，含状态机与不变量）：
  requirement(create → derive → baseline → update(带变更号) → obsolete)
    · BR-01 必须有验证方法（入口拦 + 基线再拦，双重）
    · BR-02 派生须有上游，且上游作废后下游仍可见其编号
    · BR-03 编号唯一不可变
    · BR-04 已基线不得直接改写，须带已批准变更号
    · BR-05 类型/方法受字典约束

隔离：`shadow_dbs()` —— 业务库**复制**到临时目录，测试全程只读写副本，
**真库零字节接触，且不用停 dev server**。`shadow_clear(GROUP)` 清的是副本。

运行：python app/nasa_pms/tests/verify_chain_nasa_pms.py
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
APP = "requirement"

RESULTS = []


def step(name):
    print(f"  → {name}", flush=True)


def record(ok, note=""):
    RESULTS.append((name if False else "", ok, note))
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
        return pf.call(qname, svc, **kw)

    # ── 主链（正向） ──────────────────────────────────────
    step("TC-01 录入需求")
    r1 = call("create", title="系统应支持 1000 并发用户",
              statement="8vCPU/32GB 下 P95 ≤ 2s", req_type="technical",
              verify_method="test", owner="张三")
    record(r1["req_no"] == "REQ-001" and r1["status"] == "draft", f"req_no={r1['req_no']} status={r1['status']}")

    step("TC-02 编号递增")
    r2 = call("create", title="接口应符合 ICD-001", statement="接口数据项与 ICD-001 一致",
              req_type="interface", verify_method="inspection")
    record(r2["req_no"] == "REQ-002", f"req_no={r2['req_no']}")

    step("TC-02b 编号**全局**唯一：换项目号也不重新起编（BR-03 的 2026-09-25 口径）")
    pa = call("create", title="A 项目的一条需求", statement="用于验证编号分段口径",
              req_type="technical", verify_method="test", project_no="P-A")
    pb = call("create", title="B 项目的一条需求", statement="换项目号，编号仍接续",
              req_type="technical", verify_method="test", project_no="P-B")
    record(pa["req_no"] == "REQ-003" and pb["req_no"] == "REQ-004",
           f"P-A → {pa['req_no']}、P-B → {pb['req_no']}（编号不按项目分段，全局递增）")

    step("TC-03 派生需求")
    r3 = call("derive", source_req_no="REQ-001", title="分系统应支持 200 并发",
              statement="派生自 REQ-001", verify_method="analysis")
    record(r3["req_type"] == "derived" and r3["source_req_no"] == "REQ-001",
           f"req_no={r3['req_no']} source={r3['source_req_no']}")

    step("TC-03b 提交评审（草稿 → 待评审；2026-09-25 补的服务，也是基线的前置门）")
    sr = call("submit_review", req_no="REQ-001")
    record(sr["status"] == "pending_review", f"status={sr['status']}")
    record(True, expect_err(lambda: call("submit_review", req_no="REQ-001"),
                            "只有草稿可以提交评审"))
    # 评审门本身：草稿**不能**直接进基线（否则 pending_review 又成了装饰态）
    record(True, expect_err(lambda: call("baseline", req_nos=["REQ-002"], baseline_ver="BX"),
                            "须先提交评审"))
    for no in ("REQ-002", "REQ-003"):
        call("submit_review", req_no=no)

    step("TC-04 纳入基线（全或无）")
    rb = call("baseline", req_nos=["REQ-001", "REQ-002", "REQ-003"], baseline_ver="B1")
    got = call("get", req_no="REQ-001")
    record(rb["count"] == 3 and got["status"] == "baselined" and got["baseline_ver"] == "B1",
           f"count={rb['count']} status={got['status']} ver={got['baseline_ver']}")

    step("TC-05 查询列表（按状态）")
    lst = call("list", status="baselined")
    # ⚠ list 契约是 {items, total}（前端 pageable 依赖它）；返回裸数组会让页面静默显示空态
    rec_items = lst.get("items") or []
    record(lst.get("total") == 3 and [x["req_no"] for x in rec_items] == ["REQ-001", "REQ-002", "REQ-003"],
           f"total={lst.get('total')} items={[x['req_no'] for x in rec_items]}")
    record(True, "TC-28 list 分页契约：返回 {items,total}")

    step("TC-06 查询详情")
    record(call("get", req_no="REQ-001")["title"].startswith("系统应支持"), "字段完整")

    step("TC-22 get 未命中不抛异常")
    # 对照断言（T2 门禁：本步不能只证明「没抛异常」）—— 未命中**不产生副作用**：
    _before = call("list")["total"]
    record(call("get", req_no="REQ-999") is None, "返回 None")
    record(call("list")["total"] == _before,
           f"未命中不产生副作用：列表仍 {_before} 条")

    # ── BR 逐条（负例） ──────────────────────────────────
    step("TC-11 BR-01 无验证方法 → 拒绝")
    record(True, expect_err(lambda: call("create", title="x", statement="y",
                                        req_type="technical", verify_method=""), "必须有验证方法"))

    step("TC-12 BR-05 类型非法 → 拒绝")
    record(True, expect_err(lambda: call("create", title="x", statement="x", req_type="其它",
                                        verify_method="test"), "需求类型只能是"))

    step("TC-13 验证方法非法 → 拒绝")
    record(True, expect_err(lambda: call("create", title="x", statement="x", req_type="technical",
                                        verify_method="猜"), "验证方法只能是"))

    step("TC-14 BR-02 派生缺上游 → 拒绝")
    record(True, expect_err(lambda: call("create", title="x", statement="x", req_type="derived",
                                        verify_method="test"), "派生需求必须填写上游需求"))

    step("TC-15 派生上游不存在 → 拒绝")
    record(True, expect_err(lambda: call("derive", source_req_no="REQ-999", title="x", statement="y",
                                        verify_method="test"), "不存在"))

    step("TC-16 标题为空 → 拒绝")
    record(True, expect_err(lambda: call("create", title="  ", statement="x", req_type="technical",
                                        verify_method="test"), "标题不能为空"))

    step("TC-27 正文为空 → 拒绝")
    record(True, expect_err(lambda: call("create", title="只有标题", statement="  ",
                                        req_type="technical", verify_method="test"), "正文不能为空"))

    step("TC-18 改不存在的需求 → 拒绝")
    record(True, expect_err(lambda: call("update", req_no="REQ-999", title="x"), "不存在"))

    step("TC-19 BR-04 已基线直接改 → 拒绝")
    record(True, expect_err(lambda: call("update", req_no="REQ-001", title="偷改"), "不能直接修改"))

    step("TC-20 BR-04 带变更号可改")
    ru = call("update", req_no="REQ-001", title="系统应支持 1200 并发用户", change_no="CR-001")
    record(ru["title"].endswith("1200 并发用户") and ru["change_no"] == "CR-001",
           f"title={ru['title'][:18]}… change_no={ru['change_no']}")

    step("TC-21 无内容修改 → 拒绝")
    # ⚠ 必须用**未基线**的需求：update 的检查顺序是「先过 BR-04 状态门，再看有无内容」，
    #    拿已基线的 REQ-001 测会先撞 BR-04（见详设 §6.3 的说明）
    r4 = call("create", title="待改需求", statement="正文", req_type="technical",
              verify_method="analysis")
    record(True, expect_err(lambda: call("update", req_no=r4["req_no"]), "没有要修改的内容"))

    step("TC-23 基线版本号为空 → 拒绝")
    record(True, expect_err(lambda: call("baseline", req_nos=["REQ-001"], baseline_ver=""),
                            "基线版本号不能为空"))

    step("TC-24 基线空列表 → 拒绝")
    record(True, expect_err(lambda: call("baseline", req_nos=[], baseline_ver="B2"),
                            "至少选择一条"))

    # ── 状态机：作废 + 上游作废后下游不悬空 ──────────────
    step("TC-07 作废需求（不删除）")
    ro = call("obsolete", req_no="REQ-002", reason="接口方案变更")
    record(ro["status"] == "obsolete" and call("get", req_no="REQ-002") is not None,
           f"status={ro['status']}（记录仍在）")
    # TC-07b **作废理由留痕**（2026-09-25 起 `reason` 落库到 `void_reason`）
    record(call("get", req_no="REQ-002")["void_reason"] == "接口方案变更",
           f"void_reason={call('get', req_no='REQ-002')['void_reason']!r}")
    lst_v = call("list")
    record(all("void_reason" in x for x in lst_v["items"]),
           "list 与 get 同口径（都带 void_reason，CONVENTION §7/§13）")

    step("TC-25 基线含废弃需求 → 整批拒绝，且其余状态不变")
    # ⚠ 批次里**除废弃那条外都必须是「待评审」**：2026-09-25 加了评审门之后，
    #   一条 baselined 的成员会**先撞评审门**，就测不到"已废弃"这条了（守卫顺序 × 批次成员的交叉点）。
    ok_member = call("create", title="待评审成员（对照）", statement="用于验证整批拒绝时其余状态不变",
                     req_type="technical", verify_method="test")["req_no"]
    call("submit_review", req_no=ok_member)
    before = call("get", req_no=ok_member)["status"]
    record(True, expect_err(lambda: call("baseline", req_nos=[ok_member, "REQ-002"],
                                        baseline_ver="B2"), "已废弃"))
    after = call("get", req_no=ok_member)["status"]
    record(before == after, f"{ok_member} 状态未变：{before} → {after}（全或无）")

    step("TC-26 重复作废 → 拒绝")
    record(True, expect_err(lambda: call("obsolete", req_no="REQ-002"), "已经是废弃状态"))

    # ── 汇总 ─────────────────────────────────────────────
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
