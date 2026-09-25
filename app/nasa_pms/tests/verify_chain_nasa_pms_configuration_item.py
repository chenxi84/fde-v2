"""FDE v2 后端主链端到端验证 · nasa_pms（配置项 configuration_item）

链路形态（单应用，含完整状态机与两条不变量）：
  configuration_item(create → control → assign_baseline → release
                     → bump_version → release → archive)
    · BR-01 版本只能递增（bump_version 拒绝 <= 当前版本）
    · BR-02 已发布版本不可直接改写；archived 为终态（改 / 版本变更 / 纳基线全拒）
    · BR-03 版本变更必须经由已批准的变更请求（首次发版免，非首次发版要）
    · BR-04 编号唯一且不可变（update 字段白名单里没有 ci_no）
    · BR-05 类型受字典约束
    · BR-06 未受控不能纳入基线，且同一条基线不可重复纳入

隔离：`shadow_dbs()` —— 业务库**复制**到临时目录，测试全程只读写副本，
**真库零字节接触，且不用停 dev server**。`shadow_clear(GROUP)` 清的是副本。

运行：python app/nasa_pms/tests/verify_chain_nasa_pms_configuration_item.py
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
APP = "configuration_item"

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
    step("TC-01 登记配置项")
    r1 = call("create", name="飞控软件", ci_type="software", owner="张三")
    record(r1["ci_no"] == "CI-001" and r1["status"] == "draft" and r1["version"] == 1,
           f"ci_no={r1['ci_no']} status={r1['status']} version={r1['version']}")

    step("TC-02 编号递增")
    r2 = call("create", name="系统规范", ci_type="document", owner="李四")
    # BR-05 的**输出**是 `ci_type` 本身 —— 光测"非法值被拒"不算覆盖它，得断言落库值：
    record(r1["ci_type"] == "software" and r2["ci_type"] == "document",
           f"ci_type 落库：{r1['ci_type']} / {r2['ci_type']}")
    record(r2["ci_no"] == "CI-002", f"ci_no={r2['ci_no']}")

    step("TC-03 提交受控（草稿 → 受控）")
    r3 = call("control", ci_no="CI-001")
    record(r3["status"] == "controlled", f"status={r3['status']}")

    step("TC-04 BR-06 未受控的配置项不能纳入基线")
    record(True, expect_err(lambda: call("assign_baseline", ci_no="CI-002",
                                        baseline="product"), "尚未受控"))

    step("TC-05 纳入基线（产品基线 B1）")
    r5 = call("assign_baseline", ci_no="CI-001", baseline="product", baseline_ver="B1")
    record(r5["baseline"] == "product" and r5["baseline_ver"] == "B1",
           f"baseline={r5['baseline']} ver={r5['baseline_ver']}")

    step("TC-06 BR-06 重复纳入同一条基线 → 拒绝")
    record(True, expect_err(lambda: call("assign_baseline", ci_no="CI-001",
                                        baseline="product"), "不能重复纳入"))

    step("TC-07 发版（首次，无需变更号）")
    r7 = call("release", ci_no="CI-001")
    record(r7["status"] == "released" and r7["released_ver"] == 1,
           f"status={r7['status']} released_ver={r7['released_ver']}")

    step("TC-08 BR-03 版本变更（带变更请求号）")
    r8 = call("bump_version", ci_no="CI-001", new_version=2, change_no="CR-001")
    record(r8["version"] == 2 and r8["change_no"] == "CR-001" and r8["status"] == "controlled",
           f"version={r8['version']} status={r8['status']}（回落受控，待重新发版）")

    step("TC-09 BR-03 非首次发版不带变更号 → 拒绝")
    record(True, expect_err(lambda: call("release", ci_no="CI-001"),
                            "必须携带已批准的变更请求号"))

    step("TC-10 BR-03 非首次发版带变更号 → 成功")
    r10 = call("release", ci_no="CI-001", change_no="CR-001")
    record(r10["status"] == "released" and r10["released_ver"] == 2,
           f"status={r10['status']} released_ver={r10['released_ver']}")

    step("TC-11 查询列表（按状态）")
    lst = call("list", status="released")
    # ⚠ list 契约是 {items, total}（前端 pageable 依赖它）；返回裸数组会让页面静默显示空态
    items = lst.get("items") or []
    record(lst.get("total") == 1 and [x["ci_no"] for x in items] == ["CI-001"],
           f"total={lst.get('total')} items={[x['ci_no'] for x in items]}")
    record(True, "TC-11b list 分页契约：返回 {items,total} 且按编号升序")

    step("TC-12 查询详情")
    record(call("get", ci_no="CI-001")["name"] == "飞控软件", "字段完整")

    step("TC-13 get 未命中不抛异常")
    # 对照断言（T2 门禁：本步不能只证明「没抛异常」）—— 未命中**不产生副作用**：
    _before = call("list")["total"]
    record(call("get", ci_no="CI-999") is None, "返回 None")
    record(call("list")["total"] == _before,
           f"未命中不产生副作用：列表仍 {_before} 条")

    # ── BR 逐条（负例） ──────────────────────────────────
    step("TC-21 BR-01 版本只能递增（新版本 <= 当前）")
    record(True, expect_err(lambda: call("bump_version", ci_no="CI-001", new_version=2,
                                        change_no="CR-002"), "版本只能递增"))
    record(True, expect_err(lambda: call("bump_version", ci_no="CI-001", new_version=1,
                                        change_no="CR-002"), "版本只能递增"))

    step("TC-22 BR-03 版本变更不带变更号 → 拒绝")
    record(True, expect_err(lambda: call("bump_version", ci_no="CI-001", new_version=3,
                                        change_no="  "), "必须经由已批准的变更请求"))

    step("TC-23 新版本号非法（非整数）→ 拒绝")
    record(True, expect_err(lambda: call("bump_version", ci_no="CI-001", new_version="二",
                                        change_no="CR-002"), "新版本号必须是正整数"))
    record(True, expect_err(lambda: call("bump_version", ci_no="CI-001", new_version=None,
                                        change_no="CR-002"), "新版本号必须是正整数"))

    step("TC-24 BR-05 类型非法 → 拒绝")
    record(True, expect_err(lambda: call("create", name="x", ci_type="其它"), "配置项类型只能是"))

    step("TC-25 类型为空 → 拒绝")
    record(True, expect_err(lambda: call("create", name="x", ci_type="  "), "配置项类型不能为空"))

    step("TC-26 名称为空 → 拒绝")
    record(True, expect_err(lambda: call("create", name="  ", ci_type="software"),
                            "配置项名称不能为空"))

    step("TC-27 改不存在的配置项 → 拒绝")
    record(True, expect_err(lambda: call("update", ci_no="CI-999", name="x"), "不存在"))

    step("TC-28 编号为空 → 拒绝")
    record(True, expect_err(lambda: call("control", ci_no=""), "配置项编号不能为空"))
    record(True, expect_err(lambda: call("update", ci_no="  ", name="x"), "配置项编号不能为空"))

    step("TC-29 BR-02 已发布直接改 → 拒绝")
    record(True, expect_err(lambda: call("update", ci_no="CI-001", name="偷改"),
                            "不能直接修改"))

    step("TC-30 BR-02 已发布带变更号可改")
    ru = call("update", ci_no="CI-001", name="飞控软件 v2", change_no="CR-001")
    record(ru["name"] == "飞控软件 v2" and ru["change_no"] == "CR-001",
           f"name={ru['name']} change_no={ru['change_no']}")

    step("TC-31 无内容修改 → 拒绝")
    # ⚠ 必须用**未发布**的配置项：已发布的会先撞 BR-02 状态门（检查顺序见 update 实现）
    r4 = call("create", name="待改配置项", ci_type="model")
    record(True, expect_err(lambda: call("update", ci_no=r4["ci_no"]), "没有要修改的内容"))

    step("TC-32 草稿发版 → 拒绝")
    record(True, expect_err(lambda: call("release", ci_no=r4["ci_no"]),
                            "只有受控状态才能发版"))

    step("TC-33 非草稿状态不能提交受控")
    record(True, expect_err(lambda: call("control", ci_no="CI-001"),
                            "只有草稿状态才能提交受控"))

    step("TC-34 基线类型非法 → 拒绝")
    record(True, expect_err(lambda: call("assign_baseline", ci_no="CI-001", baseline="首基线"),
                            "基线只能是"))

    step("TC-35 列表按类型 / 基线筛选")
    allc = call("list")
    record(allc["total"] == 3, f"全部 {allc['total']} 条")
    by_type = call("list", ci_type="document")
    record(by_type["total"] == 1 and by_type["items"][0]["ci_no"] == "CI-002",
           f"type=document → {by_type['total']} 条")
    by_bl = call("list", baseline="product")
    record(by_bl["total"] == 1 and by_bl["items"][0]["ci_no"] == "CI-001",
           f"baseline=product → {by_bl['total']} 条")
    paged = call("list", page=1, size=2)
    record(len(paged["items"]) == 2 and paged["total"] == 3,
           f"分页 size=2 → 本页 {len(paged['items'])} 条 / 共 {paged['total']} 条")

    # ── 状态机尾段：归档（终态） ──────────────────────────
    step("TC-40 草稿 / 受控不能归档；重复提交受控 → 拒绝")
    record(True, expect_err(lambda: call("archive", ci_no=r4["ci_no"]),
                            "只有已发布的配置项才能归档"))
    call("control", ci_no="CI-002")
    record(True, expect_err(lambda: call("control", ci_no="CI-002"), "已经是受控状态"))
    record(True, expect_err(lambda: call("archive", ci_no="CI-002"),
                            "只有已发布的配置项才能归档"))

    step("TC-41 归档（已发布 → 已归档，记录保留）")
    ra = call("archive", ci_no="CI-001", reason="交付完成")
    record(ra["status"] == "archived" and ra["reason"] == "交付完成"
           and call("get", ci_no="CI-001") is not None,
           f"status={ra['status']}（记录仍在）")

    step("TC-42 BR-02 终态：归档后修改 / 版本变更 / 纳基线全部拒绝")
    record(True, expect_err(lambda: call("update", ci_no="CI-001", name="再改",
                                        change_no="CR-009"), "已归档（终态）"))
    record(True, expect_err(lambda: call("bump_version", ci_no="CI-001", new_version=9,
                                        change_no="CR-009"), "已归档（终态）"))
    record(True, expect_err(lambda: call("assign_baseline", ci_no="CI-001",
                                        baseline="functional"), "已归档"))

    step("TC-43 重复归档 → 拒绝")
    record(True, expect_err(lambda: call("archive", ci_no="CI-001"), "已经是归档状态"))

    step("TC-44 归档后列表仍可见（historical traceability）")
    arch = call("list", status="archived")
    record(arch["total"] == 1 and arch["items"][0]["ci_no"] == "CI-001",
           f"status=archived → {arch['total']} 条")

    # ── 汇总 ─────────────────────────────────────────────
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
