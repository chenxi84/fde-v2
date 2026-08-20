"""e2e 前端验收 · psc/master_plan（主计划 · playwright，可直接运行）。
断言：本页路由渲染（非看板页 .kpi==0 防粘滞）→ 自足造数后列表有数据（plan_version/plan_qty）
→ 详情模态全字段（只读页脚无操作按钮）→ 导入表单（import_plan 批量行录入 + plan_version 自增）
→ 全程 0 console error / 0 pageerror / 0 HTTP≥400。
运行：python app/psc/tests/verify_view_psc_master_plan.py
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

# 逐应用脚本恒为 admin 单会话（受限用户菜单收敛归组级脚本）；仅播种 admin 即可。
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

GROUP = "psc"
APP = "master_plan"
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
    if (!r.ok) throw new Error(`psc/${app}.${svc} HTTP ${r.status} ${text.slice(0, 160)}`);
    if (data && data.status === "error") {
      throw new Error(`psc/${app}.${svc} biz ${(data.message || JSON.stringify(data)).slice(0, 160)}`);
    }
    return data && data.data !== undefined ? data.data : data;
  };

  // §0 自足造数（跨应用前置 + 本页主数据）
  await call("md_monthly_version", "create", {
    version_no: "202608", anchor_period: "2026-08", opening_date: "2026-08-01"
  });
  await call("md_material", "create", { material_no: "M1", material_name: "物料M1" });
  await call("md_material", "create", { material_no: "M2", material_name: "物料M2" });

  const mp1 = await call("master_plan", "import_plan", {
    version_no: "202608",
    rows: [{ material_no: "M1", rolling_month: "N+1", plan_qty: 950, latest_inbound_date: "2026-09-30" }]
  });
  const mp2 = await call("master_plan", "import_plan", {
    version_no: "202608",
    rows: [{ material_no: "M2", rolling_month: "N+1", plan_qty: 500, latest_inbound_date: "2026-09-25" }]
  });

  return { seeded: true, mp1, mp2 };
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


def choose_option(scope, label, value=None, text=None):
    loc = scope.locator(
        f'xpath=.//label[contains(normalize-space(.), "{label}")]/following::select[1]'
    )
    if not loc.count():
        loc = scope.locator(
            f'xpath=.//*[contains(normalize-space(.), "{label}")]/ancestor::*'
            f'[contains(@class,"field") or contains(@class,"frow") or contains(@class,"filter") '
            f'or contains(@class,"form")][1]//select'
        )
    if not loc.count():
        loc = scope.locator("select")

    if not loc.count():
        raise AssertionError(f"未找到下拉：{label}")

    sel = loc.first

    if value:
        try:
            sel.select_option(value=value)
            return
        except Exception:
            pass

    if text:
        try:
            sel.select_option(label=text)
            return
        except Exception:
            pass

    ok = sel.evaluate(
        """(el, opt) => {
          const opts = Array.from(el.options || []);
          let hit = null;
          if (opt.value) hit = opts.find(o => o.value === opt.value);
          if (!hit && opt.text) hit = opts.find(o => (o.text || '').includes(opt.text));
          if (!hit) return false;
          el.value = hit.value;
          el.dispatchEvent(new Event('change', {bubbles: true}));
          el.dispatchEvent(new Event('input', {bubbles: true}));
          return true;
        }""",
        {"value": value, "text": text},
    )
    if not ok:
        raise AssertionError(f"下拉选择失败：{label} value={value} text={text}")


def click_button(scope, texts):
    for t in texts:
        loc = scope.locator(
            f'button:has-text("{t}"), a:has-text("{t}"), .btn:has-text("{t}")'
        )
        if loc.count():
            loc.first.click()
            return True
    raise AssertionError(f"未找到按钮：{texts}")


def open_modal(page):
    # 本页两处模态均为 .modal-mask > .modal（详情 + 导入），x-show 控制显隐；
    # 取「可见」mask 内的 .modal（.last 规避同页多 mask）。
    page.locator(".modal-mask:visible .modal").first.wait_for(state="visible", timeout=10000)
    return page.locator(".modal-mask:visible .modal").last


def wait_modal(page):
    # 详情模态加载态：轮询 .modal-mask:visible .loadbox 消失再断言（pitfalls #16）
    try:
        page.locator(".modal-mask:visible .loadbox").wait_for(state="hidden", timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(150)


def close_modal(page, modal):
    btn = modal.locator('button:has-text("关闭"), button:has-text("取消"), button.x')
    if btn.count():
        btn.first.click()
    else:
        page.keyboard.press("Escape")
    try:
        modal.wait_for(state="hidden", timeout=3000)
    except Exception:
        page.keyboard.press("Escape")
    page.wait_for_timeout(250)


def select_autocomplete(scope, material_no):
    """点击可见 .auto-drop 内命中 material_no 的项（@mousedown.prevent 项回填）。"""
    drop = scope.locator(".auto-drop:visible")
    assert drop.count() > 0, f"物料 autocomplete 未展开（{material_no}）"
    drop.first.locator("div").filter(has_text=material_no).first.click()
    time.sleep(0.2)


def fill_import_row(page, modal, idx, material_no, rolling_month, qty, inbound_date):
    """导入模态批量行录入：物料号（行内 autocomplete）/ 滚动月度 / 需求量 / 最迟入库日期。"""
    # 物料号 autocomplete（按所在行 scope，多 autocomplete 并存用 :visible 限定）
    mat = modal.locator('input[placeholder*="物料号"]:visible').nth(idx)
    mat.click()
    mat.fill(material_no)
    page.wait_for_timeout(250)
    select_autocomplete(modal, material_no)
    page.wait_for_timeout(150)
    # 滚动月度：select 顺序 = [版本(1), row0, row1, ...] → idx + 1
    modal.locator("select").nth(idx + 1).select_option(value=rolling_month)
    # 需求量（number）与日期（date）
    modal.locator('input[type="number"]:visible').nth(idx).fill(str(qty))
    modal.locator('input[type="date"]:visible').nth(idx).fill(inbound_date)


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

            # ===================== §1 本页路由渲染（空库，防粘滞）=====================
            step("§1 路由渲染 + 防粘滞")
            page.evaluate("location.hash = '#/master_plan'")
            try:
                page.wait_for_selector("main .card, main .tbl, main table", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator("main").inner_text().strip(), "master_plan 页面无内容"
            assert page.locator("main .card").count() > 0, "master_plan 未渲染"
            assert page.locator(".kpi").count() == 0, "master_plan 挂载未重建（残留看板）"

            # 过滤条：全部月度版本下拉 + 物料号/名称…输入
            ver_sel = page.locator("main select:visible").first
            assert ver_sel.count() > 0, "过滤条缺月度版本下拉"
            opts = ver_sel.locator("option").all_inner_texts()
            assert any("全部月度版本" in o for o in opts), f"过滤条缺全部月度版本选项：{opts}"
            assert page.locator('main input[placeholder*="物料号"]:visible').count() > 0, "过滤条缺物料号输入"

            # 表格表头
            head = page.locator("main table.tbl").first.locator("th").all_inner_texts()
            for col in ["计划版本号", "物料号", "月度版本", "滚动月度", "需求量", "最迟入库日期"]:
                assert col in head, f"表头缺列：{col}（实际 {head}）"

            # 分页条（共 N 条）
            assert "共" in page.locator("main").inner_text() and "条" in page.locator("main").inner_text(), \
                "缺分页条（共 N 条）"

            # 顶部「＋ 导入」按钮存在；无「新建」按钮（数据来源铁律：唯一写入口=导入）
            assert page.locator('button:visible:has-text("导入")').count() >= 1, "缺「＋ 导入」按钮"
            assert page.locator('button:visible:has-text("新建")').count() == 0, "本页不应有「新建」按钮"

            # ===================== §0 自足造数 =====================
            step("§0 自足造数（版本 + 物料 + 主计划行）")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"造数失败：{seed}"

            # ===================== §2 造数后列表有数据 =====================
            step("§2 列表含主计划行 + 过滤抽样")
            page.reload()
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.evaluate("location.hash = '#/master_plan'")
            page.wait_for_selector('table tbody tr.data:has-text("M1")', timeout=15000)
            page.wait_for_timeout(500)

            assert page.locator("table tbody tr.data").count() >= 2, "master_plan 造数后列表无数据"

            # MP1 行：M1 × N+1 × v1 × 950（fmt 无千分位，plan_version 渲染为 v{plan_version}）
            mp1 = page.locator('table tbody tr.data:has-text("M1")').first
            txt1 = mp1.inner_text()
            for expected in ["M1", "N+1", "v1", "950", "202608", "2026-09-30"]:
                assert expected in txt1, f"MP1 行缺值：{expected}（实际 {txt1}）"

            # MP2 行：M2 × N+1 × v1 × 500
            mp2 = page.locator('table tbody tr.data:has-text("M2")').first
            txt2 = mp2.inner_text()
            for expected in ["M2", "N+1", "v1", "500", "202608", "2026-09-25"]:
                assert expected in txt2, f"MP2 行缺值：{expected}（实际 {txt2}）"

            # VT-LIST-02 过滤抽样：物料号精确匹配 M1 → 收敛（含 M1、不含 M2）
            kw = page.locator('main input[placeholder*="物料号"]:visible').first
            kw.click()
            kw.fill("M1")
            page.wait_for_timeout(300)
            drop = page.locator(".auto-drop:visible")
            assert drop.count() > 0, "过滤条物料 autocomplete 未展开"
            assert "物料M1" in drop.first.inner_text(), "过滤 autocomplete 未回显物料名称"
            select_autocomplete(page, "M1")
            page.wait_for_timeout(700)
            try:
                page.locator('table tbody tr.data:has-text("M2")').first.wait_for(state="detached", timeout=5000)
            except Exception:
                pass
            assert page.locator('table tbody tr.data:has-text("M1")').count() >= 1, "过滤后缺 M1 行"
            assert page.locator('table tbody tr.data:has-text("M2")').count() == 0, "过滤 M1 后不应有 M2 行"

            # ===================== §3 详情模态全字段 =====================
            step("§3 详情模态全字段 + 只读页脚")
            row = page.locator('table tbody tr.data:has-text("M1")').first
            row.locator(".b-link").first.click()
            modal = open_modal(page)
            wait_modal(page)
            txt = modal.locator(".modal-bd").first.inner_text()

            for expected in [
                "计划版本号", "v1", "物料号", "M1", "物料名称", "物料M1", "滚动月度", "N+1",
                "月度版本", "202608", "需求量", "950", "最迟入库日期", "2026-09-30",
            ]:
                assert expected in txt, f"master_plan 详情模态缺字段：{expected}"

            # 原始数据 details.raw 可展开（6 字段 JSON）
            raw = modal.locator("details.raw")
            assert raw.count() > 0, "详情模态缺「原始数据」details.raw"
            raw.locator("summary").first.click()
            page.wait_for_timeout(200)
            pre = raw.locator("pre.json").first.inner_text()
            for k in ["material_no", "version_no", "rolling_month", "plan_version", "plan_qty", "latest_inbound_date"]:
                assert f'"{k}"' in pre, f"原始数据缺字段：{k}"

            # 页脚无操作按钮（无状态机 · 无可用操作）
            ft = modal.locator(".modal-ft").inner_text()
            assert ("无状态机" in ft) or ("无可用操作" in ft), f"详情页脚缺只读说明：{ft}"
            assert modal.locator(".modal-ft button:visible").count() == 0, "详情页脚不应有操作按钮"
            close_modal(page, modal)

            # ===================== §4 导入表单（唯一写入口）=====================
            step("§4 导入表单（VT-FORM-01 批量行录入 + plan_version 自增）")
            page.locator('button:visible:has-text("＋ 导入")').first.click()
            modal = open_modal(page)
            choose_option(modal, "月度版本", value="202608")

            fill_import_row(page, modal, 0, "M1", "N+1", 820, "2026-10-15")
            modal.locator('button:visible:has-text("＋ 添加行")').first.click()
            page.wait_for_timeout(250)
            fill_import_row(page, modal, 1, "M2", "N+2", 640, "2026-11-20")

            modal.locator('.modal-ft button:has-text("导入")').first.click()
            page.wait_for_timeout(800)
            toasts = page.locator(".toasts .toast").all_inner_texts()
            assert any("已导入 · 新版本 v2" in t for t in toasts), f"导入 toast 缺新版本 v2：{toasts}"

            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(500)

            # 列表回显：首行（plan_version DESC 最新在前）M1 × N+1 × v2，且含 M2 × N+2 × v1
            page.wait_for_selector('table tbody tr.data:has-text("v2")', timeout=10000)
            first_row = page.locator("table tbody tr.data").first
            ftxt = first_row.inner_text()
            assert "M1" in ftxt and "N+1" in ftxt and "v2" in ftxt and "820" in ftxt, \
                f"导入后首行未回显 M1×N+1×v2：{ftxt}"
            assert page.locator('table tbody tr.data:has-text("M2")').filter(has_text="N+2").count() >= 1, \
                "导入后缺 M2×N+2 行"

            step("§4 导入表单（VT-FORM-02 必填空值预校验）")
            page.locator('button:visible:has-text("＋ 导入")').first.click()
            modal = open_modal(page)
            modal.locator('.modal-ft button:has-text("导入")').first.click()
            page.wait_for_timeout(300)
            toasts = page.locator(".toasts .toast").all_inner_texts()
            assert any("请选择月度版本" in t for t in toasts), f"缺版本预校验 toast：{toasts}"
            assert modal.is_visible(), "空版本预校验后模态应保持打开"

            # 选版本后行物料号仍空 → 触发行级预校验
            choose_option(modal, "月度版本", value="202608")
            modal.locator('.modal-ft button:has-text("导入")').first.click()
            page.wait_for_timeout(300)
            toasts = page.locator(".toasts .toast").all_inner_texts()
            assert any("第 1 行物料号不能为空" in t for t in toasts), f"缺行物料号预校验 toast：{toasts}"
            assert modal.is_visible(), "行物料号空预校验后模态应保持打开"
            close_modal(page, modal)

            step("§4 导入表单（VT-FORM-03 逐行校验回显 · 部分成功）")
            page.locator('button:visible:has-text("＋ 导入")').first.click()
            modal = open_modal(page)
            choose_option(modal, "月度版本", value="202608")

            fill_import_row(page, modal, 0, "M1", "N+2", 300, "2026-10-20")
            modal.locator('button:visible:has-text("＋ 添加行")').first.click()
            page.wait_for_timeout(250)
            # 第 2 行负数需求量（min 属性不阻止程序化 fill，直达后端逐行校验）
            fill_import_row(page, modal, 1, "M2", "N+3", -5, "2026-11-25")

            modal.locator('.modal-ft button:has-text("导入")').first.click()
            page.wait_for_timeout(800)
            toasts = page.locator(".toasts .toast").all_inner_texts()
            assert any("导入完成 · 成功 1 行 / 失败 1 行" in t for t in toasts), f"部分失败 toast：{toasts}"
            assert modal.is_visible(), "部分失败时模态不应关闭"

            err_tbl = modal.locator("table.tbl.tight").filter(has_text="行号")
            assert err_tbl.count() >= 1, "缺导入失败明细表"
            etxt = err_tbl.first.inner_text()
            assert "2" in etxt and "plan_qty" in etxt and "需求量不能为负" in etxt, \
                f"失败明细不符：{etxt}"
            close_modal(page, modal)

            # 合法行 M1 × N+2 已入库
            page.wait_for_timeout(500)
            assert page.locator('table tbody tr.data:has-text("M1")').filter(has_text="N+2").count() >= 1, \
                "合法行 M1×N+2 未入库"

            # ===================== §6 0 报错红线 =====================
            step("§6 0 报错红线")
            assert not errors, f"前端报错：{errors[:5]}"
            print("VERIFY_VIEW_psc_master_plan: PASS")

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
