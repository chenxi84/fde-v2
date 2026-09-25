"""e2e 前端验收 · psc:inventory_projection（库存推移表，playwright，可直接运行）。
断言：本页路由渲染（非看板页 .kpi==0 防粘滞）→ 预警六态 chips → 造数后列表有推移表行
→ 详情模态全字段 + 原始数据折叠 → 豁免表单（无新建/编辑/删除）+ 两个计算触发按钮（refresh/
refresh_batch，扫描预警已移除前端入口、由批量刷新内部联动）弹窗字段 + 批量刷新摘要 + 刷新提交落库回显
→ 全程 0 console error / 0 pageerror / 0 HTTP>=400。
运行：python app/psc/tests/verify_view_psc_inventory_projection.py
"""
import sqlite3
import os, pathlib, socket, subprocess, sys, time, http.client, atexit


def _project_root() -> pathlib.Path:
    """向上找项目根（含 fde_platform/ 的目录）。不用 parents[N] 定死层级——
    本范式会被照抄进不同深度的脚本（tests/、design-plus/…），按标记定位才稳。"""
    p = pathlib.Path(__file__).resolve().parent
    while not (p / "fde_platform").is_dir():
        if p.parent == p:
            raise RuntimeError("无法定位项目根目录（未找到 fde_platform/）")
        p = p.parent
    return p


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from fde_platform.shadowdb import shadow_dbs, shadow_clear, shadow_clear_prefs, auth_db_path  # noqa: E402
from fde_platform.view_watchdog import install_watchdog  # noqa: E402

# 影子库：业务库与平台库**都**复制到副本 → 真库零字节接触，**不用停 dev server**。
# config=True 是必需的：本脚本要播种 admin（写 config/auth.db），不影子化就会污染真库。
_shadow = shadow_dbs(env=True, inprocess=False, config=True)
_shadow.__enter__()
# ⚠ **必须在副本上清表**（2026-09-18 加）：影子库是**真库的拷贝** —— 真演示数据
# （e2e 的 M001/M002、PSC 的各主数据）会被一起复制进来，而本脚本自带的造数会撞主键。
# 此前不写这句也没事，只是因为当时副本落盘在另一个目录、平台读到的其实是**新建空库**；
# 布局修正后"副本是空的"这个隐含假设当场暴露 ⇒ 显式清表，语义与《验证门禁.md》
# §四之二的「view e2e 起点 = 空表」一致。
shadow_clear("psc")
# **个人 UI 偏好也要清**：它是操作者本机状态（如"手动隐藏过某列"），
# 不清就会让用例结果取决于谁在哪台机器上跑（实测：真库里藏了 sales_forecast 的两列）。
shadow_clear_prefs()
atexit.register(_shadow.__exit__, None, None, None)

# admin 账户：必须在平台子进程启动前经 users 模块建好（隔离库为空）。
from fde_platform import users  # noqa: E402
users.init_schema()
users.seed_admin()
try:
    _auth_db = auth_db_path()
    if _auth_db.exists():
        _conn = sqlite3.connect(str(_auth_db))
        _conn.execute("UPDATE users SET password_changed = 1 WHERE username = 'admin'")
        _conn.commit()
        _conn.close()
except Exception:
    pass

STEP = ""

# BR-11 历史隐藏：未选日期时列表只显示 biz_date>=今日 的行。
# 造数起点 2026-08-15 推演 90 日，默认视图条数 = 窗口内 >= 今日 的天数（随运行日变化）。
from datetime import date, timedelta  # noqa: E402

# 输出编码：控制台代码页在本机默认是 GBK，而断言文案里有 ⇒ / ✓ / ✗ / ⚠ / − 这类**非 GBK 码位** ——
# 不钉住编码的话，print 自己会抛 UnicodeEncodeError（**崩在打印结果那一步**：断言算完了却报不出来，
# 其后用例也不再执行 —— 实测 nasa_pms 的 stakeholder 脚本里有一条断言就这么"消失"过）。与 scripts/run_gates.py 给
# 子进程设 PYTHONIOENCODING 同一根因；由 scripts/verify_test_script_encoding.py 守住别忘这一行。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
_SEED_START = date(2026, 8, 15)
EXPECTED_VISIBLE = sum(
    1 for i in range(90) if _SEED_START + timedelta(days=i) >= date.today()
)


def step(name):
    global STEP
    STEP = name
    print(f"── {name} ──")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_up(port, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("GET", "/api/groups")
            resp = conn.getresponse()
            resp.read()
            return True
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("platform 未在限定时间内启动")


# 造数链（§0 自足字典）：md_material.create(M1) → update 补齐水位参数 →
# inventory_strategy.calc(202608, M1) → inventory_projection.refresh(M1, "2026-08-15", opening_stock=0)
# （refresh 是 fail-closed 的：没有水位策略就拒绝推演，所以必须**先算水位再推演**）
SEED_JS = r"""async () => {
  const call = async (app, svc, params) => {
    const r = await fetch(`/api/apps/psc/${app}/call/${svc}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(params || {})
    });
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) {}
    if (!r.ok) throw new Error(`${app}.${svc} HTTP ${r.status} ${text.slice(0, 160)}`);
    if (data && (data.ok === false || data.error || data.status === "error")) {
      throw new Error(`${app}.${svc} biz ${JSON.stringify(data).slice(0, 160)}`);
    }
    return data;
  };
  const unwrap = (x) => {
    if (!x) return x;
    if (x.data !== undefined) return x.data;
    if (x.result !== undefined) return x.result;
    return x;
  };

  await call("md_material", "create", {
    material_no: "M1",
    material_name: "测试物料A",
    status: "正常"
  });
  // 补齐算水位所需参数，先把 202608 的水位算出来（refresh fail-closed 的前置）
  await call("md_material", "update", {
    material_no: "M1",
    service_level: 0.95,
    prod_days: 3,
    logistics_days: 2
  });
  // ⚠ 2026-09-17 补：**月度版本必须先存在** —— B-09 给 `inventory_strategy._validate_version`
  // 补了「版本存在性」校验（此前只查 YYYYMM 格式），于是「随便给个版本号算水位」不再可行，
  // 本 seed 因此从绿转红。造数要按真实运营顺序来：先建版本，再算水位。
  await call("md_monthly_version", "create", {
    version_no: "202608",
    anchor_period: "2026-08",
    opening_date: "2026-08-01"
  });
  await call("inventory_strategy", "calc", {
    version_no: "202608",
    material_no: "M1"
  });
  const ip = unwrap(await call("inventory_projection", "refresh", {
    material_no: "M1",
    biz_date: "2026-08-15",
    opening_stock: 0
  }));

  return { seeded: true, generated: (ip && ip.generated) || null, material_no: "M1" };
}"""


def click_button(scope, text):
    loc = scope.locator(f'button:visible:has-text("{text}")')
    assert loc.count() > 0, f"未找到按钮：{text}"
    loc.first.click()


def wait_modal(page, timeout=10000):
    """等可见模态出现，并等详情模态 loading 的 .loadbox 消失再返回（pitfalls #16）。"""
    page.locator(".modal-mask:visible").first.wait_for(state="visible", timeout=timeout)
    end = time.time() + 8
    while time.time() < end:
        if page.locator(".modal-mask:visible .loadbox:visible").count() == 0:
            break
        page.wait_for_timeout(120)
    return page.locator(".modal-mask:visible").last


def close_modal(page, modal):
    for sel in ['button:has-text("关闭")', 'button:has-text("取消")', "button.x"]:
        btn = modal.locator(sel)
        if btn.count():
            btn.first.click()
            break
    else:
        page.keyboard.press("Escape")
    try:
        modal.wait_for(state="hidden", timeout=3000)
    except Exception:
        page.keyboard.press("Escape")
    page.wait_for_timeout(250)


def main():
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        env={**os.environ, "PLATFORM_PORT": str(port), "PORT": str(port)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    errors = []
    ignored = []
    # 卡住诊断（2026-09-18）：页面冻死/渲染进程崩溃时 playwright 调用不返回 ——
    # 由这个守护线程把「最后完成的步骤 + 已收集的错误」打出来；否则超时被强杀时现场全丢。
    install_watchdog(errors, step_getter=lambda: STEP)

    def attach(page):
        page.on("console", lambda m: errors.append(m.text[:140]) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)[:140]))

        def on_response(resp):
            if resp.status >= 400:
                url = resp.url
                if "/favicon.ico" in url or url.endswith(".map"):
                    ignored.append(f"HTTP {resp.status} {url}")
                    return
                errors.append(f"HTTP {resp.status} {url}")

        page.on("response", on_response)

    try:
        wait_up(port)
        from playwright.sync_api import sync_playwright

        base = f"http://127.0.0.1:{port}"

        with sync_playwright() as p:
            browser = p.chromium.launch()

            # admin 会话：登录页 + 登录后 new_page
            ctx = browser.new_context()
            login_page = ctx.new_page()
            attach(login_page)

            login_page.goto(f"{base}/login")
            login_page.fill('input[name="username"]', "admin")
            login_page.fill('input[name="password"]', "admin")
            login_page.click('button[type="submit"]')
            login_page.wait_for_url("**/", timeout=15000)

            page = ctx.new_page()
            attach(page)

            page.goto(f"{base}/view/psc/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)

            # ── §1 本页路由渲染（防粘滞） ──
            # §1 VT-ROUTE-01 路由渲染（main .card > 0 · 非看板页 .kpi == 0 防挂载粘滞 ·
            #    默认视图为日历 .cal-tbl 可见）
            step("§1 路由渲染")
            page.evaluate("location.hash = '#/inventory_projection'")
            page.wait_for_selector("main .card", timeout=15000)
            page.wait_for_timeout(700)

            assert page.locator("main .card").count() > 0, "库存推移表未渲染卡片"
            assert page.locator("main").inner_text().strip(), "库存推移表无内容"
            assert page.locator(".kpi").count() == 0, "非看板页残留看板 .kpi（挂载未重建）"

            # 视图切换 chips（列表 / 日历）—— 等数据行渲染后再断言，避免 x-for 动态渲染早抢跑
            page.wait_for_selector(".fchip", timeout=15000)
            # ⚠ 缺口（如实标注，未编造）：文档 §1 VT-ROUTE-02「预警六态 chips 渲染」要求断言
            #   chips 文本集合 == {全部, 无, 缺货, 击穿最低, 击穿安全, 呆滞, 超储}；本脚本只等
            #   `.fchip` 出现（此处）并按「列表/日历」切视图，**从未断言六态文案集合**。
            # 默认日历视图
            assert page.locator(".cal-tbl:visible").count() > 0, "默认应为日历视图（.cal-tbl 可见）"

            # ── 造数（真实 REST，带会话 Cookie）──
            # §0 造数（M1 + IP-M1）：下列各 VT 用例的共同前置；文档 §0 是数据字典，
            #    本身无用例编号（此处断言 refresh 推演 90 日，属造数自身的健全性检查）。
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"造数失败：{seed}"
            assert seed.get("generated") == 90, f"refresh 应推演 90 日，实际 {seed.get('generated')}"

            # 重扫注册表 mtime（pitfalls #6）
            page.reload()
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.evaluate("location.hash = '#/inventory_projection'")
            page.wait_for_selector(".fchip", timeout=15000)
            # 默认日历 → 先切列表视图做台账断言
            page.locator('.fchip', has_text="列表").first.click()
            page.wait_for_timeout(400)
            page.locator("table tr.data", has_text="M1").first.wait_for(state="visible", timeout=15000)
            page.wait_for_timeout(600)

            # §1 VT-ROUTE-02 预警六态 chips 渲染（2026-09-17 补断言）
            #   为什么以前没断到：六态 chips 在 `<template x-if="viewMode === 'list'">` 里，
            #   **只有列表视图才渲染**（默认是日历视图）—— 所以必须在切到列表之后断言。
            #   六态取自 view.html 的 `['', '无', '缺货', '击穿最低', '击穿安全', '呆滞', '超储']`
            #   （`''` 显示为「全部」），覆盖 BR-09 的枚举。
            #   注意：页面上有**两组** chips —— 视图组（列表/日历/趋势）与预警组，故按
            #   「可见 fchip 文本集合」判定（不假设 DOM 层级：首版写 `.tagline .chips` 抓到了视图组）。
            all_chips = {t.strip() for t in page.locator(".fchip:visible").all_inner_texts()}
            expect = {"全部", "无", "缺货", "击穿最低", "击穿安全", "呆滞", "超储"}
            assert expect <= all_chips, f"预警六态 chips 缺：{expect - all_chips}（实际可见 {all_chips}）"
            assert {"列表", "日历", "趋势"} <= all_chips, f"视图切换 chips 缺：{all_chips}"

            # ── §2 造数后列表有数据 ──
            # §2 VT-LIST-01 列表含所造推移表行（M1 + 2026-08-15 精确 has_text 定位 ·
            #    inbound/outbound/balance 均 0 · 预警徽章「无」+ class 含 st-slate）
            # §2 VT-LIST-04 日期输入精确匹配（先填 input[placeholder="YYYY-MM-DD"] + 点「查询」，
            #    方能回看被 BR-11 隐藏的历史日期 → 下列行断言即在该过滤结果上）
            #    ⚠ 覆盖为部分：未断言「结果集无该日之外的日期行」这一半。
            # （2026-09-17：§2 原本缺 VT-LIST-02 / VT-LIST-03 两条断言的缺口说明已撤 —— 两条均已补。）
            step("§2 列表推移表行")
            # 默认隐藏历史快照（biz_date<今日）；回看 2026-08-15 需先选具体日期
            page.locator('input[placeholder="YYYY-MM-DD"]').first.fill("2026-08-15")
            page.locator('button:has-text("查询")').first.click()
            page.wait_for_timeout(600)
            row = page.locator("table tr.data", has_text="M1").filter(has_text="2026-08-15").first
            assert row.count() > 0, "列表未含 M1 推移表行"
            row_txt = row.inner_text()
            assert "M1" in row_txt and "2026-08-15" in row_txt, "M1 行未回显物料号/业务日期"
            nums = [t.strip() for t in row.locator("td.num").all_inner_texts()]
            assert nums == ["0", "0", "0"], f"数值列 inbound/outbound/balance 应均 0，实际 {nums}"
            st = row.locator(".st").first
            assert st.inner_text().strip() == "无", "预警徽章文本应为「无」"
            assert "st-slate" in (st.get_attribute("class") or ""), "预警徽章应含 st-slate"

            # §2 VT-LIST-02 物料下拉精确筛选（2026-09-17 补断言）
            #    操作：过滤条物料 autocomplete 输入 "M1" → 点下拉项选中（`@mousedown.prevent="pickMat"`
            #    选中，不回车 —— view.html 过滤条 input 的 `@input` 只过滤、`@click.stop` 只展开，
            #    选中逻辑全在下拉项上）→ 清掉 §2 上面留下的日期过滤 → 点「查询」
            #    断言：结果集收敛为仅 M1 的行（逐行物料号 == "M1"）；「共 N 条」== 窗口内可见行数。
            #    ⚠ 2026-09-17 订正（用例文档同步改）：文档原写「总条数 == 90」—— **实测不成立**：
            #      未选日期时 BR-11 由**后端** `list` 隐藏历史快照（`biz_date >= 今日` 子句，
            #      见 inventory_projection.py 的 list），故 total == 造数 90 天里 >= 今日 的天数
            #      = EXPECTED_VISIBLE（随运行日变化，不是恒定 90）；若沿用 §2 上面选定的
            #      2026-08-15，则收敛成 1 行（该日）。「90」只在「历史不隐藏」的假设下成立，
            #      与 BR-11 冲突，故按实现订正（口径同 §4 VT-OP-05 的「共 N 条」）。
            #    另注（如实标注）：影子库只造了 M1 一个物料的推移行，故「收敛」在本数据下
            #      只能断「每行 == M1 + 条数与 BR-11 窗口一致」，无法断「M1 之外的行被滤掉」
            #      （那需要再造 M2，会牵动 §4 的条数与批量刷新摘要，超出本轮补断言范围）。
            step("§2 VT-LIST-02 物料下拉精确筛选")
            fmat = page.locator('input[placeholder="物料号 / 名称…"]').first
            fmat.click()
            page.wait_for_timeout(200)
            fmat.fill("M1")
            page.wait_for_timeout(300)
            opt = fmat.locator('xpath=../div//div[normalize-space(.)="测试物料A"]')
            assert opt.count() > 0, "过滤条物料 autocomplete 下拉未列出 M1（物料名 测试物料A）"
            opt.first.click()
            page.wait_for_timeout(250)
            assert fmat.input_value() == "M1", f"物料 autocomplete 选中后应为 M1，实际 {fmat.input_value()!r}"
            # 清掉 VT-LIST-04 留下的日期过滤（留着它结果会收敛成该日 1 行）
            page.locator('input[placeholder="YYYY-MM-DD"]').first.fill("")
            page.locator('button:has-text("查询")').first.click()
            end = time.time() + 8
            while time.time() < end:
                if f"共 {EXPECTED_VISIBLE} 条" in page.locator("main").inner_text():
                    break
                page.wait_for_timeout(150)
            assert f"共 {EXPECTED_VISIBLE} 条" in page.locator("main").inner_text(), \
                f"按 M1 查询后应「共 {EXPECTED_VISIBLE} 条」（BR-11：90 天里 >= 今日的天数）"
            mat_cells = [t.strip() for t in
                         page.locator("table tr.data:visible td:first-child .b-link").all_inner_texts()]
            assert mat_cells, "按 M1 筛选后列表不应为空"
            assert all(t == "M1" for t in mat_cells), \
                f"筛选后结果集应仅含 M1，实际出现 {sorted(set(mat_cells))}"
            assert len(mat_cells) == min(20, EXPECTED_VISIBLE), \
                f"分页首页应 {min(20, EXPECTED_VISIBLE)} 行（pageable 默认 size=20），实际 {len(mat_cells)}"

            # §2 VT-LIST-03 预警类型 chips 筛选（2026-09-17 补断言）
            #    操作：点预警组 chips「无」→ `fAlert = '无'; search()`（view.html 的 fchip @click）
            #    断言：结果集收敛且**全部行**预警徽章文本 == "无"（含 M1）；点数 > 0。
            #    反证（补强「收敛」这一半，文档原句只写了正向）：点 chips「缺货」→ 0 条 ——
            #    本页最小造数下所有行 alert_type 都是「无」（无水位线时 `_classify_alert` 回「无」，
            #    此前提已由 §2 VT-LIST-01 的徽章断言钉住），故「缺货」必须收敛成空集；
            #    若这条反证变红，说明 chips 根本没把 alert_type 传下去（假筛选）。
            step("§2 VT-LIST-03 预警 chips 筛选（无 → 全行「无」；缺货 → 空集反证）")
            chip_none = page.locator('.fchip:visible:text-is("无")')
            assert chip_none.count() == 1, f"列表视图应有唯一「无」预警 chips，实际 {chip_none.count()}"
            chip_none.first.click()
            end = time.time() + 8
            while time.time() < end:
                if "on" in (chip_none.first.get_attribute("class") or ""):
                    break
                page.wait_for_timeout(150)
            page.wait_for_timeout(500)
            assert "on" in (chip_none.first.get_attribute("class") or ""), "点「无」后 chips 未置为选中态"
            assert f"共 {EXPECTED_VISIBLE} 条" in page.locator("main").inner_text(), \
                f"点「无」后应仍为 {EXPECTED_VISIBLE} 条（造数行全为「无」）"
            sts = [t.strip() for t in page.locator("table tr.data:visible td .st").all_inner_texts()]
            assert sts and all(t == "无" for t in sts), f"筛选后全部行预警徽章应 ==「无」，实际 {sorted(set(sts))}"
            page.locator('.fchip:visible:text-is("缺货")').first.click()
            page.wait_for_timeout(700)
            assert "共 0 条" in page.locator("main").inner_text(), \
                "点「缺货」应收敛成 0 条（反证 chips 真的在传 alert_type 过滤）"
            assert page.locator("table tr.data:visible").count() == 0, "「缺货」筛选后不应有数据行"
            # 还原预警筛选（回「全部」）→ 再复位到 §2 VT-LIST-04 的过滤态
            page.locator('.fchip:visible:text-is("全部")').first.click()
            page.wait_for_timeout(400)
            # 复位到 §2 VT-LIST-04 的过滤态（§3 详情模态断言依赖 2026-08-15 那一行）
            page.locator('input[placeholder="YYYY-MM-DD"]').first.fill("2026-08-15")
            page.locator('button:has-text("查询")').first.click()
            page.wait_for_timeout(600)

            # ── §3 详情模态全字段 ──
            # §3 VT-MODAL-01 详情模态全字段（.docno == M1 + KV 标签全集 + 预警徽章「无」/st-slate
            #    + 页脚；⚠ 页脚断言为「仅【关闭】、不含【扫描预警】」，与文档「含【扫描预警】与
            #    【关闭】」**相反** —— 依实现（扫描预警入口已废除）对齐，属文档待同步）
            step("§3 模态全字段")
            page.locator("table tr.data", has_text="M1").first.locator("button.b-link").first.click()
            modal = wait_modal(page)

            assert modal.locator(".docno").first.inner_text().strip() == "M1", "详情头带 .docno 应为 M1"
            bd = modal.locator(".modal-bd").first.inner_text()
            for label in ["物料号", "M1", "业务日期", "2026-08-15",
                          "预计入库量", "预计出库量", "库存余额", "预警类型", "无", "原始数据"]:
                assert label in bd, f"详情模态缺字段：{label}"
            st = modal.locator(".st").first
            assert st.inner_text().strip() == "无", "详情预警徽章文本应为「无」"
            assert "st-slate" in (st.get_attribute("class") or ""), "详情预警徽章应含 st-slate"
            ft = modal.locator(".modal-ft").first.inner_text()
            assert "扫描预警" not in ft and "关闭" in ft, "详情页脚应仅含【关闭】（扫描预警入口已移除）"

            # §3 VT-MODAL-02 原始数据折叠展开（details.raw summary → pre.json 含 material_no/biz_date）
            summary = modal.locator("details.raw summary")
            assert summary.count() > 0, "缺「原始数据」折叠 summary"
            summary.first.click()
            page.wait_for_timeout(300)
            pre = modal.locator("details.raw pre.json")
            assert pre.count() > 0, "原始数据 pre.json 未展开"
            raw = pre.first.inner_text()
            assert '"material_no": "M1"' in raw, "原始数据缺 material_no"
            assert '"biz_date": "2026-08-15"' in raw, "原始数据缺 biz_date"

            close_modal(page, modal)

            # ── §4 豁免（无表单）+ 计算触发按钮 ──
            # §4 VT-OP-01 无表单入口（无「新建/编辑/删除」· 工具栏含 查询/重置/🌊 刷新/🌊 批量刷新；
            #    ⚠ 文档此处还要求工具栏含「🌊 扫描预警」，脚本断言的恰是**不应再出现** —— 依实现
            #    （已移除前端入口）对齐，属文档待同步）
            # ⚠ 缺口（如实标注，未编造）：文档 §4 VT-OP-04「扫描预警按钮 → 弹窗字段」随该入口
            #    一并废除，脚本**无对应断言**。
            step("§4 豁免（无表单）+ 刷新/批量刷新按钮")
            for forbidden in ["新建", "编辑", "删除"]:
                assert page.locator(f'button:visible:has-text("{forbidden}")').count() == 0, \
                    f"自动参考创建页不应出现「{forbidden}」入口"
            for btn in ["查询", "重置", "🌊 刷新", "🌊 批量刷新"]:
                assert page.locator(f'button:visible:has-text("{btn}")').count() > 0, \
                    f"工具栏缺按钮：{btn}"
            assert page.locator('button:visible:has-text("🌊 扫描预警")').count() == 0, \
                "工具栏不应再出现「🌊 扫描预警」"

            # §4 VT-OP-02 刷新按钮 → 弹窗字段（头「单物料刷新」· 字段「物料/推演起始日期/期初库存」
            #    · 物料 autocomplete 可选到 M1）
            step("§4 刷新弹窗字段")
            click_button(page, "🌊 刷新")
            modal = wait_modal(page)
            assert "单物料刷新" in modal.locator(".docno").first.inner_text(), "刷新弹窗头应「单物料刷新」"
            bd = modal.locator(".modal-bd").first.inner_text()
            for label in ["物料", "推演起始日期", "期初库存"]:
                assert label in bd, f"刷新弹窗缺字段：{label}"
            mat_input = modal.locator('input[placeholder*="搜索物料号"]')
            assert mat_input.count() > 0, "刷新弹窗缺物料 autocomplete 输入"
            mat_input.click()
            page.wait_for_timeout(200)
            mat_input.fill("M1")
            page.wait_for_timeout(200)
            assert modal.locator('div:has-text("测试物料A")').count() > 0, "物料下拉未可选到 M1"
            close_modal(page, modal)

            # §4 VT-OP-03 批量刷新按钮 → 弹窗字段（头「批量刷新」· 自动口径说明「当天/全量/
            #    自动创建需求池补库单」· 不再要日期与物料号列表；⚠ 文档写的字段标签是
            #    「推演起始日期/物料号列表」，与实现相反，属文档待同步）
            #    —— 其后「提交 → 结果摘要」段落在文档中**无用例**（见回报：脚本独有断言块）。
            step("§4 批量刷新弹窗（自动口径，无输入项）")
            click_button(page, "🌊 批量刷新")
            modal = wait_modal(page)
            assert "批量刷新" in modal.locator(".docno").first.inner_text(), "批量刷新弹窗头应「批量刷新」"
            bd = modal.locator(".modal-bd").first.inner_text()
            for label in ["当天", "全量", "自动创建需求池补库单"]:
                assert label in bd, f"批量刷新弹窗缺自动口径说明：{label}"
            assert modal.locator('input[type="date"]').count() == 0, "批量刷新不应再要求推演起始日期"
            assert modal.locator("textarea").count() == 0, "批量刷新不应再要求物料号列表"

            step("§4 批量刷新提交 → 摘要（成功/失败/触发补库物料）")
            modal.locator('button:has-text("批量刷新")').last.click()
            page.wait_for_timeout(900)
            bd = modal.locator(".modal-bd").first.inner_text()
            assert "刷新结果摘要" in bd, "批量刷新后应显示结果摘要"
            for label in ["物料总数", "成功", "失败", "自动补库单", "成功物料", "失败物料", "触发补库的物料"]:
                assert label in bd, f"批量刷新摘要缺字段：{label}"
            assert "M1" in bd, "摘要成功物料应含 M1（隔离库唯一正常物料）"
            close_modal(page, modal)

            # §4 VT-OP-05 刷新提交落库回显（toast「已推演 90 日 · M1」· 弹窗关闭 ·
            #    列表回显 90 行 / 重置后当日及以后 EXPECTED_VISIBLE 条 · 首行为今日）
            step("§4 刷新提交落库回显")
            click_button(page, "🌊 刷新")
            modal = wait_modal(page)
            mat_input = modal.locator('input[placeholder*="搜索物料号"]')
            mat_input.click()
            page.wait_for_timeout(200)
            mat_input.fill("M1")
            page.wait_for_timeout(200)
            modal.locator('div:has-text("测试物料A")').first.click()
            page.wait_for_timeout(200)
            modal.locator('input[type="date"]').fill("2026-08-15")
            modal.locator('input[type="number"]').fill("0")
            modal.locator('button:has-text("开始推演")').click()

            page.locator('.toast:has-text("已推演 90 日 · M1")').first.wait_for(state="visible", timeout=10000)
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            # 清掉 §2 遗留的日期过滤 → 默认视图：从当天开始（历史隐藏），升序
            page.locator('button:has-text("重置")').first.click()
            page.wait_for_timeout(700)
            assert f"共 {EXPECTED_VISIBLE} 条" in page.locator("main").inner_text(), \
                f"重置后应显示当日及以后共 {EXPECTED_VISIBLE} 条（历史隐藏）"
            # 默认按日期从早到晚：首行日期 = 今日
            first_cells = page.locator("table tr.data td.mono").all_inner_texts()
            dates = [t.strip() for t in first_cells if t.strip() >= "2000-"]
            assert dates and dates[0] == date.today().strftime("%Y-%m-%d"), \
                f"默认首行应为今日，实际 {dates[:3]}"

            # ── §5 日历视图（单物料月历：余额 + 入/出小字，按预警上色） ──
            # §5 VT-CAL-01 日历视图渲染 → VT-CAL-02 选料后水位行 → VT-CAL-03 今日单元格
            #    → VT-CAL-04 点今日开详情 → VT-CAL-05 月份导航与切回列表
            # （2026-09-17：文档 §5 已按本段补写，双向对上了）
            step("§5 日历视图（单物料月历）")
            page.locator('.fchip', has_text="日历").first.click()
            page.wait_for_timeout(300)
            assert page.locator(".cal-tbl").count() > 0, "日历视图应显示月历表格 .cal-tbl"
            assert page.locator('table.tbl tr th', has_text="周一").count() > 0, "日历表头应含周一~周日"

            cal_input = page.locator('input[placeholder="搜索物料号 / 名称…"]').first
            cal_input.fill("M1")
            cal_input.press("Enter")
            page.wait_for_timeout(700)

            # 三层水位行（选料后自动显示；隔离库无库存策略 → 显示暂无）
            main_txt = page.locator("main").inner_text()
            assert "库存水位" in main_txt, "选料后应显示库存水位行"
            for label in ["最低", "安全", "组批上限"]:
                assert label in main_txt, f"水位行缺标签：{label}"
            assert "暂无库存策略水位" in main_txt, "无库存策略时应显示暂无提示"

            today_str = date.today().strftime("%Y-%m-%d")
            today_cell = page.locator(".cal-cell.cal-today").first
            assert today_cell.count() > 0, "当前月应含今日高亮单元格"
            txt = today_cell.inner_text()
            for label in ["预计库存量", "预计入库量", "预计出库量"]:
                assert label in txt, f"今日单元格缺中文标签：{label}，实际 {txt}"
            assert "0" in txt, f"今日单元格应显示数值 0，实际 {txt}"

            # 点今日 → 详情模态（复用 viewX）
            today_cell.locator(".cal-inner").first.click()
            modal = wait_modal(page)
            assert "M1" in modal.locator(".docno").first.inner_text(), "日历点今日应打开 M1 详情"
            close_modal(page, modal)

            # 月份导航：上月 → 回到本月
            def month_label_text():
                labels = page.locator(".mono:visible").all_inner_texts()
                ys = [t.strip() for t in labels if len(t.strip()) == 7 and t.strip()[4] == "-"]
                assert ys, f"未找到月份标签，可见 .mono：{labels}"
                return ys[0]

            m_before = month_label_text()
            page.locator('button:has-text("◀ 上月")').first.click()
            page.wait_for_timeout(300)
            assert month_label_text() != m_before, "上月导航后月份应变化"
            page.locator('button:has-text("回到本月")').first.click()
            page.wait_for_timeout(300)
            assert page.locator(".cal-cell.cal-today").count() > 0, "回到本月后应回到含今日的当月"

            # 切回列表视图
            page.locator('.fchip', has_text="列表").first.click()
            page.wait_for_timeout(300)
            assert page.locator('table.tbl tr th', has_text="物料号").count() > 0, "切回列表应恢复台账表"

            # ── §6 0 报错红线 ──
            # §6 VT-ERR-01 会话 0 报错（console error == 0 · pageerror == 0 · HTTP≥400 == 0，favicon 除外）
            step("§6 0 报错")
            assert not errors, f"前端报错：{errors[:5]}"
            # **豁免也要受检**（2026-09-17 补）：`ignored` 收集了却从不校验，等于给「静默吞掉」
            # 开了口子 —— 任何新形态的 4xx/console error 都能混进来而不被任何人发现。
            # 本页只认 favicon / sourcemap 两种豁免理由，其余一律报出。
            for item in ignored:
                ok = ("/favicon.ico" in item or ".map" in item)
                assert ok, f"豁免理由不成立（既不是 favicon 也不是 .map）：{item!r}"
            if ignored:
                print(f"  · 本次豁免 {len(ignored)} 条（favicon/.map）：{ignored[:3]}")
            print("VERIFY_VIEW_psc_inventory_projection: PASS")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"FAIL @ {STEP}: {e}")
        sys.exit(1)
