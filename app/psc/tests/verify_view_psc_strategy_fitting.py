"""e2e 前端验收 - psc:strategy_fitting（策略拟合 · 滚动回测拟合最优方法参数）
断言：本页路由渲染防粘滞（.kpi==0）→ 造数后列表三态全显（7 条）→ 详情模态全字段
→ 表单落库回显（run / run_batch）+ 状态机操作（待复核→已生效/已否决；已生效→rollback 已否决）
→ 全程 0 console error / 0 pageerror / 0 HTTP≥400。
运行：python app/psc/tests/verify_view_psc_strategy_fitting.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit


def _project_root() -> pathlib.Path:
    """向上找项目根（含 fde_platform/ 的目录），按标记定位才稳（落点深度不固定）。"""
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

# admin 账号：必须在平台子进程启动前经 users 模块建好，切勿在浏览器里调 HTTP API 建。
from fde_platform import users  # noqa: E402
users.init_schema()
users.seed_admin()

# 首次登录强制改密（password_changed=0）绕过：把 admin 标记为已改密，否则登录后会被
# 重定向到 /change-password，无法进入视图。auth.db 已在**副本**上（影子库），此改动仅作用测试副本、真库不受影响。
import sqlite3  # noqa: E402

# 输出编码：控制台代码页在本机默认是 GBK，而断言文案里有 ⇒ / ✓ / ✗ / ⚠ / − 这类**非 GBK 码位** ——
# 不钉住编码的话，print 自己会抛 UnicodeEncodeError（**崩在打印结果那一步**：断言算完了却报不出来，
# 其后用例也不再执行 —— 实测 nasa_pms 的 stakeholder 脚本里有一条断言就这么"消失"过）。与 scripts/run_gates.py 给
# 子进程设 PYTHONIOENCODING 同一根因；由 scripts/verify_test_script_encoding.py 守住别忘这一行。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    auth_db = auth_db_path()
    if auth_db.exists():
        conn = sqlite3.connect(str(auth_db))
        conn.execute("UPDATE users SET password_changed = 1 WHERE username = 'admin'")
        conn.commit()
        conn.close()
except Exception:
    pass


STEP = ""


def step(name):
    global STEP
    STEP = name
    print(f"  → {name}", flush=True)


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
    if (data && data.status === "error") {
      throw new Error(`${app}.${svc} biz ${(data.message || "").slice(0, 160)}`);
    }
    return data && data.data !== undefined ? data.data : data;
  };

  // 跨应用前置：物料主数据（正常状态，供 run/run_batch 校验与 autocomplete）
  // ⚠ 2026-09-17 口径：**组批窗口与满足率目标由物料主数据人工维护**（拟合不再自动运算、也不覆盖），
  //    所以造数里要**像计划员那样把它们维护上** —— 否则拟合记录里这两个值是空的、详情模态显示「—」。
  await call("md_material", "create", {
    material_no: "M1", material_name: "移动平均物料A", status: "正常", base_method: "移动平均",
    batch_window: 28, service_level: 0.95
  });
  await call("md_material", "create", {
    material_no: "M2", material_name: "移动平均物料B", status: "正常", base_method: "移动平均",
    batch_window: 28, service_level: 0.95
  });

  // 客户 + 历史台账（24 期常规趋势+季节，供 statsforecast 出真实拟合、abnormal_flag=false）
  await call("md_customer", "create", { customer_no: "C001", customer_name: "客户A" });
  const seedHist = async (matNo, base) => {
    const rows = [];
    for (let i = 0; i < 24; i++) {
      const yy = 2024 + Math.floor(i / 12);
      const mm = (i % 12) + 1;
      const period = `${yy}-${String(mm).padStart(2, "0")}`;
      const qty = Math.round(base + i * 2 + 18 * Math.sin(i * 2 * Math.PI / 12));
      rows.push({ material_no: matNo, customer_no: "C001", period, qty });
    }
    await call("sales_history", "import_batch", { rows });
  };
  await seedHist("M1", 100);
  await seedHist("M2", 120);

  // SF1 M1@202608 待复核（§2/§3 目标）
  await call("strategy_fitting", "run", { material_no: "M1", fit_version: "202608" });
  // SF2 M1@202607 已生效
  await call("strategy_fitting", "run", { material_no: "M1", fit_version: "202607" });
  await call("strategy_fitting", "approve", { material_no: "M1", fit_version: "202607" });
  // SF3 M1@202606 已否决
  await call("strategy_fitting", "run", { material_no: "M1", fit_version: "202606" });
  await call("strategy_fitting", "reject", { material_no: "M1", fit_version: "202606" });
  // SF4 M2@202608 待复核（§4 approve 用）
  await call("strategy_fitting", "run", { material_no: "M2", fit_version: "202608" });
  // SF5 M2@202607 待复核（§4 reject 用）
  await call("strategy_fitting", "run", { material_no: "M2", fit_version: "202607" });
  // SF6 M2@202606 已生效（§4 rollback 用）
  await call("strategy_fitting", "run", { material_no: "M2", fit_version: "202606" });
  await call("strategy_fitting", "approve", { material_no: "M2", fit_version: "202606" });
  // SF7 M2@202605 已生效（rollback 回填上一版目标，BR-15）
  await call("strategy_fitting", "run", { material_no: "M2", fit_version: "202605" });
  await call("strategy_fitting", "approve", { material_no: "M2", fit_version: "202605" });

  return { seeded: true };
}"""


def fill_labeled(scope, label, value, tags=("input", "textarea")):
    for tag in tags:
        loc = scope.locator(
            f'xpath=.//label[contains(normalize-space(.), "{label}")]/following::{tag}[1]'
        )
        if loc.count():
            loc.first.fill(value)
            return

    for tag in tags:
        loc = scope.locator(
            f'xpath=.//*[contains(normalize-space(.), "{label}")]/ancestor::*'
            f'[contains(@class,"field") or contains(@class,"frow") or contains(@class,"form-row") '
            f'or contains(@class,"fv") or contains(@class,"filter") or contains(@class,"grid")][1]//{tag}'
        )
        if loc.count():
            loc.first.fill(value)
            return

    loc = scope.locator(f'input[placeholder*="{label}"], textarea[placeholder*="{label}"]')
    if loc.count():
        loc.first.fill(value)
        return

    raise AssertionError(f"未找到输入字段：{label}")


def click_button(scope, texts):
    for t in texts:
        loc = scope.locator(f'button:visible:has-text("{t}"), a:visible:has-text("{t}")')
        if loc.count():
            loc.first.click()
            return True
    raise AssertionError(f"未找到按钮：{texts}")


def click_chip(page, text):
    chip = page.locator(f'.fchip:visible:has-text("{text}")').first
    chip.wait_for(state="visible", timeout=5000)
    chip.click()
    page.wait_for_timeout(400)


def pick_autocomplete(page, modal, material_no):
    """发起拟合表单的物料号内联 autocomplete：只点击输入框展开面板（@focus→matOpen=true，
    matQuery 空 → matFiltered 返回全部），再点匹配选项（照 md_project_part PASS 范式）。"""
    page.wait_for_timeout(300)
    inp = modal.locator('input[placeholder*="搜索物料号"]').first
    inp.click()
    page.wait_for_timeout(500)
    opt = modal.locator(f'div.mono:has-text("{material_no}"), span.mono:has-text("{material_no}")').first
    opt.wait_for(state="visible", timeout=8000)
    opt.click()
    page.wait_for_timeout(200)


def wait_modal(page, timeout=10000):
    """等可见模态 + 轮询 .loadbox 消失（详情模态载入明细），返回可见模态（多模态取 last）。"""
    page.locator(".modal:visible").first.wait_for(state="visible", timeout=timeout)
    end = time.time() + timeout
    while time.time() < end:
        if page.locator(".modal-mask:visible .loadbox:visible").count() == 0:
            break
        page.wait_for_timeout(100)
    page.wait_for_timeout(200)
    return page.locator(".modal:visible").last


def close_modal(page, modal):
    x = modal.locator("button.x")
    if x.count():
        x.first.click()
    else:
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


def assert_toast(page, text, kind=None, timeout=6000):
    """断言 toast 出现（可选按 kind=warn/err 区分前端警告与后端 FdeError）。"""
    end = time.time() + timeout
    seen = []
    while time.time() < end:
        toasts = page.locator(".toast:visible")
        n = toasts.count()
        for i in range(n):
            t = toasts.nth(i)
            try:
                msg = t.inner_text()
                cls = t.get_attribute("class") or ""
            except Exception:
                continue
            seen.append(f"{cls}::{msg}")
            if text in msg:
                if kind is None:
                    return True
                if kind == "warn" and "warn" in cls:
                    return True
                if kind == "err" and "err" in cls:
                    return True
        page.wait_for_timeout(100)
    raise AssertionError(f"未见 toast 含『{text}』(kind={kind})，实际：{seen[-8:]}")


def find_row(page, material_no, fit_version):
    """按复合主键（fit_version+material_no）定位列表数据行。"""
    return page.locator("table.tbl.tight tr.data").filter(has_text=fit_version).filter(has_text=material_no)


def assert_rows_all_status(page, status):
    rows = page.locator("table.tbl.tight tr.data")
    n = rows.count()
    assert n >= 1, f"筛选后无数据行（{status}）"
    for i in range(n):
        txt = rows.nth(i).inner_text()
        assert status in txt, f"筛选 {status} 后混入非 {status} 行：{txt[:100]}"


def wait_status(page, material_no, fit_version, status, timeout=8000):
    """状态机动作后轮询该行 status 徽章变化（列表异步重载）。"""
    end = time.time() + timeout
    while time.time() < end:
        r = find_row(page, material_no, fit_version)
        if r.count() and status in r.first.inner_text():
            return r.first
        page.wait_for_timeout(200)
    raise AssertionError(f"{material_no}@{fit_version} 未在 {timeout}ms 内变为 {status}")


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
        def on_console(msg):
            if msg.type == "error":
                errors.append(msg.text[:140])

        def on_pageerror(err):
            errors.append(str(err)[:140])

        def on_response(resp):
            if resp.status >= 400:
                url = resp.url
                if "/favicon.ico" in url or url.endswith(".map"):
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

            # ===================== §1 本页渲染（防粘滞）=====================
            # VT-ROUTE-01 路由渲染 + 三段式挂载（.kpi==0 防粘滞）
            step("§1 本页路由渲染 + 三段式挂载（防粘滞）")
            page.evaluate("location.hash = '#/strategy_fitting'")
            try:
                page.wait_for_selector("main .card", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator("main").inner_text().strip(), "strategy_fitting 页面无内容"
            assert page.locator("main .card").count() > 0, "strategy_fitting 未渲染 card"
            assert page.locator(".kpi").count() == 0, "strategy_fitting 挂载未重建（残留看板）"
            # 过滤条三段式
            assert page.locator(".fchip").count() >= 4, "状态 chips 不全（全部/待复核/已生效/已否决）"
            assert page.locator('input[placeholder*="模糊"]').count() == 1, "物料号过滤输入框缺失"
            assert page.locator('input[placeholder*="版本"]').count() == 1, "版本过滤输入框缺失"
            assert page.locator("select").count() >= 1, "异常标记下拉缺失"
            assert page.locator('button:visible:has-text("＋ 发起拟合"), button:visible:has-text("发起拟合")').count() >= 1, "发起拟合按钮缺失"
            assert page.locator('button:visible:has-text("批量拟合")').count() >= 1, "批量拟合按钮缺失"
            assert page.locator("table.tbl.tight").count() >= 1, "表格 .tbl.tight 缺失"
            main_txt = page.locator("main").inner_text()
            assert ("共" in main_txt) and ("条" in main_txt), "分页条缺失（共 N 条）"

            # ===================== §0 造数 =====================
            step("§0 造数（md_material + strategy_fitting run/approve/reject）")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"strategy_fitting 造数失败：{seed}"

            # 列表在 init 时已空载，需重载拿到 7 条
            step("§2 列表重载（拿 7 条）")
            page.reload()
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.evaluate("location.hash = '#/strategy_fitting'")
            page.wait_for_selector("table.tbl.tight tr.data", timeout=15000)
            page.wait_for_timeout(500)
            # 前置步计数断言（**无对应用例**）：§0 造的是 SF1–SF7 共 7 条，后面每一步（含「共 7 条」
            # 分页条、三态全显）都以此为前提 —— 这里先钉死，失败时才指向「造数/重载」而不是被
            # 后续某个用例的错误文案带偏。
            page.wait_for_function(
                "document.querySelectorAll('table.tbl.tight tr.data').length === 7", timeout=15000
            )
            assert page.locator("table.tbl.tight tr.data").count() == 7, (
                f"重载后应恰 7 条（SF1–SF7），实际 {page.locator('table.tbl.tight tr.data').count()}"
            )

            # ===================== §2 造数后列表有数据 =====================
            step("§2 VT-LIST-01 列表含所造单号（三态全显）")
            assert page.locator("table.tbl.tight tr.data").count() == 7, \
                f"列表应 7 条，实际 {page.locator('table.tbl.tight tr.data').count()}"
            assert "共 7 条" in page.locator("main").inner_text(), "分页条未显示共 7 条"
            sf1 = find_row(page, "M1", "202608").first
            t1 = sf1.inner_text()
            assert "M1" in t1 and "202608" in t1 and "Auto" in t1 and "待复核" in t1, \
                f"SF1 行字段缺失（期望真实预测方法 Auto*）：{t1[:120]}"
            assert "已生效" in find_row(page, "M1", "202607").first.inner_text(), "SF2 未显示已生效"
            assert "已否决" in find_row(page, "M1", "202606").first.inner_text(), "SF3 未显示已否决"

            step("§2 VT-LIST-02 状态下拉（chips）筛选收敛")
            click_chip(page, "待复核")
            assert_rows_all_status(page, "待复核")
            assert find_row(page, "M1", "202608").count() > 0, "待复核筛选未见 SF1"
            assert find_row(page, "M1", "202607").count() == 0, \
                "待复核筛选不应见已生效的 SF2（M1@202607）—— 状态筛选未互斥"
            click_chip(page, "已生效")
            assert_rows_all_status(page, "已生效")
            assert find_row(page, "M1", "202607").count() > 0, "已生效筛选未见 SF2"
            assert find_row(page, "M1", "202608").count() == 0, \
                "已生效筛选不应见待复核的 SF1（M1@202608）—— 状态筛选未互斥"
            click_chip(page, "已否决")
            assert_rows_all_status(page, "已否决")
            assert find_row(page, "M1", "202606").count() > 0, "已否决筛选未见 SF3"
            assert find_row(page, "M1", "202608").count() == 0, \
                "已否决筛选不应见待复核的 SF1（M1@202608）—— 状态筛选未互斥"

            step("§2 VT-LIST-03 物料模糊 + 版本精确 + 异常标记 AND + 空态")
            click_chip(page, "全部")  # 清状态 chip
            mat_input = page.locator('input[placeholder*="模糊"]')
            mat_input.fill("M1")
            mat_input.press("Enter")
            page.wait_for_timeout(500)
            rows = page.locator("table.tbl.tight tr.data")
            assert rows.count() == 3, f"物料号 M1 模糊应 3 条，实际 {rows.count()}"
            for i in range(rows.count()):
                assert "M2" not in rows.nth(i).inner_text(), "物料号 M1 筛选混入 M2 行"

            ver_input = page.locator('input[placeholder*="版本"]')
            ver_input.fill("202608")
            ver_input.press("Enter")
            page.wait_for_timeout(500)
            rows = page.locator("table.tbl.tight tr.data")
            assert rows.count() == 1 and "202608" in rows.first.inner_text(), "M1+202608 应恰 1 条"

            page.locator("select").first.select_option(value="false")
            page.wait_for_timeout(500)
            rows = page.locator("table.tbl.tight tr.data")
            assert rows.count() == 1 and "M1" in rows.first.inner_text(), "叠加异常=正常后仍应为 SF1"

            ver_input.fill("209999")
            ver_input.press("Enter")
            page.wait_for_timeout(500)
            assert "无匹配数据" in page.locator("main").inner_text(), "空态文案缺失"
            assert page.locator("table.tbl.tight tr.data").count() == 0, "空结果不应有数据行"

            click_button(page, ["重置"])
            page.wait_for_timeout(500)

            # ===================== §3 模态全字段 =====================
            step("§3 VT-MODAL-01 详情模态全字段 + 待复核页脚按钮")
            find_row(page, "M1", "202608").locator("button.b-link.mono").first.click()
            modal = wait_modal(page)
            txt = modal.locator(".modal-bd").first.inner_text()
            for lb in ["物料号", "拟合版本", "物料名称", "预测方法", "预测误差（sMAPE）",
                       "预测参数（pred_params）", "服务系数", "安全水位", "组批窗口",
                       "满足率", "库存天数", "切线次数", "异常标记", "状态"]:
                assert lb in txt, f"详情模态缺字段标签：{lb}"
            # ⚠ 2026-09-17 口径变更：库存侧**不再自动运算**（组批窗口/满足率目标由物料主数据
            # 人工维护，网格寻优/回放/成本折算本期不做）⇒ 由寻优才产出的四个量**留空显示「—」**，
            # 而 `组批窗口` / `满足率` 改为**主数据人工值的镜像**。原断言里的 `1.65` 正是被
            # 编造的常量（详见《应用详设》§3.2 的口径变更说明与 BR-20）。
            for v in ["M1", "202608", "移动平均物料A", "Auto", "season_length", "28", "95%",
                      "正常", "待复核", "原始数据"]:
                assert v in txt, f"详情模态缺值：{v}"
            assert "1.65" not in txt, "服务系数本期不产出，不应再出现编造的常量 1.65"
            # 四个"由寻优产出"的量应为空值占位「—」（与同一行的多列空值一致）
            assert txt.count("—") >= 3, f"库存侧未产出的字段应显示「—」：{txt[:200]}"
            ft = modal.locator(".modal-ft").first.inner_text()
            assert "复核通过" in ft and "否决" in ft, "待复核页脚缺 复核通过/否决"
            assert "回滚" not in ft, "待复核页脚不应有回滚按钮"
            close_modal(page, modal)

            step("§3 VT-MODAL-02 已否决模态页脚无动作按钮（终态 x-show）")
            find_row(page, "M1", "202606").locator("button.b-link.mono").first.click()
            modal = wait_modal(page)
            txt = modal.locator(".modal-bd").first.inner_text()
            assert "M1" in txt and "202606" in txt, "已否决模态缺标识"
            ft = modal.locator(".modal-ft").first
            ft_text = ft.inner_text()
            assert "已否决" in ft_text and "无可用操作" in ft_text, "已否决页脚缺终态文案"
            for forbidden in ["复核通过", "否决", "回滚"]:
                assert ft.locator(f'button:visible:has-text("{forbidden}")').count() == 0, \
                    f"已否决页脚不应出现 {forbidden} 按钮"
            close_modal(page, modal)

            step("§3 VT-MODAL-03 拟合过程候选排名表 + 逐月曲线（detail_json）")
            find_row(page, "M1", "202608").locator("button.b-link.mono").first.click()
            modal = wait_modal(page)
            bd = modal.locator(".modal-bd").first
            # 候选非空时 x-if 才渲染 #fitChart；等它挂上来
            bd.locator("#fitChart").first.wait_for(state="attached", timeout=10000)
            mtxt = bd.inner_text()
            assert "下月预测" in mtxt, "模态缺「下月预测」区块"
            assert "拟合过程" in mtxt, "模态缺「拟合过程」区块"
            # 空态是 x-show 隐藏（**仍在 DOM**）——必须用 :visible/is_hidden 判，不能用 has_text 判存在
            empty_state = bd.locator('div[x-show="!fitCandidates().length"]')
            assert empty_state.count() == 1, "缺「无拟合过程数据」空态元素（x-show 兜底）"
            assert empty_state.first.is_hidden(), "候选非空时「无拟合过程数据」空态应隐藏（x-show）"
            # 「下月预测」区块含 pred_qty（点预测，非「—」空值兜底）
            pred_cell = bd.locator(
                'xpath=.//div[contains(@class,"k") and normalize-space(.)="预测销量"]'
                '/following-sibling::div[contains(@class,"v")][1]'
            ).first
            assert pred_cell.count() == 1, "「下月预测」区块缺 预测销量 单元格"
            pred_txt = pred_cell.inner_text().strip()
            assert pred_txt not in ("", "—") and any(ch.isdigit() for ch in pred_txt), \
                f"「下月预测」pred_qty 未渲染数值：{pred_txt!r}"
            # 候选排名表：表头三列 + ≥1 行（真实 Auto* 候选）+ 首行「★ 推荐」
            cand = bd.locator('table.tbl.tight:has(th:has-text("预测方法"))').first
            head = cand.locator("tr").first.inner_text()
            for col in ["预测方法", "MASE", "sMAPE"]:
                assert col in head, f"候选排名表缺列：{col}（实际 {head!r}）"
            cand_rows = cand.locator("tr.data")
            n_cand = cand_rows.count()
            assert n_cand >= 1, "候选排名表无数据行（detail_json.candidates 为空）"
            first_txt = cand_rows.first.inner_text()
            assert "★ 推荐" in first_txt, f"候选首行应标「★ 推荐」：{first_txt!r}"
            assert "Auto" in first_txt, f"候选方法应为真实 Auto*（不是回落文案）：{first_txt!r}"
            # MASE / sMAPE 两列非空（td.mono 各含数字）
            cells = cand_rows.first.locator("td.mono").all_inner_texts()
            assert len(cells) >= 2 and all(any(ch.isdigit() for ch in c) for c in cells[:2]), \
                f"候选行 MASE/sMAPE 未渲染：{cells!r}"
            # #fitChart 容器存在且 echarts 已 init（曲线真的画出来了；渲染期报错由 §6 兜底）
            page.wait_for_function(
                "() => { const el = document.getElementById('fitChart');"
                " return !!(el && window.echarts && window.echarts.getInstanceByDom(el)); }",
                timeout=8000,
            )
            # 点非首行候选 → 选中行高亮切换（候选数 ≥2 时才有非首行）
            print(f"  · 拟合候选 {n_cand} 个；首行：{first_txt.splitlines()[0][:48]!r}")
            if n_cand >= 2:
                cand_rows.nth(1).click()
                page.wait_for_timeout(400)
                style1 = cand_rows.nth(1).get_attribute("style") or ""
                assert "prime-soft" in style1, f"点击候选行后未高亮：{style1!r}"
                style0 = cand_rows.first.get_attribute("style") or ""
                assert "prime-soft" not in style0, "选中行切换后首行不应仍高亮"
            close_modal(page, modal)

            # ===================== §4 表单落库回显 + 状态机操作 =====================
            step("§4 VT-FORM-01 发起拟合（run）表单落库回显")
            click_button(page, ["＋ 发起拟合", "发起拟合"])
            modal = wait_modal(page)
            fill_labeled(modal, "物料号", "M1")
            pick_autocomplete(page, modal, "M1")
            fill_labeled(modal, "拟合版本", "202609")
            click_button(modal, ["发起拟合"])
            assert_toast(page, "已发起拟合 · M1 · 202609")
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(600)
            r = find_row(page, "M1", "202609")
            assert r.count() > 0, "run 后列表未回显 M1@202609"
            assert "待复核" in r.first.inner_text(), "新记录初始应为待复核"

            step("§4 VT-FORM-02 发起拟合必填/非法版本校验（不发请求）")
            click_button(page, ["＋ 发起拟合", "发起拟合"])
            modal = wait_modal(page)
            click_button(modal, ["发起拟合"])
            assert_toast(page, "请选择物料号", kind="warn")
            fill_labeled(modal, "物料号", "M1")
            pick_autocomplete(page, modal, "M1")
            fill_labeled(modal, "拟合版本", "2026")
            click_button(modal, ["发起拟合"])
            assert_toast(page, "拟合版本格式必须为 YYYYMM", kind="warn")
            fill_labeled(modal, "拟合版本", "202613")
            click_button(modal, ["发起拟合"])
            assert_toast(page, "拟合版本格式必须为 YYYYMM", kind="err")
            close_modal(page, modal)
            page.wait_for_timeout(300)
            assert page.locator('table.tbl.tight tr.data:has-text("202613")').count() == 0, \
                "非法版本不应产生新记录"

            step("§4 VT-FORM-03 批量拟合（run_batch）摘要 toast + 落表")
            click_button(page, ["批量拟合"])
            modal = wait_modal(page)
            fill_labeled(modal, "拟合版本", "202610")
            click_button(modal, ["批量拟合"])
            assert_toast(page, "批量拟合完成 · 共 2 · 成功 2 · 失败 0")
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(600)
            assert find_row(page, "M1", "202610").count() > 0, "批量拟合未落 M1@202610"
            assert find_row(page, "M2", "202610").count() > 0, "批量拟合未落 M2@202610"
            # 用例 §4 VT-FORM-03 断言「落表且 status=待复核」——原实现只断了行存在，
            # 「批量拟合跑出来的记录初始也是待复核」这半条没断。
            for mat in ("M1", "M2"):
                assert "待复核" in find_row(page, mat, "202610").first.inner_text(), \
                    f"批量拟合新建的 {mat}@202610 初始状态应为 待复核"

            step("§4 VT-ACT-01 待复核 → approve 已生效（行内复核通过）")
            find_row(page, "M2", "202608").locator('.rowact button:visible:has-text("复核通过")').first.click()
            assert_toast(page, "已复核通过 · M2 · 202608")
            sf4 = wait_status(page, "M2", "202608", "已生效")
            assert sf4.locator('.rowact button:visible:has-text("回滚")').count() == 1, "已生效行应显示回滚按钮"
            assert sf4.locator('.rowact button:visible:has-text("复核通过")').count() == 0, "已生效行不应再有复核通过"

            step("§4 VT-ACT-02 待复核 → reject 已否决（行内否决）")
            find_row(page, "M2", "202607").locator('.rowact button:visible:has-text("否决")').first.click()
            assert_toast(page, "已否决 · M2 · 202607")
            sf5 = wait_status(page, "M2", "202607", "已否决")
            assert sf5.locator('.rowact button:visible').count() == 0, "已否决行不应有可见操作按钮"

            step("§4 VT-ACT-03 已生效 → rollback 已否决（回滚，回填上一版参数）")
            find_row(page, "M2", "202606").locator('.rowact button:visible:has-text("回滚")').first.click()
            assert_toast(page, "已回滚 · M2 · 202606")
            sf6 = wait_status(page, "M2", "202606", "已否决")
            assert sf6.locator('.rowact button:visible').count() == 0, "回滚后不应有可见操作按钮"
            # BR-15 回填上一版参数：本页 UI 不展示物料主数据的 base_method/base_params，故按本仓库
            # 既有范式（md_breakpoint §4「软失效」）经**页面同源接口**读回，断言回填确实发生。
            # 上一版 = fit_version < 202606 且 status=已生效 的最新一条 = M2@202605（§0 SF7）。
            prev = page.evaluate("""async () => {
              const r = await fetch('/api/apps/psc/strategy_fitting/call/list',
                {method:'POST', headers:{'Content-Type':'application/json'},
                 body: JSON.stringify({material_no: 'M2', fit_version: '202605'})});
              const j = await r.json();
              return (j.data && j.data.items && j.data.items[0]) || null;
            }""")
            mat = page.evaluate("""async () => {
              const r = await fetch('/api/apps/psc/md_material/call/get',
                {method:'POST', headers:{'Content-Type':'application/json'},
                 body: JSON.stringify({material_no: 'M2'})});
              const j = await r.json();
              return (j.data !== undefined) ? j.data : j;
            }""")
            assert prev and prev.get("fit_version") == "202605", f"未取到上一版记录 SF7：{prev}"
            assert mat and mat.get("fit_version") == "202605", (
                "回滚未把上一版版本号回填进物料主数据（BR-15）："
                f"fit_version={mat and mat.get('fit_version')}"
            )
            assert mat.get("base_method") == prev.get("pred_method"), (
                "回滚未回填上一版预测方法："
                f"{mat.get('base_method')} != 上一版 {prev.get('pred_method')}"
            )

            step("§4 VT-ACT-04 已否决终态无按钮（行内 x-show 收敛）")
            sf3 = find_row(page, "M1", "202606").first
            assert "已否决" in sf3.inner_text(), "SF3 状态徽章应为已否决"
            for forbidden in ["复核通过", "否决", "回滚"]:
                assert sf3.locator(f'.rowact button:visible:has-text("{forbidden}")').count() == 0, \
                    f"已否决行不应出现 {forbidden} 按钮"

            # ===================== §6 0 报错红线 =====================
            step("§6 0 报错红线")
            assert not errors, f"前端报错：{errors[:5]}"
            # **豁免也要受检**（2026-09-17 补）：`ignored` 收集了却从不校验，等于给「静默吞掉」
            # 开了口子 —— 任何新形态的 4xx/console error 都能混进来而不被任何人发现。
            # 只认 favicon / sourcemap / 受限会话 403 三种豁免理由，其余一律报出。
            for _item in ignored:
                _ok = ("/favicon.ico" in _item or ".map" in _item or "403" in _item)
                assert _ok, f"豁免理由不成立（既不是 favicon/.map，也不是 403）：{_item!r}"
            if ignored:
                print(f"  · 本次豁免 {len(ignored)} 条：{ignored[:3]}")
            print("VERIFY_VIEW_psc_strategy_fitting: PASS", flush=True)

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
        print(f"FAIL @ {STEP}: {e}", flush=True)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR @ {STEP}: {type(e).__name__}: {e}", flush=True)
        sys.exit(1)
