"""psc 组级前端验收（第⑨步 · 壳 / 菜单序 / dashboard / 受限用户；playwright，可直接运行）。
断言：壳品牌与 20 项业务菜单序 → dashboard 三区块（KPI/主链管道/待办队列）→
受限用户菜单收敛 / 直访无授权回落 / 隐式放行有数据 → 全程 0 console error /
0 pageerror / 0 HTTP≥400（受限会话 403 属预期执法，豁免）。
用例来源：app/psc/前端测试用例.md（§1 壳与菜单序/dashboard + §5 受限三连 + §6）。
运行：python app/psc/tests/verify_view_psc.py
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

from fde_platform.dbguard import isolate_dbs  # noqa: E402

_iso = isolate_dbs()
_iso.__enter__()
atexit.register(_iso.__exit__, None, None, None)

# 受限用户（菜单收敛 / 直访回落 / 隐式放行测试用）：必须在平台子进程启动前经 users 模块建好，
# 切勿在浏览器里调 HTTP API 建用户（平台无此端点）。照 verify_view_e2e.py 的写法。
from fde_platform import users  # noqa: E402
users.init_schema()
users.seed_admin()
try:
    _auth_db = ROOT / "config" / "auth.db"
    if _auth_db.exists():
        _conn = sqlite3.connect(str(_auth_db))
        _conn.execute("UPDATE users SET password_changed = 1 WHERE username = 'admin'")
        _conn.commit()
        _conn.close()
except Exception:
    pass
_ok, _msg = users.create_role("limited_role", "受限测试角色")
assert _ok, _msg
_ok, _msg = users.set_role_page_grants(
    "limited_role",
    ["psc:dashboard", "psc:md_customer", "psc:md_monthly_version", "_platform:agent_overview"],
)
assert _ok, _msg
_ok, _msg = users.create_user("limited_psc", "Limited@123", "limited_role", [], "U400", "D001")
assert _ok, _msg
try:
    if (ROOT / "config" / "auth.db").exists():
        _c2 = sqlite3.connect(str(ROOT / "config" / "auth.db"))
        _c2.execute("UPDATE users SET password_changed = 1 WHERE username = 'limited_psc'")
        _c2.commit()
        _c2.close()
except Exception:
    pass
LIMITED_USER, LIMITED_PWD = "limited_psc", "Limited@123"

# 业务菜单 20 项（PAGE_META.order 升序，主流程在前 + 基础数据在后）
EXPECTED_MENU = [
    "产销协同看板",      # dashboard order=10
    "流程总览",          # process order=15
    "物料 360 视图",     # material_360 order=20
    "销售预测",          # sales_forecast order=100
    "库存策略",          # inventory_strategy order=110
    "毛需求与净需求",    # demand order=120
    "主计划",            # master_plan order=130
    "出库计划",          # outbound_plan order=135
    "库存推移表",        # inventory_projection order=140
    "需求池",            # demand_pool order=150
    "策略拟合",          # strategy_fitting order=160
    "历史台账",          # sales_history order=170
    "客户主数据",        # md_customer order=510
    "物料主数据",        # md_material order=520
    "项目台账",          # md_project order=530
    "达成率与置信度",    # attainment order=535
    "项目零件映射",      # md_project_part order=540
    "断点基础数据",      # md_breakpoint order=550
    "替换关系",          # md_part_replace order=560
    "月度版本",          # md_monthly_version order=570
]

# 受限菜单（授权清单 psc:dashboard / psc:md_customer / psc:md_monthly_version + 平台智能体）
LIMITED_MENU = ["产销协同看板", "客户主数据", "月度版本", "智能体"]

STEP = ""


def step(name):
    global STEP
    STEP = name
    print(f"[{name}]", flush=True)


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


# 造数 C001（受限会话 VT-PERM-03 隐式放行断言用）：经浏览器 fetch 走真实 REST（带会话 Cookie）
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
    if (data && (data.ok === false || data.error)) {
      throw new Error(`${app}.${svc} biz ${JSON.stringify(data).slice(0, 160)}`);
    }
    return data;
  };
  const r = await call("md_customer", "create", {
    customer_no: "C001",
    customer_name: "客户A",
    settle_mode: "寄售",
    line_stock_days: 0,
    transfer_lead_days: 3
  });
  return { seeded: true, customer_no: "C001", row: r };
}"""


def _nav_names(page):
    """读取侧栏 .nav-item 菜单名序列（取 name span，剥离 ic 图标 span）。"""
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('.rail .nav-item')).map(el => {
            const n = el.querySelector('span:last-child');
            return n ? n.textContent.trim() : el.textContent.trim();
        })"""
    )


def main():
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        env={**os.environ, "PLATFORM_PORT": str(port), "PORT": str(port)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    state = {"limited": False}
    errors = []
    ignored = []

    def attach(page):
        def on_console(msg):
            if msg.type == "error":
                txt = msg.text[:140]
                if state["limited"] and "403" in txt:
                    ignored.append(txt)  # 受限会话 403 属预期执法（如文件面板无权限），豁免
                    return
                errors.append(txt)

        def on_pageerror(err):
            errors.append(str(err)[:140])

        def on_response(resp):
            if resp.status >= 400:
                url = resp.url
                if "/favicon.ico" in url or url.endswith(".map"):
                    ignored.append(f"HTTP {resp.status} {url}")
                    return
                if state["limited"] and resp.status == 403:
                    ignored.append(f"HTTP {resp.status} {url}")
                    return
                errors.append(f"HTTP {resp.status} {url}")

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("response", on_response)

    try:
        wait_up(port)
        from playwright.sync_api import sync_playwright

        base = f"http://127.0.0.1:{port}"

        with sync_playwright() as p:
            browser = p.chromium.launch()

            # ===================== admin 会话 =====================
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
            page.wait_for_timeout(2000)
            page.wait_for_selector(".rail .nav-item", timeout=20000)

            # §1 VT-SHELL-01 壳品牌
            step("shell-brand")
            brand_txt = page.locator(".brand .name").first.inner_text().strip()
            assert brand_txt == "FDE·PSC", f"侧栏品牌不符：{brand_txt!r}"

            # §1 VT-SHELL-01 菜单序（前 20 个 .nav-item == 业务菜单 order 升序；
            #   admin 末尾自动追加平台页 Agent / 服务台，不计入本序断言）
            step("shell-menu")
            names = _nav_names(page)
            assert len(names) >= 20, f"业务菜单不足 20 项：{names}"
            assert names[:20] == EXPECTED_MENU, (
                f"菜单序不符：\n实际 {names[:20]}\n期望 {EXPECTED_MENU}")

            # §1 VT-SHELL-01 Agent 右栏（默认展开 · header 按钮可收起/展开）
            step("agent-rail")
            assert page.locator("aside.agent-rail").count() == 1, "缺 Agent 右栏"
            assert page.locator("aside.agent-rail").is_visible(), "Agent 右栏默认应展开"
            assert page.locator(".agent-toggle").count() == 1, "header 缺 Agent 切换按钮"
            page.locator(".agent-toggle").first.click()
            page.wait_for_timeout(300)
            assert not page.locator("aside.agent-rail").is_visible(), "点切换后 Agent 右栏应收起"
            page.locator(".agent-toggle").first.click()
            page.wait_for_timeout(300)
            assert page.locator("aside.agent-rail").is_visible(), "再点切换后 Agent 右栏应恢复展开"

            # 造数 C001（受限会话 VT-PERM-03 用；dashboard 零值兜底不依赖它）
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"造数失败：{seed}"

            # §1 VT-DASH-01 看板渲染（默认落地页即 dashboard；先等 loading 结束）
            step("dashboard")
            page.wait_for_selector("main .kpi", state="visible", timeout=20000)
            page.wait_for_timeout(300)

            assert page.locator(".kpi").count() == 6, (
                f"dashboard KPI 卡数量 != 6（实际 {page.locator('.kpi').count()}）")
            main_txt = page.locator("main").inner_text()
            assert "主链管道" in main_txt, "dashboard 缺「主链管道」区块"
            assert "待办队列" in main_txt, "dashboard 缺「待办队列」区块"
            assert page.locator(".pipe-col").count() == 10, (
                f"dashboard 管道段数 != 10（主链7+待办3，实际 {page.locator('.pipe-col').count()}）")

            # §1 VT-PROCESS-01 流程总览（数据驱动 SVG 流水线）
            step("process")
            page.evaluate("location.hash = '#/process'")
            page.wait_for_selector("main svg g[data-page]", timeout=15000)
            page.wait_for_timeout(300)
            assert page.locator("main svg g[data-page]").count() == 22, "流程总览应有 7 阶段胶囊 + 15 步骤节点 = 22 个可点节点"
            assert page.locator('button:visible:has-text("Agent 分析下一步")').count() == 1, "流程总览缺 Agent 分析按钮"
            assert page.locator('select[x-model="fv"]').count() == 1, "流程总览缺版本下拉"

            # ===================== 受限会话 =====================
            limited_ctx = browser.new_context()
            limited_page = limited_ctx.new_page()
            attach(limited_page)

            state["limited"] = True

            limited_page.goto(f"{base}/login")
            limited_page.fill('input[name="username"]', LIMITED_USER)
            limited_page.fill('input[name="password"]', LIMITED_PWD)
            limited_page.click('button[type="submit"]')
            limited_page.wait_for_url("**/", timeout=15000)

            limited_page.goto(f"{base}/view/psc/")
            limited_page.wait_for_timeout(2000)
            limited_page.wait_for_selector(".rail .nav-item", timeout=20000)
            limited_page.wait_for_timeout(600)

            # §5 VT-PERM-01 菜单收敛
            step("perm-menu")
            limited_names = _nav_names(limited_page)
            assert limited_names == LIMITED_MENU, (
                f"受限菜单不符：\n实际 {limited_names}\n期望 {LIMITED_MENU}")

            # §5 VT-PERM-02 直访无授权 hash 路由回落菜单首项（看板名「产销协同看板」，
            #   非 e2e/crm 的「首页看板」；syncRoute 不回写 hash，故断言 header 标题）
            step("perm-fallback")
            limited_page.evaluate("location.hash = '#/sales_forecast'")
            limited_page.wait_for_timeout(1200)
            header_txt = limited_page.locator("header.top h1").first.inner_text().strip()
            assert header_txt == "产销协同看板", (
                f"受限直访 sales_forecast 应回落「产销协同看板」，实际 {header_txt!r}")

            # §5 VT-PERM-03 隐式放行有数据（md_customer.list 经 X-Fde-Page 派生放行）
            step("perm-implicit")
            limited_page.evaluate("location.hash = '#/md_customer'")
            limited_page.wait_for_selector('button.b-link.mono:has-text("C001")', timeout=15000)
            limited_page.wait_for_timeout(400)
            assert limited_page.locator('button.b-link.mono:has-text("C001")').count() >= 1, (
                "md_customer 页未回显 C001（隐式放行未生效）")

            # §6 组级会话 0 报错（受限会话 403 已豁免）
            step("errors")
            assert not errors, f"前端报错：{errors[:5]}"

            print("VERIFY_VIEW_psc: PASS")

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
