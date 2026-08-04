"""FDE v2 后端主链端到端验证 · 样板（自 demo 应用组抽取；使用时按第⑤步规格改组名适配、
更名 verify_chain_<组>.py 落 app/<组>/tests/）。

链路形态（主数据 → 正向主链 → 逆向链）：
  主数据(customer/product/bonded_manual/sales_org)
  → FC(创建→提交→计划接收→APS排产回写)
  → SO(创建→提交→审批→生效)
  → FO(创建即提交·Saga 联动 FC/SO→工单回写→入库回写)
  → DN(合单创建→运输信息回写·触发 E-07→已完成)
  → RECON(归集→提交结算 E-08→结算回执 COMPLETED→回写 DN)
  → 逆向 CC(引用已完成 DN→审批→退货结论) → RO(从 CC 创建→审批→E-14→SAP 回执→回写 DN/CC)

外部系统出向适配器走本地 stub（清外部基址）；异步回执由本测试**手动调用回写服务**模拟。
数据库隔离见 fde_platform/dbguard.py（运行前移走真实库、退出还原；跑时勿开平台服务器）。
运行：python app/<组>/tests/verify_chain_<组>.py
"""
import atexit
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent                # app/<组>/tests/
def _project_root():
    """向上找项目根（含 fde_platform/ 的目录）——脚本落点深度不固定，按标记定位才稳。"""
    p = HERE
    while not (p / "fde_platform").is_dir():
        if p.parent == p:
            raise RuntimeError("无法定位项目根目录（未找到 fde_platform/）")
        p = p.parent
    return p


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from fde_platform.dbguard import force_remove, isolate_dbs  # noqa: E402

_iso = isolate_dbs()
_iso.__enter__()
atexit.register(_iso.__exit__, None, None, None)

# stub 模式：清掉 LLM 与外部系统基址，出向适配器自动降级为本地 stub
for _k in ("LLM_BASE_URL", "LLM_API_KEY", "SAP_BASE_URL", "MOM_BASE_URL",
           "WMS_BASE_URL", "MDM_BASE_URL", "APS_BASE_URL", "CTCT_BASE_URL"):
    os.environ.pop(_k, None)

GROUP = "demo"   # 本测试针对的应用组；call() 自动加组限定名（短名在 crm/demo 并存时有歧义）
APPS = ["customer", "product", "sales_org", "bonded_manual", "forecast_order",
        "sales_order", "fulfillment_order", "delivery_note", "reconciliation",
        "customer_complaint", "return_order", "fc_change_order",
        "so_change_order", "fo_change_order"]

from fde_platform.runtime import FdePlatform  # noqa: E402

STEP = ""


def step(name):
    global STEP
    STEP = name
    print(f"  → {name}", flush=True)


def clean():
    for f in (ROOT / "app" / GROUP).glob("*/*.db*"):   # 清 demo 组全部应用库
        force_remove(f)


def expect_err(fn, substr):
    from fde import FdeError
    try:
        fn()
    except FdeError as e:
        assert substr in str(e), f"错误应含『{substr}』，实际: {e}"
        return str(e)
    raise AssertionError(f"应抛 FdeError(含『{substr}』)，但未抛出")


def main():
    clean()
    pf = FdePlatform()
    pf.load_all()
    for a in APPS:
        assert f"{GROUP}/{a}" in pf.app_names(), f"应用未加载: {GROUP}/{a}"

    def call(app, svc, **kw):
        return pf.call(f"{GROUP}/{app}", svc, **kw)   # 组限定，避免短名歧义

    # ════════════════════ §1 主数据准备 ════════════════════
    step("TC-DM-01 同步客户 C001(外销)/C002(内销)")
    call("customer", "sync", data={"customer_no": "C001", "name": "某外贸客户",
         "inner_outer_flag": "外销", "grade": "A", "settlement_currency": "USD"})
    call("customer", "sync", data={"customer_no": "C002", "name": "某内销客户",
         "inner_outer_flag": "内销"})
    c001 = call("customer", "get", customer_no="C001")
    assert c001.get("inner_outer_flag") == "外销", c001

    step("TC-DM-02 同步产品 CTCT-0001(材料)/CTCT-0002(冲压件)")
    call("product", "sync", payload=[
        {"ctct_code": "CTCT-0001", "material_code": "M0001", "sap_material_no": "SAP-M001",
         "name": "铝箔", "material_type": "材料", "std_flag": "标品", "moq": 1000},
        {"ctct_code": "CTCT-0002", "material_code": "M0002", "sap_material_no": "SAP-M002",
         "name": "冲压支架", "material_type": "冲压件", "std_flag": "标品"},
    ])
    assert call("product", "get", ctct_code="CTCT-0001").get("material_type") == "材料"

    step("TC-DM-03 客户采购资格")
    q = call("product", "check_purchase_qualification", customer_no="C001", ctct_code="CTCT-0001")
    print("    资格返回:", q, flush=True)

    step("TC-DM-04 创建保税手册 C12345678(进料加工·股份)")
    call("bonded_manual", "create", manual_no="C12345678", manual_type="进料加工",
         trading_entity="股份", valid_from="2026-01-01", valid_to="2026-12-31",
         total_qty=100000)
    bm = call("bonded_manual", "get", manual_no="C12345678")
    assert bm.get("status") == "有效", bm

    step("TC-DM-05 创建两级销售组织 ORG-1 / ORG-1-1")
    call("sales_org", "create", org_code="ORG-1", name="销售一部", level="一级",
         trading_entity="股份")
    call("sales_org", "create", org_code="ORG-1-1", name="销售一科", level="二级",
         trading_entity="股份", parent_org_code="ORG-1")
    assert call("sales_org", "get_parent", org_code="ORG-1-1")["org_code"] == "ORG-1"

    # ════════════════════ §2.1 正向主链 ════════════════════
    # —— 预测单 FC ——
    step("TC-FC-01 创建预测单(保税)")
    fc = call("forecast_order", "create", customer_no="C001", ctct_code="CTCT-0001",
              demand_qty=12000, required_inbound_date="2026-09-30",
              manual_no="C12345678", org_code="ORG-1-1")
    fc_no = fc["fc_no"]
    assert fc.get("status") == "草稿", fc
    step("TC-FC-02 提交预测单")
    call("forecast_order", "submit", fc_no=fc_no)
    assert call("forecast_order", "get", fc_no=fc_no)["status"] == "已提交"
    step("TC-FC-03 计划接收")
    call("forecast_order", "receive", fc_no=fc_no, reply_inbound_date="2026-09-28",
         reply_opinion="可按期")
    assert call("forecast_order", "get", fc_no=fc_no)["status"] == "计划接收"
    step("TC-FC-04 APS 排产回写(E-01 回执模拟)")
    call("forecast_order", "on_e01_schedule", fc_no=fc_no, scheduled_qty=12000,
         batch_no="APS-B01", confirm_time="2026-08-10 10:00:00")
    assert call("forecast_order", "get", fc_no=fc_no)["status"] == "已排产待转单"
    print("    可转量:", call("forecast_order", "get_transferable", fc_no=fc_no), flush=True)

    # —— 销售订单 SO ——
    step("TC-SO-01 创建销售订单(外销·材料·保税)")
    so = call("sales_order", "create", customer_no="C001", so_type="常规",
              material_type="材料", trading_entity="股份", inner_outer_flag="外销",
              org_code="ORG-1", consignment_flag="常规销售", manual_no="C12345678",
              trade_term="FOB", trade_region="北美", currency="USD", hs_code="7607",
              trade_country_port="上海/上海港", dest_country_port="US/洛杉矶",
              intl_transport="海运",
              items=[{"ctct_code": "CTCT-0001", "demand_qty": 10000, "tolerance": 5,
                      "delivery_date": "2026-08-15", "delivery_place": "上海仓"}])
    so_no = so["so_no"]
    line_no = so["lines"][0]["line_no"]
    assert so.get("status") == "草稿", so
    step("TC-SO-02 提交销售订单")
    call("sales_order", "submit", so_no=so_no)
    assert call("sales_order", "get", so_no=so_no)["header"]["status"] == "审批中"
    step("TC-SO-03 审批通过")
    call("sales_order", "approve", so_no=so_no, opinion="同意")
    assert call("sales_order", "get", so_no=so_no)["header"]["status"] == "审批完成"
    step("TC-SO-04 生效下达")
    call("sales_order", "release", so_no=so_no)
    assert call("sales_order", "get", so_no=so_no)["header"]["status"] == "已提交"

    # —— 履约单 FO（创建即提交，Saga 联动 FC/SO）——
    step("TC-FO-01 创建履约单(SO 直下 + FC 转单)")
    fo = call("fulfillment_order", "create", so_no=so_no, so_line_no=line_no,
              order_qty=10000, related_fc_no=fc_no)
    fo_no = fo["fo_no"]
    assert call("fulfillment_order", "get", fo_no=fo_no)["status"] == "已提交"
    step("TC-FO-02 工单回写(MOM E-04 回执模拟)")
    call("fulfillment_order", "add_work_order", fo_no=fo_no, work_order_no="WO001",
         work_order_qty=10000, planned_completion_time="2026-08-12")
    assert call("fulfillment_order", "get", fo_no=fo_no)["status"] == "已排产"
    step("TC-FO-03 入库回写(WMS E-05 回执模拟)")
    call("fulfillment_order", "add_inbound", fo_no=fo_no, batch_no="B001",
         batch_weight=10000, actual_inbound_time="2026-08-13 09:00:00")
    fo3 = call("fulfillment_order", "get", fo_no=fo_no)
    assert fo3["status"] in ("部分入库", "全部入库"), fo3["status"]
    print("    已入库批次:", call("fulfillment_order", "list_inbound_batches", fo_no=fo_no), flush=True)

    # —— 交货单 DN ——
    step("TC-DN-01 创建交货单(归集 B001)")
    dn = call("delivery_note", "create", customer_no="C001", address="上海仓",
              batches=[{"batch_no": "B001", "fo_no": fo_no, "provisional_price": 20.0,
                        "unit_price": 20.0}])
    dn_no = dn["dn_no"]
    assert call("delivery_note", "get", dn_no=dn_no)["status"] == "已提交"
    step("TC-DN-02 运输信息回写(WMS E-09 → 触发 E-07 回执模拟)")
    call("delivery_note", "on_transport_info", dn_no=dn_no,
         transport_info={"waybill_no": "WB001"})
    dn2 = call("delivery_note", "get", dn_no=dn_no)
    assert dn2["status"] == "已完成", dn2

    # —— 对账单 RECON ——
    step("TC-RECON-01 创建对账单(归集未结算批次)")
    rc = call("reconciliation", "create", customer_no="C001",
              items=[{"batch_no": "B001", "dn_no": dn_no, "settle_weight": 10000,
                      "aluminum_price": 18.0, "processing_fee": 1.5,
                      "minor_metal_surcharge": 0.3, "other_charge": 0.2}],
              invoice_no="INV-001")
    recon_no = rc["recon_no"]
    assert call("reconciliation", "get", recon_no=recon_no)["status"] == "草稿"
    step("TC-RECON-02 提交结算(触发 E-08 stub)")
    call("reconciliation", "submit_to_sap", recon_no=recon_no)
    step("TC-RECON-03 结算结果回写(SAP E-08 回执模拟·成功路)")
    call("reconciliation", "on_settlement_result", recon_no=recon_no, result="COMPLETED")
    rc3 = call("reconciliation", "get", recon_no=recon_no)
    assert rc3["status"] == "完成", rc3
    assert call("delivery_note", "get", dn_no=dn_no).get("recon_no") == recon_no

    # ════════════════════ §2.2 逆向链（CC → RO）════════════════════
    step("TC-CC-01 创建客诉单(引用已完成 DN1)")
    cc = call("customer_complaint", "create", dn_no=dn_no, complaint_type="质量问题",
              description="表面瑕疵",
              lines=[{"ctct_code": "CTCT-0001", "complaint_qty": 100,
                      "problem_desc": "表面瑕疵"}])
    cc_no = cc["cc_no"]
    assert call("customer_complaint", "get", cc_no=cc_no)["status"] == "草稿"
    step("TC-CC-02 提交客诉单")
    call("customer_complaint", "submit", cc_no=cc_no)
    assert call("customer_complaint", "get", cc_no=cc_no)["status"] == "已提交"
    step("TC-CC-03 质量审批通过")
    call("customer_complaint", "approve", cc_no=cc_no, approve_opinion="属实")
    assert call("customer_complaint", "get", cc_no=cc_no)["status"] == "已审批"
    step("TC-CC-04 确定退货结论")
    call("customer_complaint", "set_conclusion", cc_no=cc_no, conclusion="退货",
         conclusion_remark="退货处理")
    assert call("customer_complaint", "get", cc_no=cc_no)["status"] == "处理中"

    step("TC-RO-01 从客诉单创建退货单(1:1)")
    ro = call("return_order", "create_from_cc", cc_no=cc_no)
    ro_no = ro["ro_no"]
    assert call("return_order", "get", ro_no=ro_no)["status"] == "draft"
    step("TC-RO-02 编辑退货数量")
    call("return_order", "edit_draft", ro_no=ro_no, line_no="10", return_qty=100,
         return_date="2026-08-20")
    step("TC-RO-03 提交退货单")
    call("return_order", "submit", ro_no=ro_no)
    assert call("return_order", "get", ro_no=ro_no)["status"] == "submitted"
    step("TC-RO-04 审批通过(自动触发 E-14)")
    call("return_order", "approve", ro_no=ro_no, opinion="同意退货")
    ro4 = call("return_order", "get", ro_no=ro_no)
    assert ro4["status"] == "sap_processing", ro4
    step("TC-RO-05 SAP 结果回写(E-14 回执模拟·成功路)")
    call("return_order", "on_sap_result", ro_no=ro_no, result="成功",
         sap_return_order_no="SAP-RO-001")
    ro5 = call("return_order", "get", ro_no=ro_no)
    assert ro5["status"] == "completed", ro5
    assert call("customer_complaint", "get", cc_no=cc_no)["status"] == "已结案"

    # ════════════════════ §3 分支 / 异常用例（自包含，复用上述数据）════════════════════
    # 3.1 主数据校验分支
    step("TC-ERR-ORG-01 二级组织缺有效父组织")
    expect_err(lambda: call("sales_org", "create", org_code="ORG-2-1", name="x",
                            level="二级", trading_entity="股份", parent_org_code="ORG-9"),
               "上级组织必须是一个有效")
    step("TC-ERR-ORG-02 一级组织不允许有上级")
    expect_err(lambda: call("sales_org", "create", org_code="ORG-3", name="y",
                            level="一级", trading_entity="股份", parent_org_code="ORG-1"),
               "一级组织不允许有上级组织")
    step("TC-ERR-BM-01 手册余量不足")
    expect_err(lambda: call("bonded_manual", "occupy", manual_no="C12345678",
                            qty=99999999, business_mode="保税进料", trading_entity="股份"),
               "手册余量不足")
    step("TC-ERR-BM-02 手册类型↔业务模式不匹配")
    expect_err(lambda: call("bonded_manual", "occupy", manual_no="C12345678",
                            qty=100, business_mode="保税来料", trading_entity="股份"),
               "手册不可用于")
    step("TC-ERR-BM-03 手册交易主体不一致")
    expect_err(lambda: call("bonded_manual", "occupy", manual_no="C12345678",
                            qty=100, business_mode="保税进料", trading_entity="重庆"),
               "手册交易主体与单据")

    # 3.2 正向链创建异常分支
    step("TC-ERR-FC-01 要求入库时间早于提前期(提交时校验)")
    _fc_err = call("forecast_order", "create", customer_no="C001",
                   ctct_code="CTCT-0001", demand_qty=1000,
                   required_inbound_date="2026-08-05", org_code="ORG-1-1")
    expect_err(lambda: call("forecast_order", "submit", fc_no=_fc_err["fc_no"]),
               "要求成品入库时间不得早于提交日+提前期")
    step("TC-ERR-SO-01 同物料同交期重复行")
    expect_err(lambda: call("sales_order", "create", customer_no="C001", so_type="常规",
                            material_type="材料", trading_entity="股份", inner_outer_flag="内销",
                            org_code="ORG-1",
                            items=[{"ctct_code": "CTCT-0001", "demand_qty": 1,
                                    "delivery_date": "2026-08-15", "tolerance": 5},
                                   {"ctct_code": "CTCT-0001", "demand_qty": 2,
                                    "delivery_date": "2026-08-15", "tolerance": 5}]),
               "同一物料同一交期只能有一行")
    step("TC-ERR-FO-01 下单量超 SO 行剩余未下单量")
    # SO1 已完成（非已提交），新建一个内销 SO 并生效用于 FO 下单校验
    _so2 = call("sales_order", "create", customer_no="C002", so_type="常规",
                material_type="材料", trading_entity="股份", inner_outer_flag="内销",
                org_code="ORG-1", items=[{"ctct_code": "CTCT-0001", "demand_qty": 1000,
                "delivery_date": "2026-08-15", "tolerance": 5, "delivery_place": "上海仓"}])
    call("sales_order", "submit", so_no=_so2["so_no"])
    call("sales_order", "approve", so_no=_so2["so_no"], opinion="同意")
    call("sales_order", "release", so_no=_so2["so_no"])
    _ln2 = _so2["lines"][0]["line_no"]
    expect_err(lambda: call("fulfillment_order", "create", so_no=_so2["so_no"],
                            so_line_no=_ln2, order_qty=99999999),
               "下单量超过 SO 行剩余未下单量")
    step("TC-ERR-CC-01 投诉数量大于 DN 发货数量")
    expect_err(lambda: call("customer_complaint", "create", dn_no=dn_no,
                            complaint_type="质量问题",
                            lines=[{"ctct_code": "CTCT-0001", "complaint_qty": 99999999}]),
               "投诉数量不得大于 DN 发货数量")

    clean()
    print("\nPHASE 1+2 PASS —— 主链全链联通（主数据/FC/SO/FO/DN/RECON/逆向 CC→RO）"
          " + 分支异常校验（组织/手册/FC/SO/FO/CC 共 9 条 expect_err）", flush=True)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\nPHASE 1 FAIL @ {STEP}: {e}", flush=True)
        sys.exit(1)
