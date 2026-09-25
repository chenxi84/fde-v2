"""FDE v2 后端主链端到端验证 · nasa_pms（技术度量 technical_measure）

链路形态（单应用，含**聚合一内两子表**与完整状态机 + 一处跨应用弱引用校验）：
  technical_measure(create → baseline → record(在阈内) → record(超阈值，同事务出告警)
                    → correct → record → rebaseline → close)                  ← 主链
  technical_measure(create → baseline → record(在阈内))                        ← 停在度量中
  technical_measure(create)                                                    ← 停在定义
  technical_measure(create → baseline → record(超阈值))                        ← 停在超阈值
    · BR-01 实测值超出阈值必须触发告警记录（卡片 I-1：**度量与告警同事务**）
    · BR-02 目标值与阈值一经基线不可直接改写，须经变更请求（卡片 I-2）
    · BR-03 编号唯一且不可变（update 的字段白名单里没有 tpm_no）
    · BR-04 类别 / 优化方向受字典约束
    · BR-05 目标值与阈值必须与优化方向一致（阈值是底线）
    · BR-06 状态守卫：未基线不得记录 / 超阈值未纠正不得继续记录或关闭 / 已关闭为硬终态
    · BR-07 度量期次在本度量内唯一
    · BR-08 数值字段（目标值 / 阈值 / 实测值）必须是数字
  并入说明（`architecture.md` 聚合根卡 7）：**告警并入本聚合** —— 它与产生它的那条实测值
  同事务落库、无独立标识（`(tpm_no, seq)` 复合主键）；跨度量汇总由 `list_alerts` 这个
  **查询视图**提供，本用例集同时覆盖它。

隔离：`shadow_dbs()` —— 业务库**复制**到临时目录，测试全程只读写副本，
**真库零字节接触，且不用停 dev server**。`shadow_clear(GROUP)` 清的是副本。

运行：python app/nasa_pms/tests/verify_chain_nasa_pms_technical_measure.py
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
APP = "technical_measure"

RESULTS = []


def step(name):
    print(f"  -> {name}", flush=True)


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
        return pf.call(qname, svc, **kw)

    def req_call(svc, **kw):
        return pf.call(f"{GROUP}/requirement", svc, **kw)

    # ── 主链（正向） ──────────────────────────────────────
    step("TC-01 定义一条技术度量（定义态，编号 TPM-001）")
    r1 = call("create", name="推进剂余量", category="tpm", direction="higher",
              target_value=15, threshold_value=10, unit="%", owner="张三",
              project_no="P-2026-01")
    record(r1["tpm_no"] == "TPM-001" and r1["status"] == "defined"
           and r1["baseline_ver"] is None and r1["readings"] == [] and r1["alerts"] == [],
           f"tpm_no={r1['tpm_no']} status={r1['status']} baseline_ver={r1['baseline_ver']}")

    step("TC-02 编号递增")
    r2 = call("create", name="整星质量", category="mop", direction="lower",
              target_value=1200, threshold_value=1250, unit="kg", owner="李四")
    record(r2["tpm_no"] == "TPM-002", f"tpm_no={r2['tpm_no']}")

    step("TC-03 基线化：定义 → 度量中（同时冻结判定口径）")
    r3 = call("baseline", tpm_no="TPM-001")
    record(r3["status"] == "measuring" and r3["baseline_ver"] == "B1",
           f"status={r3['status']} baseline_ver={r3['baseline_ver']}")

    step("TC-04 记实测值（在阈内）：度量中 → 度量中，不产生告警")
    r4 = call("record", tpm_no="TPM-001", period="2026-Q1", measured_value=12.5, note="试车数据")
    record(r4["status"] == "measuring" and r4["current_value"] == 12.5
           and r4["current_period"] == "2026-Q1" and r4["reading_total"] == 1
           and r4["alert_total"] == 0 and r4["readings"][0]["passed"] == 1,
           f"status={r4['status']} current={r4['current_value']} alert_total={r4['alert_total']}")

    step("TC-05 记实测值（超阈值）：度量中 → 超阈值，**同事务**产生告警（卡片 I-1）")
    r5 = call("record", tpm_no="TPM-001", period="2026-Q2", measured_value=8.2)
    a5 = r5["alerts"][0] if r5["alerts"] else {}
    record(r5["status"] == "exceeded" and r5["alert_open"] == 1 and r5["alert_total"] == 1
           and r5["readings"][1]["passed"] == 0
           and a5.get("period") == "2026-Q2" and a5.get("measured_value") == 8.2
           and a5.get("deviation") == 1.8 and a5.get("status") == "open",
           f"status={r5['status']} alert_open={r5['alert_open']} deviation={a5.get('deviation')}")

    step("TC-06 告警信息是人话（含名称 / 期次 / 实测值 / 阈值 / 超出量 / 单位）")
    msg = a5.get("message", "")
    record("推进剂余量" in msg and "2026-Q2" in msg and "8.2%" in msg
           and "低于阈值 10%" in msg and "超出 1.8%" in msg, f"message={msg}")

    step("TC-07 超阈值未纠正时不得继续记录（守卫顺序：硬终态 → 未基线 → 超阈值）")
    record(True, expect_err(lambda: call("record", tpm_no="TPM-001", period="2026-Q3",
                                        measured_value=13.0),
                            "必须先 correct 登记纠正措施"))

    step("TC-08 纠正：超阈值 → 已纠正（登记纠正措施并了结未了结的告警，同事务）")
    r8 = call("correct", tpm_no="TPM-001", corrective_action="减重 1.2kg 并调整加注量")
    record(r8["status"] == "corrected" and r8["alert_open"] == 0
           and r8["alerts"][0]["status"] == "handled"
           and r8["alerts"][0]["handle_note"] == "减重 1.2kg 并调整加注量",
           f"status={r8['status']} alert_open={r8['alert_open']} handle_note={r8['alerts'][0]['handle_note']}")

    step("TC-09 纠正后再测（在阈内）：已纠正 → 度量中；旧告警保留在台账里")
    r9 = call("record", tpm_no="TPM-001", period="2026-Q3", measured_value=11.0)
    record(r9["status"] == "measuring" and r9["reading_total"] == 3
           and r9["alerts"][0]["status"] == "handled"
           and r9["alerts"][0]["handle_note"].startswith("减重"),
           f"status={r9['status']} reading_total={r9['reading_total']} alert_total={r9['alert_total']}")

    step("TC-10 重设基线（BR-02：改写判定口径须携带变更请求号，基线版本递增）")
    r10 = call("rebaseline", tpm_no="TPM-001", target_value=15.5, threshold_value=11,
               change_no="CR-007")
    record(r10["baseline_ver"] == "B2" and r10["target_value"] == 15.5
           and r10["threshold_value"] == 11 and r10["change_no"] == "CR-007"
           and r10["status"] == "measuring",
           f"baseline_ver={r10['baseline_ver']} threshold={r10['threshold_value']} change_no={r10['change_no']}")

    step("TC-11 关闭度量（度量中 → 已关闭终态）")
    r11 = call("close", tpm_no="TPM-001", note="口径已达标")
    record(r11["status"] == "closed" and r11["close_note"] == "口径已达标",
           f"status={r11['status']} close_note={r11['close_note']}")

    step("TC-12 造第二条：越小越好 + 在阈内（停在「度量中」）")
    call("baseline", tpm_no="TPM-002")
    r12 = call("record", tpm_no="TPM-002", period="2026-Q1", measured_value=1210)
    record(r12["status"] == "measuring" and r12["alert_total"] == 0,
           f"status={r12['status']}（1210 ≤ 阈值 1250，在阈内）")

    step("TC-13 造第三条：停在「定义」（从未基线）")
    r13 = call("create", name="遥测数据完整率", category="kpp", direction="higher",
               target_value=99, threshold_value=95, unit="%")
    record(r13["tpm_no"] == "TPM-003" and r13["status"] == "defined"
           and r13["reading_total"] == 0,
           f"{r13['tpm_no']} status={r13['status']}")

    step("TC-14 造第四条：超阈值且未纠正（停在「超阈值」，保留一条未了结告警）")
    call("create", name="单机功耗", category="tpm", direction="lower",
         target_value=40, threshold_value=45, unit="W")
    call("baseline", tpm_no="TPM-004")
    r14 = call("record", tpm_no="TPM-004", period="2026-Q1", measured_value=47.5)
    record(r14["status"] == "exceeded" and r14["alert_open"] == 1
           and r14["alerts"][0]["deviation"] == 2.5
           and "高于阈值 45W" in r14["alerts"][0]["message"],
           f"status={r14['status']} deviation={r14['alerts'][0]['deviation']}")

    step("TC-15 查询列表（缺省：全部，按编号升序）")
    lst = call("list")
    # ⚠ list 契约是 {items, total}（前端 pageable 依赖它）；返回裸数组会让页面静默显示空态
    items = lst.get("items") or []
    record(lst.get("total") == 4 and [x["tpm_no"] for x in items]
           == ["TPM-001", "TPM-002", "TPM-003", "TPM-004"],
           f"total={lst.get('total')} items={[x['tpm_no'] for x in items]}")

    step("TC-16 list 与 get 同字段口径（主档字段逐项对齐 + 三计数）")
    one = call("get", tpm_no="TPM-001")
    row = [x for x in items if x["tpm_no"] == "TPM-001"][0]
    record(set(row.keys()) == set(one.keys()) - {"readings", "alerts"},
           f"list 行字段数={len(row)} / get 主档字段数={len(one) - 2}")
    record(row["reading_total"] == 3 and row["alert_total"] == 1 and row["alert_open"] == 0,
           f"reading_total={row['reading_total']} alert_total={row['alert_total']} "
           f"alert_open={row['alert_open']}")

    step("TC-17 分页（size=2）")
    paged = call("list", page=1, size=2)
    record(len(paged["items"]) == 2 and paged["total"] == 4,
           f"本页 {len(paged['items'])} 条 / 共 {paged['total']} 条")

    step("TC-18 查询详情：主档 + 实测值序列 + 告警台账（子表随聚合一起返回）")
    one = call("get", tpm_no="TPM-001")
    record(one["name"] == "推进剂余量" and [x["period"] for x in one["readings"]]
           == ["2026-Q1", "2026-Q2", "2026-Q3"] and len(one["alerts"]) == 1
           and one["alerts"][0]["period"] == "2026-Q2",
           "字段完整（实测值序列按 seq 升序）")

    step("TC-19 get 未命中不抛异常")
    # 对照断言（T2 门禁：本步不能只证明「没抛异常」）—— 未命中**不产生副作用**：
    _before = call("list")["total"]
    record(call("get", tpm_no="TPM-999") is None, "返回 None")
    record(call("list")["total"] == _before,
           f"未命中不产生副作用：列表仍 {_before} 条")

    # ── 跨度量告警汇总（查询视图，卡片「并入说明」） ──────
    step("TC-20 list_alerts 跨度量汇总（含所属度量的名称 / 类别 / 单位 / 目标值 / 阈值）")
    all_a = call("list_alerts")
    record(all_a["total"] == 2 and set(all_a["items"][0].keys())
           >= {"tpm_no", "seq", "period", "measured_value", "deviation", "message",
               "status", "handle_note", "name", "category", "unit", "direction",
               "target_value", "threshold_value", "tpm_status"},
           f"total={all_a['total']}（跨 TPM-001 / TPM-004 两条度量）")
    record(all_a["items"][0]["tpm_no"] == "TPM-001"
           and all_a["items"][0]["status"] == "handled"
           and all_a["items"][1]["tpm_no"] == "TPM-004",
           f"首行 {all_a['items'][0]['tpm_no']}/{all_a['items'][0]['status']}")

    step("TC-21 list_alerts 按状态 / 度量 / 类别筛选 + 分页契约")
    opened = call("list_alerts", status="open")
    record(opened["total"] == 1 and opened["items"][0]["tpm_no"] == "TPM-004",
           f"status=open → {opened['total']} 条")
    by_tpm = call("list_alerts", tpm_no="TPM-001")
    record(by_tpm["total"] == 1 and by_tpm["items"][0]["period"] == "2026-Q2",
           f"tpm_no=TPM-001 → {by_tpm['total']} 条")
    by_cat = call("list_alerts", category="tpm")
    record(by_cat["total"] == 2, f"category=tpm → {by_cat['total']} 条")
    empty_cat = call("list_alerts", category="mop")
    record(empty_cat["total"] == 0, f"category=mop → {empty_cat['total']} 条（TPM-002 未超阈值）")
    one_page = call("list_alerts", page=1, size=1)
    record(len(one_page["items"]) == 1 and one_page["total"] == 2, "分页 size=1 → 本页 1 / 共 2")

    # ── BR 逐条（负例） ──────────────────────────────────
    step("TC-30 BR-01（I-1）超阈值必须出告警：出阈次数与告警条数一对一（不多不少）")
    # TPM-001 出阈 1 次 → 1 条告警；在阈内的两期**不得**产生告警
    one1 = call("get", tpm_no="TPM-001")
    record(len([x for x in one1["readings"] if x["passed"] == 0]) == 1
           and len(one1["alerts"]) == 1,
           f"出阈实测 {len([x for x in one1['readings'] if x['passed'] == 0])} 期 / "
           f"告警 {len(one1['alerts'])} 条")

    step("TC-31 BR-01（I-1）同事务反证：被拒的 record 既不留实测值、也不留告警")
    # ⚠ 负例必须落在「能走到校验」的状态上：TPM-004 此刻是「超阈值」，record 会先撞
    #    状态守卫（BR-06）而不是期次重复那一关 —— 负例的状态与守卫顺序要逐条对齐。
    before = call("get", tpm_no="TPM-002")
    record(True, expect_err(lambda: call("record", tpm_no="TPM-002", period="2026-Q1",
                                        measured_value=1300), "同一期次不能重复记录"))
    after = call("get", tpm_no="TPM-002")
    record(after["reading_total"] == before["reading_total"]
           and after["alert_total"] == before["alert_total"]
           and after["status"] == before["status"],
           f"实测 {before['reading_total']}→{after['reading_total']} / "
           f"告警 {before['alert_total']}→{after['alert_total']}（整次调用未落库）")

    step("TC-32 BR-02（I-2）已基线后 update 不得改判定口径")
    record(True, expect_err(lambda: call("update", tpm_no="TPM-002", target_value=1100),
                            "不可直接改写，须经变更请求"))
    record(True, expect_err(lambda: call("update", tpm_no="TPM-002", threshold_value=1300),
                            "不可直接改写"))
    record(True, expect_err(lambda: call("update", tpm_no="TPM-002", direction="higher"),
                            "不可直接改写"))
    ok32 = call("update", tpm_no="TPM-002", name="整星干重", owner="李四")
    record(ok32["name"] == "整星干重" and ok32["target_value"] == 1200,
           "描述性字段（名称 / 责任人）不受冻结影响")

    step("TC-33 BR-02 未基线时判定口径可经 update 直接改（语义差：冻结的是「基线之后」）")
    ok33 = call("update", tpm_no="TPM-003", target_value=99.5, direction="higher")
    record(ok33["target_value"] == 99.5 and ok33["threshold_value"] == 95,
           f"target_value={ok33['target_value']}")

    step("TC-34 BR-02 rebaseline 必须携带变更请求号；未基线的度量不必走它")
    record(True, expect_err(lambda: call("rebaseline", tpm_no="TPM-002", target_value=1100,
                                        threshold_value=1300, change_no="  "),
                            "请提供变更请求号"))
    record(True, expect_err(lambda: call("rebaseline", tpm_no="TPM-003", target_value=99,
                                        threshold_value=95, change_no="CR-009"),
                            "尚未基线化"))
    record(True, expect_err(lambda: call("rebaseline", tpm_no="TPM-001", target_value=15,
                                        threshold_value=10, change_no="CR-009"),
                            "已关闭（终态）"))

    step("TC-35 BR-03 编号唯一且不可变（update 字段白名单里没有编号）")
    r35 = call("update", tpm_no="TPM-003", name="遥测数据完整率（改名）")
    record(r35["tpm_no"] == "TPM-003" and r35["name"] == "遥测数据完整率（改名）",
           "编号不可改，名称可改")

    step("TC-36 BR-04 类别 / 优化方向非法 → 拒绝")
    record(True, expect_err(lambda: call("create", name="x", category="其它", direction="higher",
                                        target_value=2, threshold_value=1), "度量类别只能是"))
    record(True, expect_err(lambda: call("create", name="x", category="tpm", direction="up",
                                        target_value=2, threshold_value=1), "优化方向只能是"))
    record(True, expect_err(lambda: call("create", name="x", category="  ", direction="higher",
                                        target_value=2, threshold_value=1), "度量类别不能为空"))
    record(True, expect_err(lambda: call("create", name="x", category="tpm", direction="",
                                        target_value=2, threshold_value=1), "优化方向不能为空"))

    step("TC-37 BR-05 目标值与阈值必须与优化方向一致")
    record(True, expect_err(lambda: call("create", name="x", category="tpm", direction="higher",
                                        target_value=8, threshold_value=10),
                            "目标值 8 不能低于阈值 10"))
    record(True, expect_err(lambda: call("create", name="x", category="mop", direction="lower",
                                        target_value=1300, threshold_value=1250),
                            "目标值 1300 不能高于阈值 1250"))
    record(True, expect_err(lambda: call("update", tpm_no="TPM-003", target_value=90),
                            "不能低于阈值 95"))

    step("TC-38 BR-06 未基线（定义态）不得记录 / 纠正 / 关闭")
    record(True, expect_err(lambda: call("record", tpm_no="TPM-003", period="2026-Q1",
                                        measured_value=99), "尚未基线化"))
    record(True, expect_err(lambda: call("correct", tpm_no="TPM-003", corrective_action="整改"),
                            "没有超阈值可言"))
    record(True, expect_err(lambda: call("close", tpm_no="TPM-003"), "从未开始度量"))

    step("TC-39 BR-06 超阈值未纠正不得关闭")
    record(True, expect_err(lambda: call("close", tpm_no="TPM-004"),
                            "还有 1 条告警未了结"))
    record(True, expect_err(lambda: call("baseline", tpm_no="TPM-004"), "已经基线过了"))

    step("TC-40 BR-06 已关闭为硬终态（记 / 纠正 / 改 / 重基线 / 再关闭全拒）")
    record(True, expect_err(lambda: call("record", tpm_no="TPM-001", period="2026-Q4",
                                        measured_value=12), "已关闭（终态）"))
    record(True, expect_err(lambda: call("correct", tpm_no="TPM-001", corrective_action="整改"),
                            "已关闭（终态）"))
    record(True, expect_err(lambda: call("update", tpm_no="TPM-001", name="偷改"),
                            "已关闭（终态）"))
    record(True, expect_err(lambda: call("close", tpm_no="TPM-001"), "已经是关闭状态"))

    step("TC-41 BR-07 度量期次在本度量内唯一（跨度量同名期次不受影响）")
    record(True, expect_err(lambda: call("record", tpm_no="TPM-002", period="2026-Q1",
                                        measured_value=1240), "同一期次不能重复记录"))
    r41 = call("record", tpm_no="TPM-002", period="2026-Q2", measured_value=1220)
    record(r41["reading_total"] == 2, f"2026-Q2 是新期次 → 立即可记（reading_total={r41['reading_total']}）")
    record(call("get", tpm_no="TPM-004")["readings"][0]["period"] == "2026-Q1",
           "TPM-004 的 2026-Q1 与 TPM-002 的 2026-Q1 互不影响（期次只在度量内唯一）")

    step("TC-42 BR-08 数值字段必须是数字 / 非空")
    record(True, expect_err(lambda: call("create", name="x", category="tpm", direction="higher",
                                        target_value="", threshold_value=1), "目标值不能为空"))
    record(True, expect_err(lambda: call("create", name="x", category="tpm", direction="higher",
                                        target_value="十五", threshold_value=1),
                            "目标值必须是数字"))
    record(True, expect_err(lambda: call("create", name="x", category="tpm", direction="higher",
                                        target_value=2, threshold_value=None), "阈值不能为空"))
    record(True, expect_err(lambda: call("record", tpm_no="TPM-002", period="2026-Q3",
                                        measured_value=" "), "实测值不能为空"))
    record(True, expect_err(lambda: call("record", tpm_no="TPM-002", period="2026-Q3",
                                        measured_value="abc"), "实测值必须是数字"))

    step("TC-43 名称 / 度量期次 / 编号为空 → 拒绝")
    record(True, expect_err(lambda: call("create", name="  ", category="tpm", direction="higher",
                                        target_value=2, threshold_value=1), "度量名称不能为空"))
    record(True, expect_err(lambda: call("create", name="x", category="tpm", direction="higher",
                                        target_value=2, threshold_value=1, req_no="REQ-999"),
                            "不存在"))
    record(True, expect_err(lambda: call("record", tpm_no="TPM-002", period="  ",
                                        measured_value=1220), "度量期次不能为空"))
    record(True, expect_err(lambda: call("update", tpm_no="TPM-002", name="  "), "度量名称不能为空"))
    record(True, expect_err(lambda: call("correct", tpm_no="TPM-004", corrective_action="   "),
                            "纠正措施不能为空"))
    record(True, expect_err(lambda: call("baseline", tpm_no=""), "度量编号不能为空"))
    record(call("get", tpm_no="  ") is None, "编号空白 → get 返回 None，不抛异常")

    step("TC-44 编号不存在 → 拒绝")
    record(True, expect_err(lambda: call("baseline", tpm_no="TPM-999"), "不存在"))
    record(True, expect_err(lambda: call("record", tpm_no="TPM-999", period="Q1",
                                        measured_value=1), "不存在"))
    record(True, expect_err(lambda: call("correct", tpm_no="TPM-999", corrective_action="x"),
                            "不存在"))
    record(True, expect_err(lambda: call("close", tpm_no="TPM-999"), "不存在"))
    record(True, expect_err(lambda: call("update", tpm_no="TPM-999", name="x"), "不存在"))
    record(True, expect_err(lambda: call("rebaseline", tpm_no="TPM-999", target_value=1,
                                        threshold_value=1, change_no="CR-1"), "不存在"))

    step("TC-45 无内容修改 → 拒绝")
    record(True, expect_err(lambda: call("update", tpm_no="TPM-002"), "没有要修改的内容"))

    step("TC-46 必填参数缺传 → 走契约层（系统错误），负例只能传空白")
    # 缺传必填参数进不了业务校验（Python 直接 TypeError）—— 所以本用例集里
    # 「必填为空」的负例一律传空白字符串，才能走到 FdeError 那一层。
    try:
        call("create", name="x", category="tpm", direction="higher", target_value=1)
        record(False, "缺传 threshold_value 应报错")
    except TypeError as e:
        # 「走契约层」= Python 的 TypeError（缺必填形参），**不是** FdeError ——
        # 断言到**类型与缺的那个参数名**，而不是 `record(True, …)`（那等于只证明"抛了异常"）。
        record("threshold_value" in str(e), f"缺传必填参数 → TypeError：{e}")
    except Exception as e:                                        # noqa: BLE001
        record(False, f"缺传必填参数应报 TypeError（契约层），实际 {type(e).__name__}: {e}")

    # ── 跨应用弱引用（唯一一处 self.fde.call） ────────────
    step("TC-47 关联需求存在性（跨应用只读校验，弱引用）")
    rq = req_call("create", title="推进剂余量不低于 10%", statement="全任务周期内推进剂余量不低于 10%",
                  req_type="technical", verify_method="analysis", owner="张三")
    record(rq["req_no"] == "REQ-001", f"先造一条需求 {rq['req_no']}")
    ok47 = call("create", name="推进剂余量（关联需求）", category="tpm", direction="higher",
                target_value=15, threshold_value=10, req_no="REQ-001")
    record(ok47["tpm_no"] == "TPM-005" and ok47["req_no"] == "REQ-001",
           f"{ok47['tpm_no']} req_no={ok47['req_no']}")
    record(True, expect_err(lambda: call("create", name="x", category="tpm", direction="higher",
                                        target_value=2, threshold_value=1, req_no="REQ-777"),
                            "REQ-777 不存在，请先在需求台账中录入"))
    record(True, expect_err(lambda: call("update", tpm_no="TPM-005", req_no="REQ-777"),
                            "REQ-777 不存在"))
    ok47b = call("update", tpm_no="TPM-005", req_no="")
    record(ok47b["req_no"] == "", "弱引用可清空（可悬空、可留空）")

    # ── 查询 / 筛选 ──────────────────────────────────────
    step("TC-48 列表筛选（类别 / 状态 / 优化方向 / 关联需求）")
    by_cat = call("list", category="kpp")
    record(by_cat["total"] == 1 and by_cat["items"][0]["tpm_no"] == "TPM-003",
           f"category=kpp → {by_cat['total']} 条")
    by_status = call("list", status="exceeded")
    record(by_status["total"] == 1 and by_status["items"][0]["tpm_no"] == "TPM-004",
           f"status=exceeded → {by_status['total']} 条")
    by_dir = call("list", direction="lower")
    record(by_dir["total"] == 2
           and [x["tpm_no"] for x in by_dir["items"]] == ["TPM-002", "TPM-004"],
           f"direction=lower → {by_dir['total']} 条")
    by_req = call("list", req_no="REQ-001")
    record(by_req["total"] == 0, f"req_no=REQ-001 → {by_req['total']} 条（TC-47 末尾已清空弱引用）")
    closed = call("list", status="closed")
    record(closed["total"] == 1 and closed["items"][0]["tpm_no"] == "TPM-001",
           f"status=closed → {closed['total']} 条")

    step("TC-49 已关闭的度量仍可查，且两张子表随它一起保留（不级联删）")
    gone = call("get", tpm_no="TPM-001")
    record(gone is not None and gone["status"] == "closed" and gone["reading_total"] == 3
           and gone["alert_total"] == 1,
           f"TPM-001 closed 仍在：实测 {gone['reading_total']} 期 / 告警 {gone['alert_total']} 条")

    # ── 汇总 ─────────────────────────────────────────────
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    for ok, note in bad:
        print(f"    [X] {note}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
