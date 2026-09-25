"""e2e 前端验收 - psc:sales_forecast（销售预测）
断言：路由渲染防粘滞 → 造数后列表有数据（处理表复合键 version_no/material_no/customer_no/rolling_month）
→ 详情模态全字段（base_params tryParse / abnormal_flag）→ 行级加工
（算基线 / 填预测回显 adj_qty / 决策回显 final_qty）+ 开启版本入口 → 全程 0 console error / 0 pageerror / 0 HTTP≥400。
用例来源：app/psc/sales_forecast/前端测试用例.md
（§1 VT-ROUTE-01 + §2 VT-LIST-01/02 + §3 VT-MODAL-01
 + §4 VT-FORM-01/02/03/04/05/06/07 + §6）。
2026-09-17 补齐：本轮把判据 `view_coverage.py` 报出的三条缺失断言一并补入本脚本 ——
§2 VT-LIST-02 过滤抽样、§4 VT-FORM-04 事件调整、§4 VT-FORM-06 汇总；原文的缺失说明随之撤销。
§4「新建组合（create · 客户可空）」原为脚本独有断言，VT-FORM-07 已于 2026-09-17 回写进用例文档 §4。
运行：python app/psc/tests/verify_view_psc_sales_forecast.py
"""
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

from fde_platform import users  # noqa: E402
users.init_schema()
users.seed_admin()

# seed_admin 落 password_changed=0 → 首登被强制改密闸门拦下（auth.py ②.5），
# 与 verify_view_e2e 样板/各逐应用脚本一致，先在隔离后的 config/auth.db 置 1 放行。
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


# §0 自足造数（跨应用前置 + 本页主数据，照本应用前端测试用例 §0 冻结字典）：
#   VER1 md_monthly_version.create("202608")（草稿）
#   C001 md_customer.create("C001")
#   M1   md_material.create("M1", base_method=移动平均, base_params={"window":6})
#   AT1  attainment.upsert(C001, M1, mape=0.10, bias=0.05)
#   SF1  sales_forecast.open_version("202608") → 正常物料 M1 × 客户 C001 拆 N+1/N+2/N+3 = 3 行
#   fill_customer("202608", M1, C001, N+1, orig_qty=1000) → adj_qty 自动算 = 1000×(1-0.05)=950
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
    if (!r.ok) throw new Error(`psc.${app}.${svc} HTTP ${r.status} ${text.slice(0, 160)}`);
    if (data && data.status === "error") {
      throw new Error(`psc.${app}.${svc} biz ${data.message || JSON.stringify(data).slice(0, 160)}`);
    }
    return data;
  };

  const unwrap = (x) => {
    if (!x) return x;
    if (x.data !== undefined) return x.data;
    if (x.result !== undefined) return x.result;
    return x;
  };

  const ver = unwrap(await call("md_monthly_version", "create", {
    version_no: "202608", anchor_period: "2026-08", opening_date: "2026-08-01"
  }));
  const cust = unwrap(await call("md_customer", "create", {
    customer_no: "C001", customer_name: "客户A"
  }));
  const mat = unwrap(await call("md_material", "create", {
    material_no: "M1", material_name: "物料A",
    base_method: "移动平均", base_params: '{"window":6}'
  }));
  const att = unwrap(await call("attainment", "upsert", {
    customer_no: "C001", material_no: "M1", mape: 0.10, bias: 0.05
  }));
  // 历史台账：让 M1 有采购客户 C001（open_version 按物料收窄，无历史则客户为空）。
  // qty=950 使移动平均基线=950，与 adj_qty=950 偏离 0 → 决策不异常、final=950。
  await call("sales_history", "import_batch", {
    rows: [{ material_no: "M1", customer_no: "C001", period: "2026-01", qty: 950 }]
  });
  const opened = unwrap(await call("sales_forecast", "open_version", {version_no: "202608"}));
  const filled = unwrap(await call("sales_forecast", "fill_customer", {
    version_no: "202608", material_no: "M1", customer_no: "C001",
    rolling_month: "N+1", orig_qty: 1000
  }));

  return {
    seeded: true,
    version_no: ver && ver.version_no,
    list_rows: opened && opened.list_rows,
    line_rows: opened && opened.line_rows,
    adj_qty: filled && filled.adj_qty,
  };
}"""


STEP = "init"


def step(name):
    global STEP
    STEP = name
    print(f"[step] {name}")


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
        loc = scope.locator(
            f'button:has-text("{t}"), a:has-text("{t}"), .btn:has-text("{t}")'
        )
        if loc.count():
            loc.first.click()
            return True
    raise AssertionError(f"未找到按钮：{texts}")


def wait_modal(page):
    """等 .modal-mask:visible 出现、.loadbox 消失（详情模态载入明细），返回可见模态。
    （pitfalls #16；多 .modal-bd 用 .first；页脚按钮读 .modal-mask:visible）"""
    mask = page.locator(".modal-mask:visible")
    mask.first.wait_for(state="visible", timeout=10000)
    if mask.locator(".loadbox").count():
        try:
            mask.locator(".loadbox").first.wait_for(state="hidden", timeout=5000)
        except Exception:
            pass
    return mask.last


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


def expect_toast(page, text, timeout=5000):
    loc = page.locator(f'.toast:has-text("{text}")')
    try:
        loc.first.wait_for(state="visible", timeout=timeout)
    except Exception:
        raise AssertionError(
            f"未出现预期 toast：{text}（当前：{page.locator('.toasts').inner_text()[:160]}）"
        )


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
        # 算基线 / 决策 按钮直发 confirm() → 自动接受
        page.on("dialog", lambda d: d.accept())

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

            # ===================== §0 造数 =====================
            step("§0 造数（VER1 + C001 + M1 + AT1 → SF1 open_version → fill_customer）")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"sales_forecast 造数失败：{seed}"
            assert seed.get("line_rows") == 3, f"open_version 处理表应为 3 行，实际 {seed.get('line_rows')}"
            assert seed.get("adj_qty") == 950, f"fill_customer adj_qty 应为 950，实际 {seed.get('adj_qty')}"

            # ===================== §1 本页渲染（防粘滞）=====================
            # §1 VT-ROUTE-01 路由渲染 + 防粘滞（.kpi==0 + 工具栏三按钮）
            step("§1 路由渲染防粘滞")
            page.evaluate("location.hash = '#/sales_forecast'")
            try:
                page.wait_for_selector("main .card", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator("main").inner_text().strip(), "sales_forecast 页面无内容"
            assert page.locator("main .card").count() > 0, "sales_forecast 未渲染 card"
            assert page.locator(".kpi:visible").count() == 0, "sales_forecast 挂载未重建（残留看板）"
            for label in ["开启版本", "汇总", "查看汇总"]:
                assert page.locator(f'button:visible:has-text("{label}")').count() > 0, \
                    f"工具栏缺按钮：{label}"

            # ===================== §2 造数后列表有数据 =====================
            # §2 VT-LIST-01 列表含处理表行（3 行 + 复合键四列 202608/M1/C001/N+1）
            step("§2 列表含处理表 3 行（M1×C001×N+1/N+2/N+3 复合键）")
            try:
                page.wait_for_selector('table.tbl tr.data:has-text("N+1")', timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(300)
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 3, f"sales_forecast 列表应 3 行，实际 {rows.count()}"
            for rm in ["N+1", "N+2", "N+3"]:
                assert rows.filter(has_text=rm).count() == 1, f"列表缺滚动月度 {rm} 行"
            row_n1 = page.locator('table.tbl tr.data:has-text("N+1")').first
            n1_txt = row_n1.inner_text()
            for v in ["202608", "M1", "C001", "N+1"]:
                # ⚠ 错误信息**带上看到的整行文本**（2026-09-18）：只报"缺哪个值"时，
                # 排查得先复现一次才看得到行里到底写了什么；带上原文一眼就能判是数据不对还是列没渲染。
                assert v in n1_txt, f"N+1 行复合键缺列：{v}；实际行文本={n1_txt!r}"

            # ===================== §4 算基线（calc_baseline，按钮直发）=====================
            # §4 VT-FORM-03 算基线（calc_baseline）→ 回显 base_method="移动平均"
            step("§4 算基线（calc_baseline）→ 回显 base_method 移动平均")
            row_n1 = page.locator('table.tbl tr.data:has-text("N+1")').first
            assert row_n1.locator('button:visible:has-text("算基线")').count() == 1, "N+1 草稿行应有算基线按钮"
            row_n1.locator('button:visible:has-text("算基线")').first.click()
            expect_toast(page, "已算基线")
            try:
                page.wait_for_selector('table.tbl tr.data:has-text("N+1") td:nth-child(7):has-text("移动平均")', timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(300)
            row_n1 = page.locator('table.tbl tr.data:has-text("N+1")').first
            assert "移动平均" in row_n1.locator("td").nth(6).inner_text(), \
                "算基线后 N+1 行基线方法列未回显 移动平均"

            # ===================== §3 模态全字段 =====================
            # §3 VT-MODAL-01 详情模态全字段 + base_params tryParse + abnormal_flag
            step("§3 详情模态全字段（含 base_params tryParse / abnormal_flag）")
            page.locator('table.tbl tr.data:has-text("N+1") button.b-link').first.click()
            modal = wait_modal(page)
            txt = modal.inner_text()

            for label in [
                "定位信息", "版本", "物料", "客户", "滚动月度",
                "客户预测", "原始预测", "MAPE", "bias", "调整后需求",
                "基线", "基线方法", "基线参数", "基线数量",
                "事件调整", "事件分析", "事件调整量", "基线和事件合计",
                "决策结果", "异常标记", "最终预测",
                "时间信息", "创建时间", "更新时间", "原始数据",
            ]:
                assert label in txt, f"详情模态缺字段标签：{label}"
            for val in ["202608", "M1", "C001", "N+1", "移动平均", '"window":6', "正常"]:
                assert val in txt, f"详情模态缺字段值：{val}"
            # 客户预测值（fmt 千分位 / 小数）
            for val in ["1,000", "0.1", "0.05", "950"]:
                assert val in txt, f"详情模态缺客户预测值：{val}"
            # 无断点历史（stub 空）→ bp_material_no / switch_time 不显示
            assert "断点追溯原物料" not in txt, "无断点历史时不应显示 bp_material_no"
            assert "断点切换时间" not in txt, "无断点历史时不应显示 switch_time"

            # 页脚：草稿版本可见四动作；abnormal_flag=0 无【填最终】
            ft = modal.locator(".modal-ft")
            for label in ["填预测", "算基线", "事件调整", "决策"]:
                assert ft.locator(f'button:visible:has-text("{label}")').count() >= 1, \
                    f"草稿态页脚缺 {label} 按钮"
            assert ft.locator('button:visible:has-text("填最终")').count() == 0, \
                "abnormal_flag=0 时页脚不应出现 填最终 按钮"
            close_modal(page, modal)

            # ===================== §4 填预测（fill_customer，N+2）→ 回显 adj_qty =====================
            # §4 VT-FORM-02 填预测（fill_customer）→ 回显 adj_qty == 950（orig_qty×(1−bias)）
            step("§4 填预测（fill_customer）→ 回显 adj_qty=950（orig_qty×（1-bias））")
            row_n2 = page.locator('table.tbl tr.data:has-text("N+2")').first
            assert row_n2.locator('button:visible:has-text("填预测")').count() == 1, "N+2 草稿行应有填预测按钮"
            row_n2.locator('button:visible:has-text("填预测")').first.click()
            modal = wait_modal(page)
            modal.locator('input[placeholder="客户原始预测数量"]').fill("1000")
            click_button(modal, ["提交"])
            expect_toast(page, "已填客户预测")
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            try:
                page.wait_for_selector('table.tbl tr.data:has-text("N+2") td:nth-child(5):has-text("1,000")', timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(300)

            row_n2 = page.locator('table.tbl tr.data:has-text("N+2")').first
            assert "1,000" in row_n2.locator("td").nth(4).inner_text(), "N+2 填预测后未回显 orig_qty 1,000"
            assert "950" in row_n2.locator("td").nth(5).inner_text(), "N+2 填预测后未回显 adj_qty 950"

            # ===================== §4 决策（decide，按钮直发）→ 回显 final_qty/abnormal_flag =====================
            # §4 VT-FORM-05 决策（decide）→ 回显 final_qty == 950 / abnormal_flag == 正常（0）
            step("§4 决策（decide）→ 回显 final_qty=950 / abnormal_flag=正常")
            row_n1 = page.locator('table.tbl tr.data:has-text("N+1")').first
            assert row_n1.locator('button:visible:has-text("决策")').count() == 1, "N+1 草稿行应有决策按钮"
            row_n1.locator('button:visible:has-text("决策")').first.click()
            expect_toast(page, "已决策")
            try:
                page.wait_for_selector('table.tbl tr.data:has-text("N+1") td:nth-child(11):has-text("950")', timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(300)

            row_n1 = page.locator('table.tbl tr.data:has-text("N+1")').first
            # 列序：0版本1物料2客户3滚动4原始5调整6基线方法7基线8事件调整9品种合计10异常11最终12操作
            assert "950" in row_n1.locator("td").nth(11).inner_text(), \
                "决策后 N+1 行最终预测列应为 950（基线未算 → 取客户调整后值）"
            assert "正常" in row_n1.locator("td").nth(10).inner_text(), \
                "决策后 N+1 行异常标记应为 正常"

            # ===================== §4 开启版本入口（open_version，唯一"创建"入口）=====================
            # §4 VT-FORM-01 开启版本（open_version）· 版本下拉仅「草稿」项（无发布/冻结）
            step("§4 开启版本入口（open_version · 版本下拉仅草稿项）")
            page.locator('button:visible:has-text("开启版本")').first.click()
            modal = wait_modal(page)
            sel = modal.locator("select").first
            opts = sel.evaluate("el => Array.from(el.options).map(o => ({v: o.value, t: o.text || ''}))")
            assert any(o["v"] == "202608" for o in opts), f"开启版本版本下拉缺 202608 草稿项：{opts}"
            assert not any(("发布" in o["t"]) or ("冻结" in o["t"]) for o in opts), \
                f"开启版本版本下拉不应含锁定/冻结版本：{opts}"
            close_modal(page, modal)

            # ===================== §4 事件调整（adjust_event）=====================
            # §4 VT-FORM-04 事件调整（adjust_event）→ 回显 event_analysis/event_adj
            #    位置：放在「新建组合」之前 —— 此时列表仍是 3 行，`has-text("N+1")` 唯一命中
            #    M1×C001 行（新建空客户组合后会有第二个 N+1 行，定位会变歧义）。
            #    表单（view.html 行级加工小模态 kind=event）：事件分析 input[placeholder=
            #    "促销 / SOP / 断点 分析"]、事件调整量 input[type=number]（填预测表单里的
            #    两个 number input 被 x-show 隐藏 → 必须用 `:visible` 限定，否则 fill 会等可见而超时）。
            #    断言：toast「已事件调整」；列表该行「事件调整量」列 == "+20"（`signed()` 带符号
            #    fmt，view.js）；详情模态回显 事件分析=促销 / 事件调整量=+20。
            #    另注：adjust_event 只写 event_analysis/event_adj/base_event_qty，**不动 final_qty**
            #    （sales_forecast.py），故不影响后面 VT-FORM-06 的 final_qty_sum == 950。
            step("§4 事件调整（adjust_event）→ 回显 促销 / +20")
            row_n1 = page.locator('table.tbl tr.data:has-text("N+1")').first
            assert row_n1.locator('button:visible:has-text("事件调整")').count() == 1, "N+1 草稿行应有事件调整按钮"
            row_n1.locator('button:visible:has-text("事件调整")').first.click()
            modal = wait_modal(page)
            assert "事件调整" in modal.locator(".sub").first.inner_text(), "事件调整弹窗副标题不符"
            modal.locator('input[placeholder="促销 / SOP / 断点 分析"]').fill("促销")
            modal.locator('input[type="number"]:visible').first.fill("20")
            click_button(modal, ["提交"])
            expect_toast(page, "已事件调整")
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            row_n1 = page.locator('table.tbl tr.data:has-text("N+1")').first
            # 列序：0版本1物料2客户3滚动4原始5调整6基线方法7基线8事件调整9品种合计10异常11最终12操作
            assert "+20" in row_n1.locator("td").nth(8).inner_text(), \
                "事件调整后 N+1 行事件调整量列应回显 +20（signed fmt）"
            row_n1.locator("button.b-link").first.click()
            modal = wait_modal(page)
            mtx = modal.inner_text()
            assert "促销" in mtx, "详情模态事件分析应回显 促销"
            assert "+20" in mtx, "详情模态事件调整量应回显 +20"
            close_modal(page, modal)

            # ===================== §4 新建组合（create · 物料×空客户）=====================
            # §4 VT-FORM-07 新建组合（create · 客户可空）
            step("§4 新建组合（create · 客户可空）")
            page.locator('button:visible:has-text("新建组合")').first.click()
            modal = wait_modal(page)
            assert "新建组合" in modal.locator(".docno").first.inner_text(), "新建组合弹窗标题不符"
            assert modal.locator("select").first.input_value() == "202608", "新建组合版本应默认当前草稿版本"
            mat_input = modal.locator('input[placeholder="物料（代号/名称）…"]').first
            mat_input.click()
            page.wait_for_timeout(200)
            mat_input.fill("M1")
            page.wait_for_timeout(300)
            modal.locator('.auto-drop div:has-text("物料A")').first.click()
            page.wait_for_timeout(200)
            click_button(modal, ["创建组合"])
            expect_toast(page, "已新建组合")
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            assert page.locator("table.tbl tr.data").count() == 6, \
                f"新建空客户组合后列表应为 6 行（M1×C001 3 + M1×空 3），实际 {page.locator('table.tbl tr.data').count()}"

            # ===================== §4 汇总（summarize + get_summary）=====================
            # §4 VT-FORM-06 汇总（summarize + get_summary）
            #    位置说明：文档列在 VT-FORM-05 之后、VT-FORM-07 之前；脚本放在 §4 末尾执行，
            #    **不改任何既有断言的上下文**（此时 6 行处理表已就绪：M1×C001 N+1 已 decide
            #    final_qty=950，空客户三行 final_qty 为 NULL）。
            #    选版本：两个模态的版本下拉都按 value 精确选 202608（汇总模态只列 lock_status=草稿
            #    的版本 `draftVersions()`，查询模态列 `versionOptions` 全量）。
            #    断言：① 执行 summarize 后 toast「已汇总 N 行」—— N == 3：summarize 按
            #      `GROUP BY material_no, rolling_month` 合计（sales_forecast.py，COALESCE(final_qty,0)），
            #      6 行进（M1×C001 三行 + M1×空 三行）→ 3 个分组（M1×N+1/N+2/N+3）；
            #      ②「查看汇总」模态内的 `.tbl.tight` 表头 == 版本/物料/滚动月度/最终预测合计
            #      （即契约列 version_no/material_no/rolling_month/final_qty_sum），且
            #      `get_summary` 取回 3 行；M1×N+1 行的四个单元格 == ["202608","M1","N+1","950"]
            #      （空客户行 final_qty 为 NULL → 0，不影响合计；N+2/N+3 无最终预测 → 0）。
            step("§4 汇总（summarize → toast 已汇总 N 行）")
            # 用 :text-is 精确匹配：「查看汇总」也含「汇总」子串，不能用 has-text
            page.locator('button:visible:text-is("汇总")').first.click()
            modal = wait_modal(page)
            assert "版本汇总" in modal.locator(".docno").first.inner_text(), "汇总弹窗头应「版本汇总」"
            sum_sel = modal.locator("select").first
            sum_opts = sum_sel.evaluate("el => Array.from(el.options).map(o => o.value)")
            assert "202608" in sum_opts, f"汇总版本下拉应含草稿版本 202608：{sum_opts}"
            sum_sel.select_option("202608")
            click_button(modal, ["执行汇总"])
            expect_toast(page, "已汇总 3 行")
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(300)

            step("§4 汇总（查看汇总 → get_summary 表列 + M1×N+1 合计 950）")
            page.locator('button:visible:text-is("查看汇总")').first.click()
            modal = wait_modal(page)
            assert "汇总查询" in modal.locator(".docno").first.inner_text(), "汇总查询弹窗头应「汇总查询」"
            modal.locator("select").first.select_option("202608")
            click_button(modal, ["查询汇总"])
            page.wait_for_timeout(600)
            stbl = modal.locator("table.tbl.tight")
            assert stbl.count() >= 1, "汇总查询未渲染 .tbl.tight 表"
            stbl = stbl.first
            ths = [t.strip() for t in stbl.locator("tr th").all_inner_texts()]
            assert ths == ["版本", "物料", "滚动月度", "最终预测合计"], \
                f"汇总表列应为 version_no/material_no/rolling_month/final_qty_sum 四列，实际 {ths}"
            srows = stbl.locator("tr:has(td)")
            assert srows.count() == 3, f"汇总应 3 行（M1×N+1/N+2/N+3），实际 {srows.count()}"
            r_n1 = stbl.locator("tr", has_text="N+1")
            assert r_n1.count() == 1, "汇总表缺 M1×N+1 行"
            cells = [t.strip() for t in r_n1.first.locator("td").all_inner_texts()]
            assert cells == ["202608", "M1", "N+1", "950"], \
                f"M1×N+1 汇总行应为 202608/M1/N+1/950（final_qty_sum 加粗 fmt），实际 {cells}"
            close_modal(page, modal)

            # ===================== §2 过滤抽样（一一对应）=====================
            # §2 VT-LIST-02 过滤抽样（版本/物料/客户/滚动月度四控件一一对应收敛）
            #    操作：版本下拉选 202608 → 物料 autocomplete 选 M1 → 客户 autocomplete 选 C001
            #    → 滚动月度下拉选 N+1。四个控件各自触发重查（view.js：版本 `@change=onVersionChange`、
            #    `pickMaterial` / `pickCustomer` 内部调 `search()`、滚动月度 `@change="search()"`，
            #    而 `search()` == `list.load(1)`）。
            #    断言：结果集收敛为**恰好 1 行**（M1×C001×N+1），该行复合键四列齐。
            #    位置：放最后执行 —— 过滤态留在页面上，不影响前面任何断言（§6 只查报错）。
            #    覆盖度如实标注：本页表只有 6 行而 pageable size=20 → 永远 1 页，
            #    文档里「任一过滤变化重置回第 1 页」这一半**观测不到**（无第 2 页可回），故不断；
            #    过滤控件为 `select:visible` 取第 1/2 个（版本 / 滚动月度），
            #    物料与客户用 `.auto-drop` 内 `@mousedown.prevent` 的选项（同 VT-FORM-07）。
            step("§2 过滤抽样（版本/物料/客户/滚动月度四控件 → 恰好 1 行）")
            page.locator("select:visible").first.select_option("202608")
            page.wait_for_timeout(500)
            f_mat = page.locator('input[placeholder="物料（代号/名称）…"]').first
            f_mat.click()
            f_mat.fill("M1")
            page.wait_for_timeout(300)
            f_mat.locator('xpath=../div//div[normalize-space(.)="物料A"]').first.click()
            page.wait_for_timeout(500)
            f_cus = page.locator('input[placeholder="客户（代号/名称）…"]').first
            f_cus.click()
            f_cus.fill("C001")
            page.wait_for_timeout(300)
            f_cus.locator('xpath=../div//div[normalize-space(.)="客户A"]').first.click()
            page.wait_for_timeout(500)
            page.locator("select:visible").nth(1).select_option("N+1")
            page.wait_for_timeout(700)
            assert f_mat.input_value() == "M1" and f_cus.input_value() == "C001", \
                f"物料/客户 autocomplete 选中值应为 M1 / C001，实际 {f_mat.input_value()!r} / {f_cus.input_value()!r}"
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 1, f"四控件过滤后应恰好 1 行，实际 {rows.count()}"
            ftxt = rows.first.inner_text()
            for v in ["202608", "M1", "C001", "N+1"]:
                assert v in ftxt, f"过滤后的唯一行缺复合键列：{v}"

            # ===================== §6 0 报错红线 =====================
            # §6 0 报错红线（本会话；豁免条目逐条受检）
            step("§6 会话 0 报错")
            assert not errors, f"sales_forecast 会话前端报错：{errors[:5]}"
            # **豁免也要受检**（2026-09-17 补）：`ignored` 收集了却从不校验，等于给「静默吞掉」
            # 开了口子 —— 任何新形态的 4xx/console error 都能混进来而不被任何人发现。
            # 只认 favicon / sourcemap / 受限会话 403 三种豁免理由，其余一律报出。
            for item in ignored:
                ok = ("/favicon.ico" in item or ".map" in item or "403" in item)
                assert ok, f"豁免理由不成立（既不是 favicon/.map，也不是 403）：{item!r}"
            if ignored:
                print(f"  · 本次豁免 {len(ignored)} 条：{ignored[:3]}")
            print("VERIFY_VIEW_psc_sales_forecast: PASS")

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
        print(f"VERIFY_VIEW_psc_sales_forecast: FAIL @ {STEP}: {e}")
        sys.exit(1)
