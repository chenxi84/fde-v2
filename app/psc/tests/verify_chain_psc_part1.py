"""verify_chain_psc part1: §1 主数据准备 + §2 主业务链（Happy Path）"""
# Covers: TC-DM-01~10, TC-MC-01~18


def run_part(call, step, expect_err, record):
    # 数据字典（§0 冻结）
    C001 = "C001"; C002 = "C002"
    M1 = "M1"; M2 = "M2"; M3 = "M3"; M4 = "M4"
    PRJ_1 = "PRJ-1"
    V202608 = "202608"; V202609 = "202609"
    FIT_202608 = "202608"

    # ════════════════════ §1 主数据准备 ════════════════════

    step("TC-DM-01 创建客户 C001")
    try:
        r = call("md_customer", "create", customer_no=C001, customer_name="客户A",
                 settle_mode="寄售", line_stock_days=0, transfer_lead_days=3,
                 credit_code="91110000710931000M")
        assert r.get("customer_no") == C001, r
        c = call("md_customer", "get", customer_no=C001)
        assert c.get("line_stock_days") == 0, c
        assert c.get("credit_code") == "91110000710931000M", c
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-02 创建客户 C002")
    try:
        call("md_customer", "create", customer_no=C002, customer_name="客户B",
             settle_mode="现售", line_stock_days=2, transfer_lead_days=5,
             credit_code="91350100M000100C4G")
        # credit_code 模糊过滤（片段命中 C002 唯一；小写输入经后端大写化匹配）
        lst = call("md_customer", "list", credit_code="m000100c4")
        assert lst.get("total") == 1 and lst["items"][0]["customer_no"] == C002, lst
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-03 创建物料 M1（含库存策略参数）")
    try:
        r = call("md_material", "create", material_no=M1, material_name="物料A",
                 status="正常", unit_value=100, value_class="低", change_cost=5000,
                 prod_days=10, logistics_days=5, change_risk="低", service_level=0.95,
                 batch_window=28, base_method="移动平均", base_params='{"window":6}')
        assert r.get("material_no") == M1, r
        m = call("md_material", "get", material_no=M1)
        assert m.get("base_method") == "移动平均", m
        assert m.get("service_level") == 0.95, m
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-04 创建物料 M2（多客户通用件）")
    try:
        call("md_material", "create", material_no=M2, material_name="物料B",
             base_method="移动平均", base_params='{"window":6}')
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-05 创建断点旧件 M3")
    try:
        call("md_material", "create", material_no=M3, material_name="旧件",
             base_method="移动平均", base_params='{"window":6}')
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-06 创建断点新件 M4")
    try:
        call("md_material", "create", material_no=M4, material_name="新件",
             base_method="移动平均", base_params='{"window":6}')
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-07 创建项目 PRJ-1")
    try:
        r = call("md_project", "create", project_no=PRJ_1, project_name="项目1",
                 owner="S001", stage="进行中", sop_date="2026-01-01", eop_date="2027-12-31")
        assert r.get("project_no") == PRJ_1, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-08 创建项目零件映射（PRJ-1 × M1）")
    try:
        r = call("md_project_part", "create", project_no=PRJ_1, material_no=M1, usage=1)
        assert r.get("project_no") == PRJ_1 and r.get("material_no") == M1, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-09 创建月度版本 V202608")
    try:
        r = call("md_monthly_version", "create", version_no=V202608,
                 anchor_period="2026-08", opening_date="2026-08-01")
        assert r.get("version_no") == V202608, r
        assert r.get("lock_status") == "草稿", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-10 写入客户达成率（MAPE/bias）")
    try:
        call("attainment", "upsert", customer_no=C001, material_no=M1, mape=0.10, bias=0.05)
        a = call("attainment", "get", customer_no=C001, material_no=M1)
        assert a.get("mape") == 0.10, a
        assert a.get("bias") == 0.05, a
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-11 写入历史台账（sales_history 批量导入）")
    try:
        # M1×C001 六期均值恰为 950（=客户调整后值），保证 TC-MC-04/05 偏差 0 不断言破坏；
        # M2×C002 保 C002 在 purchasing_customers，open_version 客户范围不变。
        r = call("sales_history", "import_batch", rows=[
            {"material_no": M1, "customer_no": C001, "period": "2026-01", "qty": 900},
            {"material_no": M1, "customer_no": C001, "period": "2026-02", "qty": 950},
            {"material_no": M1, "customer_no": C001, "period": "2026-03", "qty": 1000},
            {"material_no": M1, "customer_no": C001, "period": "2026-04", "qty": 950},
            {"material_no": M1, "customer_no": C001, "period": "2026-05", "qty": 920},
            {"material_no": M1, "customer_no": C001, "period": "2026-06", "qty": 980},
            {"material_no": M2, "customer_no": C002, "period": "2026-05", "qty": 80},
        ])
        assert r.get("success") == 7 and r.get("fail") == 0, r
        assert call("sales_history", "list", material_no=M1).get("total") == 6
        custs = call("sales_history", "purchasing_customers")
        assert C001 in custs and C002 in custs, custs
        record(True)
    except Exception as e:
        record(False, f"{e}")

    # ════════════════════ §2 主业务链 ════════════════════

    step("TC-MC-01 开启月度版本")
    try:
        r = call("sales_forecast", "open_version", version_no=V202608)
        rows = call("sales_forecast", "list", version_no=V202608)
        assert rows.get("total", 0) >= 1, rows
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-01b 客户维度按物料收窄（无历史 → 空客户仅一行）")
    try:
        # M1 有历史采购客户 C001；M3 无历史 → 客户为空、仅 N+1/N+2/N+3 三行
        m1 = call("sales_forecast", "list", version_no=V202608, material_no=M1)
        assert any((r.get("customer_no") or "") == C001 for r in m1.get("items", [])), m1
        m3 = call("sales_forecast", "list", version_no=V202608, material_no=M3)
        items3 = m3.get("items", [])
        assert len(items3) == 3, m3
        assert all((r.get("customer_no") or "") == "" for r in items3), m3
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-01c 手工新建组合（create，客户可空）")
    try:
        # M1 × 空客户（open_version 未覆盖的组合，手工补充）
        r = call("sales_forecast", "create", version_no=V202608, material_no=M1, customer_no="")
        assert r.get("line_rows") == 3 and r.get("customer_no") == "", r
        lst = call("sales_forecast", "list", version_no=V202608, material_no=M1)
        items = lst.get("items", [])
        assert lst.get("total") == 6, lst                       # 3 (C001) + 3 (空客户)
        assert any((x.get("customer_no") or "") == "" for x in items), lst
        assert any((x.get("customer_no") or "") == C001 for x in items), lst
        # 重复创建拦截
        expect_err(lambda: call("sales_forecast", "create", version_no=V202608,
                               material_no=M1, customer_no=""), "已存在")
        # 主数据引用铁律：物料/客户不存在拦截
        expect_err(lambda: call("sales_forecast", "create", version_no=V202608,
                               material_no="NO_SUCH_MAT", customer_no=""), "物料")
        expect_err(lambda: call("sales_forecast", "create", version_no=V202608,
                               material_no=M1, customer_no="NO_SUCH_CUST"), "客户")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-02 填客户预测（N+1/N+2/N+3）")
    try:
        for rm in ("N+1", "N+2", "N+3"):
            call("sales_forecast", "fill_customer", version_no=V202608,
                 material_no=M1, customer_no=C001, rolling_month=rm, orig_qty=1000)
        r = call("sales_forecast", "get", version_no=V202608, material_no=M1,
                 customer_no=C001, rolling_month="N+1")
        assert r.get("orig_qty") == 1000, r
        assert abs((r.get("adj_qty") or 0) - 950) < 0.01, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-03 基线计算（含断点追溯前置）")
    try:
        r = call("sales_forecast", "calc_baseline", version_no=V202608,
                 material_no=M1, customer_no=C001, rolling_month="N+1")
        assert r.get("base_method") == "移动平均", r
        assert abs((r.get("base_qty") or 0) - 950) < 0.01, r   # 六期移动平均=950（历史台账已接入）
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-04 异常决策（基线未计算 → 取客户调整后值）")
    try:
        r = call("sales_forecast", "decide", version_no=V202608,
                 material_no=M1, customer_no=C001, rolling_month="N+1")
        assert r.get("abnormal_flag") in (False, 0), r
        assert abs((r.get("final_qty") or 0) - 950) < 0.01, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-05 物料预测汇总")
    try:
        for rm in ("N+2", "N+3"):
            call("sales_forecast", "decide", version_no=V202608, material_no=M1,
                 customer_no=C001, rolling_month=rm)
        r = call("sales_forecast", "summarize", version_no=V202608)
        assert r.get("summary_rows", 0) >= 1, r
        summary = call("sales_forecast", "get_summary", version_no=V202608, material_no=M1)
        assert isinstance(summary, list) and len(summary) == 3, summary
        for row in summary:
            assert abs((row.get("final_qty_sum") or 0) - 950) < 0.01, row
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-06 计算库存策略（三层水位）")
    try:
        call("inventory_strategy", "calc", version_no=V202608, material_no=M1, customer_no=C001)
        r = call("inventory_strategy", "get", version_no=V202608, material_no=M1)
        assert "min_level" in r and "safety_level" in r and "batch_level" in r, r
        # 历史台账接入后水位应为正（不再走"无历史数据"兜底）
        assert (r.get("min_level") or 0) > 0, r
        assert (r.get("safety_level") or 0) > 0, r
        assert (r.get("batch_level") or 0) > 0, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-07 取三层水位（供毛需求）")
    try:
        r = call("inventory_strategy", "get_water_level", version_no=V202608, material_no=M1)
        assert "min_level" in r and "safety_level" in r and "batch_level" in r, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-08 合成毛需求（每期含水位）")
    try:
        wl = call("inventory_strategy", "get_water_level", version_no=V202608, material_no=M1)
        water = (wl.get("min_level") or 0) + (wl.get("safety_level") or 0) + (wl.get("batch_level") or 0)
        r = call("demand", "build_gross", version_no=V202608)
        assert r.get("material_count", 0) >= 1, r
        d = call("demand", "get", version_no=V202608, material_no=M1, rolling_month="N+1")
        assert abs((d.get("gross_qty") or 0) - (950 + water)) < 0.01, d
        assert abs((d.get("inventory_qty") or 0) - water) < 0.01, d   # N+1 也含水位
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-09 发布毛需求（冻结）")
    try:
        r = call("demand", "publish", version_no=V202608)
        assert "发布成功" in (r.get("message") or ""), r
        v = call("md_monthly_version", "get", version_no=V202608)
        assert v.get("lock_status") == "发布（锁定）", v
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-10 净需求运算（冻结版本）")
    try:
        wl = call("inventory_strategy", "get_water_level", version_no=V202608, material_no=M1)
        water = (wl.get("min_level") or 0) + (wl.get("safety_level") or 0) + (wl.get("batch_level") or 0)
        r = call("demand", "calc_net", version_no=V202608)
        assert r.get("row_count", 0) >= 1, r
        d = call("demand", "get", version_no=V202608, material_no=M1, rolling_month="N+1")
        # 净需求 = gross(950+水位) + 未发0 − 库存0 − 在途0
        assert abs((d.get("net_qty") or 0) - (950 + water)) < 0.01, d
        v = call("md_monthly_version", "get", version_no=V202608)
        assert v.get("lock_status") == "冻结", v
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-11 导入主计划（线下产能平衡结果导回）")
    try:
        r = call("master_plan", "import_plan", version_no=V202608,
                 rows=[{"material_no": M1, "rolling_month": "N+1", "plan_qty": 950,
                        "latest_inbound_date": "2026-09-30"}])
        assert r.get("plan_version") == 1, r
        assert r.get("success") == 1, r
        latest = call("master_plan", "get_latest", version_no=V202608, material_no=M1)
        assert isinstance(latest, list) and len(latest) >= 1, latest
        assert abs((latest[0].get("plan_qty") or 0) - 950) < 0.01, latest
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-12 库存推移表逐日推演")
    try:
        call("inventory_projection", "refresh", material_no=M1, biz_date="2026-08-15",
             opening_stock=0)
        r = call("inventory_projection", "get", material_no=M1, biz_date="2026-08-15")
        assert "balance" in r, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-13 预警扫描（对照水位线）")
    try:
        r = call("inventory_projection", "scan_alert", material_no=M1, version_no=V202608)
        assert r is not None, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-14 生成补库单并下达生产")
    try:
        rp = call("demand_pool", "create", material_no=M1, replenish_type="缺货补库",
                  replenish_qty=100, required_inbound="2026-08-20", capacity_tight=True)
        rp_no = rp.get("replenish_no")
        assert rp_no, rp
        assert rp.get("status") == "待下达", rp
        r = call("demand_pool", "release", replenish_no=rp_no, promised_inbound="2026-08-20")
        assert r.get("status") == "已下达", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-15 ERP 回传工单开工（回执模拟）")
    try:
        r = call("demand_pool", "on_workorder_started", replenish_no=rp_no)
        assert r.get("status") == "生产中", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-16 ERP 回传入库（回执模拟，终态）")
    try:
        r = call("demand_pool", "on_inbound", replenish_no=rp_no)
        assert r.get("status") == "已完成", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-16b 策略拟合前置：补足 M1 历史至 18 期（常规趋势，供 statsforecast 出正常拟合）")
    try:
        # 在 2026-01~06 之前补 12 期（2025-01~12）递增趋势：移动平均取末 6 期不变（仍 950），
        # 但 strategy_fitting 拿到 18 期 → 常规赛道 → Auto 模型拟合 → abnormal_flag=false。
        rows = []
        for i in range(12):
            y = 2025 + i // 12
            m = (i % 12) + 1
            rows.append({"material_no": M1, "customer_no": C001,
                         "period": f"{y}-{m:02d}", "qty": 780 + i * 10})
        call("sales_history", "import_batch", rows=rows)
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-17 策略拟合（预测拟合 + 库存拟合）")
    try:
        call("strategy_fitting", "run", material_no=M1, fit_version=FIT_202608)
        r = call("strategy_fitting", "get", fit_version=FIT_202608, material_no=M1)
        assert r.get("status") == "待复核", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-18 拟合复核通过（回填物料主数据）")
    try:
        r = call("strategy_fitting", "approve", fit_version=FIT_202608, material_no=M1)
        assert r.get("status") == "已生效", r
        record(True)
    except Exception as e:
        record(False, f"{e}")
