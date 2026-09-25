"""FDE v2 后端主链端到端验证 · nasa_pms（评审 review）

链路形态（单应用，含**聚合一内两子表**与完整状态机）：
  review(create → add_item×2 → start → conclude(有条件通过 + 行动项)
         → close_action → close)          ← 主链
  review(create → add_item → start → conclude(通过，无行动项) → concluded)  ← 无行动项支路
    · BR-01 结论为「有条件通过」必须有行动项（卡片 I-1）
    · BR-02 行动项必须指定责任人与期限（卡片 I-2）+ 期限格式 YYYY-MM-DD
    · BR-03 评审项清单为空不得结论
    · BR-04 编号唯一且不可变（update 的字段白名单里没有 review_no）
    · BR-05 类型 / 阶段 / 结论受字典约束
    · BR-06 已结论后内容冻结（结论是快照）；已关闭为硬终态（改 / 加评审项 / 动行动项全拒）
    · BR-07 行动项未全部完成不得关闭评审；行动项只能在其评审「行动项跟踪中」时关闭
  并入说明（`architecture.md` 聚合根卡 5）：**行动项并入本聚合** —— 它随 conclude 与结论
  同事务落库、无独立标识（`(review_no, seq)` 复合主键）；跨评审汇总由 `list_actions`
  这个**查询视图**提供，本用例集同时覆盖它。

隔离：`shadow_dbs()` —— 业务库**复制**到临时目录，测试全程只读写副本，
**真库零字节接触，且不用停 dev server**。`shadow_clear(GROUP)` 清的是副本。

运行：python app/nasa_pms/tests/verify_chain_nasa_pms_review.py
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
APP = "review"

RESULTS = []


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
        return pf.call(qname, svc, **kw)

    # ── 主链（正向） ──────────────────────────────────────
    step("TC-01 新建评审（计划态，编号 RV-001）")
    r1 = call("create", title="飞控软件初步设计评审", review_type="pdr", phase="b",
              subject="飞控软件初步设计", plan_no="SEMP-001", owner="张三")
    record(r1["review_no"] == "RV-001" and r1["status"] == "planned"
           and r1["items"] == [] and r1["action_total"] == 0,
           f"review_no={r1['review_no']} status={r1['status']} items={len(r1['items'])}")

    step("TC-02 编号递增")
    r2 = call("create", title="飞控系统需求评审", review_type="srr", phase="a",
              subject="飞控系统需求规格", owner="李四")
    record(r2["review_no"] == "RV-002", f"review_no={r2['review_no']}")

    step("TC-03 加评审项（聚合内子表，seq 本评审内递增）")
    call("add_item", review_no="RV-001", item="需求可追溯", criterion="每条需求有验证方法")
    i3 = call("add_item", review_no="RV-001", item="接口定义完整", criterion="接口两端都明确")
    record([x["seq"] for x in i3["items"]] == [1, 2] and i3["items"][0]["item"] == "需求可追溯",
           f"items={[x['seq'] for x in i3['items']]}")

    step("TC-04 启动评审（计划 → 进行中）")
    record(call("start", review_no="RV-001")["status"] == "in_progress", "status=in_progress")

    step("TC-05 出结论：有条件通过 + 1 条行动项（同事务落库）")
    r5 = call("conclude", review_no="RV-001", conclusion="conditional",
              minutes="评审会 2026-09-20，2 项通过、1 项留整改",
              actions=[{"content": "补充验证矩阵", "owner": "李四", "due_date": "2026-10-31"}])
    record(r5["status"] == "tracking" and r5["conclusion"] == "conditional"
           and r5["action_total"] == 1 and r5["action_open"] == 1
           and r5["actions"][0]["status"] == "open",
           f"status={r5['status']} conclusion={r5['conclusion']} action_open={r5['action_open']}")

    step("TC-06 完成行动项（open → done）")
    r6 = call("close_action", review_no="RV-001", seq=1, note="已补评审")
    record(r6["action_open"] == 0 and r6["actions"][0]["status"] == "done"
           and r6["actions"][0]["close_note"] == "已补评审",
           f"action_open={r6['action_open']}")

    step("TC-07 关闭评审（行动项清零后 → 已关闭终态）")
    r7 = call("close", review_no="RV-001", note="整改闭环")
    record(r7["status"] == "closed" and r7["close_note"] == "整改闭环", f"status={r7['status']}")

    step("TC-08 无行动项支路：通过 → 直接落到「已结论」")
    call("add_item", review_no="RV-002", item="需求覆盖率", criterion="基线需求 100% 覆盖")
    call("start", review_no="RV-002")
    r8 = call("conclude", review_no="RV-002", conclusion="pass", minutes="一次通过")
    record(r8["status"] == "concluded" and r8["action_total"] == 0,
           f"status={r8['status']}（无行动项不停留在跟踪中）")

    step("TC-09 已结论也能关闭（无行动项阻塞）")
    record(call("close", review_no="RV-002")["status"] == "closed", "status=closed")

    step("TC-10 造第三条：不通过 + 2 条行动项（留在跟踪中）")
    call("create", title="飞控软件详细设计评审", review_type="cdr", phase="c",
         subject="飞控软件详细设计", owner="王五")
    call("add_item", review_no="RV-003", item="气动模型与实测一致")
    call("start", review_no="RV-003")
    r10 = call("conclude", review_no="RV-003", conclusion="fail",
               actions=[{"content": "重做气动分析", "owner": "王五", "due_date": "2026-11-15"},
                        {"content": "补做接口验证", "owner": "李四", "due_date": "2026-11-30"}])
    record(r10["status"] == "tracking" and r10["action_open"] == 2
           and [a["seq"] for a in r10["actions"]] == [1, 2],
           f"status={r10['status']} action_open={r10['action_open']}")

    step("TC-11 造第四条：停在「进行中」")
    call("create", title="飞控软件测试就绪评审", review_type="trr", phase="d", subject="测试方案")
    call("add_item", review_no="RV-004", item="测试环境就绪")
    call("start", review_no="RV-004")
    record(call("get", review_no="RV-004")["status"] == "in_progress", "RV-004 进行中")

    step("TC-12 查询列表（缺省：全部，按编号升序）")
    lst = call("list")
    # ⚠ list 契约是 {items, total}（前端 pageable 依赖它）；返回裸数组会让页面静默显示空态
    items = lst.get("items") or []
    record(lst.get("total") == 4 and [x["review_no"] for x in items]
           == ["RV-001", "RV-002", "RV-003", "RV-004"],
           f"total={lst.get('total')} items={[x['review_no'] for x in items]}")

    step("TC-13 list 与 get 同字段口径（主档字段逐项对齐 + 行动项计数）")
    one = call("get", review_no="RV-003")
    row = [x for x in items if x["review_no"] == "RV-003"][0]
    record(set(row.keys()) == set(one.keys()) - {"items", "actions"},
           f"list 行字段数={len(row)} / get 主档字段数={len(one) - 2}")
    record(row["action_total"] == 2 and row["action_open"] == 2,
           f"action_total={row['action_total']} action_open={row['action_open']}")

    step("TC-14 分页（size=2）")
    paged = call("list", page=1, size=2)
    record(len(paged["items"]) == 2 and paged["total"] == 4,
           f"本页 {len(paged['items'])} 条 / 共 {paged['total']} 条")

    step("TC-15 查询详情：主档 + 评审项 + 行动项（子表随聚合一起返回）")
    one = call("get", review_no="RV-001")
    record(one["title"] == "飞控软件初步设计评审" and len(one["items"]) == 2
           and len(one["actions"]) == 1 and one["minutes"].startswith("评审会"),
           "字段完整")

    step("TC-16 get 未命中不抛异常")
    # 对照断言（T2 门禁：本步不能只证明「没抛异常」）—— 未命中**不产生副作用**：
    _before = call("list")["total"]
    record(call("get", review_no="RV-999") is None, "返回 None")
    record(call("list")["total"] == _before,
           f"未命中不产生副作用：列表仍 {_before} 条")

    # ── 跨评审行动项汇总（查询视图，卡片「并入说明」） ──────
    step("TC-17 list_actions 跨评审汇总（含所属评审的类型 / 阶段）")
    all_a = call("list_actions")
    record(all_a["total"] == 3 and set(all_a["items"][0].keys())
           >= {"review_no", "seq", "content", "owner", "due_date", "status",
               "review_type", "phase", "review_title"},
           f"total={all_a['total']}（跨 2 条评审）")
    record(all_a["items"][0]["review_no"] == "RV-001"
           and all_a["items"][0]["status"] == "done",
           f"首行 {all_a['items'][0]['review_no']}/{all_a['items'][0]['status']}")

    step("TC-18 list_actions 按状态 / 责任人筛选 + 分页契约")
    opened = call("list_actions", status="open")
    record(opened["total"] == 2 and all(x["review_no"] == "RV-003" for x in opened["items"]),
           f"status=open → {opened['total']} 条")
    by_owner = call("list_actions", owner="王五")
    record(by_owner["total"] == 1 and by_owner["items"][0]["content"] == "重做气动分析",
           f"owner=王五 → {by_owner['total']} 条")
    one_page = call("list_actions", page=1, size=1)
    record(len(one_page["items"]) == 1 and one_page["total"] == 3, "分页 size=1 → 本页 1 / 共 3")

    # ── BR 逐条（负例） ──────────────────────────────────
    step("TC-21 BR-01 有条件通过但无行动项 → 拒绝")
    call("create", title="待结论评审", review_type="prr", phase="d", subject="生产条件")
    call("add_item", review_no="RV-005", item="工装就绪")
    call("start", review_no="RV-005")
    record(True, expect_err(lambda: call("conclude", review_no="RV-005", conclusion="conditional"),
                            "必须给出行动项"))
    record(True, expect_err(lambda: call("conclude", review_no="RV-005", conclusion="conditional",
                                        actions=[]), "必须给出行动项"))

    step("TC-22 BR-02 行动项缺责任人 / 缺期限 → 拒绝")
    record(True, expect_err(lambda: call("conclude", review_no="RV-005", conclusion="fail",
                                        actions=[{"content": "整改", "due_date": "2026-12-01"}]),
                            "必须指定责任人"))
    record(True, expect_err(lambda: call("conclude", review_no="RV-005", conclusion="fail",
                                        actions=[{"content": "整改", "owner": "张三"}]),
                            "必须指定期限"))

    step("TC-23 BR-02 期限格式非法 / 内容为空 → 拒绝")
    record(True, expect_err(lambda: call("conclude", review_no="RV-005", conclusion="fail",
                                        actions=[{"content": "整改", "owner": "张三",
                                                  "due_date": "2026/12/01"}]),
                            "期限格式必须是 YYYY-MM-DD"))
    record(True, expect_err(lambda: call("conclude", review_no="RV-005", conclusion="fail",
                                        actions=[{"content": "  ", "owner": "张三",
                                                  "due_date": "2026-12-01"}]),
                            "行动项的内容不能为空"))
    record(True, expect_err(lambda: call("conclude", review_no="RV-005", conclusion="fail",
                                        actions="不是列表"), "行动项必须是一个列表"))
    record(True, expect_err(lambda: call("conclude", review_no="RV-005", conclusion="fail",
                                        actions=["整改"]), "第 1 条行动项的格式不正确"))

    step("TC-24 BR-03 评审项清单为空不得结论 → 拒绝")
    call("create", title="空清单评审", review_type="orr", phase="e", subject="运行条件")
    call("start", review_no="RV-006")
    record(True, expect_err(lambda: call("conclude", review_no="RV-006", conclusion="pass"),
                            "评审项清单为空"))

    step("TC-25 BR-04 编号唯一且不可变（update 字段白名单里没有编号）")
    r25 = call("update", review_no="RV-006", title="运行就绪评审（改名）")
    record(r25["review_no"] == "RV-006" and r25["title"] == "运行就绪评审（改名）",
           "编号不可改，标题可改")

    step("TC-26 BR-05 类型 / 阶段非法 → 拒绝")
    record(True, expect_err(lambda: call("create", title="x", review_type="其它", phase="a",
                                        subject="y"), "评审类型只能是"))
    record(True, expect_err(lambda: call("create", title="x", review_type="pdr", phase="z",
                                        subject="y"), "所属阶段只能是"))

    step("TC-27 BR-05 类型 / 阶段 / 结论为空 → 拒绝")
    record(True, expect_err(lambda: call("create", title="x", review_type="  ", phase="a",
                                        subject="y"), "评审类型不能为空"))
    record(True, expect_err(lambda: call("create", title="x", review_type="pdr", phase="",
                                        subject="y"), "所属阶段不能为空"))
    record(True, expect_err(lambda: call("conclude", review_no="RV-005", conclusion="  "),
                            "评审结论不能为空"))
    record(True, expect_err(lambda: call("conclude", review_no="RV-005", conclusion="maybe"),
                            "评审结论只能是"))

    step("TC-28 标题 / 评审对象为空 → 拒绝")
    record(True, expect_err(lambda: call("create", title="  ", review_type="pdr", phase="a",
                                        subject="y"), "评审标题不能为空"))
    record(True, expect_err(lambda: call("create", title="x", review_type="pdr", phase="a",
                                        subject="  "), "评审对象不能为空"))

    step("TC-29 评审项内容为空 → 拒绝")
    record(True, expect_err(lambda: call("add_item", review_no="RV-005", item="   "),
                            "评审项内容不能为空"))

    step("TC-30 计划态不能直接出结论（须先启动）")
    call("create", title="计划态评审", review_type="sar", phase="e", subject="验收条件")
    call("add_item", review_no="RV-007", item="交付物清点")
    record(True, expect_err(lambda: call("conclude", review_no="RV-007", conclusion="pass"),
                            "须先启动评审"))

    step("TC-31 BR-06 已结论后内容冻结（update / add_item 全拒）")
    record(True, expect_err(lambda: call("update", review_no="RV-003", title="偷改"),
                            "已出结论"))
    record(True, expect_err(lambda: call("add_item", review_no="RV-003", item="补一项"),
                            "已出结论"))

    step("TC-32 BR-06 已关闭为硬终态（改 / 加评审项 / 动行动项 / 再关闭全拒）")
    record(True, expect_err(lambda: call("update", review_no="RV-002", title="偷改"),
                            "已关闭（终态）"))
    record(True, expect_err(lambda: call("add_item", review_no="RV-002", item="补一项"),
                            "已关闭（终态）"))
    record(True, expect_err(lambda: call("close_action", review_no="RV-002", seq=1),
                            "已关闭（终态）"))
    record(True, expect_err(lambda: call("close", review_no="RV-002"), "已经是关闭状态"))
    record(True, expect_err(lambda: call("start", review_no="RV-002"), "已关闭（终态）"))

    step("TC-33 BR-07 行动项未清零不得关闭评审")
    record(True, expect_err(lambda: call("close", review_no="RV-003"),
                            "还有 2 条行动项未完成"))
    call("close_action", review_no="RV-003", seq=1)
    record(True, expect_err(lambda: call("close", review_no="RV-003"),
                            "还有 1 条行动项未完成"))
    call("close_action", review_no="RV-003", seq=2)
    record(call("close", review_no="RV-003", note="全部整改闭环")["status"] == "closed",
           "行动项清零 → 可关闭")

    step("TC-34 BR-07 行动项只能在其评审「行动项跟踪中」时关闭")
    record(True, expect_err(lambda: call("close_action", review_no="RV-004", seq=1),
                            "不在行动项跟踪中"))
    record(True, expect_err(lambda: call("close_action", review_no="RV-001", seq=1),
                            "已关闭（终态）"))

    step("TC-35 计划 / 进行中的评审不能跳过结论直接关闭")
    record(True, expect_err(lambda: call("close", review_no="RV-004"),
                            "只有已结论或行动项跟踪中的评审才能关闭"))
    record(True, expect_err(lambda: call("close", review_no="RV-007"),
                            "只有已结论或行动项跟踪中的评审才能关闭"))

    step("TC-36 行动项序号非法 / 不存在 / 重复完成 → 拒绝")
    # ⚠ 序号校验在**状态守卫之后**（不在跟踪中就先被拦下），所以必须先把 RV-004 推到跟踪中
    call("add_item", review_no="RV-004", item="第二项")
    call("conclude", review_no="RV-004", conclusion="fail",
         actions=[{"content": "整改环境", "owner": "张三", "due_date": "2026-12-31"}])
    record(True, expect_err(lambda: call("close_action", review_no="RV-004", seq="一"),
                            "行动项序号必须是正整数"))
    record(True, expect_err(lambda: call("close_action", review_no="RV-004", seq=0),
                            "行动项序号必须大于 0"))
    record(True, expect_err(lambda: call("close_action", review_no="RV-004", seq=9),
                            "没有序号为 9 的行动项"))
    call("close_action", review_no="RV-004", seq=1)
    record(True, expect_err(lambda: call("close_action", review_no="RV-004", seq=1),
                            "已经是完成状态"))

    step("TC-37 重复状态动作 → 拒绝")
    # ⚠ 负例的守卫顺序必须与实现的 if 顺序逐字对齐：RV-004 此时是「行动项跟踪中」，
    #    start 会先撞「不为 planned」这一条（不是终态那条）
    record(True, expect_err(lambda: call("start", review_no="RV-004"),
                            "只有计划状态才能启动"))
    record(True, expect_err(lambda: call("conclude", review_no="RV-004", conclusion="pass"),
                            "已经出过结论"))
    added = call("add_item", review_no="RV-007", item="验收准则")
    record(added["status"] == "planned" and len(added["items"]) == 2,
           "计划态可继续加评审项（未结论不冻结）")

    step("TC-38 编号为空 / 不存在 → 拒绝")
    record(True, expect_err(lambda: call("start", review_no=""), "评审编号不能为空"))
    record(True, expect_err(lambda: call("update", review_no="  ", title="x"), "评审编号不能为空"))
    record(True, expect_err(lambda: call("add_item", review_no="RV-999", item="x"), "不存在"))
    record(True, expect_err(lambda: call("start", review_no="RV-999"), "不存在"))
    record(True, expect_err(lambda: call("conclude", review_no="RV-999", conclusion="pass"),
                            "不存在"))
    record(True, expect_err(lambda: call("close", review_no="RV-999"), "不存在"))
    record(True, expect_err(lambda: call("close_action", review_no="RV-999", seq=1), "不存在"))

    step("TC-39 无内容修改 → 拒绝")
    record(True, expect_err(lambda: call("update", review_no="RV-007"), "没有要修改的内容"))

    step("TC-40 列表筛选（类型 / 阶段 / 状态 / 结论 / 依据计划）")
    by_type = call("list", review_type="srr")
    record(by_type["total"] == 1 and by_type["items"][0]["review_no"] == "RV-002",
           f"type=srr → {by_type['total']} 条")
    by_phase = call("list", phase="c")
    record(by_phase["total"] == 1 and by_phase["items"][0]["review_no"] == "RV-003",
           f"phase=c → {by_phase['total']} 条")
    by_status = call("list", status="tracking")
    record(by_status["total"] == 1 and by_status["items"][0]["review_no"] == "RV-004",
           f"status=tracking → {by_status['total']} 条")
    by_concl = call("list", conclusion="fail")
    record(by_concl["total"] == 2
           and [x["review_no"] for x in by_concl["items"]] == ["RV-003", "RV-004"],
           f"conclusion=fail → {by_concl['total']} 条")
    by_plan = call("list", plan_no="SEMP-001")
    record(by_plan["total"] == 1 and by_plan["items"][0]["review_no"] == "RV-001",
           f"plan_no=SEMP-001 → {by_plan['total']} 条")

    step("TC-41 已关闭的评审仍可查（historical traceability，不删除）")
    closed = call("list", status="closed")
    record(closed["total"] == 3 and call("get", review_no="RV-001") is not None,
           f"status=closed → {closed['total']} 条（记录仍在）")

    step("TC-42 行动项随评审关闭后仍在（同事务子表，不级联删）")
    acts = call("list_actions", review_no="RV-001")
    record(acts["total"] == 1 and acts["items"][0]["status"] == "done",
           f"RV-001 行动项 {acts['total']} 条仍在")

    # ── 汇总 ─────────────────────────────────────────────
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    for ok, note in bad:
        print(f"    ✗ {note}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
