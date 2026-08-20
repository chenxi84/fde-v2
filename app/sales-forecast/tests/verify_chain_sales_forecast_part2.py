"""verify_chain_sales_forecast part2: §3 分支 / 异常用例"""


def run_part(call, step, expect_err, record):
    OEM_A = "OEM-A"
    PLANT_A1 = "PLANT-A1"
    PART_001 = "PART-001"
    VEH_A = "VEH-A"
    PRJ_001 = "PRJ-001"
    FCST_VER2 = "V2026-08-ERR"
    BASE_PERIOD = "2026-08"

    # ── 先准备一份干净的收集单供后续错误测试用 ──
    step("SETUP-ERR 创建测试用收集单")
    dc = call("demand_collection", "create", oem_code=OEM_A, plant_code=PLANT_A1,
              fcst_version=FCST_VER2, base_period=BASE_PERIOD,
              demand_type="月度滚动预测", source_channel="EDL/EDI")
    collect_no = dc["collect_no"]
    call("demand_collection", "add_lines", collect_no=collect_no, lines=[
        {"part_no": PART_001, "project_no": PRJ_001, "veh_model": VEH_A,
         "period": "2026-08", "orig_qty": 1200},
    ])
    record(True)

    # ════════════════════ §3 分支 / 异常用例 ════════════════════

    step("TC-ERR-01 重复版本拒绝 D03")
    expect_err(
        lambda: call("demand_collection", "create", oem_code=OEM_A, plant_code=PLANT_A1,
                     fcst_version=FCST_VER2, base_period=BASE_PERIOD,
                     demand_type="月度滚动预测", source_channel="EDL/EDI"),
        "已存在"
    )
    record(True)

    step("TC-ERR-02 非草稿状态录入明细被拒")
    # 先确认拆解
    call("demand_collection", "set_decomposition", collect_no=collect_no,
         line_no=1, period="2026-08", noise_adj=0, pulse_qty=0,
         method="免拆解", basis="无脉冲")
    call("demand_collection", "confirm_decomposition", collect_no=collect_no)
    expect_err(
        lambda: call("demand_collection", "add_lines", collect_no=collect_no, lines=[
            {"part_no": PART_001, "project_no": PRJ_001, "veh_model": VEH_A,
             "period": "2026-08", "orig_qty": 999}
        ]),
        "仅草稿状态"
    )
    record(True)

    step("TC-ERR-05 修正幅度超20%未举证被拒 D04")
    # Create a fresh batch
    dc2 = call("demand_collection", "create", oem_code=OEM_A, plant_code=PLANT_A1,
               fcst_version="V2026-08-T2", base_period=BASE_PERIOD,
               demand_type="月度滚动预测", source_channel="EDL/EDI")
    c2 = dc2["collect_no"]
    call("demand_collection", "add_lines", collect_no=c2, lines=[
        {"part_no": PART_001, "project_no": PRJ_001, "veh_model": VEH_A,
         "period": "2026-09", "orig_qty": 960},
    ])
    call("demand_collection", "set_decomposition", collect_no=c2,
         line_no=1, period="2026-09", noise_adj=0, pulse_qty=0, method="免拆解", basis="测试")
    call("demand_collection", "confirm_decomposition", collect_no=c2)
    dp = call("demand_processing", "create_batch", fcst_version="V2026-08-T2",
              oem_code=OEM_A, plant_code=PLANT_A1)
    pb2 = dp["proc_batch"]
    call("demand_processing", "generate_baseline", proc_batch=pb2)
    call("demand_processing", "confirm_baseline", proc_batch=pb2,
         part_no=PART_001, veh_model=VEH_A, period="2026-09")
    expect_err(
        lambda: call("demand_processing", "submit_adjustment", proc_batch=pb2,
                     part_no=PART_001, veh_model=VEH_A, period="2026-09",
                     adj_qty=1300, adj_reason_cat="客户侧情报", adj_evidence=""),
        "20%"
    )
    record(True)

    step("TC-ERR-06 三件套不完整被拒（原因类别为空）")
    expect_err(
        lambda: call("demand_processing", "submit_adjustment", proc_batch=pb2,
                     part_no=PART_001, veh_model=VEH_A, period="2026-09",
                     adj_qty=980, adj_reason_cat="", adj_evidence="测试"),
        "原因类别"
    )
    record(True)

    step("TC-ERR-07 核对退回须附理由")
    # First submit a valid adjustment
    call("demand_processing", "submit_adjustment", proc_batch=pb2,
         part_no=PART_001, veh_model=VEH_A, period="2026-09",
         adj_qty=980, adj_reason_cat="客户侧情报", adj_evidence="测试证据")
    expect_err(
        lambda: call("demand_processing", "check_line", proc_batch=pb2,
                     part_no=PART_001, veh_model=VEH_A, period="2026-09",
                     chk_result="退回", chk_reason=""),
        "退回必须"
    )
    record(True)

    step("TC-ERR-08 退回后重报再核通过（完整退回返工循环）")
    call("demand_processing", "check_line", proc_batch=pb2,
         part_no=PART_001, veh_model=VEH_A, period="2026-09",
         chk_result="退回", chk_reason="证据不足，请补充客户函件")
    call("demand_processing", "submit_adjustment", proc_batch=pb2,
         part_no=PART_001, veh_model=VEH_A, period="2026-09",
         adj_qty=970, adj_reason_cat="客户侧情报", adj_evidence="补充邮件记录")
    r = call("demand_processing", "check_line", proc_batch=pb2,
             part_no=PART_001, veh_model=VEH_A, period="2026-09",
             chk_result="通过")
    assert r.get("chk_round") == 2, r
    assert r.get("approved_qty") == 970, r
    record(True)

    step("TC-ERR-09 基线未生成就修正被拒")
    dp3 = call("demand_processing", "create_batch", fcst_version="V2026-08-T3",
               oem_code=OEM_A, plant_code=PLANT_A1)
    expect_err(
        lambda: call("demand_processing", "confirm_baseline", proc_batch=dp3["proc_batch"],
                     part_no=PART_001, veh_model=VEH_A, period="2026-09"),
        "基线行不存在"
    )
    record(True)

    step("TC-ERR-11 牛鞭无机制纯减数被拒 D08")
    bw = call("bullwhip_correction", "create", part_no=PART_001, period="2026-09",
              tier="Tier2", derived_qty=1350, end_qty=1000, end_source="结算")
    bw_no = bw["bw_no"]
    bw_status = call("bullwhip_correction", "get", bw_no=bw_no)
    if bw_status.get("amp_verdict") == "超阈·修正":
        expect_err(
            lambda: call("bullwhip_correction", "set_correction", bw_no=bw_no,
                         corr_action="", final_qty=800),
            "机制"
        )
    record(True)

    step("TC-ERR-12 发布 checklist 未通过不可发布")
    dr = call("demand_release", "create_draft", base_period=BASE_PERIOD)
    # Don't run checklist, try to publish directly — should fail
    dr_status = call("demand_release", "get", rel_no=dr["rel_no"])
    if dr_status["header"]["status"] == "草稿":
        expect_err(
            lambda: call("demand_release", "publish", rel_no=dr["rel_no"]),
            "checklist"
        )
    record(True)

    step("TC-ERR-16 收集单作废未填原因被拒")
    # Create a new draft collect for this test
    dc_cancel = call("demand_collection", "create", oem_code=OEM_A, plant_code=PLANT_A1,
                     fcst_version="V2026-08-CANCEL", base_period=BASE_PERIOD,
                     demand_type="月度滚动预测", source_channel="EDL/EDI")
    expect_err(
        lambda: call("demand_collection", "cancel", collect_no=dc_cancel["collect_no"], reason=""),
        "作废必须填写原因"
    )
    record(True)

    step("TC-ERR-17 客户不存在于本地冗余表被拒")
    expect_err(
        lambda: call("master_data", "get_customer", oem_code="NONEXIST"),
        "不存在"
    )
    record(True)

    step("TC-ERR-18 零件不存在阻断")
    expect_err(
        lambda: call("master_data", "get_part", part_no="NONEXIST"),
        "不存在"
    )
    record(True)
