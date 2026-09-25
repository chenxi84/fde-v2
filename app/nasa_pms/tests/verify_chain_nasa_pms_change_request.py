"""FDE v2 后端主链端到端验证 · nasa_pms（变更请求 change_request）

链路形态（**本组第一个真跨应用链** —— 变更请求的影响范围要落在真实存在的配置项 / 需求上）：
  前置：configuration_item.create/control/release/archive + requirement.create/obsolete
  change_request(create → analyze → submit_review → approve → implement
                 ＋ create → analyze → submit_review → reject)
    · BR-01 变更必须指明影响范围（配置项或需求至少一个）
    · BR-02 审批与影响分析同事务落库：没有影响分析到不了审批（状态门「先批后分析」不可达）
    · BR-03 编号唯一且不可变（update 字段白名单里没有 cr_no）
    · BR-04 状态机单向；已拒绝 / 已实施为硬终态，任何动作（含审批、实施、修改）全拒
    · BR-05 影响范围的配置项 / 需求必须真实存在（跨应用 configuration_item.list / requirement.list）
    · BR-06 内容只在「已提交」可改（影响分析登记后即定型）
    · BR-07 已归档配置项 / 已废弃需求不得再作为影响范围（跨应用状态校验）

隔离：`shadow_dbs()` —— 业务库**复制**到临时目录，测试全程只读写副本，
**真库零字节接触，且不用停 dev server**。`shadow_clear(GROUP)` 清的是副本。

运行：python app/nasa_pms/tests/verify_chain_nasa_pms_change_request.py
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
APP = "change_request"
CI = f"{GROUP}/configuration_item"
REQ = f"{GROUP}/requirement"

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

    # ── 前置：跨应用造数（影响范围必须落在真实对象上） ─────────
    step("TC-00 前置造数：配置项（受控 / 已归档）+ 需求（草稿 / 已废弃）")
    pf.call(CI, "create", name="飞控软件", ci_type="software", owner="张三")
    pf.call(CI, "create", name="接口控制文档", ci_type="document", owner="李四")
    pf.call(CI, "create", name="废弃的仿真模型", ci_type="model")
    pf.call(CI, "control", ci_no="CI-001")
    pf.call(CI, "release", ci_no="CI-001")                      # CI-001 已发布（可被变更引用）
    pf.call(CI, "control", ci_no="CI-003")
    pf.call(CI, "release", ci_no="CI-003")
    pf.call(CI, "archive", ci_no="CI-003")                      # CI-003 已归档（终态，BR-07）
    pf.call(REQ, "create", title="系统应支持 1000 并发用户",
            statement="8vCPU/32GB 下 P95 ≤ 2s", req_type="technical", verify_method="test")
    pf.call(REQ, "create", title="已废弃的接口需求", statement="旧方案", req_type="interface",
            verify_method="inspection")
    pf.call(REQ, "obsolete", req_no="REQ-002", reason="接口方案变更")   # REQ-002 已废弃（BR-07）
    record(pf.call(CI, "get", ci_no="CI-003")["status"] == "archived"
           and pf.call(REQ, "get", req_no="REQ-002")["status"] == "obsolete",
           "CI-003 已归档 / REQ-002 已废弃（BR-07 的两个负例靶子就位）")

    # ── 主链（正向） ──────────────────────────────────────
    step("TC-01 提出变更请求（指明影响范围）")
    r1 = call("create", title="飞控软件并发指标上调", requester="张三",
              ci_nos=["CI-001"], req_nos=["REQ-001"],
              description="把并发指标从 1000 上调到 1200")
    record(r1["cr_no"] == "CR-001" and r1["status"] == "submitted"
           and r1["ci_nos"] == ["CI-001"] and r1["req_nos"] == ["REQ-001"],
           f"cr_no={r1['cr_no']} status={r1['status']} ci={r1['ci_nos']} req={r1['req_nos']}")

    step("TC-02 编号递增")
    r2 = call("create", title="接口定义调整", requester="李四", ci_nos="CI-002")
    record(r2["cr_no"] == "CR-002" and r2["ci_nos"] == ["CI-002"],
           f"cr_no={r2['cr_no']}（影响范围按逗号文本传入 → 解析成列表）")

    step("TC-03 BR-06 已提交状态可修改内容")
    ru = call("update", cr_no="CR-002", title="接口定义调整（修订）", description="补充说明")
    record(ru["title"] == "接口定义调整（修订）" and ru["description"] == "补充说明"
           and ru["status"] == "submitted",
           f"title={ru['title']}")

    step("TC-04 BR-01 影响范围为空 → 拒绝（新建）")
    record(True, expect_err(lambda: call("create", title="空范围变更", requester="张三"),
                            "变更必须指明影响范围"))
    record(True, expect_err(lambda: call("create", title="空范围变更", requester="张三",
                                        ci_nos=[], req_nos=" , "),
                            "变更必须指明影响范围"))

    step("TC-05 BR-01 修改时把范围改成空 → 拒绝（改后整体校验）")
    record(True, expect_err(lambda: call("update", cr_no="CR-002", ci_nos=[]),
                            "变更必须指明影响范围"))

    step("TC-06 BR-05 配置项不存在 → 拒绝")
    record(True, expect_err(lambda: call("create", title="x", requester="张三",
                                        ci_nos=["CI-999"]), "影响的配置项 CI-999 不存在"))

    step("TC-07 BR-05 需求不存在 → 拒绝")
    record(True, expect_err(lambda: call("create", title="x", requester="张三",
                                        req_nos=["REQ-999"]), "影响的需求 REQ-999 不存在"))

    step("TC-08 BR-07 已归档配置项 → 拒绝")
    record(True, expect_err(lambda: call("create", title="x", requester="张三",
                                        ci_nos=["CI-003"]), "已归档（终态）"))

    step("TC-09 BR-07 已废弃需求 → 拒绝")
    record(True, expect_err(lambda: call("create", title="x", requester="张三",
                                        req_nos=["REQ-002"]), "已废弃（终态）"))

    step("TC-10 影响范围去重 + 全角逗号归一")
    rd = call("create", title="范围归一化", requester="王五",
              ci_nos="CI-001，CI-001, CI-002 ")
    record(rd["ci_nos"] == ["CI-001", "CI-002"], f"ci_nos={rd['ci_nos']}（去重保序）")

    step("TC-11 标题 / 申请方为空 → 拒绝")
    record(True, expect_err(lambda: call("create", title="  ", requester="张三",
                                        ci_nos=["CI-001"]), "变更请求标题不能为空"))
    record(True, expect_err(lambda: call("create", title="x", requester="  ",
                                        ci_nos=["CI-001"]), "申请方不能为空"))

    # ── 影响分析 → 审批 ────────────────────────────────────
    step("TC-12 BR-02 先批后分析 → 拒绝（审批门的唯一入口是「提交审批」）")
    record(True, expect_err(lambda: call("approve", cr_no="CR-001", comment="直接批"),
                            "只有审批中的变更请求才能审批（先登记影响分析并提交审批，BR-02）"))
    record(True, expect_err(lambda: call("reject", cr_no="CR-001", comment="直接拒"),
                            "只有审批中的变更请求才能审批"))

    step("TC-13 登记影响分析（已提交 → 影响分析）")
    ra = call("analyze", cr_no="CR-001", impact_analysis="影响 CI-001 的并发指标与 REQ-001 的验证用例")
    record(ra["status"] == "analyzing" and "REQ-001" in ra["impact_analysis"],
           f"status={ra['status']}")

    step("TC-14 BR-02 影响分析为空 → 拒绝")
    record(True, expect_err(lambda: call("analyze", cr_no="CR-002", impact_analysis="   "),
                            "影响分析不能为空"))

    step("TC-15 重复登记影响分析 → 拒绝")
    record(True, expect_err(lambda: call("analyze", cr_no="CR-001", impact_analysis="再来一遍"),
                            "只有已提交的变更请求才能登记影响分析"))

    step("TC-16 BR-06 影响分析登记后内容锁定（修改被拒）")
    record(True, expect_err(lambda: call("update", cr_no="CR-001", title="偷改标题"),
                            "只有已提交的变更请求才能修改"))

    step("TC-17 未提交审批就审批 → 拒绝（影响分析 ≠ 审批中）")
    record(True, expect_err(lambda: call("approve", cr_no="CR-001", comment="批"),
                            "只有审批中的变更请求才能审批"))

    step("TC-18 提交审批（影响分析 → 审批中）")
    rr = call("submit_review", cr_no="CR-001")
    record(rr["status"] == "reviewing", f"status={rr['status']}")

    step("TC-19 重复提交审批 → 拒绝")
    record(True, expect_err(lambda: call("submit_review", cr_no="CR-001"),
                            "只有已完成影响分析的变更请求才能提交审批"))
    record(True, expect_err(lambda: call("submit_review", cr_no="CR-002"),
                            "只有已完成影响分析的变更请求才能提交审批"))

    step("TC-20 BR-02 审批意见为空 → 拒绝")
    record(True, expect_err(lambda: call("approve", cr_no="CR-001", comment="  "),
                            "审批意见不能为空"))
    # ⚠ 必填参数「缺传」由契约层拦（TypeError 被平台归一为系统错误），
    #    所以负例只能传**空白**让业务校验拦 —— 断言的是业务失败，不是参数缺失
    record(True, expect_err(lambda: call("reject", cr_no="CR-001", comment=" \n "),
                            "审批意见不能为空"))

    step("TC-21 批准（审批中 → 已批准），审批意见与审批人落库")
    rap = call("approve", cr_no="CR-001", comment="CCB 2026-09 第 3 次会议通过", approver="CCB-主席")
    record(rap["status"] == "approved" and rap["decision_note"].startswith("CCB 2026-09")
           and rap["approver"] == "CCB-主席" and rap["impact_analysis"],
           f"status={rap['status']} approver={rap['approver']}（影响分析仍在，BR-02 同事务）")

    step("TC-22 重复批准 → 拒绝")
    record(True, expect_err(lambda: call("approve", cr_no="CR-001", comment="再批一次"),
                            "只有审批中的变更请求才能审批"))

    step("TC-23 未批准就实施 → 拒绝")
    record(True, expect_err(lambda: call("implement", cr_no="CR-002"),
                            "只有已批准的变更请求才能实施"))

    step("TC-24 实施（已批准 → 已实施，终态）")
    ri = call("implement", cr_no="CR-001", note="CI-001 已在配置项侧版本变更到 v2")
    record(ri["status"] == "implemented" and ri["implement_note"].startswith("CI-001"),
           f"status={ri['status']} note={ri['implement_note'][:12]}…")

    step("TC-24b 变更实施落到配置项侧（跨应用：CR-001 驱动 CI-001 版本变更）")
    # 材料 FIGURE 6.5-4 第 9 步「Execute approved changes」的执行面在配置项应用：
    # change_request 只发号，configuration_item.bump_version(ci_no, n, cr_no) 才真正改版本。
    cb = pf.call(CI, "bump_version", ci_no="CI-001", new_version=2, change_no="CR-001")
    record(cb["version"] == 2 and cb["change_no"] == "CR-001"
           and cb["status"] == "controlled",
           f"CI-001 → v{cb['version']} change_no={cb['change_no']}（状态回落受控，待重新发版）")

    step("TC-24c 另提一条变更请求（供列表筛选 / 分页用例）")
    r4 = call("create", title="飞控软件接口微调", requester="张三", ci_nos=["CI-001"])
    record(r4["cr_no"] == "CR-004" and r4["status"] == "submitted", f"cr_no={r4['cr_no']}")

    step("TC-25 BR-04 已实施是硬终态：实施 / 修改 / 分析 / 审批 全拒")
    record(True, expect_err(lambda: call("implement", cr_no="CR-001"),
                            "已处于终态「已实施」"))
    record(True, expect_err(lambda: call("update", cr_no="CR-001", title="再改"),
                            "已处于终态「已实施」"))
    record(True, expect_err(lambda: call("analyze", cr_no="CR-001", impact_analysis="再分析"),
                            "已处于终态「已实施」"))
    record(True, expect_err(lambda: call("approve", cr_no="CR-001", comment="补批"),
                            "已处于终态「已实施」"))
    record(True, expect_err(lambda: call("submit_review", cr_no="CR-001"),
                            "已处于终态「已实施」"))

    # ── 拒绝分支 ──────────────────────────────────────────
    step("TC-26 拒绝（审批中 → 已拒绝，终态）")
    call("analyze", cr_no="CR-002", impact_analysis="只影响 ICD 文档")
    call("submit_review", cr_no="CR-002")
    rj = call("reject", cr_no="CR-002", comment="证据不足，退回补充分析", approver="CCB-主席")
    record(rj["status"] == "rejected" and rj["decision_note"].startswith("证据不足"),
           f"status={rj['status']}")

    step("TC-27 BR-04 已拒绝不得实施；终态不可再动")
    record(True, expect_err(lambda: call("implement", cr_no="CR-002"),
                            "已处于终态「已拒绝」"))
    record(True, expect_err(lambda: call("update", cr_no="CR-002", title="复活"),
                            "已处于终态「已拒绝」"))

    # ── 查询 ─────────────────────────────────────────────
    step("TC-28 查询详情 + 未命中不抛异常")
    record(call("get", cr_no="CR-001")["requester"] == "张三", "字段完整")
    # 对照断言（T2 门禁：本步不能只证明「没抛异常」）—— 未命中**不产生副作用**：
    _before = call("list")["total"]
    record(call("get", cr_no="CR-999") is None and call("get", cr_no="") is None, "返回 None")
    record(call("list")["total"] == _before,
           f"未命中不产生副作用：列表仍 {_before} 条")

    step("TC-29 list 契约：{items,total} + 全字段（与 get 同口径）")
    lst = call("list")
    # ⚠ list 返回裸数组（或只 SELECT 子集）都会让前端静默空态 / 列空白
    record(lst.get("total") == 4 and len(lst["items"]) == 4, f"total={lst.get('total')}")
    record(set(lst["items"][0].keys()) == set(call("get", cr_no="CR-001").keys()),
           "list 与 get 字段集一致")
    record(lst["items"][0]["cr_no"] == "CR-001" and isinstance(lst["items"][0]["ci_nos"], list),
           "影响范围以列表返回（视图可直接 join）")

    step("TC-30 列表筛选（状态 / 申请方 / 影响配置项 / 影响需求）+ 分页")
    by_status = call("list", status="implemented")
    record(by_status["total"] == 1 and by_status["items"][0]["cr_no"] == "CR-001",
           f"status=implemented → {by_status['total']} 条")
    by_req = call("list", requester="李四")
    record(by_req["total"] == 1 and by_req["items"][0]["cr_no"] == "CR-002",
           f"requester=李四 → {by_req['total']} 条")
    by_ci = call("list", ci_no="CI-002")
    record(by_ci["total"] == 2 and [x["cr_no"] for x in by_ci["items"]] == ["CR-002", "CR-003"],
           f"ci_no=CI-002 → {by_ci['total']} 条（CR-003 的影响范围含 CI-002，成员筛选）")
    by_reqno = call("list", req_no="REQ-001")
    record(by_reqno["total"] == 1 and by_reqno["items"][0]["cr_no"] == "CR-001",
           f"req_no=REQ-001 → {by_reqno['total']} 条")
    paged = call("list", page=1, size=2)
    record(len(paged["items"]) == 2 and paged["total"] == 4,
           f"分页 size=2 → 本页 {len(paged['items'])} 条 / 共 {paged['total']} 条")

    step("TC-31 编号为空 / 不存在 → 拒绝")
    record(True, expect_err(lambda: call("analyze", cr_no="", impact_analysis="x"),
                            "变更请求编号不能为空"))
    record(True, expect_err(lambda: call("update", cr_no="  ", title="x"),
                            "变更请求编号不能为空"))
    record(True, expect_err(lambda: call("implement", cr_no="CR-999"),
                            "变更请求 CR-999 不存在"))

    step("TC-32 无内容修改 → 拒绝")
    record(True, expect_err(lambda: call("update", cr_no="CR-004"), "没有要修改的内容"))

    # ── 汇总 ─────────────────────────────────────────────
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
