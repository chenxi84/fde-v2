"""e2e 前端验收 - psc:sales_history（历史台账）
列表渲染（4 列、无新建/操作列）+ 过滤 + 名称回显 + 批量导入回显 + 非法行错误明细 + 0 报错红线。
运行：python app/psc/tests/verify_view_psc_sales_history.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit, sqlite3


def _project_root():
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
_auth_db = ROOT / "config" / "auth.db"
if _auth_db.exists():
    _c = sqlite3.connect(str(_auth_db))
    _c.execute("UPDATE users SET password_changed = 1 WHERE username = 'admin'")
    _c.commit()
    _c.close()


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
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            c.request("GET", "/")
            c.getresponse()
            return True
        except Exception:
            time.sleep(0.3)
    return False


SEED_JS = r"""async () => {
  const call = async (app, svc, body) => {
    const r = await fetch(`/api/apps/psc/${app}/call/${svc}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
    const t = await r.text(); let d = null;
    try { d = t ? JSON.parse(t) : null; } catch (e) {}
    if (!r.ok) throw new Error(`${app}.${svc} HTTP ${r.status} ${t.slice(0, 160)}`);
    if (d && (d.ok === false || d.error)) throw new Error(`${app}.${svc} biz ${t.slice(0, 160)}`);
    return d;
  };
  await call("md_material", "create", { material_no: "M1", material_name: "前保险杠总成" });
  await call("md_customer", "create", { customer_no: "C001", customer_name: "客户A" });
  await call("sales_history", "import_batch", { rows: [
    { material_no: "M1", customer_no: "C001", period: "2026-01", qty: 900 },
    { material_no: "M1", customer_no: "C001", period: "2026-02", qty: 950 },
  ]});
  return { seeded: true };
}"""


def main():
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        env={**os.environ, "PLATFORM_PORT": str(port), "PORT": str(port)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    atexit.register(proc.kill)
    assert wait_up(port), "platform 未在限定时间内启动"

    errors = []

    def attach(page):
        def on_console(m):
            if m.type == "error":
                errors.append(m.text[:200])
        def on_pageerror(e):
            errors.append(str(e)[:200])
        def on_response(r):
            if r.status >= 400 and "/favicon.ico" not in r.url and not r.url.endswith(".map"):
                errors.append(f"HTTP {r.status} {r.url}")
        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("response", on_response)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        login = ctx.new_page()
        attach(login)
        login.goto(f"http://127.0.0.1:{port}/login")
        login.fill('input[name="username"]', "admin")
        login.fill('input[name="password"]', "admin")
        login.click('button[type="submit"]')
        login.wait_for_url("**/", timeout=15000)

        page = ctx.new_page()
        attach(page)
        page.goto(f"http://127.0.0.1:{port}/view/psc/")
        page.wait_for_selector(".rail, .menu, nav", timeout=15000)

        # §0 造数
        seed = page.evaluate(SEED_JS)
        assert seed and seed.get("seeded"), f"sales_history 造数失败：{seed}"

        page.evaluate("location.hash = '#/sales_history'")
        page.wait_for_selector("main .card", timeout=15000)
        page.wait_for_timeout(600)

        # §1 渲染：4 列表头、无新建按钮、无操作列
        header = page.locator("table.tbl.tight tr").first.inner_text()
        for col in ["期间", "物料号", "客户号", "数量"]:
            assert col in header, f"表头缺列：{col}"
        assert "操作" not in header, "历史台账不应有操作列"
        assert page.locator('button:has-text("新建")').count() == 0, "历史台账不应有新建按钮"

        # §2 行渲染 + 名称回显
        page.wait_for_selector('table tr.data:has-text("2026-01")', timeout=10000)
        row = page.locator('table tr.data:has-text("2026-01")').first.inner_text()
        for v in ["2026-01", "M1", "C001", "900", "前保险杠总成", "客户A"]:
            assert v in row, f"行缺字段：{v}（{row!r}）"

        # §3 过滤：期间过滤收敛
        page.locator('input[placeholder="物料号"]').first.fill("M1")
        page.locator('button:has-text("查询")').first.click()
        page.wait_for_timeout(500)
        assert page.locator("table tr.data").count() == 2, "过滤 M1 应 2 条"
        page.locator('input[placeholder="物料号"]').first.fill("NOPE")
        page.locator('button:has-text("查询")').first.click()
        page.wait_for_timeout(500)
        assert page.locator("table tr.data").count() == 0, "过滤 NOPE 应 0 条"
        page.locator('button:has-text("重置")').first.click()
        page.wait_for_timeout(500)

        # §4 导入：粘贴合法行 → 成功回显
        page.locator('button:has-text("批量导入")').first.click()
        modal = page.locator(".modal-mask:visible .modal").first
        modal.locator("textarea").first.fill("M1,C001,2026-03,1000")
        modal.locator('button:has-text("批量导入")').last.click()
        page.wait_for_timeout(700)
        assert "成功 1 条" in modal.inner_text(), "导入应成功 1 条"
        modal.locator('button:has-text("关闭")').first.click()
        page.wait_for_timeout(500)
        page.wait_for_selector('table tr.data:has-text("2026-03")', timeout=10000)

        # §4.2 导入：非法期间行 → 失败明细
        page.locator('button:has-text("批量导入")').first.click()
        modal = page.locator(".modal-mask:visible .modal").first
        modal.locator("textarea").first.fill("M1,C001,2026-13,1")
        modal.locator('button:has-text("批量导入")').last.click()
        page.wait_for_timeout(700)
        assert "失败 1 条" in modal.inner_text(), "非法期间应失败 1 条"
        assert "period" in modal.inner_text(), "错误明细应含字段 period"
        modal.locator('button:has-text("关闭")').first.click()

        # §6 0 报错红线
        assert not errors, f"sales_history 会话前端报错：{errors[:5]}"
        print("VERIFY_VIEW_psc_sales_history: PASS")

        browser.close()


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"FAIL: {e}")
        sys.exit(1)
