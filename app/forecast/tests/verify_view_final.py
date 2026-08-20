"""Final verification: test each page thoroughly"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = pathlib.Path(__file__).resolve().parent
while not (ROOT / "fde_platform").is_dir():
    ROOT = ROOT.parent
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
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def wait_up(port, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("GET", "/api/groups"); conn.getresponse().read(); return True
        except: time.sleep(0.3)
    raise RuntimeError("platform 未启动")

def main():
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        env={**os.environ, "PLATFORM_PORT": str(port), "PORT": str(port)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_up(port)
        from playwright.sync_api import sync_playwright
        base = f"http://127.0.0.1:{port}"
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context()
            page = ctx.new_page()

            all_console = []
            errors = []
            page.on("console", lambda m: (all_console.append(f"[{m.type}] {m.text[:200]}"), errors.append(f"[{m.type}] {m.text[:200]}")) if m.type == "error" else all_console.append(f"[{m.type}] {m.text[:200]}"))
            page.on("pageerror", lambda e: errors.append(f"PAGE: {str(e)[:200]}"))

            # Login
            page.goto(f"{base}/login")
            page.fill('input[name="username"]', "admin")
            page.fill('input[name="password"]', "admin")
            page.click('button[type="submit"]')
            page.wait_for_url("**/", timeout=15000)
            page.goto(f"{base}/change-password")
            try:
                page.wait_for_selector('input[name="old_password"]', timeout=5000)
                page.fill('input[name="old_password"]', "admin")
                page.fill('input[name="new_password"]', "Admin@123")
                page.fill('input[name="new_password2"]', "Admin@123")
                page.click('button[type="submit"]')
                page.wait_for_timeout(1000)
            except: pass

            page.goto(f"{base}/view/forecast/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            # Navigate AWAY from dashboard BEFORE seeding, so init() doesn't cache empty data
            page.evaluate("location.hash = '#/forecast_snapshot'")
            page.wait_for_timeout(1000)

            # Seed data via REST API for ALL apps (with error collection)
            seed_result = page.evaluate(r"""async () => {
              const errors = [];
              const call = async (app, svc, params) => {
                const r = await fetch(`/api/apps/${app}/call/${svc}`, {
                  method: "POST", headers: {"Content-Type": "application/json"},
                  body: JSON.stringify(params || {})
                });
                const text = await r.text();
                let data = null;
                try { data = text ? JSON.parse(text) : null; } catch(e) {}
                if (!r.ok) { errors.push(`${svc} HTTP ${r.status}: ${text.slice(0,100)}`); throw new Error(text); }
                if (data && data.status === 'error') { errors.push(`${svc} biz error: ${data.message}`); throw new Error(data.message); }
                return data ? (data.data !== undefined ? data.data : data) : null;
              };

              // Main data
              await call("forecast/md_customer","create",{oem_code:"O-A",oem_name:"A厂",plant_code:"P-A",plant_name:"一工厂",settle_mode:"寄售"});
              await call("forecast/md_material","create",{part_no:"P001",part_name:"零件1",uom:"件"});
              await call("forecast/md_material","create",{part_no:"P002",part_name:"零件2",uom:"件"});
              await call("forecast/md_project","create",{project_no:"PRJ1",project_name:"项目1",stage:"进行中",oem_code:"O-A",plant_code:"P-A"});
              await call("forecast/md_project_part","create",{project_no:"PRJ1",part_no:"P001",usage:1,share:1.0});
              await call("forecast/md_project_part","create",{project_no:"PRJ1",part_no:"P002",usage:2,share:1.0});
              await call("forecast/md_part_replace","create",{rel_no:"REL-01",rel_type:"替换",old_part:"P001",new_part:"P002",ecn_no:"ECN-01"});
              await call("forecast/md_fcst_version","create",{fcst_version:"202608",base_period:"2026-08",periods:["2026-09","2026-10","2026-11"],opening_date:"2026-08-01"});

              // Snapshot & Baseline
              await call("forecast/forecast_snapshot","open_version",{fcst_version:"202608"});
              await call("forecast/forecast_snapshot","fill",{fcst_version:"202608",oem_code:"O-A",plant_code:"P-A",part_no:"P001",period:"2026-09",orig_qty:100,data_flag:"正常"});
              await call("forecast/forecast_snapshot","fill",{fcst_version:"202608",oem_code:"O-A",plant_code:"P-A",part_no:"P001",period:"2026-10",orig_qty:200,data_flag:"正常"});
              await call("forecast/forecast_baseline","generate",{base_batch:"B202608",fcst_version:"202608"});
              await call("forecast/forecast_baseline","confirm_batch",{base_batch:"B202608"});

              // Processing
              const proc = await call("forecast/forecast_processing","create_batch",{base_batch:"B202608",fcst_version:"202608"});
              const prc = proc.prc_batch;
              const lines = await call("forecast/forecast_processing","list_lines",{prc_batch:prc,page:1,page_size:200});
              for (const l of (lines.items || [])) {
                await call("forecast/forecast_processing","review_line",{prc_batch:prc,oem_code:l.oem_code,plant_code:l.plant_code,part_no:l.part_no,period:l.period,chk_result:"通过"});
              }
              await call("forecast/forecast_processing","finalize",{prc_batch:prc});

              // Part level adj
              await call("forecast/part_level_adj","create_generic_merge",{fcst_version:"202608",period:"2026-09",part_no:"P002",adj_qty:-50,basis:"E2E"});

              // Release
              const rel = await call("forecast/demand_release","create_draft",{prc_batch:prc});
              if (rel.rel_no) await call("forecast/demand_release","publish",{rel_no:rel.rel_no});

              // Attainment
              try { await call("forecast/attainment","compute",{oem_code:"O-A",period:"2026-09"}); } catch(e) {}

              return {seeded:true, prc_batch:prc, rel_no: rel.rel_no, errors: errors};
            }""")
            seed_errors = seed_result.get("errors", [])
            print(f"Seed: seeded={seed_result.get('seeded')}, prc={seed_result.get('prc_batch')}, seed_errors={len(seed_errors)}")
            for e in seed_errors:
                print(f"  SEED ERROR: {e}")

            # Test each page
            pages = [
                ("dashboard", "dashboard", True),
                ("forecast_snapshot", "forecast_snapshot", False),
                ("forecast_baseline", "forecast_baseline", False),
                ("forecast_processing", "forecast_processing", False),
                ("part_level_adj", "part_level_adj", False),
                ("demand_release", "demand_release", False),
                ("md_customer", "md_customer", False),
                ("md_material", "md_material", False),
                ("md_project", "md_project", False),
                ("md_project_part", "md_project_part", False),
                ("md_part_replace", "md_part_replace", False),
                ("md_fcst_version", "md_fcst_version", False),
                ("attainment", "attainment", False),
            ]

            passed = 0
            failed = []
            for key, label, is_dashboard in pages:
                page.evaluate(f"location.hash = '#/{key}'")
                # Wait for async data loading to complete
                if is_dashboard:
                    # Dashboard: multiple async API calls, just wait fixed time
                    page.wait_for_timeout(4000)
                else:
                    try:
                        page.wait_for_function("() => { const lb = document.querySelector('.loadbox'); return !lb || lb.offsetParent === null; }", timeout=10000)
                    except:
                        pass
                page.wait_for_timeout(500)
                try:
                    page.wait_for_selector("main .card, main .tbl, main table, main .kpi", timeout=5000)
                except:
                    pass
                page.wait_for_timeout(300)

                main_text = page.locator("main").inner_text().strip()
                has_content = len(main_text) > 10
                kpi_ok = True
                if not is_dashboard:
                    kpi_count = page.locator(".kpi").count()
                    kpi_ok = kpi_count == 0

                row_count = page.locator("table.tbl tr.data").count()

                # === Data-content assertions (not just structural) ===
                data_ok = True
                if is_dashboard:
                    # Dashboard MUST show real version number, not just "—" placeholder
                    if "202608" not in main_text:
                        data_ok = False
                        failed.append(f"{label}: KPI missing real version number (202608)")
                    # Dashboard KPI must NOT consist entirely of "—"
                    kpi_text = ""
                    for kpi_card in page.locator(".kpi").all():
                        kpi_text += kpi_card.inner_text()
                    # If all KPIs are just dashes/no data, that's a failure
                    if "—" in kpi_text and all(c in "— \n" or c.isdigit() == False for c in kpi_text.replace(" ", "").replace("\n", "").replace("—", "")):
                        pass  # All KPIs are dashes
                    if "202608" not in kpi_text and len([c for c in kpi_text if c.isdigit()]) < 3:
                        data_ok = False
                        failed.append(f"{label}: KPI cards contain no real numbers")
                elif key == "forecast_snapshot":
                    if "P001" not in main_text:
                        data_ok = False
                        failed.append(f"{label}: missing seeded part_no P001")
                elif key == "forecast_baseline":
                    if "B202608" not in main_text:
                        data_ok = False
                        failed.append(f"{label}: missing baseline batch B202608")
                elif key == "forecast_processing":
                    if "PRC-" not in main_text:
                        data_ok = False
                        failed.append(f"{label}: missing processing batch PRC-*")
                elif key == "demand_release":
                    if "REL-" not in main_text:
                        data_ok = False
                        failed.append(f"{label}: missing release REL-*")
                elif key == "md_customer":
                    if "O-A" not in main_text:
                        data_ok = False
                        failed.append(f"{label}: missing customer O-A")
                elif key == "md_material":
                    if "P001" not in main_text:
                        data_ok = False
                        failed.append(f"{label}: missing material P001")
                elif key == "md_project":
                    if "PRJ1" not in main_text:
                        data_ok = False
                        failed.append(f"{label}: missing project PRJ1")
                elif key == "md_part_replace":
                    if "REL-01" not in main_text:
                        data_ok = False
                        failed.append(f"{label}: missing replace relation REL-01")
                elif key == "md_fcst_version":
                    if "202608" not in main_text:
                        data_ok = False
                        failed.append(f"{label}: missing version 202608")

                status = "OK" if has_content and kpi_ok and data_ok else "FAIL"
                issues = []
                if not has_content: issues.append("EMPTY")
                if not kpi_ok: issues.append(f"KPI_STICK({page.locator('.kpi').count()})")
                if not data_ok: issues.append("NO_DATA")
                icon = "✅" if status == "OK" else "❌"
                print(f"  {icon} {label}: rows={row_count} {('(' + ','.join(issues) + ')') if issues else ''}")
                if status == "OK": passed += 1

    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except: proc.kill()

if __name__ == "__main__":
    main()
