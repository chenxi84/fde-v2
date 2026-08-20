"""e2e 前端验收 - psc:sales_forecast（销售预测）
断言：路由渲染防粘滞 → 造数后列表有数据（处理表复合键 version_no/material_no/customer_no/rolling_month）
→ 详情模态全字段（base_params tryParse / abnormal_flag）→ 行级加工
（算基线 / 填预测回显 adj_qty / 决策回显 final_qty）+ 开启版本入口 → 全程 0 console error / 0 pageerror / 0 HTTP≥400。
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

from fde_platform.dbguard import isolate_dbs  # noqa: E402

_iso = isolate_dbs()
_iso.__enter__()
atexit.register(_iso.__exit__, None, None, None)

from fde_platform import users  # noqa: E402
users.init_schema()
users.seed_admin()

# seed_admin 落 password_changed=0 → 首登被强制改密闸门拦下（auth.py ②.5），
# 与 verify_view_e2e 样板/各逐应用脚本一致，先在隔离后的 config/auth.db 置 1 放行。
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
                assert v in n1_txt, f"N+1 行复合键缺列：{v}"

            # ===================== §4 算基线（calc_baseline，按钮直发）=====================
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
            step("§4 开启版本入口（open_version · 版本下拉仅草稿项）")
            page.locator('button:visible:has-text("开启版本")').first.click()
            modal = wait_modal(page)
            sel = modal.locator("select").first
            opts = sel.evaluate("el => Array.from(el.options).map(o => ({v: o.value, t: o.text || ''}))")
            assert any(o["v"] == "202608" for o in opts), f"开启版本版本下拉缺 202608 草稿项：{opts}"
            assert not any(("发布" in o["t"]) or ("冻结" in o["t"]) for o in opts), \
                f"开启版本版本下拉不应含锁定/冻结版本：{opts}"
            close_modal(page, modal)

            # ===================== §4 新建组合（create · 物料×空客户）=====================
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

            # ===================== §6 0 报错红线 =====================
            step("§6 会话 0 报错")
            assert not errors, f"sales_forecast 会话前端报错：{errors[:5]}"
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
