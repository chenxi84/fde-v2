"""verify_chain_psc part2: §3 分支 / 异常用例"""
# Covers: TC-ERR-01~38


def run_part(call, step, expect_err, record):
    C001 = "C001"; C002 = "C002"
    M1 = "M1"; M2 = "M2"; M3 = "M3"; M4 = "M4"; M5 = "M5"
    PRJ_1 = "PRJ-1"
    V202608 = "202608"; V202609 = "202609"
    FIT_202608 = "202608"

    # 先建 V202609 草稿版本（供状态机/毛需求分支用例使用）
    step("前置：创建草稿版本 V202609")
    try:
        call("md_monthly_version", "create", version_no=V202609,
             anchor_period="2026-09", opening_date="2026-09-01")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    # ════════════════════ §3.1 主数据校验分支 ════════════════════

    step("TC-ERR-01 客户编码重复拦截")
    try:
        expect_err(lambda: call("md_customer", "create", customer_no=C001,
                                customer_name="重复客户"), "存在")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-02 物料号重复拦截")
    try:
        expect_err(lambda: call("md_material", "create", material_no=M1,
                                material_name="重复物料"), "存在")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-03 拟合参数与基线方法不匹配拦截")
    try:
        expect_err(lambda: call("md_material", "set_fit_params", material_no=M1,
                                base_method="移动平均", base_params='{"alpha":0.3}',
                                batch_window=28, service_level=0.95, fit_version=FIT_202608),
                   "匹配")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-04 项目阶段跳级拦截")
    try:
        expect_err(lambda: call("md_project", "update", project_no=PRJ_1, stage="EOP"),
                   "阶段")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-05 断点原物料=新物料拦截")
    try:
        expect_err(lambda: call("md_breakpoint", "create", customer_no=C001,
                                old_material_no=M3, new_material_no=M3,
                                switch_time="2026-09-01"), "相同")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-06 替换关系原=替换拦截")
    try:
        expect_err(lambda: call("md_part_replace", "create", old_material_no=M1,
                                new_material_no=M1), "相同")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-07 项目零件映射引用不存在的项目")
    try:
        expect_err(lambda: call("md_project_part", "create", project_no="NOTEXIST",
                                material_no=M1, usage=1), "项目")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-07b 单车用量非整数拦截")
    try:
        expect_err(lambda: call("md_project_part", "create", project_no=PRJ_1,
                                material_no=M2, usage=1.5), "整数")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-40 历史台账非法导入行拦截")
    try:
        r = call("sales_history", "import_batch", rows=[
            {"material_no": "", "customer_no": C001, "period": "2026-01", "qty": 1},
            {"material_no": M5, "customer_no": C001, "period": "2026-13", "qty": 1},
            {"material_no": M5, "customer_no": C001, "period": "202607", "qty": 1},
            {"material_no": M5, "customer_no": C001, "period": "2026-01", "qty": -5},
        ])
        assert r.get("success") == 0 and r.get("fail") == 4, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-41 历史台账 upsert 幂等覆盖")
    try:
        call("sales_history", "upsert", material_no=M5, customer_no=C001, period="2026-06", qty=1000)
        call("sales_history", "upsert", material_no=M5, customer_no=C001, period="2026-06", qty=500)
        rows = call("sales_history", "list", material_no=M5)
        assert rows.get("total") == 1, rows
        assert rows["items"][0]["qty"] == 500, rows
        assert call("sales_history", "purchasing_customers", material_no=M5) == [C001]
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-42 历史台账断点链求和+缺期补0")
    try:
        call("sales_history", "import_batch", rows=[
            {"material_no": M3, "customer_no": C001, "period": "2026-01", "qty": 100},
            {"material_no": M3, "customer_no": C001, "period": "2026-02", "qty": 120},
            {"material_no": M3, "customer_no": C001, "period": "2026-03", "qty": 110},
            {"material_no": M4, "customer_no": C001, "period": "2026-03", "qty": 40},
            {"material_no": M4, "customer_no": C001, "period": "2026-05", "qty": 80},
        ])
        assert call("sales_history", "history_sequence", material_nos=[M3, M4]) == [100, 120, 150, 0, 80]
        assert call("sales_history", "history_sequence", material_nos=M4) == [40, 0, 80]
        assert call("sales_history", "history_sequence", material_nos=[M3, M4], limit=3) == [150, 0, 80]
        record(True)
    except Exception as e:
        record(False, f"{e}")

    # ════════════════════ §3.2 月度版本状态机分支 ════════════════════

    step("TC-ERR-08 非草稿版本重复发布拦截")
    try:
        expect_err(lambda: call("md_monthly_version", "publish", version_no=V202608), "草稿")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-09 草稿版本直接冻结拦截")
    try:
        expect_err(lambda: call("md_monthly_version", "freeze", version_no=V202609), "发布")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-10 已冻结版本再冻结拦截（不可逆）")
    try:
        expect_err(lambda: call("md_monthly_version", "freeze", version_no=V202608), "冻结")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    # ════════════════════ §3.3 销售预测分支 ════════════════════

    step("TC-ERR-11 已发布版本填预测拦截")
    try:
        expect_err(lambda: call("sales_forecast", "fill_customer", version_no=V202608,
                                material_no=M2, customer_no=C002, rolling_month="N+1",
                                orig_qty=100), "锁定")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-33 事件调整（adjust_event）")
    try:
        call("sales_forecast", "open_version", version_no=V202609)
        call("sales_forecast", "fill_customer", version_no=V202609, material_no=M2,
             customer_no=C002, rolling_month="N+1", orig_qty=1000)
        call("sales_forecast", "adjust_event", version_no=V202609, material_no=M2,
             customer_no=C002, rolling_month="N+1", event_analysis="促销", event_adj=100)
        r = call("sales_forecast", "get", version_no=V202609, material_no=M2,
                 customer_no=C002, rolling_month="N+1")
        assert abs((r.get("event_adj") or 0) - 100) < 0.01, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-12 非异常行人工填最终预测拦截")
    try:
        expect_err(lambda: call("sales_forecast", "set_final", version_no=V202609,
                                material_no=M2, customer_no=C002, rolling_month="N+1",
                                final_qty=999), "异常")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    # ════════════════════ §3.4 毛需求/净需求分支 ════════════════════

    step("TC-ERR-13 已发布版本合成毛需求拦截")
    try:
        expect_err(lambda: call("demand", "build_gross", version_no=V202608), "发布")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-14 未合成即发布拦截")
    try:
        expect_err(lambda: call("demand", "publish", version_no=V202609), "合成")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-15 草稿版本运算净需求拦截")
    try:
        expect_err(lambda: call("demand", "calc_net", version_no=V202609), "发布")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-16 已冻结版本重复运算净需求拦截")
    try:
        expect_err(lambda: call("demand", "calc_net", version_no=V202608), "冻结")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    # ════════════════════ §3.5 需求池状态机分支 ════════════════════

    step("TC-ERR-20 缺货补库（产能紧张档）")
    try:
        rp = call("demand_pool", "create", material_no=M1, replenish_type="缺货补库",
                  replenish_qty=100, required_inbound="2026-08-20", capacity_tight=True)
        rp_no_20 = rp.get("replenish_no")
        assert rp_no_20 and rp.get("status") == "待下达", rp
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-21 最低库存补库（产能富余档）")
    try:
        rp = call("demand_pool", "create", material_no=M1, replenish_type="最低库存补库",
                  replenish_qty=200, required_inbound="2026-08-21", capacity_tight=False)
        assert rp.get("replenish_no") and rp.get("status") == "待下达", rp
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-22 安全库存补库")
    try:
        rp = call("demand_pool", "create", material_no=M1, replenish_type="安全库存补库",
                  replenish_qty=300, required_inbound="2026-08-22")
        rp_no_22 = rp.get("replenish_no")
        assert rp_no_22 and rp.get("status") == "待下达", rp
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-30 待下达补库单取消（正向）")
    try:
        r = call("demand_pool", "cancel", replenish_no=rp_no_22)
        assert r.get("status") == "已取消", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-17 非待下达状态下达拦截")
    try:
        call("demand_pool", "release", replenish_no=rp_no_20)
        expect_err(lambda: call("demand_pool", "release", replenish_no=rp_no_20), "状态")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-18 非生产中状态入库回传拦截")
    try:
        expect_err(lambda: call("demand_pool", "on_inbound", replenish_no=rp_no_20), "状态")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-19 已完成状态取消拦截")
    try:
        call("demand_pool", "on_workorder_started", replenish_no=rp_no_20)
        call("demand_pool", "on_inbound", replenish_no=rp_no_20)
        expect_err(lambda: call("demand_pool", "cancel", replenish_no=rp_no_20), "状态")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    # ════════════════════ §3.6 替换件合并 / 断点追溯 ════════════════════

    step("TC-ERR-23 替换关系建立")
    try:
        r = call("md_part_replace", "create", old_material_no=M3, new_material_no=M4,
                 ecn_no="ECN-001")
        rel_no = r.get("rel_no")
        assert rel_no, r
        rows = call("md_part_replace", "list", status="生效")
        assert rows.get("total", 0) >= 1, rows
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-29 替换关系停用（生效→失效）")
    try:
        r = call("md_part_replace", "disable", rel_no=rel_no)
        assert r.get("status") == "失效", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-24 断点追溯原物料链")
    try:
        r = call("md_breakpoint", "create", customer_no=C001, old_material_no=M3,
                 new_material_no=M4, switch_time="2026-09-01", ecn_no="ECN-002")
        assert r.get("bp_id"), r
        chain = call("md_breakpoint", "trace", new_material_no=M4)
        assert isinstance(chain, list) and len(chain) >= 1, chain
        assert M3 in chain or M4 in chain, chain
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-24c 算基线回填断点切换时间（switch_time）")
    try:
        r = call("sales_forecast", "calc_baseline", version_no=V202609,
                 material_no=M4, customer_no=C001, rolling_month="N+1")
        assert r.get("bp_material_no") == M3, r
        assert r.get("switch_time") == "2026-09-01", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-24b 即将切换断点（upcoming 日期窗口）")
    try:
        from datetime import datetime, timedelta
        d10 = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        d100 = (datetime.now() + timedelta(days=100)).strftime("%Y-%m-%d")
        call("md_breakpoint", "create", customer_no=C001, old_material_no=M3,
             new_material_no=M4, switch_time=d10, ecn_no="ECN-UP1")
        call("md_breakpoint", "create", customer_no=C001, old_material_no=M4,
             new_material_no=M3, switch_time=d100, ecn_no="ECN-UP2")
        rows60 = call("md_breakpoint", "upcoming", days=60)
        assert any((r.get("switch_time") == d10) for r in rows60), rows60
        assert not any((r.get("switch_time") == d100) for r in rows60), rows60
        rows1 = call("md_breakpoint", "upcoming", days=1)
        assert not any((r.get("switch_time") == d10) for r in rows1), rows1
        record(True)
    except Exception as e:
        record(False, f"{e}")

    # ════════════════════ §3.7 策略拟合状态机分支 ════════════════════

    step("TC-ERR-25 非待复核状态复核通过拦截")
    try:
        expect_err(lambda: call("strategy_fitting", "approve", fit_version=FIT_202608,
                                material_no=M1), "待复核")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-26 非待复核状态否决拦截")
    try:
        expect_err(lambda: call("strategy_fitting", "reject", fit_version=FIT_202608,
                                material_no=M1), "待复核")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-31 拟合否决（待复核→已否决）")
    try:
        call("strategy_fitting", "run", material_no=M2, fit_version=FIT_202608)
        r = call("strategy_fitting", "reject", fit_version=FIT_202608, material_no=M2)
        assert r.get("status") == "已否决", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-32 拟合回滚（已生效→回滚上一版）")
    try:
        # 先构造上一版已生效（202607），再回滚 202608 到上一版
        call("strategy_fitting", "run", material_no=M1, fit_version="202607")
        call("strategy_fitting", "approve", fit_version="202607", material_no=M1)
        r = call("strategy_fitting", "rollback", fit_version=FIT_202608, material_no=M1)
        assert r.get("status") == "已否决", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-27 非已生效状态回滚拦截")
    try:
        expect_err(lambda: call("strategy_fitting", "rollback", fit_version=FIT_202608,
                                material_no=M2), "生效")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    # ════════════════════ §3.8 批量服务补充 ════════════════════

    step("TC-ERR-28 项目阶段正向推进（进行中→SOP）")
    try:
        r = call("md_project", "update", project_no=PRJ_1, stage="SOP")
        assert r.get("stage") == "SOP", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-34 库存策略批量计算（calc_batch）")
    try:
        r = call("inventory_strategy", "calc_batch", version_no=V202609)
        assert r is not None, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-35 推移表批量刷新（refresh_batch）")
    try:
        r = call("inventory_projection", "refresh_batch", biz_date="2026-08-15")
        assert r is not None, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-36 拟合批量（run_batch）")
    try:
        r = call("strategy_fitting", "run_batch", fit_version="202609")
        assert r is not None, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-37 月度版本取活跃版本（get_active）")
    try:
        r = call("md_monthly_version", "get_active")
        assert r is not None, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-38 物料批量导入（import_batch upsert）")
    try:
        r = call("md_material", "import_batch",
                 rows=[{"material_no": M5, "material_name": "物料C", "base_method": "移动平均",
                        "base_params": '{"window":6}'},
                       {"material_no": M1, "material_name": "物料A更新"}])
        assert r.get("success", 0) == 2, r
        assert r.get("fail", 0) == 0, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    # ════════════════════ §3.6 出库计划（outbound_plan）分支 / 链路 ════════════════════
    # 用新物料 M6 + 新客户 C003，避免污染既有断言
    C003 = "C003"
    M6 = "M6"

    step("TC-OP-01 前置：创建客户 C003 + 物料 M6")
    try:
        call("md_customer", "create", customer_no=C003, customer_name="客户C")
        call("md_material", "create", material_no=M6, material_name="物料F")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-OP-02 新建出库计划（未来日期 → 待出库）")
    op1 = None
    try:
        op1 = call("outbound_plan", "create", customer_no=C003, material_no=M6,
                   qty=300, out_date="2026-09-20")
        assert op1.get("status") == "待出库", op1
        assert str(op1.get("plan_no", "")).startswith("OB"), op1
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-OP-03 新建出库计划（过去日期 → 直接已关闭）")
    op2 = None
    try:
        op2 = call("outbound_plan", "create", customer_no=C003, material_no=M6,
                   qty=50, out_date="2026-08-10")
        assert op2.get("status") == "已关闭", op2
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-OP-04 主数据引用铁律 / 数量 / 日期校验")
    try:
        expect_err(lambda: call("outbound_plan", "create", customer_no=C003,
                                material_no="NO_SUCH_MAT", qty=1, out_date="2026-09-20"), "物料")
        expect_err(lambda: call("outbound_plan", "create", customer_no="NO_SUCH_CUST",
                                material_no=M6, qty=1, out_date="2026-09-20"), "客户")
        expect_err(lambda: call("outbound_plan", "create", customer_no=C003,
                                material_no=M6, qty=0, out_date="2026-09-20"), "大于0")
        expect_err(lambda: call("outbound_plan", "create", customer_no=C003,
                                material_no=M6, qty=1, out_date="2026-13-99"), "日期")
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-OP-05 列表过滤（material_no / status）")
    try:
        call("outbound_plan", "create", customer_no=C003, material_no=M6,
             qty=100, out_date="2026-09-25")
        assert call("outbound_plan", "list", material_no=M6).get("total") == 3
        assert call("outbound_plan", "list", material_no=M6, status="待出库").get("total") == 2
        assert call("outbound_plan", "list", material_no=M6, status="已关闭").get("total") == 1
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-OP-06 已关闭计划编辑延期 → 恢复待出库")
    try:
        r = call("outbound_plan", "update", plan_no=op2["plan_no"], out_date="2026-10-05")
        assert r.get("status") == "待出库", r
        assert r.get("out_date") == "2026-10-05", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-OP-07 回填实际出库单号（待出库保持）")
    try:
        r = call("outbound_plan", "update", plan_no=op1["plan_no"], actual_out_no="OUT-0001")
        assert r.get("actual_out_no") == "OUT-0001", r
        assert r.get("status") == "待出库", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-OP-08 删除约束（已关闭拦截；待出库可删）")
    try:
        op3 = call("outbound_plan", "create", customer_no=C003, material_no=M6,
                   qty=10, out_date="2026-08-01")
        assert op3.get("status") == "已关闭", op3
        expect_err(lambda: call("outbound_plan", "delete", plan_no=op3["plan_no"]), "不可删除")
        # 延期恢复待出库后可删
        call("outbound_plan", "update", plan_no=op3["plan_no"], out_date="2026-11-01")
        r = call("outbound_plan", "delete", plan_no=op3["plan_no"])
        assert r.get("deleted") is True, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-OP-09 close_expired 幂等")
    try:
        r = call("outbound_plan", "close_expired")
        assert r.get("closed") == 0, r   # 过期单已在读取/创建时结算
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-OP-10 库存推移表消费出库计划（预计出库量）")
    try:
        call("inventory_projection", "refresh", material_no=M6,
             biz_date="2026-08-20", opening_stock=0)
        r = call("inventory_projection", "get", material_no=M6, biz_date="2026-09-20")
        assert r.get("outbound_qty") == 300, r     # TC-OP-02 的计划
        r = call("inventory_projection", "get", material_no=M6, biz_date="2026-09-25")
        assert r.get("outbound_qty") == 100, r     # TC-OP-05 新增的计划
        r = call("inventory_projection", "get", material_no=M6, biz_date="2026-10-05")
        assert r.get("outbound_qty") == 50, r      # TC-OP-06 延期恢复的计划
        r = call("inventory_projection", "get", material_no=M6, biz_date="2026-08-20")
        assert r.get("outbound_qty") == 0, r       # 起始日无出库
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-ERR-39 统一社会信用代码非法拦截（校验位/长度）")
    try:
        # 校验位错误（91350100M000100C4 的正确校验位为 G，传 3 必拒）
        expect_err(lambda: call("md_customer", "create", customer_no="CERR1",
                                customer_name="信用代码校验位错", credit_code="91350100M000100C43"),
                   "校验位")
        # 长度不足
        expect_err(lambda: call("md_customer", "update", customer_no=C001,
                                credit_code="91110000710931"),
                   "18位")
        # 合法值可经 update 回填
        r = call("md_customer", "update", customer_no=C001, credit_code="91350100M000100C4G")
        assert r.get("credit_code") == "91350100M000100C4G", r
        record(True)
    except Exception as e:
        record(False, f"{e}")
