"""FDE v2 后端主链端到端验证 · psc（产销协同管理）
链路形态（主数据 → 销售预测 → 库存策略 → 毛需求/净需求 → 主计划 → 库存推移表 → 需求池 → 策略拟合）：
  主数据(md_customer/md_material/md_project/md_project_part/md_breakpoint/md_part_replace/md_monthly_version/attainment)
  → sales_forecast(open_version→fill_customer→calc_baseline→decide→summarize)
  → inventory_strategy(calc→get_water_level)
  → demand(build_gross→publish→calc_net)
  → master_plan(import_plan→get_latest)
  → inventory_projection(refresh→scan_alert)
  → demand_pool(create→release→on_workorder_started→on_inbound 回执模拟)
  → strategy_fitting(run→approve 回填 md_material)

外部系统出向适配器走本地 stub（清外部基址）；异步回执由测试手动调用回写服务模拟。
隔离初始化：经 fde_platform.dbguard.isolate_dbs 将真实库临时移走、测试在空库上经 schema.sql 重建，
退出时删除残料、原样还回用户数据——绝不触碰真实库（运行期间需停掉平台服务器，避免库文件被占用）。
运行：python app/psc/tests/verify_chain_psc.py
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

# 测试数据库隔离：把真实 app/**/*.db* 与 config/ 库临时移走，测试在空库上跑，
# 退出时删除残料、原样还回用户数据。链路测试此前用 clean() 直接 DROP 真实库，
# 会洗掉用户在平台上积累的数据（2026-08-20 曾因此丢失 202610 版本）——现已改用
# dbguard 隔离，与 verify_view_*.py 一致，绝不再触碰真实数据。
from fde_platform.dbguard import isolate_dbs  # noqa: E402
import atexit  # noqa: E402

_iso = isolate_dbs()
_iso.__enter__()
atexit.register(_iso.__exit__, None, None, None)

# stub 模式：清掉外部系统基址，出向适配器自动降级为本地 stub
for _k in ("LLM_BASE_URL", "LLM_API_KEY", "SAP_BASE_URL", "MOM_BASE_URL",
           "WMS_BASE_URL", "MDM_BASE_URL", "APS_BASE_URL", "CTCT_BASE_URL"):
    os.environ.pop(_k, None)

GROUP = "psc"
APPS = [
    "md_customer", "md_material", "md_project", "md_project_part",
    "md_breakpoint", "md_part_replace", "md_monthly_version", "attainment",
    "sales_history",
    "sales_forecast", "inventory_strategy", "demand", "master_plan",
    "inventory_projection", "demand_pool", "strategy_fitting",
    "outbound_plan",
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


PARTS = [
    ("part1", "§1 主数据准备 + §2 主业务链"),
    ("part2", "§3 分支 / 异常用例"),
]


def main():
    # 真实库已由 isolate_dbs 移走，FdePlatform 在空库上经 schema.sql 重建（审计列就位）。
    pf = FdePlatform()
    pf.load_all()

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
            mod = importlib.import_module(f"verify_chain_psc_{name}")
            mod.run_part(call, step, expect_err, record)
            time.sleep(1.0)
        except Exception as e:
            record(False, f"[{label}] CRASH: {e}")
            import traceback
            traceback.print_exc()

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
