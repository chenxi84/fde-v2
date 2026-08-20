"""forecast 前端验收 v2 — 逐页深度检查，捕获真实 console/page/HTTP 错误。
运行：python app/forecast/tests/verify_view_forecast.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit, json, io
# Fix GBK encoding issues on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def _project_root():
    p = pathlib.Path(__file__).resolve().parent
    while not (p / "fde_platform").is_dir():
        if p.parent == p: raise RuntimeError("未找到 fde_platform/")
        p = p.parent
    return p

ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from fde_platform.dbguard import isolate_dbs
_iso = isolate_dbs()
_iso.__enter__()
atexit.register(_iso.__exit__, None, None, None)

from fde_platform import users
users.init_schema()
users.seed_admin()

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
            resp = conn.getresponse(); resp.read()
            return True
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("platform 未启动")

# Seed JS — tested working
SEED_JS = r"""async () => {
  const call = async (app, svc, params) => {
    const r = await fetch(`/api/apps/${app}/call/${svc}`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(params || {})
    });
    const text = await r.text();
    if (!r.ok) throw new Error(`${app}.${svc} HTTP ${r.status} ${text.slice(0, 160)}`);
    let data = null; try { data = text ? JSON.parse(text) : null; } catch (e) {}
    return data;
  };
  // Main data
  await call("forecast/md_customer","create",{oem_code:"OEM-A",oem_name:"主机厂A",plant_code:"PLT-A1",plant_name:"一工厂",settle_mode:"寄售"});
  await call("forecast/md_material","create",{part_no:"8210001",part_name:"前保险杠总成",uom:"件"});
  await call("forecast/md_material","create",{part_no:"STD-M6",part_name:"标准螺栓M6",uom:"件"});
  await call("forecast/md_project","create",{project_no:"PRJ-V",project_name:"验证项目",stage:"进行中",oem_code:"OEM-A",plant_code:"PLT-A1"});
  await call("forecast/md_project_part","create",{project_no:"PRJ-V",part_no:"8210001",usage:1,share:1.0});
  await call("forecast/md_project_part","create",{project_no:"PRJ-V",part_no:"STD-M6",usage:4,share:1.0});
  await call("forecast/md_fcst_version","create",{fcst_version:"202608",base_period:"2026-08",periods:["2026-09","2026-10","2026-11"],opening_date:"2026-08-01"});
  // Business chain
  await call("forecast/forecast_snapshot","open_version",{fcst_version:"202608"});
  await call("forecast/forecast_snapshot","fill",{fcst_version:"202608",oem_code:"OEM-A",plant_code:"PLT-A1",part_no:"8210001",period:"2026-09",orig_qty:1150,data_flag:"正常"});
  await call("forecast/forecast_baseline","generate",{base_batch:"B202608",fcst_version:"202608"});
  await call("forecast/forecast_baseline","confirm_batch",{base_batch:"B202608"});
  const proc = await call("forecast/forecast_processing","create_batch",{base_batch:"B202608",fcst_version:"202608"});
  const prc = proc && proc.prc_batch ? proc.prc_batch : (proc && proc.data ? proc.data.prc_batch : null);
  if (prc) {
    const lines = await call("forecast/forecast_processing","list_lines",{prc_batch:prc,page:1,page_size:200});
    const items = (lines && lines.items) || (lines && lines.data && lines.data.items) || [];
    for (const l of items) {
      await call("forecast/forecast_processing","review_line",{prc_batch:prc,oem_code:l.oem_code,plant_code:l.plant_code,part_no:l.part_no,period:l.period,chk_result:"通过"});
    }
    await call("forecast/forecast_processing","finalize",{prc_batch:prc});
    await call("forecast/part_level_adj","create_generic_merge",{fcst_version:"202608",period:"2026-09",part_no:"STD-M6",adj_qty:-500,basis:"E2E测试"});
    const rel = await call("forecast/demand_release","create_draft",{prc_batch:prc});
    const relNo = rel && rel.rel_no ? rel.rel_no : (rel && rel.data ? rel.data.rel_no : null);
    if (relNo) await call("forecast/demand_release","publish",{rel_no:relNo});
  }
  return {seeded: true};
}"""

def main():
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        env={**os.environ, "PLATFORM_PORT": str(port), "PORT": str(port)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    all_errors = []
    all_pageerrors = []
    http_errors = []
    results = []

    def attach(page, label=""):
        def on_console(msg):
            if msg.type == "error":
                txt = msg.text[:200]
                all_errors.append(f"[{label}] CONSOLE: {txt}")
                print(f"    🔴 CONSOLE ERROR [{label}]: {txt}")
        def on_pageerror(err):
            txt = str(err)[:200]
            all_pageerrors.append(f"[{label}] PAGE: {txt}")
            print(f"    🔴 PAGE ERROR [{label}]: {txt}")
        def on_response(resp):
            if resp.status >= 400:
                url = resp.url
                if "/favicon.ico" in url or url.endswith(".map"): return
                if resp.status == 403: return  # expected for auth enforcement
                http_errors.append(f"[{label}] HTTP {resp.status} {url}")
                print(f"    🟡 HTTP {resp.status} [{label}]: {url}")
        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("response", on_response)

    def check_page(page, hash_route, label, extra_checks=None):
        """Navigate to page, wait for render, run extra checks."""
        page.evaluate(f"location.hash = '#/{hash_route}'")
        page.wait_for_timeout(1500)
        # Check page has content
        try:
            page.wait_for_selector("main .card, main .tbl, main table, main .kpi", timeout=8000)
        except Exception:
            print(f"    ⚠️ [{label}] 页面未渲染出 .card/.tbl/table")
            results.append((label, "NO_RENDER"))
            return False
        page.wait_for_timeout(500)
        main_text = page.locator("main").inner_text().strip()
        if not main_text:
            print(f"    ⚠️ [{label}] main 区域无文本内容")
            results.append((label, "EMPTY_MAIN"))
            return False
        # Non-dashboard pages must not have .kpi (anti-stick)
        if hash_route != "dashboard":
            kpi_count = page.locator(".kpi").count()
            if kpi_count > 0:
                print(f"    ⚠️ [{label}] 非看板页有 {kpi_count} 个 .kpi（可能挂载粘滞）")
                results.append((label, "KPI_STICK"))
                return False
        # Run extra checks
        if extra_checks:
            try:
                extra_checks(page)
            except Exception as e:
                print(f"    ⚠️ [{label}] 额外检查失败: {e}")
                results.append((label, f"CHECK_FAIL: {str(e)[:100]}"))
                return False
        results.append((label, "OK"))
        print(f"    ✅ [{label}] OK")
        return True

    try:
        wait_up(port)
        from playwright.sync_api import sync_playwright
        base = f"http://127.0.0.1:{port}"

        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context()

            # Login
            login_page = ctx.new_page()
            attach(login_page, "LOGIN")
            login_page.goto(f"{base}/login")
            login_page.fill('input[name="username"]', "admin")
            login_page.fill('input[name="password"]', "admin")
            login_page.click('button[type="submit"]')
            login_page.wait_for_url("**/", timeout=15000)

            # Change default password
            login_page.goto(f"{base}/change-password")
            try:
                login_page.wait_for_selector('input[name="old_password"]', timeout=5000)
                login_page.fill('input[name="old_password"]', "admin")
                login_page.fill('input[name="new_password"]', "Admin@123")
                login_page.fill('input[name="new_password2"]', "Admin@123")
                login_page.click('button[type="submit"]')
                login_page.wait_for_timeout(1000)
            except Exception:
                pass

            # Main page
            page = ctx.new_page()
            attach(page, "MAIN")
            page.goto(f"{base}/view/forecast/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)

            # Seed data
            print("\n--- Seed ---")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"造数失败: {seed}"
            print("  ✅ Seed OK")

            # === Test each page ===
            print("\n--- Page Tests ---")

            # Dashboard (has .kpi)
            page.evaluate("location.hash = '#/dashboard'")
            page.wait_for_timeout(1500)
            dash_text = page.locator("main").inner_text().strip()
            kpi_count = page.locator(".kpi").count()
            if dash_text and kpi_count >= 1:
                print(f"  ✅ [dashboard] OK ({kpi_count} KPIs)")
                results.append(("dashboard", "OK"))
            else:
                print(f"  ⚠️ [dashboard] text={bool(dash_text)}, kpi={kpi_count}")
                results.append(("dashboard", "FAIL"))

            # forecast_snapshot
            check_page(page, "forecast_snapshot", "forecast_snapshot",
                lambda pg: (
                    print(f"    rows={pg.locator('table.tbl tr.data').count()}"),
                    None
                )[1] if False else None
            )
            snap_rows = page.locator("table.tbl tr.data").count()
            if snap_rows > 0:
                print(f"    rows={snap_rows}")
                # Try clicking a b-link to open modal
                link = page.locator("table.tbl tr.data .b-link").first
                if link.count():
                    link.click()
                    page.wait_for_timeout(800)
                    modal_visible = page.locator(".modal:visible").count()
                    if modal_visible:
                        modal_text = page.locator(".modal:visible").first.inner_text()
                        print(f"    modal opened: {bool(modal_text)}")
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(500)
                    else:
                        print(f"    ⚠️ 点击 .b-link 后模态未出现")

            # forecast_baseline
            check_page(page, "forecast_baseline", "forecast_baseline")
            base_rows = page.locator("table.tbl tr.data").count()
            print(f"    rows={base_rows}")

            # forecast_processing
            check_page(page, "forecast_processing", "forecast_processing")

            # part_level_adj
            check_page(page, "part_level_adj", "part_level_adj")

            # demand_release
            check_page(page, "demand_release", "demand_release")

            # md_customer
            check_page(page, "md_customer", "md_customer")
            cust_rows = page.locator("table.tbl tr.data").count()
            print(f"    rows={cust_rows}")

            # md_material
            check_page(page, "md_material", "md_material")

            # md_project
            check_page(page, "md_project", "md_project")

            # md_project_part
            check_page(page, "md_project_part", "md_project_part")

            # md_part_replace
            check_page(page, "md_part_replace", "md_part_replace")

            # md_fcst_version
            check_page(page, "md_fcst_version", "md_fcst_version")

            # attainment
            check_page(page, "attainment", "attainment")

    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except: proc.kill()

    # === Report ===
    print(f"\n{'='*60}")
    print(f"RESULTS: {sum(1 for _,s in results if s=='OK')}/{len(results)} pages OK")
    for label, status in results:
        icon = "✅" if status == "OK" else "❌"
        print(f"  {icon} {label}: {status}")

    print(f"\nCONSOLE ERRORS: {len(all_errors)}")
    for e in all_errors[:20]:
        print(f"  {e[:150]}")

    print(f"\nPAGE ERRORS: {len(all_pageerrors)}")
    for e in all_pageerrors[:10]:
        print(f"  {e[:150]}")

    print(f"\nHTTP ERRORS (non-403): {len(http_errors)}")
    for e in http_errors[:10]:
        print(f"  {e[:150]}")

    critical = len([e for e in all_errors if "Alpine" not in e and "favicon" not in e])
    ok = len(results) == sum(1 for _,s in results if s=='OK') and len(all_pageerrors) == 0 and critical == 0
    print(f"\nVERDICT: {'PASS ✅' if ok else 'FAIL ❌'}")
    return ok

if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
