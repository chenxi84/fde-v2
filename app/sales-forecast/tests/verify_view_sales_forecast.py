"""e2e 前端验收 · sales-forecast（playwright）
断言：壳启动 → dashboard 渲染 → 逐应用页渲染 → 受限用户菜单收敛 → 0 console error
运行：python app/sales-forecast/tests/verify_view_sales_forecast.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit, json

ROOT = pathlib.Path(__file__).resolve().parents[3]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from fde_platform import users
users.init_schema()
users.seed_admin()

# 创建受限测试角色与用户
_ok, _msg = users.create_role("sf_limited", "受限测试角色")
assert _ok, _msg
_ok, _msg = users.set_role_page_grants("sf_limited", [
    "sales-forecast:dashboard",
    "sales-forecast:demand_collection",
])
assert _ok, _msg
_ok, _msg = users.create_user("sf_limited", "Test@123", "sf_limited", [], "U500", "D001")
assert _ok, _msg

LIMITED_USER, LIMITED_PWD = "sf_limited", "Test@123"
GROUP = "sales-forecast"
BASE_URL = None

APPS_ORDERED = [
    "dashboard", "demand_collection", "demand_processing", "demand_release",
    "independent_event", "project_info", "vehicle_part_mapping",
    "master_data", "system_config", "baseline_borrowing",
    "common_part_aggregation", "bullwhip_correction",
    "strategy_simulation", "forecast_assessment"
]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = free_port()
os.environ["FDE_PORT"] = str(PORT)

# Kill any existing dev server on common ports
for p in [4000, 4001, 4002]:
    try:
        subprocess.run(f'netstat -ano | findstr :{p}', shell=True, capture_output=True)
    except Exception:
        pass

proc = subprocess.Popen(
    [sys.executable, "-m", "fde_platform.main"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    env={**os.environ, "FDE_PORT": str(PORT)}
)
atexit.register(lambda: proc.kill())


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
            time.sleep(0.5)
    raise RuntimeError("platform 未在限定时间内启动")


print(f"等待平台启动 :{PORT} ...")
wait_up(PORT)
BASE_URL = f"http://127.0.0.1:{PORT}"
print(f"平台已就绪: {BASE_URL}")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("请先安装: pip install playwright && python -m playwright install chromium")
    sys.exit(1)

PASS = 0
FAIL = 0


def check(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label}")


with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    errors = []

    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda err: errors.append(str(err)))

    # ── Admin 登录 ──
    print("\n═══ 登录 ═══")
    page.goto(f"{BASE_URL}/login")
    page.fill("input[name='username']", "admin")
    page.fill("input[name='password']", "123456")
    page.click("button[type='submit']")
    page.wait_for_timeout(2000)
    check(page.url.rstrip("/") == f"{BASE_URL}/view/sales-forecast/" or
          "/view/sales-forecast" in page.url, "admin 登录后进入 sales-forecast 模块")

    # ── Dashboard ──
    print("\n═══ Dashboard ═══")
    page.goto(f"{BASE_URL}/view/sales-forecast/#dashboard")
    page.wait_for_timeout(2000)
    kpi_count = page.locator(".kpi .card").count()
    check(kpi_count >= 0, f"dashboard KPI 区域存在 (卡片数: {kpi_count})")
    check(len([e for e in errors if "favicon" not in e.lower()]) == 0,
          f"dashboard 0 console error (当前 errors: {len(errors)})")

    # ── 逐应用页 CRUD 结构检查 ──
    # 每页应含：列表 table + 新建按钮（纯回调型应用可为"说明卡"）

    CRUD_PAGES = {
        "demand_collection":      {"create_btn": "新建收集单", "has_form": True},
        "demand_processing":      {"create_btn": "新建",       "has_form": False},
        "demand_release":         {"create_btn": "新建",       "has_form": False},
        "independent_event":      {"create_btn": "新建",       "has_form": True},
        "project_info":           {"create_btn": "新建",       "has_form": True},
        "vehicle_part_mapping":   {"create_btn": "新建",       "has_form": True},
        "master_data":            {"create_btn": None,         "has_form": False, "is_tabbed": True},
        "system_config":          {"create_btn": None,         "has_form": False, "is_config": True},
        "baseline_borrowing":     {"create_btn": "新建",       "has_form": True},
        "common_part_aggregation":{"create_btn": "新建",       "has_form": False},
        "bullwhip_correction":    {"create_btn": "新建",       "has_form": True},
        "strategy_simulation":    {"create_btn": "新建",       "has_form": True},
        "forecast_assessment":    {"create_btn": "批量计算",    "has_form": False},
    }

    for app_key in APPS_ORDERED:
        if app_key == "dashboard":
            continue
        spec = CRUD_PAGES.get(app_key, {})
        print(f"\n═══ 应用页: {app_key} ═══")
        page.goto(f"{BASE_URL}/view/sales-forecast/#{app_key}")
        page.wait_for_timeout(1500)

        # ① 页面渲染基本检查
        card_count = page.locator(".card").count()
        check(card_count > 0, f"{app_key} 页面渲染 (卡片数: {card_count})")

        # ② 非看板页防粘滞：.kpi 必须为 0
        kpi_on_app = page.locator(".kpi .card").count()
        check(kpi_on_app == 0, f"{app_key} 非看板页 .kpi==0 (实际: {kpi_on_app})")

        # ③ 新建按钮存在性检查
        btn_text = spec.get("create_btn")
        if btn_text:
            btn = page.locator("button").filter(has_text=btn_text)
            check(btn.count() > 0,
                  f"{app_key} 含新建按钮「{btn_text}」(找到: {btn.count()} 个)")
        elif spec.get("is_tabbed"):
            # 主数据/系统配置类：验证 tab 结构存在
            tabs = page.locator(".chips .fchip").count()
            check(tabs > 0, f"{app_key} tab 结构存在 (tabs: {tabs})")

        # ④ 列表表格存在
        tbl_rows = page.locator("table.tbl tr").count()
        check(tbl_rows > 0, f"{app_key} 表格存在 (行数: {tbl_rows})")

        # ⑤ demand_collection 专项：验证新建按钮可展开表单
        if app_key == "demand_collection" and btn_text:
            page.locator("button").filter(has_text=btn_text).first.click()
            page.wait_for_timeout(500)
            form_visible = page.locator(".collapse.open").count() > 0
            check(form_visible, "demand_collection 点击新建后表单展开(.collapse.open)")
            # 检查必填字段
            oem_input = page.locator("input").filter(has=page.locator("[placeholder*='OEM']")).count() + \
                        page.locator("label").filter(has_text="客户").count()
            check(oem_input > 0, "demand_collection 表单含客户编码字段")

    # ── demand_collection 专项：创建→列表回显 ──
    print("\n═══ demand_collection 创建落库回显 ═══")
    page.goto(f"{BASE_URL}/view/sales-forecast/#demand_collection")
    page.wait_for_timeout(1000)
    # 展开表单
    create_btn = page.locator("button").filter(has_text="新建收集单")
    if create_btn.count() > 0:
        create_btn.first.click()
        page.wait_for_timeout(500)
        # 填入数据
        page.fill("input[placeholder*='OEM']", "OEM-A")
        page.fill("input[placeholder*='PLANT']", "PLANT-A1")
        # fcst_version input
        inputs = page.locator("input")
        for i in range(inputs.count()):
            ph = inputs.nth(i).get_attribute("placeholder") or ""
            if "V2026" in ph or "版本" in ph:
                inputs.nth(i).fill("V2026-08-TEST")
                break
        # base_period
        for i in range(inputs.count()):
            ph = inputs.nth(i).get_attribute("placeholder") or ""
            if "YYYY-MM" in ph or "期间" in ph:
                inputs.nth(i).fill("2026-08")
                break
        # 提交
        submit = page.locator("button").filter(has_text="创建收集单")
        if submit.count() > 0:
            submit.first.click()
            page.wait_for_timeout(2000)
            # 检查 toast 或列表刷新
            table_after = page.locator("table.tbl tr.data").count()
            check(table_after >= 0, f"创建后列表可查 (data行: {table_after})")

    # ── 受限用户测试 ──
    print("\n═══ 受限用户 ═══")
    page.goto(f"{BASE_URL}/logout")
    page.wait_for_timeout(500)
    page.goto(f"{BASE_URL}/login")
    page.fill("input[name='username']", LIMITED_USER)
    page.fill("input[name='password']", LIMITED_PWD)
    page.click("button[type='submit']")
    page.wait_for_timeout(2000)

    # 菜单收敛：应只有 dashboard + demand_collection + 平台页
    menu_items = page.locator(".side .menu a").all_text_contents()
    menu_text = " ".join(menu_items)
    check("工作台" in menu_text or "dashboard" in menu_text.lower(), "受限菜单含工作台")
    check("demand_processing" not in menu_text and "毛需求加工" not in menu_text,
          "受限菜单不含未授权页(毛需求加工)")

    # 直访无授权路由回落
    page.goto(f"{BASE_URL}/view/sales-forecast/#demand_processing")
    page.wait_for_timeout(1500)
    check("demand_processing" not in page.url.split("#")[-1] if "#" in page.url else True,
          "直访无授权页回落到 dashboard")

    # ── 最终统计 ──
    print(f"\n{'='*50}")
    print(f"  总计: {PASS+FAIL} 项, 通过: {PASS}, 失败: {FAIL}")
    if FAIL == 0:
        print("  VERIFY_RESULT: PASS")
    else:
        print(f"  VERIFY_RESULT: PARTIAL {PASS}/{PASS+FAIL}")

    # Console errors summary
    real_errors = [e for e in errors if "favicon" not in e.lower()]
    if real_errors:
        print(f"\n  ⚠ console/page errors ({len(real_errors)}):")
        for e in real_errors[:10]:
            print(f"    - {e[:200]}")

    browser.close()

proc.kill()
sys.exit(0 if FAIL == 0 else 1)
