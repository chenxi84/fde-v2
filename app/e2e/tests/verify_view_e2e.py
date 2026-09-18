"""e2e 组级前端验收（第⑨步 · 壳 / 菜单序 / 首页看板 / 流程总览 / 受限用户；playwright，可直接运行）。

断言：壳品牌与**现算的**菜单序（平台置顶页 + 4 业务页）→ 首页看板（4 张 KPI + 2 段状态分布，
且造数后成员总数 == 1、两处同源同值）→ 流程总览（svg g[data-page] == 8）→ 受限用户菜单收敛 /
直访无授权回落菜单首项 / 隐式放行有数据 → 全程 0 console error / 0 pageerror / 0 HTTP≥400
（受限会话 403 属预期执法，豁免；**豁免清单逐条受检并打印**）。

用例来源：`app/e2e/前端测试用例.md`（§1 壳与菜单序 / 看板 / 流程总览 + §5 受限三连 + §6）。
运行：python app/e2e/tests/verify_view_e2e.py      （影子库隔离，真库零接触，**不用停 dev server**）
"""
import sqlite3
import os, pathlib, re, socket, subprocess, sys, time, http.client, atexit


def _project_root() -> pathlib.Path:
    """向上找项目根（含 fde_platform/ 的目录）。不用 parents[N] 定死层级。"""
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
shadow_clear("e2e")
# **个人 UI 偏好也要清**：它是操作者本机状态（如"手动隐藏过某列"），
# 不清就会让用例结果取决于谁在哪台机器上跑（实测：真库里藏了 sales_forecast 的两列）。
shadow_clear_prefs()
atexit.register(_shadow.__exit__, None, None, None)

# 受限用户：必须在平台子进程启动前经 users 模块建好（平台无建用户端点）。
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
_ok, _msg = users.create_role("limited_role", "受限测试角色")
assert _ok, _msg
_ok, _msg = users.set_role_page_grants(
    "limited_role",
    # 授权键格式 `_platform:<key>`；平台置顶页的 key 是 `workbench`（侧栏名「AI管家」）——
    # **不是** `agent` / `agent_overview`（那两个全仓都不存在，PSC 那边踩过）。
    ["e2e:dashboard", "e2e:member", "_platform:workbench"],
)
assert _ok, _msg
_ok, _msg = users.create_user("limited_e2e", "Limited@123", "limited_role", [], "U500", "D001")
assert _ok, _msg
try:
    if (auth_db_path()).exists():
        _c2 = sqlite3.connect(str(auth_db_path()))
        _c2.execute("UPDATE users SET password_changed = 1 WHERE username = 'limited_e2e'")
        _c2.commit()
        _c2.close()
except Exception:
    pass
LIMITED_USER, LIMITED_PWD = "limited_e2e", "Limited@123"


# 期望菜单**从页面自己声明的元数据现算**，不手抄（手抄会漂：PSC 那份漂了三处，
# 组级脚本因此一直红着）。真值来源 = 各页 `PAGE_META.order` + shell 的 `PLATFORM_PAGES`。
def _expected_business_menu():
    metas = []
    for path in list((ROOT / "app" / "e2e").glob("*/view.js")) + list((ROOT / "app" / "e2e").glob("*.js")):
        text = path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"export const PAGE_META\s*=\s*\{(.*?)\};", text, re.S)
        if not m:
            continue
        body = m.group(1)
        name = re.search(r'name\s*:\s*"([^"]*)"', body)
        order = re.search(r"order\s*:\s*(\d+)", body)
        if name and order:
            metas.append((int(order.group(1)), name.group(1)))
    return [n for _o, n in sorted(metas)]


def _top_platform_menu():
    """排在业务页**之前**的平台页名（`PLATFORM_PAGES` 里 `top: true` 且非 hidden）。"""
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
LIMITED_MENU = _top_platform_menu() + ["首页看板", "成员管理"]

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


# 造数（受限会话 VT-PERM-03 隐式放行断言 + 看板 KPI 非零断言，两者共用）：
# 经浏览器 fetch 走真实 REST（带会话 Cookie，pitfalls #18）。REST 信封是 `{status:"ok", data:…}`。
# ⚠ 2026-09-18 起**必须同时造任务**：看板 4 张 KPI 里 3 张（任务总数/进行中/已完成）与 3 行状态
# 分布都来自 `task.list`。此前只造成员，任务侧全 0 —— 而 `task.list` 当时无参返回**裸 list**，
# 看板按 `{total, items}` 取值恒定读成 0，**两边都是 0 于是断言恒真**，真缺陷被放行了一整轮。
# 现在造 1 待办 + 1 进行中 + 1 已完成，让任务侧断言**非零且可区分**（0 不再能蒙对）。
SEED_JS = r"""async () => {
  const post = async (app, svc, body) => {
    const r = await fetch(`/api/apps/e2e/${app}/call/${svc}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)
    });
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) {}
    if (!r.ok) throw new Error(`${app}.${svc} HTTP ${r.status} ${text.slice(0, 160)}`);
    if (!data || data.status !== "ok") {
      throw new Error(`${app}.${svc} biz ${JSON.stringify(data).slice(0, 160)}`);
    }
    return data.data;
  };
  await post("member", "create", {
    member_no: "M001", name: "张管理", email: "m001@example.com", role: "admin"
  });
  await post("task", "create", {
    title: "待办样本", assignee_member_no: "M001", priority: "low"
  });
  const doing = await post("task", "create", {
    title: "进行中样本", assignee_member_no: "M001", priority: "high"
  });
  await post("task", "start", {task_no: doing.task_no});
  const done = await post("task", "create", {
    title: "已完成样本", assignee_member_no: "M001", priority: "high"
  });
  await post("task", "start", {task_no: done.task_no});
  await post("task", "complete", {task_no: done.task_no});
  return {seeded: true, member_no: "M001", tasks: 3, doing: 1, done: 1};
}"""


def _nav_names(page):
    """读取侧栏 `.nav-item` 菜单名序列（取 name span，剥离 ic 图标 span）。"""
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
                    ignored.append(txt)          # 受限会话 403 属预期执法，豁免
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

            page.goto(f"{base}/view/e2e/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.wait_for_timeout(1500)
            page.wait_for_selector(".rail .nav-item", timeout=20000)

            # §1 VT-SHELL-01 壳品牌
            step("shell-brand")
            brand_txt = page.locator(".brand .name").first.inner_text().strip()
            assert brand_txt == "FDE·E2E", f"侧栏品牌不符：{brand_txt!r}"

            # §1 VT-SHELL-01 菜单序（**前 N 项** == 平台置顶页 + 业务页 order 升序；N 由现算的期望表长度定）
            step("shell-menu")
            names = _nav_names(page)
            n = len(EXPECTED_MENU)
            assert len(names) >= n, f"菜单不足 {n} 项：{names}"
            assert names[:n] == EXPECTED_MENU, (
                f"菜单序不符：\n实际 {names[:n]}\n期望 {EXPECTED_MENU}"
                f"\n（期望值由 app/e2e 各页 PAGE_META + view/lib/shell.js 的 PLATFORM_PAGES 现算；"
                f"若确有新增页，菜单会多一项 —— 那种情况应改的是 PAGE_META 的顺序，不是这里）")

            # 造数 M001（看板 KPI 非零断言 + 受限会话 VT-PERM-03 共用）
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"造数失败：{seed}"

            # §1 VT-DASH-01 首页看板渲染（默认落地页；先等 loading 结束）
            step("dashboard")
            # ⚠ 必须**绕一步路由再回来**：看板是默认落地页，它的 `init()` 在**造数之前**就跑完了，
            # 此时再 `location.hash = '#/dashboard'` 等于**没有路由变化** ⇒ 不会重挂载 ⇒ KPI 停在 0。
            # 绕一步（#/member → #/dashboard）强制它重新 init，顺便也验了"切页重挂载"。
            page.evaluate("location.hash = '#/member'")
            page.wait_for_timeout(400)
            page.evaluate("location.hash = '#/dashboard'")
            page.wait_for_selector("main .kpi", state="visible", timeout=20000)
            page.wait_for_timeout(600)
            assert page.locator(".kpi").count() == 4, \
                f"看板 KPI 卡数量 != 4（实际 {page.locator('.kpi').count()}）"
            main_txt = page.locator("main").inner_text()
            assert "任务状态分布" in main_txt, "看板缺「任务状态分布」区块"
            assert page.locator(".pipe-col").count() == 2, \
                f"看板通道段数 != 2（实际 {page.locator('.pipe-col').count()}）"
            for st in ["待办", "进行中", "已完成"]:
                assert st in main_txt, f"状态分布缺徽章：{st}"
            # **非零断言 + 同源对账**：造了 1 成员 + 3 任务（1 待办 / 1 进行中 / 1 已完成）
            # ⇒ 4 张 KPI 与 3 行状态分布**全部非零且互不相同**（0 再也蒙不对，"探测失败"与
            # "真的没有"由此可分）。逐项对账三张任务类 KPI 与状态分布计数 —— 两者同源于
            # 同一次 `task.list`，任何一侧读错形状都会在这里露出来。
            kpi_vals = [t.strip() for t in page.locator(".kpi .v").all_inner_texts()]
            assert kpi_vals == ["1", "3", "1", "1"], (
                f"看板 4 张 KPI 应为 [成员1, 任务3, 进行中1, 已完成1]，实际 {kpi_vals}"
                f"（任务侧恒 0 ⇒ 多为 `task.list` 返回形状与看板取值口径不一致）")
            right_mono = [t.strip() for t in page.locator(".pipe-col .right.mono").all_inner_texts()]
            assert len(right_mono) == 2, f"两个 .pipe-col 各应有一个 .right.mono，实际 {right_mono}"
            # 第一个 .right.mono 在「任务 · 按状态」列头上（第二个在「成员主数据」列头上，见 dashboard.html）
            assert right_mono == [kpi_vals[1], kpi_vals[0]], (
                f"状态分布两列右上角应与 KPI 同源同值：任务列={right_mono[0]}/KPI={kpi_vals[1]}、"
                f"成员列={right_mono[1]}/KPI={kpi_vals[0]}")
            dist = [t.strip() for t in
                    page.locator(".pipe-col").first.locator(".sline b").all_inner_texts()]
            assert dist == ["1", "1", "1"], \
                f"状态分布（待办/进行中/已完成）应各 1，实际 {dist}"
            assert int(dist[1]) == int(kpi_vals[2]) and int(dist[2]) == int(kpi_vals[3]), \
                f"状态分布计数应与 KPI 同源：进行中 {dist[1]} vs {kpi_vals[2]}、已完成 {dist[2]} vs {kpi_vals[3]}"
            assert sum(int(x) for x in dist) == int(kpi_vals[1]), \
                f"三行状态计数之和应等于任务总数：{sum(int(x) for x in dist)} vs {kpi_vals[1]}"

            # §1 VT-PROCESS-01 流程总览（数据驱动 SVG：3 阶段胶囊 + 5 步骤节点 = 8 个可点节点）
            step("process")
            page.evaluate("location.hash = '#/process'")
            page.wait_for_selector("main svg g[data-page]", timeout=15000)
            page.wait_for_timeout(300)
            assert page.locator("main svg g[data-page]").count() == 8, \
                f"流程总览应有 3 阶段 + 5 步骤 = 8 个可点节点（实际 {page.locator('main svg g[data-page]').count()}）"
            proc_txt = page.locator("main").inner_text()
            assert "点击节点进入对应页面" in proc_txt, "流程总览缺图例说明"

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

            limited_page.goto(f"{base}/view/e2e/")
            limited_page.wait_for_timeout(2000)
            limited_page.wait_for_selector(".rail .nav-item", timeout=20000)
            limited_page.wait_for_timeout(600)

            # §5 VT-PERM-01 菜单收敛
            step("perm-menu")
            limited_names = _nav_names(limited_page)
            assert limited_names == LIMITED_MENU, (
                f"受限菜单不符：\n实际 {limited_names}\n期望 {LIMITED_MENU}")

            # §5 VT-PERM-02 直访无授权 hash 路由回落**菜单首项**
            #   ⚠ 「菜单首项」是平台置顶页「AI管家」（shell.js 把 top:true 的平台页排在业务页之前），
            #   不是看板；`syncRoute` 回落的是 `menu[0]`，故期望值 = 现算的 EXPECTED_MENU[0]。
            #   `view/lib/shell.js` 是平台公共基座（约定只 import 不改），所以按事实对齐断言。
            step("perm-fallback")
            limited_page.evaluate("location.hash = '#/task'")
            limited_page.wait_for_timeout(1200)
            header_txt = limited_page.locator("header.top h1").first.inner_text().strip()
            assert header_txt == EXPECTED_MENU[0], (
                f"受限直访 task 应回落菜单首项 {EXPECTED_MENU[0]!r}，实际 {header_txt!r}")

            # §5 VT-PERM-03 隐式放行有数据（member.list 经 X-Fde-Page 派生放行）
            step("perm-implicit")
            limited_page.evaluate("location.hash = '#/member'")
            limited_page.wait_for_selector('button.b-link.mono:has-text("M001")', timeout=15000)
            limited_page.wait_for_timeout(400)
            assert limited_page.locator('button.b-link.mono:has-text("M001")').count() >= 1, \
                "member 页未回显 M001（隐式放行未生效）"

            # §6 VT-ERR-01 0 报错（受限会话 403 已豁免）
            step("errors")
            assert not errors, f"前端报错：{errors[:5]}"
            # **豁免也要受检**：只认 favicon / sourcemap / 受限会话 403，其余一律报出
            for item in ignored:
                ok = ("/favicon.ico" in item or ".map" in item or "403" in item)
                assert ok, f"豁免理由不成立（既不是 favicon/.map，也不是 403）：{item!r}"
            if ignored:
                print(f"  · 本次豁免 {len(ignored)} 条（favicon/.map/受限 403）：{ignored[:3]}")

            print("VERIFY_VIEW_e2e: PASS")

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
