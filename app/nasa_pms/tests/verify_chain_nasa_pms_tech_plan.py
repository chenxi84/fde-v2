"""FDE v2 后端主链端到端验证 · nasa_pms（技术计划 tech_plan）

链路形态（单应用，含**聚合内一张子表**（版本台账）、一条**环状**状态机、一个跨聚合**查询视图**，
**无任何跨应用调用** —— 卡片 10 的「跨应用调用：无」）：
  tech_plan(create → submit → approve(落版本台账) → revise(版本递增、阶段推进)
            → submit → approve)                                              ← 主链
  tech_plan(create → submit → withdraw(回草稿) → update → submit)            ← 撤回后可改、停在审批中
  tech_plan(create → submit → approve → revise → submit → withdraw)          ← 撤回回「已修订」
  tech_plan(create → submit → approve → revise)                              ← 停在已修订
  tech_plan(create)                                                          ← 停在草稿
    · BR-01 计划编号唯一且不可变（PLAN-<三位序号>；update 的字段白名单里没有 plan_no）
    · BR-02 计划与阶段绑定：计划类型 / 覆盖阶段受字典约束且必填（卡片 I-1 前半）
    · BR-03（I-1）同一阶段同一类型只允许一份「已批准」（approve 同事务拦截）
    · BR-04（I-2）版本只增不减、历史版本保留（revise 是唯一递增入口；approve 落版本台账）
    · BR-05 状态守卫：审批中与已批准内容锁定，各有解锁入口（withdraw / revise）
    · BR-06 修订只能从「已批准」发起，且必须给修订说明
    · BR-07 成熟度受字典约束 + 「更新」（U）须已有基线版本（附录 K TABLE K-1 图例）
    · BR-08 批准必须记名（批准人非空）
  查询视图（卡片 I-1 的「至少一份」面）：`coverage` —— 阶段 × 计划类型的覆盖矩阵
  （材料附录 K TABLE K-1 就是这张矩阵），本用例集覆盖它。

隔离：`shadow_dbs()` —— 业务库**复制**到临时目录，测试全程只读写副本，
**真库零字节接触，且不用停 dev server**。`shadow_clear(GROUP)` 清的是副本。

运行：python app/nasa_pms/tests/verify_chain_nasa_pms_tech_plan.py
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
APP = "tech_plan"

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
        print(f"  [!] 应用未加载: {qname}", flush=True)
        return 1
    print(f"  [OK] {qname}", flush=True)

    def call(svc, **kw):
        return pf.call(qname, svc, **kw)

    # ── 主链（正向） ──────────────────────────────────────
    step("TC-01 建一份技术计划（草稿态 V1，编号 PLAN-001）")
    r1 = call("create", name="系统工程管理计划", plan_type="semp", phase="a",
              maturity="preliminary", owner="张三", scope="系统工程过程与 17 项共性技术过程")
    record(r1["plan_no"] == "PLAN-001" and r1["status"] == "draft" and r1["version"] == 1
           and r1["maturity"] == "preliminary" and r1["version_total"] == 0
           and r1["latest_approved_ver"] is None and r1["versions"] == [],
           f"plan_no={r1['plan_no']} status={r1['status']} version=V{r1['version']} "
           f"已批准版本数={r1['version_total']}")

    step("TC-02 编号递增；并造出第二份已批准（PLAN-002，verification@a）")
    r2 = call("create", name="验证与确认计划", plan_type="verification", phase="a",
              maturity="preliminary", owner="李四")
    call("submit", plan_no="PLAN-002")
    r2b = call("approve", plan_no="PLAN-002", approver="李四")
    record(r2["plan_no"] == "PLAN-002" and r2["status"] == "draft"
           and r2b["status"] == "approved" and r2b["version_total"] == 1,
           f"plan_no={r2['plan_no']}（V&V Plan 覆盖 A 阶段）→ 已批准 V1")

    step("TC-03 提交审批：草稿 → 审批中")
    r3 = call("submit", plan_no="PLAN-001")
    record(r3["status"] == "in_review" and r3["version"] == 1,
           f"status={r3['status']}（审批中内容即锁定 —— 审的就是这一版）")

    step("TC-04 批准：审批中 → 已批准，**同一次调用**落一行版本台账（卡片 I-2）")
    r4 = call("approve", plan_no="PLAN-001", approver="李四", note="SRR 前批准")
    v4 = r4["versions"][0] if r4["versions"] else {}
    record(r4["status"] == "approved" and r4["version_total"] == 1
           and r4["latest_approved_ver"] == 1 and r4["latest_approver"] == "李四"
           and v4.get("version") == 1 and v4.get("phase") == "a"
           and v4.get("maturity") == "preliminary" and v4.get("approver") == "李四"
           and v4.get("note") == "SRR 前批准",
           f"status={r4['status']} 台账首行 V{v4.get('version')}@{v4.get('phase')}"
           f"/{v4.get('maturity')} by {v4.get('approver')}")

    step("TC-05 修订（阶段推进）：已批准 → 已修订，**版本递增**（卡片 I-2）")
    r5 = call("revise", plan_no="PLAN-001", summary="阶段推进到 B 阶段，过程裁剪口径更新",
              phase="b", maturity="baseline")
    record(r5["status"] == "revised" and r5["version"] == 2 and r5["phase"] == "b"
           and r5["maturity"] == "baseline"
           and r5["revise_note"] == "阶段推进到 B 阶段，过程裁剪口径更新"
           and r5["version_total"] == 1,
           f"V{r5['version']} phase={r5['phase']} maturity={r5['maturity']}"
           f"（台账仍 1 行 —— 修订本身还没被批准）")

    step("TC-06 历史版本保留：推进到 B 阶段后，A 阶段那一版仍在台账里且**未被改写**")
    r6 = call("get", plan_no="PLAN-001")
    record(len(r6["versions"]) == 1 and r6["versions"][0]["phase"] == "a"
           and r6["versions"][0]["maturity"] == "preliminary"
           and r6["versions"][0]["approver"] == "李四",
           f"台账：V{r6['versions'][0]['version']}@{r6['versions'][0]['phase']}"
           f"（主档当前已是 phase={r6['phase']} —— 快照不回溯改写）")

    step("TC-07 修订后再提交 + 批准：V2 进台账（两版都留着）")
    call("submit", plan_no="PLAN-001")
    r7 = call("approve", plan_no="PLAN-001", approver="李四")
    record(r7["status"] == "approved" and r7["version"] == 2 and r7["version_total"] == 2
           and [v["version"] for v in r7["versions"]] == [1, 2]
           and r7["latest_approved_ver"] == 2,
           f"V{r7['version']} 已批准 · 台账 {r7['version_total']} 版"
           f"（{'/'.join('V%d' % v['version'] for v in r7['versions'])}）")

    step("TC-08 造 PLAN-003：停在「审批中」（覆盖矩阵里的缺口就靠它）")
    call("create", name="集成计划", plan_type="integration", phase="c", owner="王五")
    r8 = call("submit", plan_no="PLAN-003")
    record(r8["plan_no"] == "PLAN-003" and r8["status"] == "in_review"
           and r8["maturity"] == "approach",
           f"{r8['plan_no']} status={r8['status']} maturity={r8['maturity']}（缺省「方法」）")

    step("TC-09 造 PLAN-004：停在「草稿」（从未提交）")
    r9 = call("create", name="人因集成计划", plan_type="hsi", phase="b", owner="赵六")
    record(r9["plan_no"] == "PLAN-004" and r9["status"] == "draft"
           and r9["version_total"] == 0 and r9["versions"] == [],
           f"{r9['plan_no']} status={r9['status']}（草稿态可自由改）")

    step("TC-10 造 PLAN-005：停在「已修订」（V2 待提交；成熟度可用「更新」）")
    call("create", name="技术开发计划", plan_type="technology_dev", phase="d",
         maturity="preliminary", owner="王五")
    call("submit", plan_no="PLAN-005")
    call("approve", plan_no="PLAN-005", approver="王五", note="PDR 前批准")
    r10 = call("revise", plan_no="PLAN-005", summary="D 阶段技术成熟度方案更新",
               maturity="update")
    record(r10["plan_no"] == "PLAN-005" and r10["status"] == "revised"
           and r10["version"] == 2 and r10["maturity"] == "update"
           and r10["version_total"] == 1,
           f"{r10['plan_no']} V{r10['version']} maturity={r10['maturity']}"
           f"（BR-07：「更新」以已有获批版本为前提，此处成立）")

    step("TC-11 造 PLAN-006 / PLAN-007：两张已批准（同类不同阶段—— BR-03 的正面）")
    call("create", name="评审计划", plan_type="review", phase="b", maturity="preliminary")
    call("submit", plan_no="PLAN-006")
    r11a = call("approve", plan_no="PLAN-006", approver="李四")
    call("create", name="验证与确认计划（B 阶段）", plan_type="verification", phase="b",
         maturity="preliminary")
    call("submit", plan_no="PLAN-007")
    r11b = call("approve", plan_no="PLAN-007", approver="王四")
    record(r11a["status"] == "approved" and r11b["status"] == "approved",
           f"PLAN-006（review@b）与 PLAN-007（verification@b）均批准；"
           "PLAN-002（verification@a）不与之冲突")

    step("TC-12 撤回（V1 回草稿）→ 改内容 → 再提交，停在「审批中」")
    call("create", name="配置管理计划", plan_type="cm", phase="e")
    call("submit", plan_no="PLAN-008")
    r12a = call("withdraw", plan_no="PLAN-008", reason="数据管理口径要补")
    r12b = call("update", plan_no="PLAN-008", name="配置管理计划（含数据管理）", owner="孙七")
    r12c = call("submit", plan_no="PLAN-008")
    record(r12a["status"] == "draft" and r12b["name"] == "配置管理计划（含数据管理）"
           and r12c["status"] == "in_review",
           f"V1 撤回回「{r12a['status']}」→ 草稿态内容可改 → 再次提交（{r12c['status']}）")

    step("TC-13 撤回（V2 回「已修订」—— 撤回不丢信息）")
    call("create", name="风险管理计划", plan_type="risk_mgmt", phase="c", maturity="preliminary")
    call("submit", plan_no="PLAN-009")
    call("approve", plan_no="PLAN-009", approver="赵六")
    call("revise", plan_no="PLAN-009", summary="C 阶段风险口径修订")
    call("submit", plan_no="PLAN-009")
    r13 = call("withdraw", plan_no="PLAN-009")
    record(r13["status"] == "revised" and r13["version"] == 2
           and r13["version_total"] == 1,
           f"V2 撤回后回「{r13['status']}」（V2 及以后回已修订，V1 才回草稿）")

    # ── 查询 / 筛选 ──────────────────────────────────────
    step("TC-14 计划列表（缺省：全部 9 份，按编号升序）")
    lst = call("list")
    # ⚠ list 契约是 {items, total}（前端 pageable 依赖它）；返回裸数组会让页面静默显示空态
    items = lst.get("items") or []
    record(lst.get("total") == 9 and [x["plan_no"] for x in items]
           == [f"PLAN-00{i}" for i in range(1, 10)],
           f"total={lst.get('total')} items={[x['plan_no'] for x in items]}")

    step("TC-15 list 与 get 同字段口径（主档字段逐项对齐 + 三计数）")
    one = call("get", plan_no="PLAN-001")
    row = [x for x in items if x["plan_no"] == "PLAN-001"][0]
    record(set(row.keys()) == set(one.keys()) - {"versions"},
           f"list 行字段数={len(row)} / get 主档字段数={len(one) - 1}")
    record(row["version_total"] == 2 and row["latest_approved_ver"] == 2
           and row["latest_approver"] == "李四",
           f"version_total={row['version_total']} latest_approved_ver=V"
           f"{row['latest_approved_ver']} latest_approver={row['latest_approver']}")

    step("TC-16 分页（size=4）")
    paged = call("list", page=1, size=4)
    record(len(paged["items"]) == 4 and paged["total"] == 9,
           f"本页 {len(paged['items'])} 条 / 共 {paged['total']} 条")

    step("TC-17 计划详情：主档 + 版本台账（子表随聚合一起返回）")
    one = call("get", plan_no="PLAN-001")
    record(one["name"] == "系统工程管理计划"
           and [(v["version"], v["phase"]) for v in one["versions"]] == [(1, "a"), (2, "b")],
           "版本台账按 seq 升序：[V1@a, V2@b]（阶段推进的两版都在）")

    step("TC-18 get 未命中 / 空编号不抛异常")
    # 对照断言（T2 门禁：本步不能只证明「没抛异常」）—— 未命中**不产生副作用**：
    _before = call("list")["total"]
    record(call("get", plan_no="PLAN-999") is None, "PLAN-999 → None")
    record(call("list")["total"] == _before,
           f"未命中不产生副作用：列表仍 {_before} 条")
    record(call("get", plan_no="  ") is None, "空编号 → None（不抛异常）")

    # ── 覆盖矩阵（查询视图，卡片 I-1 的「至少一份」面） ────
    step("TC-19 coverage 缺省：6 阶段 × 8 计划类型 = 48 格")
    cov = call("coverage")
    record(cov["total"] == 48 and len(cov["items"]) == 48
           and set(cov["items"][0].keys()) == {"phase", "plan_type", "covered", "covered_by",
                                               "plan_count", "approved_no", "approved_ver",
                                               "approved_maturity"},
           f"total={cov['total']}（格字段：phase/plan_type/covered/covered_by/plan_count/"
           "approved_no/approved_ver/approved_maturity）")

    step("TC-20 覆盖的两个来源：此刻已批准 vs 版本台账里曾获批")
    ca = {r["plan_type"]: r for r in call("coverage", phase="a")["items"]}
    record(len(ca) == 8 and ca["semp"]["covered"] == 1
           and ca["semp"]["covered_by"] == "history" and ca["semp"]["approved_no"] == "PLAN-001"
           and ca["semp"]["approved_ver"] == 1 and ca["semp"]["approved_maturity"] == "preliminary"
           and ca["semp"]["plan_count"] == 0,
           "A 阶段 semp：由**历史版本** V1 覆盖（计划已推进到 B，主档不再是 a）")
    record(ca["verification"]["covered"] == 1
           and ca["verification"]["covered_by"] == "current"
           and ca["verification"]["approved_no"] == "PLAN-002"
           and ca["verification"]["approved_ver"] == 1,
           "A 阶段 verification：由**此刻已批准**的 PLAN-002 覆盖")

    step("TC-21 缺口可见：B 阶段覆盖 3 格；集成计划在 C 阶段只有「审批中」-> 未覆盖")
    cb = {r["plan_type"]: r for r in call("coverage", phase="b")["items"]}
    covered_b = sorted(k for k, r in cb.items() if r["covered"])
    record(covered_b == ["review", "semp", "verification"]
           and cb["hsi"]["covered"] == 0 and cb["hsi"]["plan_count"] == 1,
           f"B 阶段已覆盖 {covered_b}（hsi 有 1 份计划但停在草稿 -> 缺口）")
    cc = {r["plan_type"]: r for r in call("coverage", phase="c")["items"]}
    record(cc["integration"]["covered"] == 0 and cc["integration"]["plan_count"] == 1
           and cc["risk_mgmt"]["covered"] == 1 and cc["risk_mgmt"]["covered_by"] == "history"
           and cc["risk_mgmt"]["approved_ver"] == 1,
           "C 阶段：集成计划（审批中）未覆盖 · 风险管理计划由台账 V1 覆盖")

    step("TC-22 D 阶段由台账覆盖；E 阶段全空（0/8）")
    cd = {r["plan_type"]: r for r in call("coverage", phase="d")["items"]}
    record(cd["technology_dev"]["covered"] == 1
           and cd["technology_dev"]["covered_by"] == "history"
           and cd["technology_dev"]["approved_maturity"] == "preliminary",
           "D 阶段 technology_dev：台账 V1（当时 maturity=preliminary）覆盖 —— "
           "主档成熟度已改成 update，台账仍是当时的快照")
    ce = call("coverage", phase="e")["items"]
    record(sum(r["covered"] for r in ce) == 0,
           f"E 阶段 0/{len(ce)} 覆盖（配置管理计划停在审批中）")

    step("TC-23 coverage 过滤 + 分页契约")
    by_type = call("coverage", plan_type="verification")
    covered_v = sorted(r["phase"] for r in by_type["items"] if r["covered"])
    record(by_type["total"] == 6 and covered_v == ["a", "b"],
           f"plan_type=verification → {by_type['total']} 格，已覆盖 {covered_v}")
    page5 = call("coverage", page=1, size=5)
    record(len(page5["items"]) == 5 and page5["total"] == 48,
           "分页 size=5 → 本页 5 / 共 48")
    bad = call("coverage", phase="zz")
    record(bad["total"] == 0 and bad["items"] == [],
           "非法筛选值 → 空矩阵（与 list 的过滤口径一致，不抛异常）")

    step("TC-24 全矩阵覆盖计数 = 7 格（a:2 / b:3 / c:1 / d:1）")
    allc = call("coverage")["items"]
    hot = sorted((r["phase"], r["plan_type"]) for r in allc if r["covered"])
    record(len(hot) == 7 and hot == [("a", "semp"), ("a", "verification"), ("b", "review"),
                                     ("b", "semp"), ("b", "verification"), ("c", "risk_mgmt"),
                                     ("d", "technology_dev")],
           f"已覆盖 {len(hot)}/48：{hot}")

    # ── BR 逐条（负例） ──────────────────────────────────
    step("TC-30 BR-02 计划类型 / 覆盖阶段受字典约束（先 clean 再判空）")
    record(True, expect_err(lambda: call("create", name="x", plan_type="其它", phase="a"),
                            "计划类型只能是"))
    record(True, expect_err(lambda: call("create", name="x", plan_type="  ", phase="a"),
                            "计划类型不能为空"))
    record(True, expect_err(lambda: call("create", name="x", plan_type="semp", phase="z"),
                            "覆盖阶段只能是"))
    record(True, expect_err(lambda: call("create", name="x", plan_type="semp", phase=""),
                            "覆盖阶段不能为空"))
    record(True, expect_err(lambda: call("create", name="  ", plan_type="semp", phase="a"),
                            "计划名称不能为空"))

    step("TC-31 BR-07 成熟度字典 + 「更新」（U）须已有基线版本")
    record(True, expect_err(lambda: call("create", name="x", plan_type="semp", phase="a",
                                        maturity="其它"), "成熟度只能是"))
    record(True, expect_err(lambda: call("create", name="x", plan_type="semp", phase="a",
                                        maturity="update"),
                            "成熟度「更新」以已有基线版本为前提"))
    record(True, expect_err(lambda: call("update", plan_no="PLAN-004", maturity="update"),
                            "还没有获批过任何版本"))
    ok31 = call("update", plan_no="PLAN-004", maturity="preliminary")
    record(ok31["maturity"] == "preliminary", "未获批过的计划可标「初步」（U 之外都合法）")

    step("TC-32 BR-03（I-1）同一阶段同一类型只允许一份「已批准」")
    r32a = call("create", name="验证与确认计划（另起一份）", plan_type="verification",
                phase="a", maturity="preliminary")
    call("submit", plan_no="PLAN-010")
    record(True, expect_err(lambda: call("approve", plan_no="PLAN-010", approver="钱七"),
                            "同一阶段同一类型只允许一份生效"))
    r32b = call("get", plan_no="PLAN-010")
    record(r32b["status"] == "in_review" and r32b["version_total"] == 0
           and r32a["plan_no"] == "PLAN-010",
           f"被拒后仍是「{r32b['status']}」且台账为空（整次调用未落库）；"
           f"编号递增到 {r32a['plan_no']}（BR-01）")

    step("TC-33 BR-04/BR-05 已批准内容锁定，解锁入口是「修订」（版本递增，不是原地改）")
    record(True, expect_err(lambda: call("update", plan_no="PLAN-002", name="偷改"),
                            "要改请「修订」（revise）出下一版"))
    record(True, expect_err(lambda: call("update", plan_no="PLAN-002", phase="b"),
                            "内容不可直接修改"))
    record(True, expect_err(lambda: call("submit", plan_no="PLAN-002"), "不能重复提交"))
    record(True, expect_err(lambda: call("approve", plan_no="PLAN-002", approver="x"),
                            "已经批准"))
    record(True, expect_err(lambda: call("withdraw", plan_no="PLAN-002"), "已批准，不能撤回"))

    step("TC-34 BR-05 审批中内容锁定，解锁入口是「撤回」")
    record(True, expect_err(lambda: call("update", plan_no="PLAN-003", name="偷改"),
                            "要改请先 withdraw 撤回"))
    record(True, expect_err(lambda: call("submit", plan_no="PLAN-003"), "已经在审批中"))
    record(True, expect_err(lambda: call("revise", plan_no="PLAN-003", summary="x"),
                            "只有已批准的计划才能修订"))
    record(True, expect_err(lambda: call("withdraw", plan_no="PLAN-004"),
                            "不在审批中，无需撤回"))

    step("TC-35 BR-08 批准必须记名")
    record(True, expect_err(lambda: call("approve", plan_no="PLAN-010", approver="   "),
                            "批准人不能为空"))
    record(True, expect_err(lambda: call("approve", plan_no="PLAN-008", approver=""),
                            "批准人不能为空"))

    step("TC-36 BR-06 修订只能从「已批准」发起，且修订说明必填")
    record(True, expect_err(lambda: call("revise", plan_no="PLAN-004", summary="x"),
                            "只有已批准的计划才能修订"))
    record(True, expect_err(lambda: call("revise", plan_no="PLAN-005", summary="x"),
                            "不能连续修订"))
    record(True, expect_err(lambda: call("revise", plan_no="PLAN-002", summary="   "),
                            "修订说明不能为空"))
    record(True, expect_err(lambda: call("revise", plan_no="PLAN-002", summary="x", phase="z"),
                            "覆盖阶段只能是"))
    ok36 = call("revise", plan_no="PLAN-002", summary="A 阶段口径微调")
    record(ok36["version"] == 2 and ok36["phase"] == "a" and ok36["maturity"] == "preliminary",
           f"合法修订：V{ok36['version']}（阶段 / 成熟度不传则沿用当前）")
    ok36b = call("submit", plan_no="PLAN-002")
    ok36c = call("approve", plan_no="PLAN-002", approver="李四")
    record(ok36b["status"] == "in_review" and ok36c["status"] == "approved"
           and ok36c["version_total"] == 2,
           "修订 → 提交 → 批准走通（V2 进台账）")

    step("TC-37 编号不存在 → 拒绝")
    record(True, expect_err(lambda: call("submit", plan_no="PLAN-999"), "不存在"))
    record(True, expect_err(lambda: call("approve", plan_no="PLAN-999", approver="x"), "不存在"))
    record(True, expect_err(lambda: call("revise", plan_no="PLAN-999", summary="x"), "不存在"))
    record(True, expect_err(lambda: call("withdraw", plan_no="PLAN-999"), "不存在"))
    record(True, expect_err(lambda: call("update", plan_no="PLAN-999", name="x"), "不存在"))

    step("TC-38 空编号 / 无内容修改")
    record(True, expect_err(lambda: call("submit", plan_no=""), "计划编号不能为空"))
    record(True, expect_err(lambda: call("update", plan_no="PLAN-004"), "没有要修改的内容"))

    step("TC-39 流转字段不在 update 白名单里（走契约层）+ 必填缺传走契约层")
    # 版本号 / 状态 / 修订说明是流转产物，只能经 submit / approve / revise 写入 ——
    # 根本没有同名形参，传进去由 Python 直接拦下（TypeError），进不了业务校验。
    for kw in ("status", "version", "revise_note", "plan_no"):
        try:
            call("update", plan_no="PLAN-004", **{kw: "x"})
            record(False, f"update 不该接受 {kw}")
        except Exception as e:                                    # noqa: BLE001
            record("TypeError" in type(e).__name__,
                   f"update({kw}=...) → {type(e).__name__}（字段白名单外，走契约层）")
    try:
        call("create", name="x", plan_type="semp")
        record(False, "缺传 phase 应报错")
    except Exception as e:                                        # noqa: BLE001
        record("TypeError" in type(e).__name__,
               f"缺传必填参数 → {type(e).__name__}（走契约层，非业务校验）")

    step("TC-40 BR-01 编号唯一且不可变")
    ok40 = call("update", plan_no="PLAN-004", name="人因集成计划（改名）")
    record(ok40["plan_no"] == "PLAN-004" and ok40["name"] == "人因集成计划（改名）",
           "编号不可改，名称可改")

    step("TC-41 台账是**快照**：不因主档推进 / 成熟度改写而回溯变化")
    p5 = call("get", plan_no="PLAN-005")
    record(p5["maturity"] == "update" and p5["versions"][0]["maturity"] == "preliminary"
           and p5["versions"][0]["phase"] == "d" and p5["versions"][0]["version"] == 1,
           f"主档 maturity={p5['maturity']} / 台账 V1 maturity="
           f"{p5['versions'][0]['maturity']}（当时的判定，不改写）")

    step("TC-42 已停止的计划仍可查、台账随它一起保留（不级联删）")
    p3 = call("get", plan_no="PLAN-003")
    record(p3 is not None and p3["status"] == "in_review" and p3["version_total"] == 0
           and p3["versions"] == [],
           f"PLAN-003（审批中）仍在：{p3['status']} / 台账 {p3['version_total']} 行")

    # ── 汇总 ─────────────────────────────────────────────
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{'='*60}")
    print(f" 用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    for ok, note in bad:
        print(f"    [X] {note}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
