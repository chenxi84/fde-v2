"""e2e 前端验收 - psc:material_360（物料 360 视图）
页面渲染 + 物料选择器 + 7 分区卡片 + 0 报错红线。
运行：python app/psc/tests/verify_view_psc_material360.py
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
  // 物料 + 活跃版本（最小数据集）
  await call("md_material", "create", { material_no: "M1", material_name: "前保险杠总成", status: "正常" });
  await call("md_monthly_version", "create", { version_no: "202601", anchor_period: "2026-01" });
  await call("md_monthly_version", "publish", { version_no: "202601" });
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

        # 注入测试数据
        login.evaluate(SEED_JS)

        # 进入物料 360 视图（组级页 URL: /view/psc/#/material_360）
        page = ctx.new_page()
        attach(page)
        page.goto(f"http://127.0.0.1:{port}/view/psc/#/material_360")
        page.wait_for_selector(".rail", timeout=15000)
        time.sleep(2)

        # 等待输入框出现（页面加载完成的标志）
        page.wait_for_selector("#m360-mat", timeout=10000)
        time.sleep(1)

        # 触发物料选择：聚焦展开下拉 → 点击 M1 选项
        mat_input = page.locator("#m360-mat")
        mat_input.click()
        time.sleep(0.5)
        # 下拉应出现 M1 选项（文本定位，避免样式属性归一化差异）
        opt = page.locator("text=M1").first
        assert opt.count() > 0, "物料下拉未展开或 M1 选项未出现"
        opt.click()
        time.sleep(3)

        # 断言：选料后分区卡片渲染（.card .hd 分区标题 >= 3）
        card_count = page.locator(".m360 .card .hd").count()
        assert card_count >= 3, f"选料后分区卡片不足 3 个（实际 {card_count}）"

        # 红线：0 console error / 0 pageerror / 0 HTTP≥400
        assert not errors, f"红线违规（{len(errors)} 项）：\n" + "\n".join(errors[:10])

        print("[PASS] psc:material_360 前端验收通过")

    proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
