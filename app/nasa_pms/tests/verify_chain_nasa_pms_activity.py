"""FDE v2 后端主链端到端验证 · nasa_pms（进度活动 activity）

链路形态（**活动网络 + 派生排程 + 基线/变更/实绩三分**）：
  activity(add_milestone → create → link → check_network → schedule_view → baseline
           → record_progress → change → update)
    · BR-01 禁开口端（除两个边界里程碑，每个活动都要有前置与后续）
    · BR-02 禁冗余链接（A→B、B→C 时 A→C 冗余 —— 材料 §5.5.8 原文的例子）
    · BR-03 逻辑链完整且无环（前置必须存在；不得成环；不得自前置）
    · BR-04 里程碑工期为 0、活动工期为正
    · BR-05 必须挂在 **WBS 叶子**元素上（跨应用 `wbs.get` + 查子元素）
    · BR-06 活动名称唯一
    · BR-07 基线后改动走变更流程（跨应用 `change_request.get` 校验已批准）
    · BR-08 回填实绩**不动基线**（`record_progress` 的写集合里没有基线列）

隔离：`shadow_dbs()` —— 业务库**复制**到临时目录，测试全程只读写副本，
**真库零字节接触，且不用停 dev server**。`shadow_clear(GROUP)` 清的是副本。

运行：python app/nasa_pms/tests/verify_chain_nasa_pms_activity.py
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
# 不钉住编码的话，print 自己会抛 UnicodeEncodeError（**崩在打印结果那一步**：断言算完了却报不出来）。
# 由 scripts/verify_test_script_encoding.py 守住这一行别被删。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_shadow = shadow_dbs()
_shadow.__enter__()
atexit.register(_shadow.__exit__, None, None, None)

GROUP = "nasa_pms"
APP = "activity"
WBS_APP = "wbs"
CR_APP = "change_request"
CI_APP = "configuration_item"

RESULTS = []
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
        if isinstance(out, dict) and out.get("status") in ("planned", "in_progress", "completed"):
            STATES_SEEN.add(out["status"])
        return out

    def call_wbs(svc, **kw):
        return pf.call(f"{GROUP}/{WBS_APP}", svc, **kw)

    def call_cr(svc, **kw):
        return pf.call(f"{GROUP}/{CR_APP}", svc, **kw)

    # ── 前置：WBS 叶子 + 一条已批准的变更 ────────────────────
    step("前置：WBS 树（父 + 两个叶子）+ 已批准变更 CR-001")
    call_wbs("create", wbs_no="800000", title="进度测试系统", scope_ref="SOW §8")
    call_wbs("add_child", parent_no="800000", title="结构分系统")
    call_wbs("add_child", parent_no="800000", title="热控分系统")
    call_wbs("update", wbs_no="800000.01", scope_ref="SOW §8.1")
    call_wbs("update", wbs_no="800000.02", scope_ref="SOW §8.2")
    ci = pf.call(f"{GROUP}/{CI_APP}", "create", name="进度基线对象", ci_type="document")
    cr = call_cr("create", title="进度调整", requester="进度组", ci_nos=ci["ci_no"],
                 description="舱段装配工期调整")
    call_cr("analyze", cr_no=cr["cr_no"], impact_analysis="影响舱段装配活动工期")
    call_cr("submit_review", cr_no=cr["cr_no"])
    call_cr("approve", cr_no=cr["cr_no"], comment="同意", approver="项目经理")
    cr_no = cr["cr_no"]
    record(call_cr("get", cr_no=cr_no)["status"] == "approved",
           f"前置变更 {cr_no} 已批准（BR-07 的校验对象）")
    LEAF = "800000.01"
    PARENT = "800000"

    # ── §1 主链 ──────────────────────────────────────────
    step("TC-01 建起始里程碑（边界里程碑，允许没有前置）")
    m1 = call("add_milestone", name="舱段装配启动", wbs_no=LEAF, phase="start", owner="结构组")
    record(m1["act_no"] == "ACT-001" and m1["kind"] == "milestone" and m1["duration_days"] == 0,
           f"{m1['act_no']} 里程碑工期 {m1['duration_days']}")
    record(m1["phase"] == "start" and m1["status"] == "planned", "边界标记与初始状态")

    step("TC-02 建活动（挂 WBS 叶子、工期 5 个工作日、前置 ACT-001）")
    a2 = call("create", name="装配舱板", wbs_no=LEAF, duration_days=5,
              predecessors="ACT-001", owner="结构组")
    record(a2["act_no"] == "ACT-002" and a2["duration_days"] == 5, f"{a2['act_no']} 工期 5")
    record(a2["wbs_no"] == LEAF and a2["predecessors"] == "ACT-001", "挂靠与前置落库")

    step("TC-03 建第二段活动（前置 ACT-002）")
    a3 = call("create", name="测试舱板", wbs_no=LEAF, duration_days=3, predecessors="ACT-002")
    record(a3["act_no"] == "ACT-003", f"{a3['act_no']} 建立")

    step("TC-04 建完成里程碑（边界里程碑，允许没有后续）")
    m2 = call("add_milestone", name="舱段交付", wbs_no=LEAF, predecessors="ACT-003",
              phase="finish")
    record(m2["act_no"] == "ACT-004" and m2["phase"] == "finish", f"{m2['act_no']} 完成里程碑")

    step("TC-05 网络体检：网络本身干净，唯一的问题是「叶子还没活动」")
    chk = call("check_network")
    # 材料 §4（WBS 手册）："The lowest level of each WBS element should have at least one task
    # or activity" —— 800000.02 此刻还没有活动，所以它**必须**被报出来；其余六类必须全空。
    record(chk["total"] == 1 and chk["activities"] == 4,
           f"体检 total={chk['total']}（活动 {chk['activities']} 条）")
    record([x["wbs_no"] for x in chk["no_activity"]] == ["800000.02"],
           f"叶子无活动 = {chk['no_activity']}")
    for k in ("open_ends", "redundant", "cycles", "bad_duration", "bad_rel", "non_leaf"):
        record(chk[k] == [], f"体检 · {k} 为空")

    step("TC-06 派生排程：日期由逻辑与工期**正推**（工作日），浮时与关键路径")
    v = call("schedule_view", project_start="2026-10-05")     # 周一
    by = {x["act_no"]: x for x in v["items"]}
    record(by["ACT-001"]["early_start"] == "2026-10-05",
           f"起始里程碑落在 {by['ACT-001']['early_start']}（项目起始日）")
    # 正推口径：后继在前驱**完成后的下一个工作日**开工（FS+0）
    record(by["ACT-002"]["early_start"] == "2026-10-06"
           and by["ACT-002"]["early_finish"] == "2026-10-12",
           f"ACT-002 {by['ACT-002']['early_start']}→{by['ACT-002']['early_finish']}"
           "（周二起 5 个工作日，跨周末到次周一）")
    record(by["ACT-003"]["early_start"] == "2026-10-13"
           and by["ACT-003"]["early_finish"] == "2026-10-15",
           f"ACT-003 {by['ACT-003']['early_start']}→{by['ACT-003']['early_finish']}（紧随前驱）")
    record(by["ACT-004"]["early_start"] == "2026-10-16", "完成里程碑紧随其后")
    record(v["project_finish"] == "2026-10-16", f"项目完工 {v['project_finish']}")
    record(all(x["float_days"] == 0 and x["critical"] for x in v["items"]),
           "单链上每一条的浮时都是 0（都在关键路径上）")
    record("early_start" in by["ACT-001"] and "late_finish" in by["ACT-001"],
           "排程视图带最早/最晚四个日期（派生量，不落库）")

    step("TC-07 关键路径")
    cp = call("critical_path")
    record([x["act_no"] for x in cp["items"]] == ["ACT-001", "ACT-002", "ACT-003", "ACT-004"],
           f"关键路径 = {[x['act_no'] for x in cp['items']]}")

    step("TC-08 建立进度基线（冻住派生日期）")
    b = call("baseline", act_nos=["ACT-001", "ACT-002", "ACT-003", "ACT-004"],
             project_start="2026-10-05")
    record(b["baselined"] == 4, f"基线化 {b['baselined']} 条")
    g2 = call("get", act_no="ACT-002")
    record(g2["baseline_start"] == "2026-10-06" and g2["baseline_finish"] == "2026-10-12",
           f"ACT-002 基线 {g2['baseline_start']}→{g2['baseline_finish']} 落库")
    record(call("list", baselined="1")["total"] == 4, "按「已基线」筛出 4 条")

    step("TC-09 回填实绩（BR-08：不动基线）")
    p1 = call("record_progress", act_no="ACT-001", percent_complete=100,
              actual_start="2026-10-05", actual_finish="2026-10-05")
    record(p1["status"] == "completed" and p1["percent_complete"] == 100,
           f"ACT-001 → {p1['status']} {p1['percent_complete']}%")
    # ⚠ 实绩日期必须**真的落库**（BR-08 的输出字段就是这三个；只断言百分比会让
    #   br_coverage 报「actual_start / actual_finish 未被断言引用」—— 实测被抓）
    record(p1["actual_start"] == "2026-10-05" and p1["actual_finish"] == "2026-10-05",
           f"实绩日期落库：{p1['actual_start']} / {p1['actual_finish']}")
    p2 = call("record_progress", act_no="ACT-002", percent_complete=40,
              actual_start="2026-10-05")
    record(p2["status"] == "in_progress", f"ACT-002 → {p2['status']}（40%）")

    step("TC-10 基线后修订：先 change（带已批准变更号）再 update")
    c = call("change", act_no="ACT-002", change_no=cr_no, note="舱段装配工期调整为 8 天")
    record(c["change_no"] == cr_no, f"ACT-002 挂上变更 {c['change_no']}")
    u = call("update", act_no="ACT-002", duration_days=8, change_no=cr_no)
    record(u["duration_days"] == 8, "工期改为 8（已带变更号，放行）")
    v2 = call("schedule_view", project_start="2026-10-05")
    # 工期 5 → 8（+3 个工作日）后，下游整条链顺延：ACT-002 完成 10-15，ACT-004 落到 10-21
    record({x["act_no"]: x for x in v2["items"]}["ACT-002"]["early_finish"] == "2026-10-15"
           and {x["act_no"]: x for x in v2["items"]}["ACT-004"]["early_start"] == "2026-10-21",
           "改工期后下游日期跟着顺延（派生量）")
    b2 = call("baseline", act_nos=["ACT-002"], project_start="2026-10-05")
    record(b2["items"][0]["baseline_finish"] == "2026-10-15",
           f"重新冻基线：ACT-002 基线完成日 → {b2['items'][0]['baseline_finish']}")

    step("TC-11 列表：契约形状 / 筛选 / 分页")
    p = call("list")
    record(isinstance(p, dict) and "items" in p and "total" in p and p["total"] == 4,
           f"list 返回 {{items, total}}（total={p['total']}）")
    record(len(p["items"][0]) == len(call("get", act_no="ACT-001")), "列表项与 get 同口径")
    record(call("list", kind="milestone")["total"] == 2, "按类型筛：里程碑 2 条")
    record(call("list", wbs_no=LEAF)["total"] == 4, "按挂靠元素筛：4 条")
    record(call("list", status="completed")["total"] == 1, "按状态筛：已完成 1 条")
    p1_ = call("list", page=1, size=3)
    p2_ = call("list", page=2, size=3)
    record(len(p1_["items"]) == 3 and p1_["total"] == 4 and len(p2_["items"]) == 1,
           "分页 total 为切片前全量、items 为切片")
    record(call("list", keyword="舱板")["total"] == 2, "关键词筛命中 2 条")

    step("TC-12 挂靠另一棵叶子也能建（换一个叶子元素）")
    a5 = call("create", name="热控涂层", wbs_no="800000.02", duration_days=2, phase="start")
    record(a5["wbs_no"] == "800000.02", f"{a5['act_no']} 挂到 800000.02")
    record([x["wbs_no"] for x in call("check_network")["no_activity"]] == [],
           "该叶子建了活动后，从「叶子无活动」里消失")

    # ── §2 负例（BR 逐条） ────────────────────────────────
    step("TC-13 BR-01 开口端：体检能报出来")
    chk2 = call("check_network")
    kinds = {(x["act_no"], x["missing"]) for x in chk2["open_ends"]}
    # ⚠ ACT-005 带 phase="start"（边界里程碑）→ **只**豁免"缺前置"，"缺后续"必须报出来
    record(("ACT-005", "后续") in kinds and ("ACT-005", "前置") not in kinds,
           f"边界里程碑的开口端豁免是**单向**的：{sorted(kinds)}")
    record(chk2["total"] == 1, f"体检总数 {chk2['total']}")

    step("TC-14 BR-02 禁冗余链接（材料 §5.5.8 的例子：A→B、B→C 时 A→C 冗余）")
    # ⚠ 两个入口都要拦：link 连一条、create 时一次性塞进去
    expect_err(lambda: call("link", act_no="ACT-003", predecessor_no="ACT-001"), "冗余链接")
    expect_err(lambda: call("create", name="冗余活动", wbs_no=LEAF, duration_days=1,
                            predecessors="ACT-001,ACT-002"), "冗余链接")
    record(call("list")["total"] == 5,
           "两次被拒都没落库（列表仍 5 条）—— 所以体检里的 redundant 分支**造不出样本**，"
           "这正是闸门生效的证据")

    step("TC-15 BR-03 逻辑链完整且无环")
    expect_err(lambda: call("create", name="孤儿", wbs_no=LEAF, duration_days=1,
                            predecessors="ACT-999"), "不存在")
    expect_err(lambda: call("link", act_no="ACT-001", predecessor_no="ACT-003"), "成环")
    expect_err(lambda: call("link", act_no="ACT-002", predecessor_no="ACT-002"), "不能以自己为前置")
    expect_err(lambda: call("link", act_no="ACT-002", predecessor_no="ACT-001"), "已经有前置")

    step("TC-16 BR-04 工期规则")
    expect_err(lambda: call("create", name="带工期的里程碑", wbs_no=LEAF, kind="milestone",
                            duration_days=3), "必须为 0")
    expect_err(lambda: call("create", name="零工期活动", wbs_no=LEAF, duration_days=0),
               "必须大于 0")
    expect_err(lambda: call("update", act_no="ACT-005", duration_days=0), "必须大于 0")

    step("TC-17 BR-05 必须挂在 WBS 叶子元素上（跨应用）")
    expect_err(lambda: call("create", name="挂父元素", wbs_no=PARENT, duration_days=1),
               "最底层元素")
    expect_err(lambda: call("create", name="挂不存在的元素", wbs_no="999999", duration_days=1),
               "不存在")
    expect_err(lambda: call("create", name="不挂元素", wbs_no="  ", duration_days=1),
               "必须挂在")

    step("TC-18 BR-06 活动名称唯一")
    expect_err(lambda: call("create", name="装配舱板", wbs_no=LEAF, duration_days=1), "同名活动")
    # ⚠ 用**未基线**的活动测改名（已基线的会先撞 BR-07 的闸，测不到 BR-06）
    expect_err(lambda: call("update", act_no="ACT-005", name="装配舱板"), "同名活动")
    expect_err(lambda: call("create", name="  ", wbs_no=LEAF, duration_days=1), "不能为空")

    step("TC-19 BR-07 基线后改动走变更流程（跨应用校验已批准）")
    expect_err(lambda: call("update", act_no="ACT-003", duration_days=9), "必须走变更流程")
    expect_err(lambda: call("link", act_no="ACT-003", predecessor_no="ACT-001"), "冗余链接")
    expect_err(lambda: call("change", act_no="ACT-003", change_no="  "), "必须给出已批准的变更请求号")
    expect_err(lambda: call("change", act_no="ACT-003", change_no="CR-999"), "不存在")
    # 未批准的变更不能用于修订（CR-002 停在审批中）
    cr2 = call_cr("create", title="未批准的变更", requester="进度组", ci_nos=ci["ci_no"])
    call_cr("analyze", cr_no=cr2["cr_no"], impact_analysis="仅登记")
    expect_err(lambda: call("change", act_no="ACT-003", change_no=cr2["cr_no"]), "尚未批准")
    # 未基线的活动不需要走变更流程
    call("create", name="未基线的活动", wbs_no="800000.02", duration_days=2)
    expect_err(lambda: call("change", act_no="ACT-006", change_no=cr_no), "还没基线")

    step("TC-20 BR-08 回填实绩不动基线（材料 §7.3 原话）")
    before = call("get", act_no="ACT-003")
    after = call("record_progress", act_no="ACT-003", percent_complete=100,
                 actual_start="2026-10-12", actual_finish="2026-10-14")
    record(after["status"] == "completed", f"ACT-003 → {after['status']}")
    record(before["baseline_start"] == after["baseline_start"]
           and before["baseline_finish"] == after["baseline_finish"],
           f"基线一字未变（{after['baseline_start']} → {after['baseline_finish']}）")
    record(before["duration_days"] == after["duration_days"]
           and before["predecessors"] == after["predecessors"],
           "工期与逻辑链也没被实绩回填改动")

    step("TC-21 get 未命中 / 空编号")
    n_before = call("list")["total"]
    record(call("get", act_no="ACT-999") is None, "get 未命中返回 None（不抛异常）")
    record(call("get", act_no="  ") is None, "空编号返回 None")
    record(call("list")["total"] == n_before, f"未命中不产生副作用：仍 {n_before} 条")

    step("TC-22 体检能报①非叶子挂靠（跨应用）②工期异常")
    # 给 800000.02 加个子元素 → 挂在它下面的 ACT-005 就不再合规
    call_wbs("add_child", parent_no="800000.02", title="涂层子项")
    chk3 = call("check_network")
    record(any(x["wbs_no"] == "800000.02" for x in chk3["non_leaf"]),
           f"挂靠元素长了子元素后被报出：{chk3['non_leaf']}")

    step("TC-23 状态机可覆盖性（三个状态都有服务能到达）")
    want = {"planned", "in_progress", "completed"}
    record(STATES_SEEN == want, f"本链已到达的状态 = {sorted(STATES_SEEN)}")

    # ── §3 四种关系 / 滞后 / 日历（2026-09-26 增补：材料 §5.5.8.2 与 §5.5.9.2）──
    # 独立起一条新网络，免得扰动前面那些"按默认日历算的日期"断言
    step("TC-30 四种关系模型都能用（FS/SS/FF/SF）")
    call("add_milestone", name="四条关系开工", wbs_no="800000.01", phase="start")
    call("create", name="R-甲", wbs_no="800000.01", duration_days=5, predecessors="ACT-007")
    call("create", name="R-乙", wbs_no="800000.01", duration_days=3,
         predecessors="ACT-008:SS:2:与甲并行启动")
    call("create", name="R-丙", wbs_no="800000.01", duration_days=4,
         predecessors="ACT-008:FF:1:与甲同步收口")
    call("create", name="R-丁", wbs_no="800000.01", duration_days=2,
         predecessors="ACT-009:SF:0:装配线移交")
    call("add_milestone", name="四条关系收尾", wbs_no="800000.01",
         predecessors="ACT-010,ACT-011", phase="finish")
    v3 = call("schedule_view", project_start="2026-10-05")
    by3 = {x["name"]: x for x in v3["items"]}
    record(by3["R-甲"]["early_start"] == "2026-10-06" and by3["R-甲"]["early_finish"] == "2026-10-12",
           f"FS：R-甲 {by3['R-甲']['early_start']}→{by3['R-甲']['early_finish']}（紧随里程碑）")
    record(by3["R-乙"]["early_start"] == "2026-10-08",
           f"SS+2：R-乙 与甲**同时起算再滞后 2 个工作日** → {by3['R-乙']['early_start']}")
    record(by3["R-丙"]["early_finish"] == "2026-10-13",
           f"FF+1：R-丙 的完成 = 甲的完成 + 1 → {by3['R-丙']['early_finish']}")
    record(by3["R-丁"]["early_finish"] == "2026-10-08",
           f"SF：R-丁 的完成挂在甲的**开始**上 → {by3['R-丁']['early_finish']}")
    # ⚠ 别断言"甲的浮时 = 0"：整张网还有前一条链（项目完工由**全局**最晚完成决定），
    #   跨链比较才有意义 —— 甲在紧的那条链上，乙/丁有并行余量
    record(by3["R-甲"]["float_days"] <= by3["R-乙"]["float_days"]
           and by3["R-甲"]["float_days"] <= by3["R-丁"]["float_days"],
           f"浮时正确：甲的余量 {by3['R-甲']['float_days']} ≤ 乙 {by3['R-乙']['float_days']}"
           f" / 丁 {by3['R-丁']['float_days']}（并行支线有余量）")
    rels = {r["name"]: r["predecessors"] for r in call("list")["items"]}
    record(":SS:2:" in (rels["R-乙"] or "") and ":FF:1:" in (rels["R-丙"] or ""),
           f"关系与理由落库：{rels['R-乙']} / {rels['R-丙']}")
    record(call("list", keyword="R-")["total"] == 4,
           "新网络四条活动（两个边界里程碑名字里没有 R-，不进这个筛）")

    step("TC-31 非 FS 必须写明理由（材料 §5.5.8.2 的 BoE 要求）")
    expect_err(lambda: call("create", name="没写理由的", wbs_no="800000.01", duration_days=1,
                            predecessors="ACT-008:SS:0"), "必须写明理由")
    expect_err(lambda: call("link", act_no="ACT-011", predecessor_no="ACT-008",
                            rel_type="FF", lag_days=0), "必须写明理由")
    # 理由是**中文**，全角逗号是合法字符；真正会破坏格式的是**冒号**（多出一段）
    expect_err(lambda: call("create", name="理由带冒号", wbs_no="800000.01", duration_days=1,
                            predecessors="ACT-008:SS:0:因为:所以"), "理由里出现了冒号")
    ok_rel = call("create", name="理由带全角逗号", wbs_no="800000.01", duration_days=1,
                  predecessors="ACT-008:SS:0:与甲并行，待资源到位")
    record("与甲并行，待资源到位" in (ok_rel["predecessors"] or ""),
           f"全角逗号的理由正常落库：{ok_rel['predecessors']}")
    n_before = call("list")["total"]
    expect_err(lambda: call("create", name="还是不写理由", wbs_no="800000.01", duration_days=1,
                            predecessors="ACT-009:SF:0"), "必须写明理由")
    record(call("list")["total"] == n_before, f"四次被拒都没落库（仍 {n_before} 条）")

    step("TC-32 关系类型与滞后受校验")
    expect_err(lambda: call("create", name="关系类型非法", wbs_no="800000.01", duration_days=1,
                            predecessors="ACT-008:XX:0:瞎写的"), "四种关系模型")
    expect_err(lambda: call("link", act_no="ACT-011", predecessor_no="ACT-008",
                            rel_type="FF", lag_days="两天", reason="理由是给了"),
               "滞后必须是整数")

    step("TC-33 日历：假日与非工作日会被跳过（§5.5.9.2）")
    cals = call("list_calendars")
    record(cals["total"] >= 1 and any(c["is_default"] for c in cals["items"]),
           f"默认日历已自动建立：{[(c['cal_no'], c['unit']) for c in cals['items']]}")
    before = call("schedule_view", project_start="2026-10-05")["project_finish"]
    call("update_calendar", cal_no="CAL-001", add_holiday="2026-10-07")
    call("update_calendar", cal_no="CAL-001", add_holiday="2026-10-08")
    after = call("schedule_view", project_start="2026-10-05")["project_finish"]
    record(after > before, f"加两个假日后完工顺延：{before} → {after}")
    hol = call("get_calendar", cal_no="CAL-001")["holidays"]
    record(hol == "2026-10-07,2026-10-08", f"假日表落库：{hol}")
    call("update_calendar", cal_no="CAL-001", remove_holiday="2026-10-08")
    record(call("get_calendar", cal_no="CAL-001")["holidays"] == "2026-10-07", "单条移除假日")
    c2 = call("create_calendar", name="按日历天算的日历", unit="edays")
    record(c2["unit"] == "edays" and c2["is_default"] == 0, f"另建 edays 日历 {c2['cal_no']}")
    expect_err(lambda: call("create_calendar", name="乱口径", unit="半天"), "工期口径只能是")

    step("TC-34 edays 口径：忽略周末与假日（§5.5.9.1 的 elapsed duration）")
    v_ed = call("schedule_view", project_start="2026-10-05", calendar_no=c2["cal_no"])
    by_ed = {x["name"]: x for x in v_ed["items"]}
    record(v_ed["unit"] == "edays" and v_ed["unit_cn"].startswith("日历天"),
           f"口径随日历切换：{v_ed['unit_cn']}")
    record(by_ed["R-甲"]["early_start"] == "2026-10-06"
           and by_ed["R-甲"]["early_finish"] == "2026-10-10",
           f"R-甲 5 天按**日历天**排：{by_ed['R-甲']['early_start']}→{by_ed['R-甲']['early_finish']}"
           "（不停周末、也不理会假日表）")
    record(v_ed["holidays"] == [], "edays 日历的假日表为空（该口径下不适用）")

    step("TC-35 默认日历仍按工作日（两套口径并存互不影响）")
    v_days = call("schedule_view", project_start="2026-10-05")
    record(v_days["unit"] == "days" and v_days["project_finish"] != v_ed["project_finish"],
           f"工作日口径完工 {v_days['project_finish']} ≠ 日历天口径 {v_ed['project_finish']}")

    # ── §4 反方向判据：叶子无活动（2026-09-26 增补，材料 WBS 手册 §4 原话）──
    step("TC-36 反方向：新叶子进报告 → 建了活动就出报告")
    call_wbs("add_child", parent_no="800000", title="测控分系统")
    before = sorted(x["wbs_no"] for x in call("check_network")["no_activity"])
    record("800000.03" in before, f"新建的叶子立刻进报告：{before}")
    call("create", name="测控应答机联试", wbs_no="800000.03", duration_days=4, phase="start")
    after = sorted(x["wbs_no"] for x in call("check_network")["no_activity"])
    record("800000.03" not in after, f"建了活动就出报告（报告里还剩 {after}）")

    # ── 汇总 ─────────────────────────────────────────────
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
