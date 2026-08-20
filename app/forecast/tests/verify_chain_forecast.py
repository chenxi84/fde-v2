"""FDE v2 销售预测应用组 · 后端主链端到端验证"""
import os, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
def _project_root():
    p = HERE
    while not (p / "fde_platform").is_dir():
        if p.parent == p: raise RuntimeError("无法定位项目根目录")
        p = p.parent
    return p

ROOT = _project_root(); os.chdir(ROOT); sys.path.insert(0, str(ROOT))

for _k in ("LLM_BASE_URL","LLM_API_KEY","SAP_BASE_URL","MOM_BASE_URL","WMS_BASE_URL","MDM_BASE_URL","APS_BASE_URL","CTCT_BASE_URL"):
    os.environ.pop(_k, None)

from fde_platform.runtime import FdePlatform
from fde import FdeError

# 测试数据库隔离：真实库临时移走、空库跑测试、退出时还原用户数据（绝不触碰真实库）。
# 此前 clean() 直接删 app/forecast/*/*.db*，会洗掉用户 demo 数据。
from fde_platform.dbguard import isolate_dbs
import atexit
_iso = isolate_dbs(); _iso.__enter__()
atexit.register(_iso.__exit__, None, None, None)

platform = None; PASS = 0; FAIL = 0
FV = "202608"

def call(app, svc, **params):
    return platform.call(f"forecast/{app}", svc, **params)

def expect_err(fn, substr):
    try: fn()
    except FdeError as e:
        msg = str(e); assert substr in msg, f"错误应含'{substr}'，实际: {e}"
        print(f"    [OK] 预期错误: {msg}"); return msg
    raise AssertionError(f"应抛 FdeError(含'{substr}')，但未抛出")

def assert_eq(actual, expected, label=""):
    assert actual == expected, f"{label} 期望={expected}, 实际={actual}"
    if label: print(f"    [OK] {label}: {actual}")

def tc(name, fn):
    global PASS, FAIL
    print(f"\n[{name}]")
    try: fn(); PASS += 1; print(f"  PASS")
    except Exception as e: FAIL += 1; print(f"  FAIL: {e}")

def main():
    global platform, PASS, FAIL
    platform = FdePlatform(); platform.load_all()

    # ====== §1 主数据 ======
    print("\n===== §1 主数据准备 =====")

    def dm01():
        assert_eq(call("md_customer","create",oem_code="OEM-A",oem_name="主机厂A",plant_code="PLT-A1",plant_name="一工厂",settle_mode="寄售"),
                  {"oem_code":"OEM-A","plant_code":"PLT-A1","oem_name":"主机厂A","plant_name":"一工厂","settle_mode":"寄售"},"寄售客户")
    tc("TC-DM-01 创建寄售客户", dm01)

    def dm02():
        assert_eq(call("md_customer","create",oem_code="OEM-B",oem_name="主机厂B",plant_code="PLT-B1",plant_name="一工厂",settle_mode="非寄售")["settle_mode"],"非寄售","非寄售")
    tc("TC-DM-02 创建非寄售客户", dm02)

    def dm03():
        call("md_material","create",part_no="8210001",part_name="前保险杠总成",uom="件")
        call("md_material","create",part_no="STD-M6",part_name="标准螺栓M6",uom="件")
        call("md_material","create",part_no="8210001-B",part_name="前保险杠总成(改款)",uom="件")
        print("    [OK] 3个物料")
    tc("TC-DM-03 创建物料", dm03)

    def dm04():
        call("md_project","create",project_no="PRJ-001",project_name="车型A",stage="进行中",oem_code="OEM-A",plant_code="PLT-A1")
        call("md_project","create",project_no="PRJ-002",project_name="车型B",stage="进行中",oem_code="OEM-B",plant_code="PLT-B1")
        print("    [OK] 2个项目")
    tc("TC-DM-04 创建项目", dm04)

    def dm05():
        call("md_project_part","create",project_no="PRJ-001",part_no="8210001",usage=1,share=1.0)
        call("md_project_part","create",project_no="PRJ-001",part_no="STD-M6",usage=4,share=1.0)
        call("md_project_part","create",project_no="PRJ-002",part_no="STD-M6",usage=4,share=1.0)
        call("md_project_part","create",project_no="PRJ-001",part_no="8210001-B",usage=1,share=1.0)
        print("    [OK] 4个映射")
    tc("TC-DM-05 项目零件映射", dm05)

    def dm06():
        assert_eq(call("md_part_replace","create",rel_no="ECN-A-118",rel_type="替换",old_part="8210001",new_part="8210001-B",ecn_no="ECN-A-118")["status"],"生效","替换关系")
    tc("TC-DM-06 替换关系", dm06)

    def dm07():
        assert_eq(call("md_fcst_version","create",fcst_version="202608",base_period="2026-08",periods=["2026-09","2026-10","2026-11"],opening_date="2026-08-01")["status"],"活跃","版本")
    tc("TC-DM-07 月度版本", dm07)

    # ====== §2 主业务链 ======
    print("\n===== §2 主业务链 =====")

    def s01():
        r = call("forecast_snapshot","open_version",fcst_version=FV)
        assert r["created"] >= 6, f"快照行数 >= 6, 实际={r['created']}"
        print(f"    [OK] {r['created']} 行快照")
    tc("TC-S01 Opening快照", s01)

    def s02():
        r = call("forecast_snapshot","fill",fcst_version=FV,oem_code="OEM-A",plant_code="PLT-A1",part_no="8210001",period="2026-09",orig_qty=1150,data_flag="正常")
        assert_eq(r["orig_qty"],1150,"预测量"); assert_eq(r["data_flag"],"正常","标记")
    tc("TC-S02 填预测", s02)

    def s03():
        call("forecast_snapshot","fill",fcst_version=FV,oem_code="OEM-A",plant_code="PLT-A1",part_no="8210001",period="2026-10",orig_qty=1100,data_flag="正常")
        call("forecast_snapshot","fill",fcst_version=FV,oem_code="OEM-A",plant_code="PLT-A1",part_no="8210001",period="2026-11",orig_qty=1050,data_flag="正常")
    tc("TC-S03 填更多预测", s03)

    def s04():
        r = call("forecast_baseline","generate",fcst_version=FV)
        assert r["created"] >= 6, f"基线行数 >= 6, 实际={r['created']}"
    tc("TC-S04 生成基线", s04)

    def s05():
        r = call("forecast_baseline","confirm_all",fcst_version=FV)
        assert r["confirmed"] >= 1, f"确认行数 >= 1"
    tc("TC-S05 确认基线", s05)

    def s06():
        r = call("forecast_processing","generate",fcst_version=FV)
        assert r["created"] >= 6, f"加工行数 >= 6"
    tc("TC-S06 生成加工数据", s06)

    def s06b():
        expect_err(lambda: call("demand_release","create_draft",fcst_version=FV),"未锁定")
    tc("TC-ERR-06 未锁定不可发布", s06b)

    def s07():
        r = call("forecast_processing","fill_line",fcst_version=FV,oem_code="OEM-A",plant_code="PLT-A1",part_no="8210001",period="2026-09",conf_adj=10,conf_reason="达成率97.5%近直采",onetime_adj=180,onetime_reason="客户加库存",onetime_tag="大一次性")
        assert_eq(r["conf_adj"],10,"置信度"); assert_eq(r["onetime_adj"],180,"一次性")
        assert_eq(r["indep_qty"],round(r["base_qty"]+190,2),"独立需求")
    tc("TC-S07 填调整", s07)

    def s08():
        lines = call("forecast_processing","list",fcst_version=FV,page=1,page_size=200)
        items = lines.get("items",[])
        for line in items:
            call("forecast_processing","review_line",fcst_version=FV,oem_code=line["oem_code"],plant_code=line["plant_code"],part_no=line["part_no"],period=line["period"],chk_result="通过")
        print(f"    [OK] {len(items)} 行核定通过")
    tc("TC-S08 核定全部行", s08)

    def s09():
        assert_eq(call("forecast_processing","finalize",fcst_version=FV)["status"],"已锁定")
    tc("TC-S09 锁定加工", s09)

    def s10():
        assert call("part_level_adj","create_generic_merge",fcst_version=FV,period="2026-09",part_no="STD-M6",adj_qty=-1600,basis="口头加码0.65折减")["adj_no"].startswith("PAD-"),"通用件合并"
    tc("TC-S10 通用件合并", s10)

    def s11():
        r = call("part_level_adj","create_breakpoint_adj",fcst_version=FV,period="2026-10",old_part="8210001",new_part="8210001-B",old_adj=-420,new_adj=400,ecn_no="ECN-A-118")
        assert r["pair_no"],"配对号非空"
        assert_eq(r["old"]["func_type"],"断点处理"); assert_eq(r["new"]["func_type"],"断点处理")
    tc("TC-S11 断点成对", s11)

    def s12():
        r = call("demand_release","create_draft",fcst_version=FV)
        assert_eq(r["status"],"草稿"); assert r["created"] >= 1,"发布行数>=1"
    tc("TC-S12 创建发布草稿", s12)

    def s13():
        r = call("demand_release","apply_part_adj",fcst_version=FV,part_no="STD-M6",period="2026-09",adj_qty=-1600,func_type="通用件合并",basis="口头加码折减")
        print(f"    [OK] rel_qty={r['rel_qty']}")
    tc("TC-S13 应用零件级处理", s13)

    def s14():
        assert_eq(call("demand_release","publish",fcst_version=FV)["status"],"已发布")
        assert_eq(call("md_fcst_version","get",fcst_version=FV)["status"],"锁定","版本锁定")
    tc("TC-S14 发布", s14)

    def s15():
        r = call("demand_release","get_version",fcst_version=FV)
        assert_eq(r["status"],"已发布"); assert len(r.get("lines",[])) >= 1
    tc("TC-S15 验证发布数据", s15)

    # ====== §3 异常用例 ======
    print("\n===== §3 异常用例 =====")

    def err01():
        expect_err(lambda: call("forecast_snapshot","open_version",fcst_version=FV),"非活跃")
    tc("TC-ERR-01 锁定版本不可Opening", err01)

    def err02():
        expect_err(lambda: call("forecast_snapshot","fill",fcst_version=FV,oem_code="OEM-A",plant_code="PLT-A1",part_no="8210001",period="2026-09",orig_qty=9999),"已录入")
    tc("TC-ERR-02 已录入行不可改", err02)

    def err03():
        expect_err(lambda: call("forecast_processing","fill_line",fcst_version=FV,oem_code="OEM-A",plant_code="PLT-A1",part_no="8210001",period="2026-09",conf_adj=50),"已锁定")
    tc("TC-ERR-03 已锁定不可改", err03)

    def err04():
        expect_err(lambda: call("demand_release","publish",fcst_version=FV),"已发布")
    tc("TC-ERR-04 已发布不可重复", err04)

    def err05():
        expect_err(lambda: call("md_customer","create",oem_code="OEM-A",plant_code="PLT-A1",oem_name="X",plant_name="X",settle_mode="寄售"),"已存在")
    tc("TC-ERR-05 重复客户被拒", err05)

    # ====== 报告 ======
    print(f"\n{'='*50}")
    print(f"VERIFY_RESULT: {'PASS' if FAIL == 0 else 'FAIL'}")
    print(f"  通过: {PASS}, 失败: {FAIL}")
    print(f"{'='*50}")
    return FAIL == 0

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
