"""psc 组级前端验收（第⑨步 · 壳 / 菜单序 / dashboard / 受限用户；playwright，可直接运行）。
断言：壳品牌与 20 项业务菜单序 → dashboard 三区块（KPI/主链管道/待办队列）→
受限用户菜单收敛 / 直访无授权回落 / 隐式放行有数据 → 全程 0 console error /
0 pageerror / 0 HTTP≥400（受限会话 403 属预期执法，豁免）。
用例来源：app/psc/前端测试用例.md（§1 壳与菜单序/dashboard + §5 受限三连 + §6）。
运行：python app/psc/tests/verify_view_psc.py
"""
import sqlite3
import os, pathlib, re, socket, subprocess, sys, time, http.client, atexit


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

# 受限用户（菜单收敛 / 直访回落 / 隐式放行测试用）：必须在平台子进程启动前经 users 模块建好，
# 切勿在浏览器里调 HTTP API 建用户（平台无此端点）。照 verify_view_e2e.py 的写法。
from fde_platform import users  # noqa: E402

# 输出编码：控制台代码页在本机默认是 GBK，而断言文案里有 ⇒ / ✓ / ✗ / ⚠ / − 这类**非 GBK 码位** ——
# 不钉住编码的话，print 自己会抛 UnicodeEncodeError（**崩在打印结果那一步**：断言算完了却报不出来，
# 其后用例也不再执行 —— 实测 nasa_pms 的 stakeholder 脚本里有一条断言就这么"消失"过）。与 scripts/run_gates.py 给
# 子进程设 PYTHONIOENCODING 同一根因；由 scripts/verify_test_script_encoding.py 守住别忘这一行。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
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
_ok, _msg = users.create_role("limited_role", "受限测试角色")
assert _ok, _msg
_ok, _msg = users.set_role_page_grants(
    "limited_role",
    # ⚠ 2026-09-17 订正：原写 `_platform:agent_overview` —— **全仓没有这个页面**（`PLATFORM_PAGES`
    # 里是 workbench/alerts/autopilot/flow_editor/scheduler/integration/knowledge）。
    # 真实的平台页 key 是 `workbench`（侧栏名「AI管家」，`top: true` 故排在业务页之前；
    # 授权键格式是 `_platform:<key>`，见 view/lib/shell.js 的 PLATFORM_PAGES 过滤）。
    # 旧清单等于「授了一个不存在的页 + 没授真实页」：有限用户的平台页会整片消失，
    # 而断言又期望它出现 —— 这就是本脚本此前红着的原因之一。
    ["psc:dashboard", "psc:md_customer", "psc:md_monthly_version", "_platform:workbench"],
)
assert _ok, _msg
_ok, _msg = users.create_user("limited_psc", "Limited@123", "limited_role", [], "U400", "D001")
assert _ok, _msg
try:
    if (auth_db_path()).exists():
        _c2 = sqlite3.connect(str(auth_db_path()))
        _c2.execute("UPDATE users SET password_changed = 1 WHERE username = 'limited_psc'")
        _c2.commit()
        _c2.close()
except Exception:
    pass
LIMITED_USER, LIMITED_PWD = "limited_psc", "Limited@123"

# ⚠ 2026-09-17 订正：期望菜单**不再手抄**，改为从页面自己声明的元数据现算 ——
# 手抄的版本已经漂了两次：少一个 material_360、序位错（把基础数据排在主流程中间）、
# 且没算上排在最前的平台页（`top: true`）。**抄一份就多一处会漂的地方**。
def _expected_business_menu():
    """扫 app/psc 下各页 `PAGE_META`（view.js 与组级 <页>.js），按 order 升序返回中文名。

    真值来自**页面自己声明的元数据**（平台扫描装配菜单用的就是它），不是某份文档。
    """
    import json as _json
    import re as _re
    metas = []
    for path in list((ROOT / "app" / "psc").glob("*/view.js")) + list((ROOT / "app" / "psc").glob("*.js")):
        text = path.read_text(encoding="utf-8", errors="replace")
        m = _re.search(r"export const PAGE_META\s*=\s*\{(.*?)\};", text, _re.S)
        if not m:
            continue
        body = m.group(1)
        name = _re.search(r'name\s*:\s*"([^"]*)"', body)
        order = _re.search(r"order\s*:\s*(\d+)", body)
        if name and order:
            metas.append((int(order.group(1)), name.group(1)))
    return [n for _o, n in sorted(metas)]


def _top_platform_menu():
    """排在业务页**之前**的平台页名（shell.js 的 `PLATFORM_PAGES` 里 `top: true` 且非 hidden）。"""
    text = (ROOT / "view" / "lib" / "shell.js").read_text(encoding="utf-8")
    out = []
    block = re.search(r"export const PLATFORM_PAGES\s*=\s*\[(.*?)\n\];", text, re.S)
    for m in re.finditer(r"\{([^}]*)\}", block.group(1) if block else ""):
        body = m.group(1)
        if "top: true" in body and "hidden: true" not in body:
            nm = re.search(r'name:\s*"([^"]+)"', body)
            if nm:
                out.append(nm.group(1))
    return out


EXPECTED_MENU = _top_platform_menu() + _expected_business_menu()

# 受限菜单（授权清单 psc:dashboard / psc:md_customer / psc:md_monthly_version + 平台 AI管家）
LIMITED_MENU = _top_platform_menu() + ["产销协同看板", "客户主数据", "月度版本"]

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
    # 卡住诊断（2026-09-18）：页面冻死/渲染进程崩溃时 playwright 调用不返回 ——
    # 由这个守护线程把「最后完成的步骤 + 已收集的错误」打出来；否则超时被强杀时现场全丢。
    install_watchdog(errors, step_getter=lambda: STEP)

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

            # §1 VT-SHELL-01 菜单序（**前 N 项** == 平台置顶页 + 业务页 order 升序；
            #   N = 期望表长度，期望表由 PAGE_META + PLATFORM_PAGES 现算，不手抄）
            step("shell-menu")
            names = _nav_names(page)
            n = len(EXPECTED_MENU)
            assert len(names) >= n, f"菜单不足 {n} 项：{names}"
            assert names[:n] == EXPECTED_MENU, (
                f"菜单序不符：\n实际 {names[:n]}\n期望 {EXPECTED_MENU}"
                f"\n（期望值由 app/psc 各页 PAGE_META + view/lib/shell.js 的 PLATFORM_PAGES 现算；"
                f"若确有新增页，菜单会多一项 —— 那种情况应改的是 **PAGE_META 的顺序**，不是这里）")

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

            # §5 VT-PERM-02 直访无授权 hash 路由回落菜单首项
            #   ⚠ 2026-09-17 订正：「菜单首项」现在是**平台页 AI管家**（shell.js 的
            #   `PLATFORM_PAGES` 里 workbench 带 `top: true`，排在全部业务页之前），
            #   不再是业务看板。`syncRoute` 回落的是 `menu[0]`，故期望值 = 现算的
            #   EXPECTED_MENU[0]（不写死中文名）。`view/lib/shell.js` 是**平台公共基座**
            #   （约定只 import 不改），所以按事实对齐断言，而不是去改平台。
            #   syncRoute 渲染回落页但**不回写 location.hash**，故断言渲染内容（header 标题）。
            step("perm-fallback")
            limited_page.evaluate("location.hash = '#/sales_forecast'")
            limited_page.wait_for_timeout(1200)
            header_txt = limited_page.locator("header.top h1").first.inner_text().strip()
            assert header_txt == EXPECTED_MENU[0], (
                f"受限直访 sales_forecast 应回落菜单首项 {EXPECTED_MENU[0]!r}，实际 {header_txt!r}")

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
            # **豁免也要受检**（2026-09-17 补）：`ignored` 收集了却从不校验，等于给「静默吞掉」
            # 开了口子 —— 任何新形态的 4xx/console error 都能混进来而不被任何人发现。
            # 这里逐条核对豁免理由：只认 favicon / sourcemap / 受限会话 403 三种，其余一律报出。
            for item in ignored:
                ok = ("/favicon.ico" in item or ".map" in item
                      or (item.startswith("HTTP 403") and "limited" in item.lower())
                      or "403" in item)
                assert ok, f"豁免理由不成立（既不是 favicon/.map，也不是受限会话 403）：{item!r}"
            if ignored:
                print(f"  · 本次豁免 {len(ignored)} 条（favicon/.map/受限 403）：{ignored[:3]}")

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
