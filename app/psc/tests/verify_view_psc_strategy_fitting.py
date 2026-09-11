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

from fde_platform.dbguard import isolate_dbs  # noqa: E402

_iso = isolate_dbs()
_iso.__enter__()
atexit.register(_iso.__exit__, None, None, None)

# admin 账号：必须在平台子进程启动前经 users 模块建好，切勿在浏览器里调 HTTP API 建。
from fde_platform import users  # noqa: E402
users.init_schema()
users.seed_admin()

# 首次登录强制改密（password_changed=0）绕过：把 admin 标记为已改密，否则登录后会被
# 重定向到 /change-password，无法进入视图。auth.db 已被 dbguard 隔离成空库，此改动仅作用测试库。
import sqlite3  # noqa: E402
try:
    auth_db = ROOT / "config" / "auth.db"
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
  await call("md_material", "create", {
    material_no: "M1", material_name: "移动平均物料A", status: "正常", base_method: "移动平均"
  });
  await call("md_material", "create", {
    material_no: "M2", material_name: "移动平均物料B", status: "正常", base_method: "移动平均"
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
            click_chip(page, "已生效")
            assert_rows_all_status(page, "已生效")
            assert find_row(page, "M1", "202607").count() > 0, "已生效筛选未见 SF2"
            click_chip(page, "已否决")
            assert_rows_all_status(page, "已否决")
            assert find_row(page, "M1", "202606").count() > 0, "已否决筛选未见 SF3"

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
            for v in ["M1", "202608", "移动平均物料A", "Auto", "season_length", "1.65", "28", "95%",
                      "正常", "待复核", "原始数据"]:
                assert v in txt, f"详情模态缺值：{v}"
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

            step("§4 VT-ACT-04 已否决终态无按钮（行内 x-show 收敛）")
            sf3 = find_row(page, "M1", "202606").first
            assert "已否决" in sf3.inner_text(), "SF3 状态徽章应为已否决"
            for forbidden in ["复核通过", "否决", "回滚"]:
                assert sf3.locator(f'.rowact button:visible:has-text("{forbidden}")').count() == 0, \
                    f"已否决行不应出现 {forbidden} 按钮"

            # ===================== §6 0 报错红线 =====================
            step("§6 0 报错红线")
            assert not errors, f"前端报错：{errors[:5]}"
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
