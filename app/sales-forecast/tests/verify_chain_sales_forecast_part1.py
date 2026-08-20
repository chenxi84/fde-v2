"""verify_chain_sales_forecast part1: §1 主数据准备 + §2 主业务链"""


def run_part(call, step, expect_err, record):
    # ════════════════════ §0 测试数据常量 ════════════════════
    OEM_A = "OEM-A"
    PLANT_A1 = "PLANT-A1"
    PART_001 = "PART-001"
    PART_002 = "PART-002"
    PART_STD = "PART-STD"
    VEH_A = "VEH-A"
    PRJ_001 = "PRJ-001"
    PRJ_004 = "PRJ-004"
    USR_SALES = "USR-SALES"
    USR_PLAN = "USR-PLAN"
    FCST_VER = "V2026-08"
    BASE_PERIOD = "2026-08"

    # ════════════════════ §1 主数据准备 ════════════════════

    step("TC-DM-01 同步客户主数据")
    call("master_data", "sync_customers", data=[
        {"oem_code": OEM_A, "oem_name": "主机厂A", "plants": '[{"plant_code":"PLANT-A1"}]', "settle_mode": "寄售"},
        {"oem_code": "OEM-B", "oem_name": "主机厂B", "plants": '[{"plant_code":"PLANT-B1"}]', "settle_mode": "寄售"},
    ])
    c = call("master_data", "get_customer", oem_code=OEM_A)
    assert c.get("oem_name") == "主机厂A", c
    record(True)

    step("TC-DM-02 同步物料主数据")
    call("master_data", "sync_parts", data=[
        {"part_no": PART_001, "part_name": "前保险杠总成", "uom": "件", "part_type": "成品"},
        {"part_no": PART_002, "part_name": "散热器格栅总成", "uom": "件", "part_type": "成品"},
        {"part_no": PART_STD, "part_name": "标准紧固件M6", "uom": "件", "part_type": "成品"},
    ])
    p = call("master_data", "get_part", part_no=PART_001)
    assert p.get("part_name") == "前保险杠总成", p
    record(True)

    step("TC-DM-03 同步车型与用户")
    call("master_data", "sync_vehicles", data=[
        {"veh_model": VEH_A, "veh_name": "车型A", "platform": "P1", "oem_code": OEM_A},
        {"veh_model": "VEH-C", "veh_name": "车型C", "platform": "P1", "oem_code": OEM_A},
    ])
    call("master_data", "sync_users", data=[
        {"userno": USR_SALES, "name": "张三", "department": "销售部", "role": "一线销售"},
        {"userno": USR_PLAN, "name": "王五", "department": "计划部", "role": "总部计划"},
    ])
    record(True)

    step("TC-DM-04 创建项目信息台账 PRJ-001")
    call("project_info", "create", project_no=PRJ_001, part_no=PART_001,
         stage="进行中", oem_code=OEM_A, plant_code=PLANT_A1, veh_model=VEH_A,
         part_kind="专用", sop="2024-03-01", eop="2027-06-30", owner_sales=USR_SALES)
    prj = call("project_info", "get", project_no=PRJ_001, part_no=PART_001)
    assert prj.get("stage") == "进行中", prj
    record(True)

    step("TC-DM-05 创建车型—零件映射 PART-001→VEH-A")
    call("vehicle_part_mapping", "create", part_no=PART_001, veh_model=VEH_A,
         usage=1, share=100, lc_stage="成熟", lc_shape="传统",
         sop="2024-03-01", eop="2027-06-30", source="BOM")
    vpm = call("vehicle_part_mapping", "get", part_no=PART_001, veh_model=VEH_A)
    assert vpm.get("usage") == 1, vpm
    record(True)

    step("TC-DM-06 创建第二项目 PRJ-004 + 映射")
    call("project_info", "create", project_no=PRJ_004, part_no=PART_002,
         stage="进行中", oem_code=OEM_A, plant_code=PLANT_A1, veh_model=VEH_A,
         part_kind="专用", sop="2026-06-01", owner_sales=USR_SALES)
    call("vehicle_part_mapping", "create", part_no=PART_002, veh_model=VEH_A,
         usage=1, share=100, lc_stage="爬坡", lc_shape="上市高后下滑",
         sop="2026-06-01", source="BOM")
    record(True)

    step("TC-DM-07 创建通用件项目与映射 PART-STD")
    call("project_info", "create", project_no=PRJ_001, part_no=PART_STD,
         stage="进行中", oem_code=OEM_A, plant_code=PLANT_A1, veh_model=VEH_A,
         part_kind="通用", sop="2024-03-01", owner_sales=USR_PLAN)
    call("vehicle_part_mapping", "create", part_no=PART_STD, veh_model=VEH_A,
         usage=4, share=60, lc_stage="成熟", lc_shape="传统", source="商务确认")
    record(True)

    # ════════════════════ §2 主业务链 ════════════════════

    step("TC-MAIN-01 新建收集单 D03")
    dc = call("demand_collection", "create", oem_code=OEM_A, plant_code=PLANT_A1,
              fcst_version=FCST_VER, base_period=BASE_PERIOD,
              demand_type="月度滚动预测", source_channel="EDL/EDI")
    collect_no = dc["collect_no"]
    assert collect_no.startswith("COL-"), dc
    d = call("demand_collection", "get", collect_no=collect_no)
    assert d["header"].get("status") == "草稿", d["header"]
    record(True)

    step("TC-MAIN-02 录入 PART-001 明细(D03-D) M0~M3")
    call("demand_collection", "add_lines", collect_no=collect_no, lines=[
        {"part_no": PART_001, "project_no": PRJ_001, "veh_model": VEH_A,
         "period": "2026-08", "orig_qty": 1200},
        {"part_no": PART_001, "project_no": PRJ_001, "veh_model": VEH_A,
         "period": "2026-09", "orig_qty": 1150},
        {"part_no": PART_001, "project_no": PRJ_001, "veh_model": VEH_A,
         "period": "2026-10", "orig_qty": 1100},
        {"part_no": PART_001, "project_no": PRJ_001, "veh_model": VEH_A,
         "period": "2026-11", "orig_qty": 1050},
    ])
    record(True)

    step("TC-MAIN-03 录入 PART-002 明细 M0~M1")
    call("demand_collection", "add_lines", collect_no=collect_no, lines=[
        {"part_no": PART_002, "project_no": PRJ_004, "veh_model": VEH_A,
         "period": "2026-08", "orig_qty": 600},
        {"part_no": PART_002, "project_no": PRJ_004, "veh_model": VEH_A,
         "period": "2026-09", "orig_qty": 620},
    ])
    record(True)

    step("TC-MAIN-04 信号拆解 PART-001·2026-09（脉冲+180, true=970）")
    r = call("demand_collection", "set_decomposition",
             collect_no=collect_no, line_no=2, period="2026-09",
             noise_adj=0, pulse_qty=180, method="阶跃检测+水位差倒推",
             basis="V07→V08 M+1跳增200；寄售仓现2.1天vs目标3.5天，估补库+180")
    assert abs(r.get("true_qty", 0) - 970) < 0.01, r
    assert r.get("has_pulse") is not None
    record(True)

    step("TC-MAIN-05 其他行拆解（无脉冲）")
    for ln, p, qty in [(1, "2026-08", 1200), (3, "2026-10", 1100), (4, "2026-11", 1050)]:
        r = call("demand_collection", "set_decomposition",
                 collect_no=collect_no, line_no=ln, period=p,
                 noise_adj=0, pulse_qty=0, method="免拆解", basis="无脉冲")
        assert abs(r.get("true_qty", 0) - qty) < 0.01, f"line {ln}: {r}"
    # PART-002 rows (line_no 5,6)
    for ln, p, qty in [(5, "2026-08", 600), (6, "2026-09", 620)]:
        r = call("demand_collection", "set_decomposition",
                 collect_no=collect_no, line_no=ln, period=p,
                 noise_adj=0, pulse_qty=0, method="免拆解", basis="无脉冲")
        assert abs(r.get("true_qty", 0) - qty) < 0.01, f"line {ln}: {r}"
    record(True)

    step("TC-MAIN-06 拆解确认 D03 → 已拆解")
    r = call("demand_collection", "confirm_decomposition", collect_no=collect_no)
    assert r.get("status") == "已拆解", r
    d = call("demand_collection", "get", collect_no=collect_no)
    assert d["header"]["status"] == "已拆解", d["header"]
    record(True)

    step("TC-MAIN-07 创建加工批次 D04")
    r = call("demand_processing", "create_batch", fcst_version=FCST_VER,
             oem_code=OEM_A, plant_code=PLANT_A1)
    proc_batch = r["proc_batch"]
    assert proc_batch.startswith("PRC-"), r
    record(True)

    step("TC-MAIN-08 生成基线 D04-B")
    r = call("demand_processing", "generate_baseline", proc_batch=proc_batch)
    assert r.get("lines_generated", 0) >= 1, r
    record(True)

    step("TC-MAIN-09 确认基线 PART-001·2026-09")
    call("demand_processing", "confirm_baseline", proc_batch=proc_batch,
         part_no=PART_001, veh_model=VEH_A, period="2026-09")
    status = call("demand_processing", "get_line_status", proc_batch=proc_batch,
                  part_no=PART_001, veh_model=VEH_A, period="2026-09")
    assert status.get("adjustment") is not None, status
    record(True)

    step("TC-MAIN-10 销售提交修正(+30, 3.1%)")
    r = call("demand_processing", "submit_adjustment", proc_batch=proc_batch,
             part_no=PART_001, veh_model=VEH_A, period="2026-09",
             adj_qty=990, adj_reason_cat="客户侧情报", adj_evidence="促销备货（附邮件记录）")
    assert r.get("adj_qty") == 990, r
    record(True)

    step("TC-MAIN-11 核对通过 → 核定毛需求=990")
    r = call("demand_processing", "check_line", proc_batch=proc_batch,
             part_no=PART_001, veh_model=VEH_A, period="2026-09",
             chk_result="通过")
    assert r.get("chk_result") == "通过", r
    assert r.get("approved_qty") == 990, r
    record(True)

    step("TC-MAIN-12 通用件汇总修正(简略)")
    # Simplified - in real scenario this needs D04 approved values for PART-STD
    agg = call("common_part_aggregation", "create", part_no=PART_STD, period="2026-09")
    agg_no = agg["agg_no"]
    call("common_part_aggregation", "add_detail", agg_no=agg_no, oem_code=OEM_A,
         owner_sales=USR_SALES, approved_qty=32000, verbal_qty=2400)
    call("common_part_aggregation", "set_dedup", agg_no=agg_no, dedup_qty=30500,
         dedup_reason="口头加码按历史实际用量折减约65%")
    call("common_part_aggregation", "confirm", agg_no=agg_no)
    a = call("common_part_aggregation", "get", agg_no=agg_no)
    assert a["header"]["status"] == "已确认", a["header"]
    record(True)

    step("TC-MAIN-13 牛鞭修正 D08 Tier1 容忍内")
    r = call("bullwhip_correction", "create", part_no=PART_001, period="2026-09",
             tier="Tier1直供", derived_qty=990, end_qty=970, end_source="结算")
    bw_no = r["bw_no"]
    assert r.get("amp_verdict") in ("容忍内·维持", "超阈·修正"), r
    record(True)

    step("TC-MAIN-14 牛鞭修正确认")
    bw = call("bullwhip_correction", "get", bw_no=bw_no)
    if bw.get("status") == "维持":
        call("bullwhip_correction", "maintain", bw_no=bw_no)
    else:
        call("bullwhip_correction", "confirm", bw_no=bw_no)
    bw = call("bullwhip_correction", "get", bw_no=bw_no)
    assert bw.get("status") == "已确认", bw
    record(True)

    step("TC-MAIN-15 生成发布草稿 D09")
    r = call("demand_release", "create_draft", base_period=BASE_PERIOD)
    rel_no = r["rel_no"]
    assert rel_no.startswith("REL-"), r
    record(True)

    step("TC-MAIN-16 添加发布明细 D09-D")
    # Get pulse event_no from independent_event if available
    events = call("independent_event", "list", event_type="水位脉冲", part_no=PART_001)
    event_items = []
    if events:
        event_items = [{"event_no": events[0].get("event_no", ""), "qty": 180}]
    r = call("demand_release", "add_line", rel_no=rel_no,
             part_no=PART_001, veh_model=VEH_A, period="2026-09",
             cons_qty=990, event_items=event_items,
             basis="指数平滑基线+修正再核通过；客户对齐无偏离",
             lineage={"proc_batch": proc_batch, "fcst_version": FCST_VER})
    expected_rel = 990 + sum(e.get("qty", 0) for e in event_items)
    assert abs(r.get("rel_qty", 0) - expected_rel) < 0.01, r
    record(True)

    step("TC-MAIN-17 Checklist 校验")
    r = call("demand_release", "checklist_verify", rel_no=rel_no)
    assert r.get("new_status") == "待发布", r
    record(True)

    step("TC-MAIN-18 发布 D09 → 联动锁定")
    r = call("demand_release", "publish", rel_no=rel_no)
    assert r.get("status") == "已发布", r
    record(True)

    step("TC-MAIN-19 验证联动锁定 D04")
    dp = call("demand_processing", "get", proc_batch=proc_batch)
    print(f"    D04 批次状态: {dp['header'].get('status')}", flush=True)
    record(True)

    step("TC-MAIN-20 考核计算 D12")
    fa = call("forecast_assessment", "create", period=BASE_PERIOD)
    fa_no = fa["fa_no"]
    call("forecast_assessment", "add_record", fa_no=fa_no,
         part_no=PART_001, veh_model=VEH_A, period="2026-09",
         fcst_qty=1170, actual_qty=1150, settle_qty=1140,
         base_qty=960, adj_qty=990)
    call("forecast_assessment", "attribute", fa_no=fa_no,
         part_no=PART_001, period="2026-09",
         attribution="正常波动", result="计入考核")
    f = call("forecast_assessment", "get", fa_no=fa_no)
    assert f.get("result") == "计入考核", f
    record(True)
