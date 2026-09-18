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
        # BR-04 调拨提前期（对冲判定要用）/ BR-05 结算模式（业务分类）—— 回读而非只回显入参
        assert c.get("transfer_lead_days") == 3, c
        assert c.get("settle_mode") == "寄售", c
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
        assert m.get("change_cost") == 5000, m            # BR-07 切线成本（回读，非只回显入参）
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-04 创建物料 M2（多客户通用件）")
    try:
        r = call("md_material", "create", material_no=M2, material_name="物料B",
                 service_level=0.95, prod_days=10, logistics_days=5,
                 base_method="移动平均", base_params='{"window":6}')
        # 造数步也要一条业务字段断言 —— 否则它只是「没抛异常」
        assert r["material_no"] == M2 and r["service_level"] == 0.95, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-05 创建断点旧件 M3")
    try:
        r = call("md_material", "create", material_no=M3, material_name="旧件",
                 service_level=0.95, prod_days=10, logistics_days=5,
                 base_method="移动平均", base_params='{"window":6}')
        # 造数步也要一条业务字段断言 —— 否则它只是「没抛异常」
        assert r["material_no"] == M3 and r["service_level"] == 0.95, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-06 创建断点新件 M4")
    try:
        r = call("md_material", "create", material_no=M4, material_name="新件",
                 service_level=0.95, prod_days=10, logistics_days=5,
                 base_method="移动平均", base_params='{"window":6}')
        # 造数步也要一条业务字段断言 —— 否则它只是「没抛异常」
        assert r["material_no"] == M4 and r["service_level"] == 0.95, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-07 创建项目 PRJ-1")
    try:
        r = call("md_project", "create", project_no=PRJ_1, project_name="项目1",
                 owner="S001", stage="进行中", sop_date="2026-01-01", eop_date="2027-12-31")
        assert r.get("project_no") == PRJ_1, r
        # BR-04 立项/停产日期（报废点/清尾口径的输入）
        assert r.get("sop_date") == "2026-01-01" and r.get("eop_date") == "2027-12-31", r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-DM-08 创建项目零件映射（PRJ-1 × M1）")
    try:
        # 不传 veh_model/share：详设「数据治理变更（2026-08）」明确这两列已移出映射表
        # （车型/份额为项目级信息，只在 md_project 维护）。此前按旧版用例文档补参反而撞
        # TypeError —— T1 报「文档≠脚本」时，**对错要对照详设裁决**，不是无脑向文档看齐。
        r = call("md_project_part", "create", project_no=PRJ_1, material_no=M1, usage=1)
        assert r.get("project_no") == PRJ_1 and r.get("material_no") == M1, r
        assert r.get("usage") == 1, r        # BR-05 单车用量（需求折算系数）
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
        # 达成率两兄弟必须**一起写**：`decide` 取 mape 的同时也取 bias（同一次 attainment.get）——
        # 此前只写 mape，于是「只走过 decide 的行」两个同源字段一有一无（不对称）。
        att = call("attainment", "get", customer_no=C001, material_no=M1)
        assert r.get("bias") == att.get("bias"),             f"decide 应把 attainment 的 bias 一并落库：行={r.get('bias')} attainment={att.get('bias')}"
        assert r.get("mape") == att.get("mape"), r
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

    step("TC-PRED-06 人工定稿优先：decide 不再覆盖已定稿行")
    try:
        # ① 造一行「异常」：客户预测改成 800 → 调整后 760，与基线 950 偏离 25% > 5%
        call("sales_forecast", "fill_customer", version_no=V202608, material_no=M1,
             customer_no=C001, rolling_month="N+1", orig_qty=800)
        r = call("sales_forecast", "decide", version_no=V202608, material_no=M1,
                 customer_no=C001, rolling_month="N+1")
        assert r.get("abnormal_flag") in (1, True), r      # 双源分歧 → 异常
        assert r.get("final_qty") is None, r               # 异常行不定稿，等人工
        # ② 人工定稿
        r = call("sales_forecast", "set_final", version_no=V202608, material_no=M1,
                 customer_no=C001, rolling_month="N+1", final_qty=950)
        assert abs((r.get("final_qty") or 0) - 950) < 0.01, r
        # ③ 再跑一次批量决策：必须**跳过**它并报出来，定稿不能被清
        r = call("sales_forecast", "decide_batch", version_no=V202608)
        assert r.get("settled_skipped") == 1, r
        assert (r.get("settled_rows") or [{}])[0].get("material_no") == M1, r
        line = call("sales_forecast", "get", version_no=V202608, material_no=M1,
                    customer_no=C001, rolling_month="N+1")
        assert abs((line.get("final_qty") or 0) - 950) < 0.01, \
            f"人工定稿被 decide 覆盖了：{line.get('final_qty')}"
        # ④ 复原客户预测（后续用例按 final=950 断言），定稿仍在
        call("sales_forecast", "fill_customer", version_no=V202608, material_no=M1,
             customer_no=C001, rolling_month="N+1", orig_qty=1000)
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
        # BR-07 服务系数映射：满足率 95% → 1.65（这张映射表是详设原文，不是算出来的量）
        assert r.get("service_factor") == 1.65, r
        # BR-08 安全库存 C = 服务系数 × 响应窗口波动 —— 用同一行的两个分量**现算**比对
        # （不写死 C 的数值：造数一变就假红，而这里要守的是公式）
        assert abs((r.get("safety_level") or 0)
                   - round((r.get("service_factor") or 0) * (r.get("resp_volatility") or 0), 2)) < 0.01, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-07 取三层水位（供毛需求）")
    try:
        r = call("inventory_strategy", "get_water_level", version_no=V202608, material_no=M1)
        A, C, B = r["min_level"], r["safety_level"], r["batch_level"]
        # BR-10 水位带：下限=A+C，上限=下限+B（纯内部一致性，不猜造数）
        assert A >= 0 and C >= 0 and B >= 0, f"三层水位应非负：{A}/{C}/{B}"
        assert abs(r["lower"] - (A + C)) < 0.01, f"下限应=A+C：{r['lower']} vs {A+C}"
        assert abs(r["upper"] - (A + C + B)) < 0.01, f"上限应=A+C+B：{r['upper']}"
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-08 合成毛需求（每期含水位）")
    try:
        # 前置：水位策略。build_gross 要把水位叠进毛需求，且**取不到就报错**（fail-closed），
        # 所以必须先算策略——这也是文档里的既定顺序（水位节点在毛需求节点之前）。
        call("inventory_strategy", "calc_batch", version_no=V202608)
        wl = call("inventory_strategy", "get_water_level", version_no=V202608, material_no=M1)
        water = (wl.get("min_level") or 0) + (wl.get("safety_level") or 0) + (wl.get("batch_level") or 0)
        r = call("demand", "build_gross", version_no=V202608)
        assert r.get("material_count", 0) >= 1, r
        d = call("demand", "get", version_no=V202608, material_no=M1, rolling_month="N+1")
        assert abs((d.get("gross_qty") or 0) - (950 + water)) < 0.01, d
        assert abs((d.get("inventory_qty") or 0) - water) < 0.01, d   # N+1 也含水位
        # BR-03 销售预测逐期拆分：该期毛需求的预测层 = 汇总值（950），不是 0 ——
        # 这一层当年正是 B-01「预测静默归零、6025.88 件没进毛需求」出事的地方，
        # 而它此前**没有任何断言引用过**（见《测试用例.md》§4.9）
        assert abs((d.get("forecast_qty") or 0) - 950) < 0.01, d
        # BR-01 毛需求 = 预测 + 库存策略：用同一行的两个分量现算，不写死水位
        assert abs((d.get("gross_qty") or 0)
                   - ((d.get("forecast_qty") or 0) + (d.get("inventory_qty") or 0))) < 0.01, d
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

    step("TC-MC-11b 净需求原样通过导入（import_from_net，FUNC-05）")
    try:
        net = call("demand", "get", version_no=V202608, material_no=M1, rolling_month="N+1")
        r = call("master_plan", "import_from_net", version_no=V202608, material_nos=M1,
                 rolling_month="N+1", latest_inbound_date="2026-09-30")
        assert r.get("success") == 1, r
        assert r.get("plan_version") == 2, r     # TC-MC-11 的 import_plan 已占 v1
        assert r.get("materials") == [M1] and r.get("missing") == [], r
        latest = call("master_plan", "get_latest", version_no=V202608, material_no=M1)
        # 原样通过：plan_qty 逐字等于 net_qty，不掺任何再计算
        assert abs((latest[0].get("plan_qty") or 0) - (net.get("net_qty") or 0)) < 0.01, latest
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-11c 净需求原样通过导入：料号无命中须报错，不静默导 0 行")
    try:
        expect_err(lambda: call("master_plan", "import_from_net", version_no=V202608,
                                material_nos="NO-SUCH-MAT", rolling_month="N+1",
                                latest_inbound_date="2026-09-30"), "可导")
        # material_nos 写成 JSON 数组串也要认（调用方常这么传）
        r = call("master_plan", "import_from_net", version_no=V202608,
                 material_nos='["%s"]' % M1, rolling_month="N+1",
                 latest_inbound_date="2026-09-30")
        assert r.get("success") == 1 and r.get("materials") == [M1], r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-12 库存推移表逐日推演")
    try:
        from datetime import datetime
        res = call("inventory_projection", "refresh", material_no=M1, biz_date="2026-08-15",
                   opening_stock=0)
        rows = res.get("rows") or []
        assert len(rows) >= 2, f"应至少推演 2 天：{len(rows)}"
        # BR-07 推演窗口 = 未来 3 个月自然日；BR-01 行标识 = 物料号 + 日期
        assert res.get("biz_date") == "2026-08-15", res
        assert rows[0]["material_no"] == M1 and rows[0]["biz_date"] == "2026-08-15", rows[0]
        assert len(rows) == 90, f"BR-07 窗口应为 90 个自然日，实际 {len(rows)}"
        # BR-03 起始库存口径：调用方传入优先（ERP 适配器是 stub，只有传了才有真数据）
        assert res.get("opening_stock") == 0, res
        bal = res.get("opening_stock") or 0   # BR-02 逐日递推
        for d in rows[:5]:
            bal = bal + d["inbound_qty"] - d["outbound_qty"]
            assert abs(d["balance"] - bal) < 0.01, f"{d['biz_date']} 递推不符"
        # BR-11 已结束日**隐藏不删除**：默认列表只给 `biz_date ≥ 今日` 的行，而显式指定
        # 历史日期仍能精确回看（说明数据还在库里）。本组用例假定演示日期晚于 2026-08-15
        # （与 TC-OP-03「2026-08-10 → 已关闭」同一假设）
        today = datetime.now().strftime("%Y-%m-%d")
        shown = [x["biz_date"] for x in call("inventory_projection", "list",
                                            material_no=M1, size=500).get("items", [])]
        assert shown and all(x >= today for x in shown), \
            f"默认列表只应给 ≥ 今日({today}) 的行：{shown[:3]}…"
        assert "2026-08-15" not in shown, f"已结束日不应出现在默认列表：{shown[:3]}…"
        hist = call("inventory_projection", "list", material_no=M1, biz_date="2026-08-15")
        assert hist.get("total") == 1, f"历史快照应保留可回看：{hist}"
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-MC-13 预警扫描（对照水位线）")
    try:
        r = call("inventory_projection", "scan_alert", material_no=M1, version_no=V202608)
        assert r.get("scanned", 0) > 0, f"应扫描到推演行：{r}"
        if r.get("breach_count", 0) > 0:      # BR-04 击穿触发创建
            assert len(r.get("replenishments") or []) > 0, f"有击穿却没补库单：{r}"
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
        assert rp.get("replenish_type") == "缺货补库", rp        # BR-02 补库类型枚举
        assert rp.get("required_inbound") == "2026-08-20", rp    # BR-10 要求入库时间由触发时点给
        r = call("demand_pool", "release", replenish_no=rp_no, promised_inbound="2026-08-20")
        assert r.get("status") == "已下达", r
        assert r.get("promised_inbound") == "2026-08-20", r      # BR-12 承诺入库时间落库
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
        hist = call("sales_history", "list", material_no=M1)
        _items = hist.get("items") if isinstance(hist, dict) else hist
        assert len({r["period"] for r in (_items or [])}) >= 18, "M1 补足后应 ≥18 期"
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
        # BR-20 拟合参数回填版本记录：主表要留下 fit_version 与生效时间（回滚的依据之一）
        m = call("md_material", "get", material_no=M1)
        assert m.get("fit_version") == FIT_202608, m
        assert m.get("fit_effective_at"), m
        # BR-20 **库存侧参数取主数据人工值**（2026-09-17 口径）：
        #   ① 复核通过**不得覆盖**人工维护的组批窗口/满足率目标（此前 `approve` 会把拟合的
        #      常量 28/0.95 写回去 —— 人工设的值被静默冲掉，且看不出来）；
        #   ② 拟合记录里的两个值应是主数据当前值的**镜像**（供复核页追溯"依据的库存参数"）。
        assert m.get("batch_window") == 28, f"人工维护的组批窗口被拟合覆盖了：{m.get('batch_window')}"
        assert m.get("service_level") == 0.95, f"人工维护的满足率目标被覆盖了：{m.get('service_level')}"
        fit_row = call("strategy_fitting", "get", fit_version=FIT_202608, material_no=M1)
        assert fit_row.get("batch_window") == m.get("batch_window"), (fit_row.get("batch_window"), m.get("batch_window"))
        assert fit_row.get("fulfill_rate") == m.get("service_level"), (fit_row.get("fulfill_rate"), m.get("service_level"))
        record(True)
    except Exception as e:
        record(False, f"{e}")
