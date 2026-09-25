"""FDE v2 后端主链端到端验证 · nasa_pms（接口 interface）

链路形态（单应用，含**聚合内一子表（版本变更通知记录）**与完整状态机）：
  前置：configuration_item.create/control/release/archive（接口文档本身是配置项，弱引用校验要靶子）
  interface(create → release → revise → release → revise → release → freeze)   ← 主链
  interface(create → release → freeze)                                          ← 短支路
  interface(create → release → revise)                                          ← 停在「变更中」
    · BR-01 接口必须明确两端（卡片 I-1）：两端非空**且不能是同一个系统**
    · BR-02 接口类型受字典约束（材料 §6.3.1.3 的 ICD / IRD / IDD / ICP）
    · BR-03 版本只能递增（字母修订版，首次发布定 A）
    · BR-04 版本变更必须通知两端（卡片 I-2）：每次变更**同事务**写两条通知（提供方 + 使用方）；
            且**只在版本号发生变化的那一刻**通知（变更落实回发布时不重复通知）
    · BR-05 已定版后「两端」与「约定内容（ICD）」不可直接改 —— 须走 revise
    · BR-06 编号唯一且不可变（update 的字段白名单里没有 if_no）
    · BR-07 已冻结为硬终态（改 / 发布 / 变更 / 再冻结全拒）
    · BR-08 关联配置项必须真实存在且**未归档**（跨应用 configuration_item.list）
    · BR-09 只有已发布的接口才能冻结（定义中 / 变更中都不能冻）
  聚合边界（`architecture.md` 聚合根卡 9）：**版本变更通知记录并入本聚合** —— 它随版本变更
  同事务落库、无独立标识（`(if_no, seq)` 复合主键）；跨接口的汇总由 `list_changes`
  这个**查询视图**提供，本用例集同时覆盖它。

隔离：`shadow_dbs()` —— 业务库**复制**到临时目录，测试全程只读写副本，
**真库零字节接触，且不用停 dev server**。`shadow_clear(GROUP)` 清的是副本。

运行：python app/nasa_pms/tests/verify_chain_nasa_pms_interface.py
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
APP = "interface"
CI = f"{GROUP}/configuration_item"

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

    # ── 前置：跨应用造数（关联配置项必须落在真实对象上） ───────
    step("TC-00 前置造数：配置项（草稿 ×2 + 已归档 ×1）")
    pf.call(CI, "create", name="接口控制文档（ICD）", ci_type="document", owner="张三")   # CI-001
    pf.call(CI, "create", name="配电单元设计文件", ci_type="document", owner="李四")     # CI-002
    pf.call(CI, "create", name="已归档的仿真模型", ci_type="model")                     # CI-003
    pf.call(CI, "control", ci_no="CI-003")
    pf.call(CI, "release", ci_no="CI-003")
    pf.call(CI, "archive", ci_no="CI-003")                                             # 终态
    record(pf.call(CI, "get", ci_no="CI-003")["status"] == "archived",
           "CI-001 / CI-002 可用 · CI-003 已归档（BR-08 的负例靶子就位）")

    # ── 主链（正向） ──────────────────────────────────────
    step("TC-01 定义接口（定义中，编号 IF-001，**此时尚无版本**）")
    r1 = call("create", if_name="飞控计算机—舵机控制器 总线接口", if_type="icd",
              provider="飞控计算机（FCC）", consumer="舵机控制器（SACU）",
              icd_content="1553B 总线，周期 20ms", ci_no="CI-001", owner="张三")
    record(r1["if_no"] == "IF-001" and r1["status"] == "defined" and r1["version"] is None
           and r1["changes"] == [] and r1["change_total"] == 0
           and r1["provider"] == "飞控计算机（FCC）" and r1["ci_no"] == "CI-001",
           f"if_no={r1['if_no']} status={r1['status']} version={r1['version']}")

    step("TC-02 编号递增")
    r2 = call("create", if_name="星务计算机—测控应答机 数据接口", if_type="ird",
              provider="星务计算机（OBC）", consumer="测控应答机（TT&C）", owner="李四")
    record(r2["if_no"] == "IF-002" and r2["version"] is None, f"if_no={r2['if_no']}")

    step("TC-03 再定义两条 + 一条停在已发布（供筛选与负例）")
    call("create", if_name="姿控计算机—地面测试设备 测试接口", if_type="idd",
         provider="姿控计算机（ADCS）", consumer="地面测试设备（GSE）")                  # IF-003
    call("create", if_name="电源分系统—配电单元 供电接口", if_type="icd",
         provider="电源分系统（EPS）", consumer="配电单元（PDU）", ci_no="CI-002")      # IF-004
    call("create", if_name="星务计算机—姿控计算机 数据接口", if_type="ird",
         provider="星务计算机（OBC）", consumer="姿态控制计算机（ADCS）")               # IF-005
    record(call("get", if_no="IF-005")["if_no"] == "IF-005", "IF-003 / IF-004 / IF-005 就位")

    step("TC-04 BR-06 定义中可改（含两端与约定内容）—— 编号不可变")
    r4 = call("update", if_no="IF-003", if_name="姿控计算机—地面测试设备 测试接口（修订）",
              provider="姿态控制计算机（ADCS）", icd_content="测试连接器 J1，28V 供电",
              owner="王五")
    record(r4["if_no"] == "IF-003" and r4["if_name"].endswith("（修订）")
           and r4["provider"] == "姿态控制计算机（ADCS）" and r4["owner"] == "王五"
           and r4["change_total"] == 0,
           "编号不可改，定义中的两端与 ICD 内容可改（BR-06 / BR-05 前半）")

    step("TC-05 IF-001 首次发布（定义中 → 已发布：定版 A + **通知两端**）")
    r5 = call("release", if_no="IF-001")
    cs = r5["changes"]
    record(r5["status"] == "released" and r5["version"] == "A" and r5["change_total"] == 2,
           f"status={r5['status']} version={r5['version']} 通知 {r5['change_total']} 条")
    record([(c["seq"], c["action"], c["party"], c["old_version"], c["new_version"])
            for c in cs]
           == [(1, "release", "provider", None, "A"), (2, "release", "consumer", None, "A")],
           "卡片 I-2：提供方一条 + 使用方一条（同事务落库）")
    record(cs[0]["party_name"] == "飞控计算机（FCC）"
           and cs[1]["party_name"] == "舵机控制器（SACU）",
           "通知对象是两端名称快照")

    step("TC-06 IF-001 版本变更 A→B（已发布 → 变更中，再通知两端）")
    r6 = call("revise", if_no="IF-001", new_version="B",
              reason="舵机控制器换代，消息周期 20ms→10ms",
              icd_content="1553B 总线，周期 10ms，见 ICD-001 §3.3")
    record(r6["status"] == "changing" and r6["version"] == "B" and r6["change_total"] == 4,
           f"status={r6['status']} version={r6['version']} 通知 {r6['change_total']} 条")
    record([(c["seq"], c["action"], c["party"], c["old_version"], c["new_version"])
            for c in r6["changes"][2:]]
           == [(3, "revise", "provider", "A", "B"), (4, "revise", "consumer", "A", "B")]
           and r6["changes"][2]["reason"].startswith("舵机控制器换代"),
           "第二次变更同样两端各一条（含变更原因）")
    record("周期 10ms" in (r6["icd_content"] or ""),
           "约定内容（ICD）随版本变更一起更新")

    step("TC-07 变更落实：变更中 → 已发布（**不重复通知**）")
    r7 = call("release", if_no="IF-001")
    record(r7["status"] == "released" and r7["version"] == "B" and r7["change_total"] == 4,
           f"status={r7['status']} version={r7['version']} 通知仍 {r7['change_total']} 条")

    step("TC-08 再变更一次 B→C 并落实（版本号是唯一递增的）")
    r8 = call("revise", if_no="IF-001", new_version="C", reason="增加余度通道")
    record(r8["change_total"] == 6 and r8["version"] == "C", f"通知 {r8['change_total']} 条")
    record(call("release", if_no="IF-001")["status"] == "released", "变更落实完成")

    step("TC-09 IF-001 冻结（已发布 → 已冻结，硬终态）")
    r9 = call("freeze", if_no="IF-001", note="接口随 CDR 定稿，纳入配置管理")
    record(r9["status"] == "frozen" and r9["version"] == "C" and r9["change_total"] == 6
           and r9["freeze_note"] == "接口随 CDR 定稿，纳入配置管理",
           f"status={r9['status']} 累计通知 {r9['change_total']} 条（3 轮 × 两端）")

    step("TC-10 短支路：IF-002 定义 → 发布（A）→ 冻结")
    call("release", if_no="IF-002")
    r10 = call("freeze", if_no="IF-002")
    record(r10["status"] == "frozen" and r10["version"] == "A" and r10["change_total"] == 2,
           f"status={r10['status']} version={r10['version']}")

    step("TC-11 IF-004 / IF-005 发布（各定版 A、各通知两端）")
    r11 = call("release", if_no="IF-004")
    r11b = call("release", if_no="IF-005")
    record(r11["status"] == "released" and r11["change_total"] == 2
           and r11b["status"] == "released" and r11b["version"] == "A",
           "IF-004 已发布 · IF-005 已发布")

    step("TC-12 IF-004 版本变更 A→B（**停在「变更中」**，供后续负例）")
    r12 = call("revise", if_no="IF-004", new_version="B", reason="配电单元增加一路备份供电")
    record(r12["status"] == "changing" and r12["version"] == "B" and r12["change_total"] == 4,
           f"status={r12['status']} version={r12['version']} 通知 {r12['change_total']} 条")

    # ── BR 逐条（负例，全部不改变状态） ──────────────────────
    step("TC-21 BR-01 两端必填（卡片 I-1）→ 拒绝")
    record(True, expect_err(lambda: call("create", if_name="x", if_type="icd",
                                        provider="  ", consumer="B"), "提供方不能为空"))
    record(True, expect_err(lambda: call("create", if_name="x", if_type="icd",
                                        provider="A", consumer=""), "使用方不能为空"))
    record(True, expect_err(lambda: call("create", if_name="x", if_type="icd",
                                        provider="系统甲", consumer="系统甲"),
                            "两端不能是同一个系统"))

    step("TC-22 BR-01 修改**后**的两端也不能相同（改一端也可能撞成同一个）")
    record(True, expect_err(lambda: call("update", if_no="IF-003",
                                        consumer="姿态控制计算机（ADCS）"),
                            "两端不能是同一个系统"))
    record(True, expect_err(lambda: call("update", if_no="IF-003",
                                        provider="地面测试设备（GSE）"),
                            "两端不能是同一个系统"))

    step("TC-23 BR-02 接口类型受字典约束 → 拒绝")
    record(True, expect_err(lambda: call("create", if_name="x", if_type="  ",
                                        provider="A", consumer="B"), "接口类型不能为空"))
    record(True, expect_err(lambda: call("create", if_name="x", if_type="其它",
                                        provider="A", consumer="B"), "接口类型只能是"))
    record(True, expect_err(lambda: call("update", if_no="IF-003", if_type="api"),
                            "接口类型只能是"))

    step("TC-24 BR-08 关联配置项必须存在且未归档（跨应用 configuration_item.list）")
    record(True, expect_err(lambda: call("create", if_name="x", if_type="icd",
                                        provider="A", consumer="B", ci_no="CI-999"),
                            "关联的配置项 CI-999 不存在"))
    record(True, expect_err(lambda: call("create", if_name="x", if_type="icd",
                                        provider="A", consumer="B", ci_no="CI-003"),
                            "已归档（终态），不能作为新的关联"))
    record(True, expect_err(lambda: call("update", if_no="IF-003", ci_no="CI-999"),
                            "不存在"))
    r24 = call("update", if_no="IF-003", ci_no="CI-001")
    record(r24["ci_no"] == "CI-001", "已存在且未归档的配置项可关联")

    step("TC-25 名称必填 / 无内容修改 → 拒绝")
    record(True, expect_err(lambda: call("create", if_name="  ", if_type="icd",
                                        provider="A", consumer="B"), "接口名称不能为空"))
    record(True, expect_err(lambda: call("update", if_no="IF-003", if_name="   "),
                            "接口名称不能为空"))
    record(True, expect_err(lambda: call("update", if_no="IF-003"), "没有要修改的内容"))

    step("TC-26 BR-03 未定版的接口不能变更版本；BR-09 未定版的接口不能冻结（IF-003 定义中）")
    record(True, expect_err(lambda: call("revise", if_no="IF-003", new_version="A",
                                        reason="随便改改"), "尚未定版（定义中）"))
    record(True, expect_err(lambda: call("freeze", if_no="IF-003"),
                            "只有已发布的接口才能冻结"))

    step("TC-27 BR-03 新版本号非法 / 非递增 → 拒绝（IF-005 当前版本 A）")
    record(True, expect_err(lambda: call("revise", if_no="IF-005", new_version="",
                                        reason="改"), "新版本号不能为空"))
    record(True, expect_err(lambda: call("revise", if_no="IF-005", new_version="b",
                                        reason="改"), "必须是单个大写字母"))
    record(True, expect_err(lambda: call("revise", if_no="IF-005", new_version="AB",
                                        reason="改"), "必须是单个大写字母"))
    record(True, expect_err(lambda: call("revise", if_no="IF-005", new_version="A",
                                        reason="改"), "版本只能递增"))

    step("TC-28 BR-04 版本变更必须说明变更原因 → 拒绝")
    record(True, expect_err(lambda: call("revise", if_no="IF-005", new_version="B",
                                        reason="   "), "必须说明变更原因"))

    step("TC-29 BR-03 已发布的接口不能重复发布；BR-09 变更中的接口不能冻结")
    record(True, expect_err(lambda: call("release", if_no="IF-005"), "已经是已发布状态"))
    record(True, expect_err(lambda: call("freeze", if_no="IF-004"),
                            "只有已发布的接口才能冻结"))
    record(True, expect_err(lambda: call("revise", if_no="IF-004", new_version="C",
                                        reason="再改一次"), "已经在变更中"))

    step("TC-30 BR-05 已定版后两端与约定内容不可直接改（IF-005 已发布 / IF-004 变更中）")
    record(True, expect_err(lambda: call("update", if_no="IF-005",
                                        consumer="其它分系统"), "两端不能再改"))
    record(True, expect_err(lambda: call("update", if_no="IF-005",
                                        icd_content="偷改约定内容"), "不能直接改"))
    record(True, expect_err(lambda: call("update", if_no="IF-004",
                                        provider="其它电源"), "两端不能再改"))
    record(True, expect_err(lambda: call("update", if_no="IF-004",
                                        icd_content="偷改约定内容"), "不能直接改"))
    r30 = call("update", if_no="IF-005", owner="赵六", project_no="P-2026-01")
    record(r30["owner"] == "赵六" and r30["project_no"] == "P-2026-01"
           and r30["status"] == "released",
           "描述性字段（责任人 / 所属项目）已发布后仍可改")

    step("TC-31 BR-07 冻结后为硬终态（IF-001 已冻结）")
    record(True, expect_err(lambda: call("update", if_no="IF-001", if_name="偷改"),
                            "已冻结（终态），不能再修改"))
    record(True, expect_err(lambda: call("release", if_no="IF-001"),
                            "已冻结（终态），不能再发布"))
    record(True, expect_err(lambda: call("revise", if_no="IF-001", new_version="D",
                                        reason="再改"), "已冻结（终态），不能再变更版本"))
    record(True, expect_err(lambda: call("freeze", if_no="IF-001"), "已经是冻结状态"))

    step("TC-32 编号为空 / 不存在 → 拒绝")
    record(True, expect_err(lambda: call("release", if_no=""), "接口编号不能为空"))
    record(True, expect_err(lambda: call("update", if_no="  ", if_name="x"),
                            "接口编号不能为空"))
    record(True, expect_err(lambda: call("release", if_no="IF-999"), "不存在"))
    record(True, expect_err(lambda: call("revise", if_no="IF-999", new_version="B",
                                        reason="x"), "不存在"))
    record(True, expect_err(lambda: call("freeze", if_no="IF-999"), "不存在"))
    record(True, expect_err(lambda: call("update", if_no="IF-999", if_name="x"), "不存在"))

    # ── 查询（状态已全部定型，此处的期望值按上面的动作序列算出） ──
    step("TC-41 详情：主档 + 变更通知记录子表（随聚合一起返回）")
    one = call("get", if_no="IF-001")
    record(len(one["changes"]) == 6 and one["changes"][0]["action"] == "release"
           and one["changes"][2]["action"] == "revise"
           and (one["changes"][0]["created_at"] or "") != "",
           f"IF-001 通知 {len(one['changes'])} 条（含落库时间）")

    step("TC-42 get 未命中不抛异常")
    # 对照断言（T2 门禁：本步不能只证明「没抛异常」）—— 未命中**不产生副作用**：
    _before = call("list")["total"]
    record(call("get", if_no="IF-999") is None, "返回 None")
    record(call("list")["total"] == _before,
           f"未命中不产生副作用：列表仍 {_before} 条")

    step("TC-43 查询列表（缺省：全部 5 条，按编号升序）")
    lst = call("list")
    # ⚠ list 契约是 {items, total}（前端 pageable 依赖它）；返回裸数组会让页面静默显示空态
    items = lst.get("items") or []
    record(lst.get("total") == 5 and [x["if_no"] for x in items]
           == ["IF-001", "IF-002", "IF-003", "IF-004", "IF-005"],
           f"total={lst.get('total')} items={[x['if_no'] for x in items]}")

    step("TC-44 list 与 get 同字段口径（主档字段逐项对齐 + 通知计数）")
    one = call("get", if_no="IF-004")
    row = [x for x in items if x["if_no"] == "IF-004"][0]
    record(set(row.keys()) == set(one.keys()) - {"changes"},
           f"list 行字段数={len(row)} / get 主档字段数={len(one) - 1}")
    record(row["change_total"] == 4 and row["version"] == "B" and row["status"] == "changing",
           f"change_total={row['change_total']} version={row['version']}")

    step("TC-45 分页（size=2）")
    paged = call("list", page=2, size=2)
    record(len(paged["items"]) == 2 and paged["total"] == 5
           and [x["if_no"] for x in paged["items"]] == ["IF-003", "IF-004"],
           f"第 2 页 {[x['if_no'] for x in paged['items']]} / 共 {paged['total']} 条")

    step("TC-46 列表筛选（类型 / 状态 / 提供方 / 使用方 / 关联配置项）")
    by_type = call("list", if_type="icd")
    record(by_type["total"] == 2
           and [x["if_no"] for x in by_type["items"]] == ["IF-001", "IF-004"],
           f"if_type=icd → {by_type['total']} 条")
    by_status = call("list", status="frozen")
    record(by_status["total"] == 2
           and [x["if_no"] for x in by_status["items"]] == ["IF-001", "IF-002"],
           f"status=frozen → {by_status['total']} 条")
    record(call("list", status="changing")["total"] == 1
           and call("list", status="defined")["total"] == 1
           and call("list", status="released")["total"] == 1,
           "status 四态各有其条（定义中 / 已发布 / 变更中 / 已冻结）")
    by_prov = call("list", provider="姿态控制计算机（ADCS）")
    record(by_prov["total"] == 1 and by_prov["items"][0]["if_no"] == "IF-003",
           f"provider=姿控计算机 → {by_prov['total']} 条（IF-003 改后的提供方）")
    by_cons = call("list", consumer="姿态控制计算机（ADCS）")
    record(by_cons["total"] == 1 and by_cons["items"][0]["if_no"] == "IF-005",
           f"consumer=姿控计算机 → {by_cons['total']} 条（同一名称在另一端只命中 IF-005）")
    by_ci = call("list", ci_no="CI-001")
    # ⚠ 期望值是 2 不是 1：TC-24 把 IF-003 也关联到了 CI-001（同一份用例自己的动作改写了世界，
    #   这是"用例与代码同源"最典型的盲点 —— 期望值必须按**实际动作序列**重算）
    record(by_ci["total"] == 2
           and [x["if_no"] for x in by_ci["items"]] == ["IF-001", "IF-003"],
           f"ci_no=CI-001 → {by_ci['total']} 条（IF-001 + TC-24 关联的 IF-003）")

    step("TC-47 跨接口变更通知台账（查询视图 list_changes）")
    allc = call("list_changes")
    record(allc["total"] == 14 and set(allc["items"][0].keys())
           >= {"if_no", "seq", "action", "old_version", "new_version", "party", "party_name",
               "reason", "created_at", "if_name", "if_type", "if_status"},
           f"total={allc['total']}（IF-001 6 + IF-002 2 + IF-004 4 + IF-005 2）")
    prov = call("list_changes", party="provider")
    cons = call("list_changes", party="consumer")
    record(prov["total"] == 7 and cons["total"] == 7
           and all(x["party"] == "provider" for x in prov["items"]),
           f"按端筛：提供方 {prov['total']} 条 / 使用方 {cons['total']} 条（I-2 的两端对称）")
    rel = call("list_changes", action="release")
    rev = call("list_changes", action="revise")
    record(rel["total"] == 8 and rev["total"] == 6,
           f"按起因筛：首次发布 {rel['total']} 条 / 版本变更 {rev['total']} 条")
    one_if = call("list_changes", if_no="IF-001")
    record(one_if["total"] == 6 and len({(x["party"], x["seq"]) for x in one_if["items"]}) == 6,
           f"IF-001 通知 {one_if['total']} 条（3 轮 × 两端）")
    pg = call("list_changes", page=1, size=3)
    record(len(pg["items"]) == 3 and pg["total"] == 14, "分页 size=3 → 本页 3 / 共 14")

    step("TC-48 冻结的接口仍可查（historical traceability，不删除）")
    record(call("get", if_no="IF-001")["status"] == "frozen"
           and call("list", status="frozen")["total"] == 2,
           "已冻结记录留存，含全部通知记录")

    # ── 汇总 ─────────────────────────────────────────────
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    for ok, note in bad:
        print(f"    - {note}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
