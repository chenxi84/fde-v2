"""e2e 前端验收范式（第⑨步 · 组级 + 逐应用切片；playwright，可直接运行）。

**本文件是范式样板**：第⑨步生成器把它当「范式全文」注入每个生成 job，所以它的形态 = 每个
生成脚本的形态。**组级脚本** = 范式段 A/B/D/E/F；**逐应用脚本** = 范式段 C 的按页切片。
每段都有 `═══ 范式段 X ═══` banner，可单独取用。

对 `e2e` 组**可直接运行**（它是本组的真实验收，不是伪代码）：

    断言：壳品牌与**现算的**菜单序 → 看板（4 张 KPI · 状态分布 · 与 KPI 同源对账）→
    逐应用切片（渲染防粘滞 → 造数 → 列表 → 详情模态全字段 → **表单落库** → **负例：被拒且不落库**）→
    流程总览（SVG 可点节点）→ 受限会话三连（菜单收敛 / 直访回落 / 隐式放行）→
    全程 0 console error / 0 pageerror / 0 HTTP≥400（受限会话 403 属预期执法，**豁免逐条受检**）。

运行：python design-plus/前端验收样板/verify_view_e2e.py

⚠ **三条纪律**（范式体现、生成的脚本必须照抄）
  1. **影子库**：`shadow_dbs(env=True, inprocess=False, config=True)` + `shadow_clear(<组>)`
     + `shadow_clear_prefs()` —— 真库零字节接触，**不用停 dev server**（《验证门禁.md》§四之二）。
     ⚠ 不要改回 `dbguard.isolate_dbs()`：那是「移库」，要求**先停服**、且并行会被锁拒绝；
     它现在是备用手段，不是默认。
  2. **期望值现算、不手抄**：菜单序从各页 `PAGE_META` + `shell.js` 的 `PLATFORM_PAGES` 现算，
     且**排序键与 `fde_platform/view_registry.boot_manifest` 逐字一致**（含并列时按 `key` 兜底 ——
     `order` 并列会让菜单序静默变成文件名字母序，见 pitfalls #43）。手抄的期望表会与实现**一起漂**。
  3. **豁免受检**：`ignored` 收集了就要逐条核对理由（只认 favicon / sourcemap / 受限会话 403），
     否则任何新形态的 4xx / console error 都能混进来而无人发现（PSC 2026-09-17 的教训）。
"""
import sqlite3
import os, pathlib, re, socket, subprocess, sys, time, http.client, atexit


def _project_root() -> pathlib.Path:
    """向上找项目根（含 fde_platform/ 的目录）。不用 parents[N] 定死层级——
    本范式会被照抄进不同深度的脚本（app/<组>/tests/、design-plus/…），按标记定位才稳。"""
    p = pathlib.Path(__file__).resolve().parent
    while not (p / "fde_platform").is_dir():
        if p.parent == p:
            raise RuntimeError("无法定位项目根目录（未找到 fde_platform/）")
        p = p.parent
    return p


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# ═══════════════ 基建段 · 隔离与受限用户播种（每个脚本原样照抄，只改组名）═══════════════

from fde_platform.shadowdb import shadow_dbs, shadow_clear, shadow_clear_prefs, auth_db_path  # noqa: E402
from fde_platform.view_watchdog import install_watchdog  # noqa: E402

# 影子库：业务库与平台库**都**复制到副本 → 真库零字节接触，**不用停 dev server**。
# config=True 是必需的：本脚本要播种 admin（写 config/auth.db），不影子化就会污染真库。
_shadow = shadow_dbs(env=True, inprocess=False, config=True)
_shadow.__enter__()
# ⚠ **必须在副本上清表**：影子库是**真库的拷贝** —— 真演示数据会被一起复制进来，
# 而本脚本自带的造数会撞主键。清表后起点 = 《验证门禁.md》§四之二的「view e2e 起点 = 空表」。
shadow_clear("e2e")
# **个人 UI 偏好也要清**：它是操作者本机状态（如"手动隐藏过某列"），
# 不清就会让用例结果取决于谁在哪台机器上跑。
shadow_clear_prefs()
atexit.register(_shadow.__exit__, None, None, None)

# 受限用户：必须在平台子进程启动前经 users 模块建好，**切勿在浏览器里调 HTTP API 建用户**
# （平台没有建用户端点 —— 老范式用浏览器 JS 去建，早就走不通了）。
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
    if auth_db_path().exists():
        _conn = sqlite3.connect(str(auth_db_path()))
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
    if auth_db_path().exists():
        _c2 = sqlite3.connect(str(auth_db_path()))
        _c2.execute("UPDATE users SET password_changed = 1 WHERE username = 'limited_e2e'")
        _c2.commit()
        _c2.close()
except Exception:
    pass
LIMITED_USER, LIMITED_PWD = "limited_e2e", "Limited@123"


# 期望菜单**从页面自己声明的元数据现算**，不手抄。真值来源 = 各页 `PAGE_META` + shell 的 `PLATFORM_PAGES`。
def _expected_business_menu():
    """按平台**同款排序键** `(order 缺省, order, key)` 返回业务页中文名。

    ⚠ 排序键必须与 `fde_platform/view_registry.boot_manifest` 逐字一致（含并列时的 `key` 兜底）：
    少了 `key` 那一层，`order` 并列时这里算的"期望"与平台实际渲染的会是两个不同答案。
    """
    metas = []
    for path in list((ROOT / "app" / "e2e").glob("*/view.js")) + list((ROOT / "app" / "e2e").glob("*.js")):
        text = path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"export const PAGE_META\s*=\s*\{(.*?)\};", text, re.S)
        if not m:
            continue
        body = m.group(1)
        name = re.search(r'name\s*:\s*"([^"]*)"', body)
        order = re.search(r"order\s*:\s*(\d+)", body)
        key = re.search(r'key\s*:\s*"([^"]*)"', body)
        if name and order and key:
            metas.append((False, int(order.group(1)), key.group(1), name.group(1)))
    metas.sort(key=lambda t: (t[0], t[1], t[2]))
    return [t[3] for t in metas]


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


# ═══════════════ 造数段 · 一律经浏览器 fetch 走真实 REST（带会话 Cookie）═══════════════
# 为什么在浏览器里造数：REST 信封 `{status:"ok", data:…}` 与 `_coerce` 的参数强转是**真实链路**的一部分
# （手写 sqlite 直插会绕过它，契约形状错了也测不出来）。
# ⚠ 造数必须在**断言之前**、且看板类页面要**绕一步路由再回来**才吃到新数据（见段 B 注释）。
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


# ═══════════════ 页面操作 helper（选择器纪律见 pitfalls #40：不用 `following::` 轴）═══════════════

def fill_field(scope, label, value):
    """按业务名填输入框：**属性定位优先**、标签兜底，三级都要求「唯一命中」。

    ⚠ 三级**都不用 `following::` 轴** —— 它是**文档序**轴、不受 `scope` 约束：标签文案恰好也
    出现在壳里（Agent 右栏 / 文件面板）时会抓到**壳里的全局输入框**，表现为
    `element is not visible` 超时（实测抓到 `#agent-rail-file`）。
    这里用到的 `following-sibling::` 与 `parent::` 都**留在 scope 内**。
    命中数 != 1 时报错并打印 scope 内可用字段，别让"填错了字段"伪装成"元素不可见"。
    """
    q = f'label[contains(normalize-space(.), "{label}")]'
    tiers = [
        # ① 标签文案本身出现在 placeholder 里（最稳：纯属性选择器）
        scope.locator(f'input[placeholder*="{label}"], textarea[placeholder*="{label}"]'),
        # ② 标签的**兄弟**元素（仍在 scope 内）
        scope.locator(f'xpath=.//{q}/following-sibling::input[1]'
                      f' | .//{q}/following-sibling::textarea[1]'
                      f' | .//{q}/following-sibling::*[1]//input[1]'),
        # ③ 标签的**父容器**内（最近的包裹层）
        scope.locator(f'xpath=.//{q}/parent::*//input[1] | .//{q}/parent::*//textarea[1]'),
    ]
    for loc in tiers:
        if loc.count() == 1:
            loc.first.fill(value)
            return
    diag = scope.locator("input, textarea").evaluate_all(
        "(els) => els.map(e => e.placeholder || e.getAttribute('x-model') || e.type).slice(0, 12)")
    raise AssertionError(f"未找到唯一输入字段：{label}（scope 内可用：{diag}）")


def choose_option(scope, label, value=None, text=None):
    """按业务名选下拉值：遍历 scope 内全部 `<select>`，选**含目标选项**的那个。

    ⚠ 不做「label 后第一个 select」的猜测（复杂表单里会命中相邻下拉）；`select` 遍历天然受 scope 约束。
    选不中时把各下拉的选项打出来 —— 下拉相关失败九成是"选项值变了"，而不是"没点到"。
    """
    sels = scope.locator("select")
    n = sels.count()
    if not n:
        raise AssertionError(f"未找到下拉：{label}")
    tried = []
    for i in range(n):
        sel = sels.nth(i)
        opts = sel.evaluate(
            "(el) => Array.from(el.options || []).map(o => ({v: o.value, t: o.textContent.trim()}))")
        tried.append(opts)
        if value is not None and any(o["v"] == value for o in opts):
            sel.select_option(value=value)
            return
        if text is not None and any(o["t"] == text for o in opts):
            sel.select_option(label=text)
            return
    raise AssertionError(f"下拉选择失败：{label} value={value} text={text}；scope 内各下拉={tried[:4]}")


def click_button(scope, texts):
    for t in texts:
        loc = scope.locator(f'button:has-text("{t}"), a:has-text("{t}"), .btn:has-text("{t}")')
        if loc.count():
            loc.first.click()
            return True
    raise AssertionError(f"未找到按钮：{texts}")


def open_modal(page):
    """等**可见**的模态并返回其中最后一个。

    页面可能同时挂多个 `.modal`（详情 + 创建），`.last` 直接取会拿到隐藏的那个。
    """
    page.locator(".modal:visible, [role='dialog']:visible").first.wait_for(state="visible", timeout=10000)
    return page.locator(".modal:visible, [role='dialog']:visible").last


def wait_modal(page, timeout=10000):
    """轮询可见模态的 `.loadbox` 消失（详情经异步 `get` 回填，须等加载完再读内容）。"""
    end = time.time() + timeout
    while time.time() < end:
        if page.locator(".modal-mask:visible .loadbox").count() == 0:
            return True
        page.wait_for_timeout(200)
    return True


def close_modal(page, modal):
    btn = modal.locator('button:has-text("关闭"), button:has-text("取消")')
    if btn.count():
        btn.first.click()
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

    state = {"limited": False}
    errors = []
    ignored = []
    # 卡住诊断：页面冻死/渲染进程崩溃时 playwright 调用不返回 ——
    # 由这个守护线程把「最后完成的步骤 + 已收集的错误」打出来；否则超时被强杀时现场全丢。
    install_watchdog(errors, step_getter=lambda: STEP)

    def attach(page):
        """三路报错收集。**豁免只在这里发生**，且理由必须窄到能被 `ignored` 复核（见段 F）。"""
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

            # ═══ 范式段 A · 壳与菜单序（组级）═══
            step("shell-brand")
            brand_txt = page.locator(".brand .name").first.inner_text().strip()
            assert brand_txt == "FDE·E2E", f"侧栏品牌不符：{brand_txt!r}"

            step("shell-menu")
            names = _nav_names(page)
            n = len(EXPECTED_MENU)
            assert len(names) >= n, f"菜单不足 {n} 项：{names}"
            assert names[:n] == EXPECTED_MENU, (
                f"菜单序不符：\n实际 {names[:n]}\n期望 {EXPECTED_MENU}"
                f"\n（期望值由 app/e2e 各页 PAGE_META + view/lib/shell.js 的 PLATFORM_PAGES 现算；"
                f"若确有新增页，菜单会多一项 —— 那种情况应改的是 PAGE_META 的顺序，不是这里。"
                f"⚠ order 并列时平台按 key 字母序落位，等于把菜单序交给文件名，见 pitfalls #43）")

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

            # 造数（看板非零断言 + 段 C 列表 + 受限会话隐式放行，三处共用）
            step("seed")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"造数失败：{seed}"

            # ═══ 范式段 B · 看板（组级）═══
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
            # **非零 + 同源对账**：造了 1 成员 + 3 任务（1 待办 / 1 进行中 / 1 已完成）
            # ⇒ 4 张 KPI 与 3 行状态分布**全部非零且互不相同**（0 再也蒙不对，"探测失败"与
            # "真的没有"由此可分）。逐项对账三张任务类 KPI 与状态分布计数 —— 两者同源于同一次
            # `task.list`，任何一侧读错形状都会在这里露出来。
            kpi_vals = [t.strip() for t in page.locator(".kpi .v").all_inner_texts()]
            assert kpi_vals == ["1", "3", "1", "1"], (
                f"看板 4 张 KPI 应为 [成员1, 任务3, 进行中1, 已完成1]，实际 {kpi_vals}"
                f"（任务侧恒 0 ⇒ 多为 `task.list` 返回形状与看板取值口径不一致）")
            right_mono = [t.strip() for t in page.locator(".pipe-col .right.mono").all_inner_texts()]
            assert len(right_mono) == 2, f"两个 .pipe-col 各应有一个 .right.mono，实际 {right_mono}"
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

            # ═══ 范式段 C · 逐应用切片（本例 member；逐应用脚本 = 本段的按页切片）═══
            # ① 渲染防粘滞：**非看板页 `.kpi` 必须为 0**（pitfalls #2 —— 页面切换不重建会残留看板）
            step("page-render")
            for key in ("member", "task"):
                page.evaluate(f"location.hash = '#/{key}'")
                page.wait_for_selector("main table, main .card", timeout=15000)
                page.wait_for_timeout(600)
                assert page.locator("main").inner_text().strip(), f"页面 {key} 无内容"
                assert page.locator("main .card, main .tbl, main table").count() > 0, f"页面 {key} 未渲染"
                assert page.locator(".kpi").count() == 0, f"页面 {key} 挂载未重建（残留看板）"

            # ② 列表：造数后**有数据**（行数断到具体值 —— "0 行"与"探测失败"必须可分）
            step("page-list")
            page.evaluate("location.hash = '#/member'")
            page.wait_for_selector('table.tbl tr.data:has-text("M001")', timeout=15000)
            page.wait_for_timeout(400)
            assert page.locator("table.tbl tr.data").count() == 1, \
                f"member 列表应有 1 行（造数 M001），实际 {page.locator('table.tbl tr.data').count()}"

            # ③ **表单落库**：UI 新建 M003（走完整链路：填表 → 提交 → 服务 → 列表回显）
            step("page-form-save")
            click_button(page, ["+ 新建成员", "新建成员", "创建成员"])
            modal = open_modal(page)
            fill_field(modal, "成员编号", "M003")
            fill_field(modal, "姓名", "王五")
            fill_field(modal, "邮箱", "wangwu@example.com")
            choose_option(modal, "角色", value="member")
            click_button(modal, ["创建", "保存", "提交"])
            page.wait_for_selector('table.tbl tr.data:has-text("M003")', timeout=10000)
            page.wait_for_timeout(400)
            assert page.locator("table.tbl tr.data").count() == 2, \
                f"新建 M003 后应有 2 行，实际 {page.locator('table.tbl tr.data').count()}"

            # ④ 详情模态**全字段**（详情经异步 `get` 回填 ⇒ 先等 `.loadbox` 消失再读）
            step("page-detail")
            page.locator('table.tbl tr.data:has-text("M003") button.b-link').first.click()
            modal = open_modal(page)
            wait_modal(page)
            txt = modal.inner_text()
            for expected in ("M003", "王五", "wangwu@example.com", "成员"):
                assert expected in txt, f"member 详情模态缺字段：{expected}"
            close_modal(page, modal)

            # ⑤ **负例**：业务失败被拒 ⇒ 列表**不增** + 模态**保持打开**（便于改后重试）
            #    业务失败是 HTTP 200 + `{status:"error"}`（`FdeError` 不返 4xx），所以它
            #    **不触** 0 报错红线，但也**不能**只看"没报错"就算过 —— 必须断言副作用没发生。
            step("page-negative")
            before = page.locator("table.tbl tr.data").count()
            click_button(page, ["+ 新建成员", "新建成员", "创建成员"])
            modal = open_modal(page)
            fill_field(modal, "成员编号", "M003")          # 重复编号
            fill_field(modal, "姓名", "重复样本")
            fill_field(modal, "邮箱", "dup@example.com")
            choose_option(modal, "角色", value="member")
            click_button(modal, ["创建", "保存", "提交"])
            page.wait_for_timeout(900)
            assert page.locator("table.tbl tr.data").count() == before, \
                "重复成员编号竟然落库了（唯一性约束未生效）"
            assert modal.is_visible(), "被拒后创建模态应保持打开（api.js 已 toast，便于改后重试）"
            close_modal(page, modal)

            # ═══ 范式段 D · 组级聚合页（本例流程总览：数据驱动 SVG）═══
            step("process")
            page.evaluate("location.hash = '#/process'")
            page.wait_for_selector("main svg g[data-page]", timeout=15000)
            page.wait_for_timeout(300)
            assert page.locator("main svg g[data-page]").count() == 8, \
                f"流程总览应有 3 阶段 + 5 步骤 = 8 个可点节点（实际 {page.locator('main svg g[data-page]').count()}）"
            assert "点击节点进入对应页面" in page.locator("main").inner_text(), "流程总览缺图例说明"

            # ═══ 范式段 E · 受限会话三连（组级）═══
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

            # §5 VT-PERM-01 菜单收敛（**精确等值**，不是「包含」）
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

            # §5 VT-PERM-03 隐式放行有数据（member.list 经 X-Fde-Page 派生放行，无需个人特授服务）
            step("perm-implicit")
            limited_page.evaluate("location.hash = '#/member'")
            limited_page.wait_for_selector('button.b-link.mono:has-text("M001")', timeout=15000)
            limited_page.wait_for_timeout(400)
            assert limited_page.locator('button.b-link.mono:has-text("M001")').count() >= 1, \
                "member 页未回显 M001（隐式放行未生效）"

            # ═══ 范式段 F · 0 报错红线（全会话）═══
            step("errors")
            assert not errors, f"前端报错：{errors[:5]}"
            # **豁免也要受检**：`ignored` 收集了却从不校验，等于给「静默吞掉」开了口子 ——
            # 任何新形态的 4xx / console error 都能混进来而不被任何人发现。逐条核对豁免理由。
            for item in ignored:
                ok = ("/favicon.ico" in item or ".map" in item
                      or (item.startswith("HTTP 403") and "limited" in item.lower())
                      or ("403" in item and state["limited"]))
                assert ok, f"豁免理由不成立（既不是 favicon/.map，也不是受限会话 403）：{item!r}"
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
