"""FDE v2 后端主链端到端验证 · parts-fc（备件预测）
链路形态（台账/映射 → 收集 → 拆解 → 加工 → 汇总修正 → 牛鞭修正 → 发布 → 考核）：
  台账/映射(project_ledger/vehicle_part_map)
  → D03(收集→录入明细→拆解→确认)
  → D04(创建批次→生成基线→确认基线→销售修正→核对通过)
  → D07(通用件汇总→去重修正→确认)
  → D08(牛鞭修正→确认)
  → D09(生成草稿→添加明细→checklist→发布→联动锁定)
  → D12(考核计算→归因)

外部系统出向适配器走本地 stub（清外部基址）。
运行：python app/parts-fc/tests/verify_chain_parts_fc.py
"""
import importlib
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

# 测试数据库隔离：真实库临时移走、空库跑测试、退出时还原用户数据（绝不触碰真实库）。
# 此前 clean() 直接 DROP 真实库表，会洗掉用户 demo 数据。
from fde_platform.dbguard import isolate_dbs  # noqa: E402
import atexit  # noqa: E402
_iso = isolate_dbs(); _iso.__enter__()
atexit.register(_iso.__exit__, None, None, None)

# stub 模式
for _k in ("LLM_BASE_URL", "LLM_API_KEY", "SAP_BASE_URL", "MOM_BASE_URL",
           "WMS_BASE_URL", "MDM_BASE_URL", "APS_BASE_URL", "CTCT_BASE_URL"):
    os.environ.pop(_k, None)

GROUP = "parts-fc"
APPS = [
    "project_ledger", "vehicle_part_map",
    "demand_collection", "demand_processing", "baseline_borrowing",
    "independent_event", "common_parts_agg", "bullwhip_correction",
    "demand_release", "strategy_fitting", "forecast_assessment"
]

STEP = ""
STEP_RESULTS = []


def step(name):
    global STEP
    STEP = name
    print(f"  → {name}", flush=True)


def record(ok, note=""):
    STEP_RESULTS.append((STEP, ok, note))
    status = "[OK]" if ok else "[FAIL]"
    print(f"    {status} {note}" if note else f"    {status}", flush=True)


def expect_err(fn, substr):
    from fde import FdeError
    try:
        fn()
    except FdeError as e:
        msg = str(e)
        if substr not in msg:
            raise AssertionError(f"错误应含『{substr}』，实际: {msg}")
        return msg
    raise AssertionError(f"应抛 FdeError(含『{substr}』)，但未抛出")


# Parts to execute in order
PARTS = [
    ("part1", "§1 主数据准备 + §2 主业务链"),
    ("part2", "§3 分支 / 异常用例"),
    ("part3", "§3A~§3K 补充覆盖"),
]


def main():
    pf = FdePlatform()
    pf.load_all()

    # Verify all apps loaded
    for a in APPS:
        qname = f"{GROUP}/{a}"
        if qname not in pf.app_names():
            print(f"  ⚠ 应用未加载: {qname}", flush=True)
        else:
            print(f"  [OK] {qname}", flush=True)

    def call(app, svc, **kw):
        return pf.call(f"{GROUP}/{app}", svc, **kw)

    import time
    for name, label in PARTS:
        print(f"\n{'='*60}\n  {label}\n{'='*60}", flush=True)
        try:
            safe_group = GROUP.replace("-", "_")
            mod = importlib.import_module(f"verify_chain_{safe_group}_{name}")
            mod.run_part(call, step, expect_err, record)
            time.sleep(2.0)
        except Exception as e:
            record(False, f"[{label}] CRASH: {e}")
            import traceback
            traceback.print_exc()

    # Report
    passed = sum(1 for _, ok, _ in STEP_RESULTS if ok)
    total = len(STEP_RESULTS)
    print(f"\n{'='*60}", flush=True)
    print(f"  测试结果: {passed}/{total} 通过", flush=True)
    for s, ok, note in STEP_RESULTS:
        status = "[OK]" if ok else "[FAIL]"
        print(f"  {status} {s}" + (f" — {note}" if note else ""), flush=True)

    if passed == total:
        print("\nVERIFY_RESULT: PASS", flush=True)
        sys.exit(0)
    else:
        print(f"\nVERIFY_RESULT: PARTIAL {passed}/{total}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAIL_STEP: {STEP}", flush=True)
        print(f"VERIFY_RESULT: CRASH — {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
