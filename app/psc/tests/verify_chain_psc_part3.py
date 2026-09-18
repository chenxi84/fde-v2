"""verify_chain_psc part3: §3.11 适配器穿透（影子库内注入非零值）

## 为什么单独一层

BR-04/06/07（净需求扣减）、BR-03（起始库存）、BR-08/09（预警级别）依赖的 ERP 适配器
**在演示环境恒返回空 / 0**，于是这些列永远是 0 —— 常规用例写不出非零期望，这几条 BR 的
输出字段**长期没有任何断言引用**（见 `app/psc/测试用例.md` §4.9 的 A 类）。

做法与对账体检的 X-H 组同源：在**影子库**（副本）里把适配器换成受控值，真库零字节接触。
与 X-H 的区别是它留在了**常驻用例**里 —— 体检脚本里那种一次性检查组每轮只跑一次、也不在
链测试层，而这一层随主链天天跑。

**断言全部是关系型的**，不写死造数常数：

- `net = gross + 未发 − 库存 − 在途`（三个分量从**同一行**读回）
- N+2 / N+3 不扣减（远期口径，BR-08 的后半句）
- 负净额钳 0
- 预警级别由**水位带**（A / A+C / B，现场取）划出的区间决定

## 版本为什么复用 V202609

`md_monthly_version` 的 BR 是**同一时刻仅一个活跃版本**：V202608 在 part1 已冻结，
part2 建的 V202609 到本层仍是草稿 ⇒ 本层只能挂在 V202609 上（`build_gross` 要求草稿，
`calc_net` 要求「已发布未冻结」）。
"""
# Covers: TC-PEN-01~06（穿透用例 + BR-04 过期补库单口径；对应《测试用例.md》§3.11）


def _patch(step_cls, names, values, fn):
    """临时替换类上的适配器方法，跑完**无论成败都还原**。

    为什么能这么打：平台把应用加载成 `sys.modules["fde_app_<组>__<应用>"]`（见
    `fde_platform/runtime.py::_load`），所以这里拿到的**就是同一个类对象**，
    改类属性对平台的实例同样生效。测的仍然是真实路由（`platform.call`），
    被替换的只有最外那一层「外部系统适配器」—— 它本来就是 stub 边界。
    """
    originals = [getattr(step_cls, n) for n in names]
    for n, v in zip(names, values):
        setattr(step_cls, n, v)
    try:
        return fn()
    finally:
        for n, o in zip(names, originals):
            setattr(step_cls, n, o)


def run_part(call, step, expect_err, record):
    import sys

    C001 = "C001"
    M13, M14 = "M13", "M14"
    V = "202609"          # 复用 part2 建的活跃草稿版本（同时刻仅一个活跃版本，见文件头）

    # ════════════════ 前置：两个「参数齐全 + 有历史」的物料 ════════════════

    step("前置：建 M13/M14（水位参数齐全 + 6 期历史）")
    try:
        for m, name in ((M13, "穿透件A"), (M14, "穿透件B")):
            call("md_material", "create", material_no=m, material_name=name,
                 status="正常", value_class="低", prod_days=10, logistics_days=5,
                 service_level=0.95, batch_window=28,
                 base_method="移动平均", base_params='{"window":6}')
        # M13 的历史**有波动**（σ_L>0 ⇒ 安全库存 C>0）—— 后面「击穿安全」那一档才谈得上
        rows = [{"material_no": M13, "customer_no": C001, "period": "2026-%02d" % i, "qty": q}
                for i, q in enumerate([900, 950, 1000, 950, 920, 980], start=1)]
        # M14 的历史**恒定**（σ_L=0 ⇒ C=0）：它的用途只是判「负净额钳 0」，不需要安全库存
        rows += [{"material_no": M14, "customer_no": C001, "period": "2026-%02d" % i, "qty": 100}
                 for i in range(1, 7)]
        r = call("sales_history", "import_batch", rows=rows)
        assert r.get("success") == 12 and r.get("fail") == 0, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("前置：V202609 水位策略全物料可算（补齐存量物料的满足率）")
    try:
        # build_gross 是 fail-closed 的：**任一**物料取不到水位就整版中止。M5/M7/M8/M9
        # 建料时没给满足率（part2 的 TC-ERR-34 因此有失败项），这里补上 ——
        # 否则 build_gross(V202609) 根本跑不起来，穿透测试无从谈起。
        for m in ("M5", "M7", "M8", "M9"):
            call("md_material", "update", material_no=m, service_level=0.95,
                 prod_days=10, logistics_days=5)
        r = call("inventory_strategy", "calc_batch", version_no=V)
        assert r.get("fail") == 0, f"补齐参数后应全物料可算：{r.get('errors')}"
        assert r.get("success", 0) > 0, r
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("前置：V202609 合成毛需求并发布（净需求穿透的前置）")
    try:
        # part2 的 open_version(V202609) 早于 M13/M14 建料 ⇒ 这两料的处理行要手工补
        for m in (M13, M14):
            call("sales_forecast", "create", version_no=V, material_no=m, customer_no=C001)
        for rm in ("N+1", "N+2", "N+3"):
            call("sales_forecast", "fill_customer", version_no=V, material_no=M13,
                 customer_no=C001, rolling_month=rm, orig_qty=1000)
        call("sales_forecast", "decide_batch", version_no=V)
        call("sales_forecast", "summarize", version_no=V)
        r = call("demand", "build_gross", version_no=V)
        assert r.get("material_count", 0) >= 1, r
        p = call("demand", "publish", version_no=V)
        assert "发布成功" in (p.get("message") or ""), p
        record(True)
    except Exception as e:
        record(False, f"{e}")

    # ════════════════ 穿透一：净需求的三层扣减（BR-04/06/07/08）════════════════

    step("TC-PEN-01 净需求扣减穿透（未发/库存/在途注入非零值）")
    try:
        Demand = getattr(sys.modules["fde_app_psc__demand"], "Demand")
        # 受控值：M13 三层各给一个非零数（10/40/15，与 BR-04 的公式示例同型）；
        # M14 的库存给到足以吃掉全部毛需求 ⇒ 验证「负净额钳 0」
        r = _patch(
            Demand,
            ("_load_open_order", "_load_inventory", "_load_in_transit"),
            (lambda self, version_no: {M13: 10},
             lambda self, version_no: {M13: 40, M14: 999999},
             lambda self, version_no: {M13: 15}),
            lambda: call("demand", "calc_net", version_no=V),
        )
        assert r.get("row_count", 0) >= 1, r
        n1 = call("demand", "get", version_no=V, material_no=M13, rolling_month="N+1")
        # 三个扣减层分别落库（BR-06 / BR-07 的输出字段，此前恒 0、无任何断言）
        assert n1["open_order_qty"] == 10, n1
        assert n1["onhand_qty"] == 40, n1
        assert n1["in_transit_qty"] == 15, n1
        # BR-04 公式：net = gross + 未发 − 库存 − 在途（四个量都从同一行读回）
        assert abs(n1["net_qty"] - (n1["gross_qty"] + n1["open_order_qty"]
                                    - n1["onhand_qty"] - n1["in_transit_qty"])) < 0.01, n1
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-PEN-02 远期不扣减（N+2/N+3 净=毛）与负净额钳 0（BR-08）")
    try:
        for rm in ("N+2", "N+3"):
            d = call("demand", "get", version_no=V, material_no=M13, rolling_month=rm)
            assert d["open_order_qty"] == 0 and d["onhand_qty"] == 0, d
            assert d["in_transit_qty"] == 0, d
            assert abs(d["net_qty"] - d["gross_qty"]) < 0.01, d
        # M14：库存 999999 远超毛需求 ⇒ 公式结果是负的，必须置 0（已被库存覆盖，无需生产）
        d14 = call("demand", "get", version_no=V, material_no=M14, rolling_month="N+1")
        assert d14["gross_qty"] < d14["onhand_qty"], d14      # 前提：确实是负数场景
        assert d14["net_qty"] == 0, f"负净额应钳 0，实际 {d14['net_qty']}"
        record(True)
    except Exception as e:
        record(False, f"{e}")

    # ════════════════ 穿透二：推移表的起始库存与预警级别（BR-03/08/09/01）════════════════

    step("TC-PEN-03 起始库存穿透：ERP 适配器路径（不传 opening_stock）")
    try:
        Proj = getattr(sys.modules["fde_app_psc__inventory_projection"], "InventoryProjection")
        # 不传 opening_stock 时才走 `_load_inventory`（BR-03 的 ERP 口径）；首日余额 = 锚点
        res = _patch(Proj, ("_load_inventory",), (lambda self, material_no: 777,),
                     lambda: call("inventory_projection", "refresh", material_no=M13,
                                  biz_date="2026-09-05"))
        assert res.get("opening_stock") == 777, res
        assert res["rows"][0]["balance"] == 777, res["rows"][0]
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-PEN-04 预警级别穿透：由水位带区间决定（五档全覆）")
    try:
        w = call("inventory_strategy", "get_water_level", version_no=V, material_no=M13)
        A, C, B = w["min_level"], w["safety_level"], w["batch_level"]
        assert A > 0 and C > 0, f"本用例需要非空水位带（A>0 且 C>0）：{w}"
        assert B >= 0, f"BR-10 的水位带应满足 B ≥ 0（上限 A+C+B 不低于下限 A+C）：{w}"
        cases = [
            (-1.0, "缺货"),                        # balance < 0（最严重级别优先）
            (round(A / 2, 2), "击穿最低"),          # 0 ≤ balance < A
            (round(A + C / 2, 2), "击穿安全"),      # A ≤ balance < A+C
            (round(A + C, 2), "无"),               # A+C ≤ balance ≤ A+C+B（水位带内）
            (round(A + C + B, 2), "无"),           # 恰好等于上限，仍是「无」
            (round(A + C + B + 1, 2), "超储"),     # balance > 上限 A+C+B（**不是裸 B**，见 B-10）
        ]
        for opening, want in cases:
            res = call("inventory_projection", "refresh", material_no=M13,
                       biz_date="2026-09-05", opening_stock=opening)
            got = res["rows"][0]["alert_type"]
            assert got == want, \
                f"起始库存 {opening}（水位 A={A}/C={C}/B={B}）应判「{want}」，实际「{got}」"
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-PEN-06 过期补库单钳到窗口首日（BR-04 口径）")
    try:
        # 造一张「要求入库日已过期、但仍未下达」的补库单 —— 它的入库日落在推演窗口**之前**
        rp = call("demand_pool", "create", material_no=M13, replenish_type="最低库存补库",
                  replenish_qty=123.45, required_inbound="2026-08-20")
        rp_no = rp.get("replenish_no")
        assert rp_no, rp
        res = call("inventory_projection", "refresh", material_no=M13, biz_date="2026-09-05",
                   opening_stock=0)
        # ① **明确报出**（不得静默丢）：返回里带着该单与"已过期→钳到首日"的原因
        od = res.get("overdue_inbound") or []
        assert [x.get("replenish_no") for x in od] == [rp_no], f"过期单应被明确报出：{od}"
        assert od[0].get("inbound_date") == "2026-08-20" and od[0].get("clamped_to") == "2026-09-05", od[0]
        # ② **钳到窗口首日计入**：首日入库量 == 该单量，余额 = 起始库存 0 + 它
        first = (res.get("rows") or [])[0]
        assert first["biz_date"] == "2026-09-05", first
        assert abs(first["inbound_qty"] - 123.45) < 0.01,             f"过期单应按「尽快到货」钳到窗口首日计入，旧行为是静默丢掉（入库 0）：{first}"
        assert abs(first["balance"] - 123.45) < 0.01, first
        record(True)
    except Exception as e:
        record(False, f"{e}")

    step("TC-PEN-05 同日重复刷新不产生重复行（BR-01 行唯一）")
    try:
        lst = call("inventory_projection", "list", material_no=M13, biz_date="2026-09-05")
        assert lst.get("total") == 1, f"「物料 + 日期」应唯一：{lst}"
        assert lst["items"][0]["biz_date"] == "2026-09-05", lst
        record(True)
    except Exception as e:
        record(False, f"{e}")
