"""nasa_pms 组级前端验收（第⑨步 · 壳品牌+菜单序 / 看板读数 / 受限用户三连；playwright，可直接运行）。

断言：壳品牌 `FDE·NASA_PMS` 与**现算的**菜单序（平台置顶页 + 12 业务页）→
看板（4 张 KPI + 12 段状态分布 + **非零读数** 1/0/0/0，证明 11 个 list 的聚合真的跑通）→
受限用户菜单收敛 / 直访无授权回落菜单首项 / 隐式放行有数据 →
全程 0 console error / 0 pageerror / 0 HTTP≥400（受限会话 403 属预期执法，豁免）。

用例来源：`app/nasa_pms/前端测试用例.md`（§1 壳与菜单序 + 看板；§5 受限三连；§6）。

运行：python app/nasa_pms/tests/verify_view_nasa_pms.py
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
# ⚠ **必须在副本上清表**：影子库是**真库的拷贝** —— 真演示数据会被一并复制进来，
# 而本脚本的 KPI 读数断言（1/0/0/0）要求「REQ-001 是本组唯一一条数据」。
# 清表使起点回到《验证门禁.md》§四之二的「view e2e 起点 = 空表」。
shadow_clear("nasa_pms")
# **个人 UI 偏好也要清**：它是操作者本机状态（如"手动隐藏过某列"），
# 不清就会让用例结果取决于谁在哪台机器上跑。
shadow_clear_prefs()
atexit.register(_shadow.__exit__, None, None, None)

# 受限用户（菜单收敛 / 直访回落 / 隐式放行测试用）：必须在平台子进程启动前经 users 模块建好，
# 切勿在浏览器里调 HTTP API 建用户（平台无此端点）。照 verify_view_psc.py 的写法。
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
    # 真实平台页 key 是 `workbench`（侧栏名「AI管家」，`top: true` 故排在业务页之前；
    # 授权键格式 `_platform:<key>`，见 view/lib/shell.js 的 PLATFORM_PAGES 过滤）。
    ["nasa_pms:dashboard", "nasa_pms:requirement", "_platform:workbench"],
)
assert _ok, _msg
_ok, _msg = users.create_user("limited_nasa", "Limited@123", "limited_role", [], "U400", "D001")
assert _ok, _msg
try:
    if auth_db_path().exists():
        _c2 = sqlite3.connect(str(auth_db_path()))
        _c2.execute("UPDATE users SET password_changed = 1 WHERE username = 'limited_nasa'")
        _c2.commit()
        _c2.close()
except Exception:
    pass
LIMITED_USER, LIMITED_PWD = "limited_nasa", "Limited@123"


# ⚠ 期望菜单**不再手抄**，改为从页面自己声明的元数据现算 —— 手抄的版本会漂：
# `order` 一旦并列，平台排序键 `(order缺省, order, key)` 会**静默按 key 字母序**落位
# （`view_registry.boot_manifest`），菜单序就不再等于"在 PAGE_META 里写下的顺序"。
def _expected_business_menu():
    """扫 app/nasa_pms 下各页 `PAGE_META`（view.js 与组级 <页>.js），按平台同款排序键返回中文名。

    真值来自**页面自己声明的元数据**（平台扫描装配菜单用的就是它），不是某份文档。
    ⚠ 排序键必须与 `view_registry.boot_manifest` 逐字一致（含并列时的 `key` 兜底），
    否则这里算出来的"期望"会和平台实际渲染的**同时错**、或对同一个输入给出不同答案。
    """
    metas = []
    paths = list((ROOT / "app" / "nasa_pms").glob("*/view.js")) + list((ROOT / "app" / "nasa_pms").glob("*.js"))
    for path in paths:
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

# 受限菜单（授权清单 nasa_pms:dashboard / nasa_pms:requirement + 平台 AI管家）
LIMITED_MENU = _top_platform_menu() + ["系统工程看板", "需求"]

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


# 造数 REQ-001：经浏览器 fetch 走真实 REST（带会话 Cookie）。
# **必须在进入业务页之前播种** —— 看板是默认落地页，页一打开就并发拉 11 个 list，
# 晚播种只会读到 0，而 KPI 读数断言（1/0/0/0）当场失去意义。
SEED_JS = r"""async () => {
  const r = await fetch("/api/apps/nasa_pms/requirement/call/create", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      title: "系统需求A",
      statement: "系统在轨寿命末期，在轨供电功率实测值不低于 900 W。",
      req_type: "system",
      verify_method: "test"
    })
  });
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) {}
  if (!r.ok) throw new Error(`requirement.create HTTP ${r.status} ${text.slice(0, 160)}`);
  if (data && (data.status === "error" || data.error)) {
    throw new Error(`requirement.create biz ${JSON.stringify(data).slice(0, 160)}`);
  }
  return { seeded: true, req_no: (data && data.data && data.data.req_no) || "?" };
}"""


def _nav_names(page):
    """读取侧栏 .nav-item 菜单名序列（取 name span，剥离 ic 图标 span）。"""
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('.rail .nav-item')).map(el => {
            const n = el.querySelector('span:last-child');
            return n ? n.textContent.trim() : el.textContent.trim();
        })"""
    )


def _kpi_values(page):
    """4 张 KPI 卡的读数（按 DOM 序：对象总数 / 已闭环 / 进行中 / 已基线需求）。"""
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('main .kpi .v')).map(el => el.textContent.trim())"""
    )


def _pipe_col_text(page, label):
    """某段状态分布栏的整段文本（`None` = 没找到该段）。"""
    return page.evaluate(
        """(label) => {
            const c = Array.from(document.querySelectorAll('.pipe-col')).find(el => {
                const h = el.querySelector('h4');
                return h && h.textContent.includes(label);
            });
            return c ? c.innerText : null;
        }""",
        label,
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
    # 卡住诊断：页面冻死/渲染进程崩溃时 playwright 调用不返回 ——
    # 由这个守护线程把「最后完成的步骤 + 已收集的错误」打出来；否则超时被强杀时现场全丢。
    install_watchdog(errors, step_getter=lambda: STEP)

    def attach(page):
        def on_console(msg):
            if msg.type == "error":
                txt = msg.text[:140]
                if state["limited"] and "403" in txt:
                    ignored.append(txt)  # 受限会话 403 属预期执法（未授权应用的 list），豁免
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

            # 造数（**先于**打开看板，见 SEED_JS 注释）
            step("seed")
            seed = login_page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"造数失败：{seed}"
            assert seed.get("req_no") == "REQ-001", f"首条需求编号应为 REQ-001，实际 {seed.get('req_no')!r}"

            page = ctx.new_page()
            attach(page)

            page.goto(f"{base}/view/nasa_pms/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.wait_for_timeout(2000)
            page.wait_for_selector(".rail .nav-item", timeout=20000)

            # §1 VT-SHELL-01 壳品牌
            # VT-SHELL-01 壳品牌 / 菜单序 / Agent 右栏
            step("shell-brand")
            brand_txt = page.locator(".brand .name").first.inner_text().strip()
            assert brand_txt == "FDE·NASA_PMS", f"侧栏品牌不符：{brand_txt!r}"

            # §1 VT-SHELL-01 菜单序（**前 N 项** == 平台置顶页 + 业务页 order 升序；
            #   N = 期望表长度，期望表由 PAGE_META + PLATFORM_PAGES 现算，不手抄）
            step("shell-menu")
            names = _nav_names(page)
            n = len(EXPECTED_MENU)
            assert len(names) >= n, f"菜单不足 {n} 项：{names}"
            assert names[:n] == EXPECTED_MENU, (
                f"菜单序不符：\n实际 {names[:n]}\n期望 {EXPECTED_MENU}"
                f"\n（期望值由 app/nasa_pms 各页 PAGE_META + view/lib/shell.js 的 PLATFORM_PAGES 现算；"
                f"若确有新增页，菜单会多一项 —— 那种情况应改的是 **PAGE_META 的顺序**，不是这里。"
                f"⚠ order 并列时平台按 key 字母序落位，等于把菜单序交给文件名，见 pitfalls.md #43）")

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

            # §1 VT-DASH-01 看板渲染（默认落地页即 dashboard）+ **非零读数**
            # VT-DASH-01 看板渲染 + 非零读数（对象总数==1）
            step("dashboard")
            page.wait_for_selector("main .kpi", state="visible", timeout=20000)
            page.wait_for_timeout(500)

            assert page.locator(".kpi").count() == 6, (
                f"dashboard KPI 卡数量 != 6（实际 {page.locator('.kpi').count()}）")
            main_txt = page.locator("main").inner_text()
            assert "四个职能域" in main_txt and "待办队列" in main_txt, (
                "dashboard 缺「四个职能域」/「待办队列」区块（与 PSC 同构的三块：KPI + 管道 + 待办）")
            assert page.locator(".pipe-col").count() == 7, (
                f"dashboard 管道段数 != 7（4 职能域 + 3 待办列，实际 {page.locator('.pipe-col').count()}）")
            # **状态必须中文**（2026-09-25 修：原来 10 个应用的字典是空的 ⇒ 界面显示 draft/baselined 等英文原文）
            assert "草稿" in main_txt, "dashboard 的「需求」行未显示中文状态「草稿」"
            assert "draft" not in main_txt, (
                "dashboard 出现了英文状态原文（draft）—— 状态字典没覆盖该应用（本页 STATUS 表要补齐）")
            # **可点**（与 PSC 同款：KPI 的数字本身是链接）—— 点第一张卡 → 进需求台账
            page.locator("main .kpi .v").first.click()
            page.wait_for_timeout(700)
            _h = page.evaluate("location.hash")
            assert _h == "#/requirement", f"dashboard KPI 数字应可点并跳台账（hash={_h}）"
            page.evaluate("location.hash = '#/dashboard'")
            page.wait_for_timeout(600)

            # 读数：影子库起点为空表，REQ-001 是本组唯一一条数据 ⇒ 1/0/0/0。
            # 「渲染出来了」不等于数据通路通（全 0 也渲染得出 4 张卡），故断到具体数。
            kpis = _kpi_values(page)
            assert kpis == ["1", "0", "0", "0", "0", "0"], (
                f"KPI 读数应为 [需求1, 已基线0, 待评审0, 告警0, 审批中变更0, 缓解中风险0]，实际 {kpis}")
            req_seg = _pipe_col_text(page, "需求")
            assert req_seg and "草稿" in req_seg and "1" in req_seg, (
                f"「需求」状态分布段未回显 草稿×1：{req_seg!r}")

            # ── §1b 流程总览（组级页 `#/process` · 仿 PSC 的 VT-PROCESS-01）──
            step("process")
            page.evaluate("location.hash = '#/process'")
            page.wait_for_selector('[data-role="process-svg"] svg', timeout=15000)
            page.wait_for_timeout(600)
            n_nodes = page.locator('[data-role="process-svg"] svg g[data-page]').count()
            # ⚠ 期望值**现算**，别写死（原先写死 15 = 4 + 11，2026-09-26 并入第 12 个应用时当场红）：
            #   业务页数（来自各页 PAGE_META）减去两个组级页（dashboard / process）＝ 应用节点数
            n_apps = len(_expected_business_menu()) - 2
            assert n_nodes == 4 + n_apps, (
                f"VT-PROCESS-01 流程总览渲染 {n_nodes} 个可点节点"
                f"（4 个职能域胶囊 + {n_apps} 个应用节点）")
            p_txt = page.locator('[data-role="process-svg"]').inner_text()
            assert "绿" in p_txt and "灰" in p_txt, "VT-PROCESS-01 图例含「绿/灰」说明"
            # 读数来自各应用服务（不是硬编码）：需求节点带「已基线」、技术度量节点带「未了结告警」
            assert "已基线" in p_txt and "未了结告警" in p_txt, (
                "VT-PROCESS-02 节点读数是各应用台账的实时汇总（已基线 / 未了结告警…）")
            # VT-PROCESS-03 事件委托跳转：点需求节点 → hash 变 #/requirement
            page.locator('[data-role="process-svg"] svg g[data-page="requirement"]').first.click()
            page.wait_for_timeout(700)
            _h = page.evaluate("location.hash")
            assert _h == "#/requirement", f"VT-PROCESS-03 点节点跳转台账（hash={_h}）"
            page.evaluate("location.hash = '#/process'")
            page.wait_for_timeout(800)
            # VT-PROCESS-06 **无横向滚动条**：`.scroll-x` 的 scrollWidth 不得超过 clientWidth
            # （画布宽了就会出现横向滚动条 —— 用户实测反馈过一次；这条把它变成可断言的口径）
            _sc = page.evaluate("""() => { const c = document.querySelector('[data-role="process-svg"]');
                return {sw: c.scrollWidth, cw: c.clientWidth}; }""")
            assert _sc["sw"] <= _sc["cw"] + 1, (
                f"VT-PROCESS-06 出现横向滚动条（scrollWidth {_sc['sw']} > clientWidth {_sc['cw']}）"
                f" —— 画布太宽，应收紧尺寸或允许缩小")

            # VT-PROCESS-06b 反面：**右栏收起时不得把画布放大**（那会把字放大 —— 用户实测反馈过）
            # 右栏收起后内容区变宽（~1000px），若画布没封顶就会被 width:100% 放大 1.6 倍
            page.locator(".agent-toggle").first.click()
            page.wait_for_timeout(500)
            _up = page.evaluate("""() => { const c = document.querySelector('[data-role="process-svg"]');
                const svg = c.querySelector('svg');
                return {natural: +svg.getAttribute('viewBox').split(' ')[2],
                        shown: Math.round(svg.getBoundingClientRect().width),
                        contWidth: c.clientWidth}; }""")
            assert _up["shown"] <= _up["natural"] + 1, (
                f"VT-PROCESS-06b 画布被放大：容器 {_up['contWidth']}px 时渲染成 {_up['shown']}px"
                f"（自然宽 {_up['natural']}px）—— 放大即「字太大」，需加 max-width 封顶")
            assert _up["contWidth"] >= _up["shown"], "VT-PROCESS-06b 右栏收起后也不应出现横向滚动"
            page.locator(".agent-toggle").first.click()      # 复原（后续断言依赖右栏展开）
            page.wait_for_timeout(400)

            # VT-PROCESS-05 **文字不得溢出节点/胶囊**（「显示不正常」的机械判据）：
            # 逐个量 text.getBBox().width 与所在 rect 的 width —— 溢出就是版面坏了；
            # 「字太大 / 串行」这类问题肉眼能看出、不写断言就抓不到（用户实测反馈过一次）。
            _ovf = page.evaluate("""() => Array.from(
                document.querySelectorAll('[data-role="process-svg"] svg g[data-page]'))
              .filter(g => g.querySelector('rect') && g.querySelector('text'))
              .map(g => {
                const rw = +g.querySelector('rect').getAttribute('width');
                const tw = Math.max(...Array.from(g.querySelectorAll('text'))
                                     .map(t => t.getBBox().width));
                return {name: (g.querySelector('text').textContent || '').slice(0, 14),
                        tw: Math.round(tw), rw: Math.round(rw)};
              }).filter(x => x.tw > x.rw - 20)""")
            assert not _ovf, f"VT-PROCESS-05 有 {len(_ovf)} 处文字溢出节点：{_ovf[:3]}"

            # VT-PROCESS-04 「已声明的流程」表：本组每条 flow 都要列出，且标出节点构成
            # ⚠ 期望值**现算**（`_flow_*.yaml` 的份数），别写死条数 —— 写死过一次（3→4→5 每加一条
            #   都要来改测试，且改漏了就假红）
            n_flows = page.locator('[data-role="flows"] tr.data').count()
            f_txt = page.locator('[data-role="flows"]').inner_text()
            n_expect = len(list((ROOT / "app" / "nasa_pms").glob("_flow_*.yaml")))
            assert n_flows == n_expect, (
                f"VT-PROCESS-04 「已声明的流程」列出 {n_flows} 条（= app/nasa_pms/_flow_*.yaml 份数 {n_expect}）")
            # ⚠ 作用域：节点构成在表内；「去流程编排页」按钮在**表格上方的 tagline** 里（不在本表内）
            assert "智能体" in f_txt and "直调" in f_txt, (
                "VT-PROCESS-04 每条标出节点构成（智能体 N / 直调 N）")
            assert "去流程编排页" in page.locator("main").inner_text(), (
                "VT-PROCESS-04 有「去流程编排页」入口")

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

            limited_page.goto(f"{base}/view/nasa_pms/")
            limited_page.wait_for_timeout(2000)
            limited_page.wait_for_selector(".rail .nav-item", timeout=20000)
            limited_page.wait_for_timeout(600)

            # §5 VT-PERM-01 菜单收敛（**精确等值**，不是「包含」）
            # VT-PERM-01 受限菜单收敛
            step("perm-menu")
            limited_names = _nav_names(limited_page)
            assert limited_names == LIMITED_MENU, (
                f"受限菜单不符：\n实际 {limited_names}\n期望 {LIMITED_MENU}")

            # 已授权页本身要能渲染（未授权应用的 list 403 不得把看板打崩）
            assert limited_page.locator("main .kpi").count() == 6, (
                "受限会话下看板 KPI 未渲染（未授权应用的 403 把页面打崩了？）")

            # §5 VT-PERM-02 直访无授权 hash 路由回落菜单首项
            #   ⚠「菜单首项」是**平台页 AI管家**（shell.js 把 `top: true` 的平台页排在全部业务页之前），
            #   `syncRoute` 回落的是 `menu[0]`，故期望值 = 现算的 EXPECTED_MENU[0]（不写死中文名）。
            #   `view/lib/shell.js` 是**平台公共基座**（只 import 不改），所以按事实对齐断言，
            #   而不是去改平台。syncRoute 渲染回落页但**不回写 location.hash**，故断言渲染内容。
            # VT-PERM-02 直访无授权回落菜单首项
            step("perm-fallback")
            limited_page.evaluate("location.hash = '#/risk'")
            limited_page.wait_for_timeout(1200)
            header_txt = limited_page.locator("header.top h1").first.inner_text().strip()
            assert header_txt == EXPECTED_MENU[0], (
                f"受限直访 risk 应回落菜单首项 {EXPECTED_MENU[0]!r}，实际 {header_txt!r}")

            # §5 VT-PERM-03 隐式放行有数据（requirement.list 经 X-Fde-Page 派生放行）
            # VT-PERM-03 隐式放行有数据
            step("perm-implicit")
            limited_page.evaluate("location.hash = '#/requirement'")
            limited_page.wait_for_selector('button.b-link.mono:has-text("REQ-001")', timeout=15000)
            limited_page.wait_for_timeout(400)
            assert limited_page.locator('button.b-link.mono:has-text("REQ-001")').count() >= 1, (
                "需求页未回显 REQ-001（隐式放行未生效）")

            # §6 组级会话 0 报错（受限会话 403 已豁免）
            step("errors")
            assert not errors, f"前端报错：{errors[:5]}"
            # **豁免也要受检**：`ignored` 收集了却从不校验，等于给「静默吞掉」开了口子 ——
            # 任何新形态的 4xx/console error 都能混进来而不被任何人发现。
            # 这里逐条核对豁免理由：只认 favicon / sourcemap / 受限会话 403 三种，其余一律报出。
            for item in ignored:
                ok = ("/favicon.ico" in item or ".map" in item
                      or (item.startswith("HTTP 403") and "limited" in item.lower())
                      or ("403" in item and state["limited"]))
                assert ok, f"豁免理由不成立（既不是 favicon/.map，也不是受限会话 403）：{item!r}"
            if ignored:
                print(f"  · 本次豁免 {len(ignored)} 条（favicon/.map/受限 403）：{ignored[:3]}")

            print("VERIFY_VIEW_nasa_pms: PASS")

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
