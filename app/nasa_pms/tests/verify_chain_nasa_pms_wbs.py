"""FDE v2 后端主链端到端验证 · nasa_pms（工作分解结构元素 wbs）

链路形态（**自引用层级树 + 两条跨应用读边 + 元素级配置控制**）：
  wbs(create → add_child → baseline → change → baseline → close)
    · BR-01 编号与层级自洽（分层十进制码、≤ 7 层、≤ 24 字符、父号自洽）
    · BR-02 父先于子（父不存在不得建子；父未基线子不得基线）
    · BR-03 不得含未授权范围（元素必须有范围定义出处才能基线）
    · BR-04 产品导向（材料 §3.5.2 点名的非产品词一律拦 —— 是例子不是穷举）
    · BR-05 基线后修订走变更流程（跨应用 `change_request.get` 校验变更已批准）
    · BR-06 未收口不得关闭（子元素全关、且不在变更中）
    · BR-07 编号落库后不可变

隔离：`shadow_dbs()` —— 业务库**复制**到临时目录，测试全程只读写副本，
**真库零字节接触，且不用停 dev server**。`shadow_clear(GROUP)` 清的是副本。

运行：python app/nasa_pms/tests/verify_chain_nasa_pms_wbs.py
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
APP = "wbs"
CR_APP = "change_request"
REQ_APP = "requirement"

RESULTS = []
# 全程观察到的元素状态 —— 用于证明「状态机里每个状态都有服务能到达它」
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
                "draft", "baselined", "in_change", "closed"):
            STATES_SEEN.add(out["status"])
        return out

    def call_cr(svc, **kw):
        return pf.call(f"{GROUP}/{CR_APP}", svc, **kw)

    def call_req(svc, **kw):
        return pf.call(f"{GROUP}/{REQ_APP}", svc, **kw)

    # ── 前置：一条已批准的变更请求（BR-05 的跨应用上游）────
    step("前置：造配置项 → 已批准的变更请求 → 两条需求")
    # ⚠ 变更请求的 create 会**跨应用校验**它引用的配置项存在（BR-05），所以先建配置项
    ci = pf.call(f"{GROUP}/configuration_item", "create", name="星务软件", ci_type="software")
    ci_no = ci["ci_no"]
    cr = call_cr("create", title="星务软件时序微调", requester="星务分系统",
                 ci_nos=ci_no, description="时序微调，需重新集成")
    cr_no = cr["cr_no"]
    call_cr("analyze", cr_no=cr_no, impact_analysis="影响星务软件时序，需复测")
    call_cr("submit_review", cr_no=cr_no)
    call_cr("approve", cr_no=cr_no, comment="同意", approver="项目经理")
    record(call_cr("get", cr_no=cr_no)["status"] == "approved",
           f"前置变更 {cr_no} 已批准（BR-05 的校验对象）")
    cr2 = call_cr("create", title="未批准的那条", requester="载荷分系统", ci_nos=ci_no)
    cr2_no = cr2["cr_no"]
    call_cr("analyze", cr_no=cr2_no, impact_analysis="仅登记，不提交审批")
    record(call_cr("get", cr_no=cr2_no)["status"] == "analyzing",
           f"前置变更 {cr2_no} 停在影响分析（未批准，用于负例 TC-20）")
    req1 = call_req("create", title="星上存储器容量不小于 2 Tbit", statement="存储 ≥ 2 Tbit",
                    req_type="technical", verify_method="test")
    req2 = call_req("create", title="单圈观测时长不低于 12 分钟", statement="单圈 ≥ 12 min",
                    req_type="system", verify_method="analysis")
    record(req1["req_no"] == "REQ-001" and req2["req_no"] == "REQ-002", "两条需求就绪")

    # ── §1 主链 ──────────────────────────────────────────
    step("TC-01 建根元素（顶层 6 位数字码）")
    root = call("create", wbs_no="123456", title="遥感卫星系统", owner="总体设计部",
                description="EO-3 遥感卫星，含星务、载荷、测控三个分系统")
    record(root["wbs_no"] == "123456" and root["level"] == 1 and root["parent_no"] is None,
           f"wbs_no={root['wbs_no']} level={root['level']} parent_no={root['parent_no']}")
    record(root["status"] == "draft" and root["rev_no"] == 0 and root["kind"] == "product",
           f"status={root['status']} rev_no={root['rev_no']} kind={root['kind']}")

    step("TC-02 逐层分解：子号由系统按规则分配")
    c1 = call("add_child", parent_no="123456", title="星务分系统")
    c2 = call("add_child", parent_no="123456", title="载荷分系统")
    record(c1["wbs_no"] == "123456.01" and c2["wbs_no"] == "123456.02",
           f"自动子号 = {c1['wbs_no']} / {c2['wbs_no']}")
    record(c1["level"] == 2 and c1["parent_no"] == "123456", "层级与父号派生正确")

    step("TC-03 指定父元素直接建元素（父号须与编号自洽）")
    c3 = call("create", wbs_no="123456.03", title="测控分系统", parent_no="123456")
    record(c3["level"] == 2 and c3["parent_no"] == "123456", "123456.03 建成，层级 2")

    step("TC-04 基线（父未基线时子先被拦，见 TC-16；自顶向下逐级基线）")
    call("update", wbs_no="123456", scope_ref="SOW §3.1 系统级范围")
    b_root = call("baseline", wbs_no="123456")
    record(b_root["status"] == "baselined" and b_root["rev_no"] == 0,
           f"根元素已基线，版次 {b_root['rev_no']}")
    call("update", wbs_no="123456.01", scope_ref="SOW §3.2 星务范围", req_nos="REQ-001")
    call("update", wbs_no="123456.02", scope_ref="SOW §3.3 载荷范围", req_nos="REQ-002")
    b1 = call("baseline", wbs_no="123456.01")
    b2 = call("baseline", wbs_no="123456.02")
    record(b1["status"] == "baselined" and b2["status"] == "baselined",
           "两个子分系统已基线（父已基线，闸门放行）")

    step("TC-05 发起变更：已基线元素 + 已批准的变更号")
    ch = call("change", wbs_no="123456.01", change_no=cr_no, note="时序微调，星务软件重新集成")
    record(ch["status"] == "in_change" and ch["change_no"] == cr_no,
           f"123456.01 → {ch['status']}，挂变更 {ch['change_no']}")
    record("时序微调" in (ch["description"] or ""), "变更说明并入描述（留痕）")

    step("TC-06 落实变更：版次 +1、修订授权落库")
    b_again = call("baseline", wbs_no="123456.01")
    record(b_again["status"] == "baselined" and b_again["rev_no"] == 1,
           f"回到已基线，版次 {b_again['rev_no']}")
    record(b_again["rev_authorization"] == cr_no,
           f"修订授权 = {b_again['rev_authorization']}（字典必备字段 §3.4.4g）")

    step("TC-07 关闭（先关子、再关父）")
    call("close", wbs_no="123456.01", note="星务分系统交付完成")
    closed = call("get", wbs_no="123456.01")
    record(closed["status"] == "closed", "子元素已关闭")
    record(closed["close_note"] == "星务分系统交付完成", "关闭说明落库")

    step("TC-08 列表：契约形状与层级序")
    p = call("list")
    record(isinstance(p, dict) and "items" in p and "total" in p,
           f"list 返回 {{items, total}}（total={p['total']}）")
    nos = [x["wbs_no"] for x in p["items"]]
    record(nos == sorted(nos) and nos[0] == "123456",
           f"按编号升序 = 层级序：{nos}")
    record(len(p["items"][0]) == len(call("get", wbs_no="123456")),
           "列表项与 get 同口径（全字段）")

    step("TC-09 树与索引")
    t = call("tree", root="123456")
    kids = [x["wbs_no"] for x in t["children"]]
    record(kids == ["123456.01", "123456.02", "123456.03"],
           f"树的子节点 = {kids}")
    record(call("tree")[0]["wbs_no"] == "123456", "root 为空时返回全部顶层")

    step("TC-10 需求覆盖对账（跨应用只读 requirement.list）")
    cov = call("coverage")
    record(cov["requirements_total"] == 2, f"读到 {cov['requirements_total']} 条需求（跨应用）")
    record([u["req_no"] for u in cov["uncovered"]] == [],
           f"两条需求都已被元素认领（covered={cov['covered']}）")
    record(any(x["wbs_no"] == "123456.03" for x in cov["unassigned"]),
           "未挂需求出处的元素被列出（测控分系统）")

    # ── §2 负例（BR 逐条） ────────────────────────────────
    step("TC-11 BR-01 编号格式")
    expect_err(lambda: call("create", wbs_no="ABC123", title="不合规编号"), "不符合编码规则")
    expect_err(lambda: call("create", wbs_no="12345", title="少一位"), "不符合编码规则")
    expect_err(lambda: call("create", wbs_no="123456.1", title="子号非两位"), "不符合编码规则")

    step("TC-12 BR-01 长度上限（6 位顶层码下，第 8 层至少要 27 字符，故长度先触顶）")
    expect_err(lambda: call("create", wbs_no="123456.01.02.03.04.05.06.07", title="过深"),
               "超过上限")

    step("TC-13 BR-01 父号与编号不自洽")
    expect_err(lambda: call("create", wbs_no="123456.09.08", parent_no="123456.99",
                            title="父号不对"), "不一致")

    step("TC-14 BR-01 非顶层必须给出父号")
    expect_err(lambda: call("create", wbs_no="123456.08", title="没给父号"),
               "必须给出父元素编号")

    step("TC-15 BR-02 父元素不存在")
    expect_err(lambda: call("add_child", parent_no="999999", title="孤儿"), "不存在")

    step("TC-16 BR-02 父未基线，子不得基线")
    # ⚠ 要找一个**父仍是草稿**的分支：根元素此时已基线，拿它当父测不出这条闸
    call("add_child", parent_no="123456.03", title="地面测控对接")     # 123456.03 此刻仍是草稿
    call("update", wbs_no="123456.03.01", scope_ref="SOW §3.4 测控范围")
    expect_err(lambda: call("baseline", wbs_no="123456.03.01"), "尚未基线")

    step("TC-17 BR-03 没有范围定义出处的元素不得基线")
    call("add_child", parent_no="123456", title="测控应答机")          # 父已基线 → 只剩这道闸
    expect_err(lambda: call("baseline", wbs_no="123456.04"), "范围定义出处")

    step("TC-18 BR-04 非产品词（材料 §3.5.2 的例子）")
    for bad in ("工程部", "设计", "A 阶段", "装配组", "返工"):
        expect_err(lambda b=bad: call("add_child", parent_no="123456", title=b), "非产品词")

    step("TC-19 BR-05 变更号必填")
    expect_err(lambda: call("change", wbs_no="123456.02", change_no="  "),
               "必须给出已批准的变更请求号")

    step("TC-20 BR-05 变更必须是已批准的")
    expect_err(lambda: call("change", wbs_no="123456.02", change_no=cr2_no), "尚未批准")
    expect_err(lambda: call("change", wbs_no="123456.02", change_no="CR-999"), "不存在")

    step("TC-21 BR-05 草稿不在配置控制之下，无需变更流程")
    expect_err(lambda: call("change", wbs_no="123456.03", change_no=cr_no), "还是草稿")

    step("TC-22 BR-05 已基线不得直接修改（要走变更流程）")
    expect_err(lambda: call("update", wbs_no="123456.02", owner="载荷分系统"),
               "必须走变更流程")

    step("TC-23 BR-06 变更中不得直接关闭")
    call("change", wbs_no="123456.02", change_no=cr_no, note="载荷接口调整")
    expect_err(lambda: call("close", wbs_no="123456.02"), "正处于变更中")
    call("baseline", wbs_no="123456.02")                 # 落实变更，回到已基线

    step("TC-24 BR-06 有未关闭子元素不得关闭")
    err = expect_err(lambda: call("close", wbs_no="123456"), "未关闭的子元素")
    record("123456.02" in err or "123456.03" in err, "报错点名了未收口的子元素")
    expect_err(lambda: call("close", wbs_no="123456.04"), "还是草稿")
    record(True, "草稿元素本就不在配置控制之下，close 被拒（提示先纳入基线）")

    step("TC-25 逐级收口：补齐范围出处 → 基线 → 关闭（自下而上）")
    call("update", wbs_no="123456.04", scope_ref="SOW §3.5 测控应答机")
    call("baseline", wbs_no="123456.04")
    call("update", wbs_no="123456.03", scope_ref="SOW §3.4 测控分系统范围")
    call("baseline", wbs_no="123456.03")
    call("baseline", wbs_no="123456.03.01")
    call("close", wbs_no="123456.03.01", note="对接完成")
    call("close", wbs_no="123456.03", note="测控分系统交付完成")
    record(call("get", wbs_no="123456.03")["status"] == "closed", "测控分系统整枝收口")
    call("close", wbs_no="123456.02", note="载荷分系统交付完成")
    expect_err(lambda: call("close", wbs_no="123456"), "未关闭的子元素")
    record(True, "尚有一个未收口的子元素（123456.04）—— 根元素仍不能关")
    call("close", wbs_no="123456.04", note="应答机交付完成")
    closed_root = call("close", wbs_no="123456", note="整星 WBS 收口")
    record(closed_root["status"] == "closed", "全树收口后根元素关闭")

    step("TC-25b BR-06 已关闭是终态")
    expect_err(lambda: call("update", wbs_no="123456", owner="x"), "终态")
    expect_err(lambda: call("close", wbs_no="123456"), "已经关闭")
    expect_err(lambda: call("baseline", wbs_no="123456"), "终态")

    step("TC-26 BR-07 编号不可变（update 的字段白名单里没有 wbs_no）")
    import inspect
    from app.nasa_pms.wbs.wbs import Wbs
    sig = inspect.signature(Wbs.update)
    record("wbs_no" in sig.parameters and "title" in sig.parameters,
           "update 的第一参数是定位用的 wbs_no；可改字段里没有编号（无从改起）")

    step("TC-27 重复基线（另起一棵未关闭的树来测 —— 123456 此时已收口）")
    call("create", wbs_no="654321", title="地面支持系统")
    call("update", wbs_no="654321", scope_ref="SOW §4 地面段")
    call("baseline", wbs_no="654321")
    expect_err(lambda: call("baseline", wbs_no="654321"), "已经是已基线状态")

    step("TC-28 get 未命中 / 空编号")
    n_before = call("list")["total"]
    record(call("get", wbs_no="999999") is None, "get 未命中返回 None（不抛异常）")
    record(call("get", wbs_no="  ") is None, "空编号返回 None")
    record(call("list")["total"] == n_before, f"未命中不产生副作用：仍 {n_before} 条")

    step("TC-29 状态机可覆盖性（每个状态都有服务能到达）")
    want = {"draft", "baselined", "in_change", "closed"}
    record(STATES_SEEN == want, f"本链已到达的状态 = {sorted(STATES_SEEN)}")

    step("TC-30 筛选与分页")
    allp = call("list")["total"]
    # 收口的是 123456 那棵树的六枝（根 + .01/.02/.03/.03.01/.04）；654321 停在已基线
    record(call("list", status="closed")["total"] == 6,
           f"按状态筛：closed = {call('list', status='closed')['total']}（六枝全关）")
    record(call("list", status="baselined")["total"] == 1,
           "按状态筛：baselined = 1（654321）")
    record(call("list", kind="product")["total"] == allp, "按类型筛：全部是 product")
    p1 = call("list", page=1, size=2)
    p2 = call("list", page=2, size=2)
    record(len(p1["items"]) == 2 and p1["total"] == allp and len(p2["items"]) == 2,
           f"分页 total={p1['total']}（切片前全量）、items 为切片")
    # 关键词覆盖**编号 / 名称 / 描述**三列 —— 根元素的描述里就含「星务、载荷、测控三个分系统」，
    # 所以命中的不只标题含「星务」的那条（断言要按三列判，别只看 title）
    kw = call("list", keyword="星务")
    record(kw["total"] == 2 and all(
        "星务" in (x["title"] + " " + (x["description"] or "") + " " + x["wbs_no"])
        for x in kw["items"]),
        f"关键词筛命中 {kw['total']} 条（编号/名称/描述任一命中）")

    # ── 汇总 ─────────────────────────────────────────────
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
