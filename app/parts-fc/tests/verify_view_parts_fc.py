"""e2e 前端验收 - parts-fc 组级（壳/菜单序/dashboard/受限用户）
断言：壳启动品牌与菜单序 → dashboard KPI/管道/待办渲染 → 受限用户菜单收敛/直访回落 → 全程 0 报错。
运行：python app/parts-fc/tests/verify_view_parts_fc.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit


def _project_root() -> pathlib.Path:
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
_ok, _msg = users.create_role("limited_role", "受限测试角色")
assert _ok, _msg
_ok, _msg = users.set_role_page_grants("limited_role", [
    "parts-fc:dashboard", "parts-fc:project_ledger", "parts-fc:vehicle_part_map", "_platform:agent"
])
assert _ok, _msg
_ok, _msg = users.create_user("limited_pfc", "Limited@123", "limited_role", [], "U400", "D001")
assert _ok, _msg
LIMITED_USER, LIMITED_PWD = "limited_pfc", "Limited@123"

MENU_ORDER = [
    "首页看板", "项目信息台账", "车型零件映射", "需求收集", "需求加工",
    "基线借用", "独立事件", "策略拟合", "通用件汇总", "牛鞭修正", "需求发布", "预测考核"
]
LIMITED_MENU = ["首页看板", "项目信息台账", "车型零件映射", "Agent"]


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


DASH_SEED_JS = r"""async () => {
  const call = async (app, svc, params) => {
    const r = await fetch(`/api/apps/${app}/call/${svc}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(params || {})
    });
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) {}
    if (!r.ok) throw new Error(`${app}.${svc} HTTP ${r.status} ${text.slice(0, 160)}`);
    if (data && (data.ok === false || data.error)) {
      throw new Error(`${app}.${svc} biz ${JSON.stringify(data).slice(0, 160)}`);
    }
    return data;
  };

  const unwrap = (x) => {
    if (!x) return x;
    if (x.data !== undefined) return x.data;
    if (x.result !== undefined) return x.result;
    return x;
  };

  // 跨应用前置：车型映射 + 项目台账
  await call("vehicle_part_map", "create", {
    part_no: "DASH-PART-001", veh_model: "DASH-MODEL-A", usage: 1, share: 100,
    lc_stage: "成熟", lc_shape: "传统", sop: "2025-01", source: "BOM"
  });
  await call("project_ledger", "create", {
    project_no: "DASH-PRJ-001", part_no: "DASH-PART-001", oem_code: "OEM-A",
    plant_code: "PLANT-1", veh_model: "DASH-MODEL-A", part_kind: "专用",
    sop: "2025-01", owner_sales: "S001"
  });

  // KPI 数据：草稿收集单 + 进行中批次 + 已发布发布单
  const dc = await call("demand_collection", "create", {
    oem_code: "OEM-A", plant_code: "PLANT-1", fcst_version: "V2026-08-DASH",
    base_period: "2026-08"
  });
  const dp = await call("demand_processing", "create_batch", {
    fcst_version: "V2026-08-DASH", oem_code: "OEM-A", plant_code: "PLANT-1"
  });
  const dr = await call("demand_release", "create_draft", {base_period: "2026-08"});

  // 独立事件：待确认 + 确认生效
  const ie = await call("independent_event", "create", {
    event_type: "水位脉冲", part_no: "DASH-PART-001", period: "2026-09",
    event_qty: 500, source_basis: "阶跃检测", oem_code: "OEM-A", veh_model: "DASH-MODEL-A"
  });
  const ieData = unwrap(ie);
  const ieNo = ieData && (ieData.event_no || ieData.no);
  if (ieNo) {
    await call("independent_event", "confirm", {event_no: ieNo});
  }

  return {seeded: true, dc_no: unwrap(dc), dp_batch: unwrap(dp), dr_no: unwrap(dr)};
}"""


def click_button(scope, texts):
    for t in texts:
        loc = scope.locator(
            f'button:has-text("{t}"), a:has-text("{t}"), .btn:has-text("{t}")'
        )
        if loc.count():
            loc.first.click()
            return True
    raise AssertionError(f"未找到按钮：{texts}")


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

            # admin 会话
            ctx = browser.new_context()
            login_page = ctx.new_page()
            attach(login_page)

            login_page.goto(f"{base}/login")
            login_page.fill('input[name="username"]', "admin")
            login_page.fill('input[name="password"]', "admin")
            login_page.click('button[type="submit"]')
            login_page.wait_for_timeout(3000)
            # After first login, change default password to satisfy platform security
            try:
                login_page.fill('input[name="old_password"]', "admin")
                login_page.fill('input[name="new_password"]', "Admin@123")
                login_page.fill('input[name="confirm_password"]', "Admin@123")
                login_page.click('button[type="submit"]')
                login_page.wait_for_timeout(2000)
            except Exception:
                pass  # change-password page may redirect or not appear
            login_page.wait_for_url("**/", timeout=15000)

            page = ctx.new_page()
            attach(page)

            # ===================== §1 壳启动与菜单序 =====================
            page.goto(f"{base}/view/parts-fc/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.wait_for_selector("header.top h1", timeout=10000)
            page.wait_for_timeout(800)

            nav_txt = page.locator(".rail, .menu, nav").first.inner_text()

            # 品牌
            assert any(w in nav_txt.upper() for w in ["FDE", "PARTS-FC", "PARTS_FC"]), \
                f"侧栏未见品牌标识：{nav_txt[:120]}"

            # 菜单项集合（12项）
            for item in MENU_ORDER:
                assert item in nav_txt, f"菜单缺失：{item}"

            # 菜单序：首页看板居首
            dash_idx = nav_txt.index("首页看板") if "首页看板" in nav_txt else -1
            ledger_idx = nav_txt.index("项目信息台账") if "项目信息台账" in nav_txt else 999
            assert 0 <= dash_idx < ledger_idx, f"菜单序错误：首页看板({dash_idx}) 应在项目信息台账({ledger_idx})之前"

            # 默认路由
            page.wait_for_timeout(500)

            # ===================== §1 dashboard 页渲染 =====================
            seed = page.evaluate(DASH_SEED_JS)
            assert seed and seed.get("seeded"), f"Dashboard 造数失败：{seed}"

            page.evaluate("location.hash = '#/dashboard'")
            page.wait_for_selector(".kpi", timeout=15000)
            page.wait_for_timeout(1500)

            # KPI 数 > 0（与各应用页防粘滞断言互为镜像）
            assert page.locator(".kpi").count() > 0, "Dashboard KPI 区域未渲染"

            kpi_txt = page.locator(".kpi").first.inner_text()
            assert any(w in kpi_txt for w in ["待收集", "待修正", "已发布"]), \
                f"Dashboard KPI 缺预期指标：{kpi_txt[:120]}"

            # 主链管道区存在
            pipeline_loc = page.locator(".pipeline-node, .pipeline, .flow-node")
            if pipeline_loc.count() > 0:
                pipe_txt = pipeline_loc.first.inner_text()
                assert any(w in pipe_txt for w in ["收集", "加工", "通用件", "牛鞭", "发布"]), \
                    f"主链管道缺节点：{pipe_txt[:120]}"

            # 待办队列区存在
            todo_loc = page.locator('.card:has-text("待办"), .card:has-text("待核对"), .todo')
            assert todo_loc.count() > 0, "Dashboard 待办队列区未渲染"

            # 快捷入口区存在
            quick_loc = page.locator('.card:has-text("项目信息台账"), .card:has-text("车型零件映射")')
            assert quick_loc.count() > 0, "Dashboard 快捷入口区未渲染"

            # ===================== §3 dashboard 待办跳转连通 =====================
            kpi_collect = page.locator('.kpi:has-text("待收集"), [class*="kpi"]:has-text("待收集")').first
            if kpi_collect.count():
                kpi_collect.click()
                page.wait_for_timeout(1000)
                assert "#/demand_collection" in page.evaluate("location.hash"), \
                    "KPI 待收集跳转失败"

            page.evaluate("location.hash = '#/dashboard'")
            page.wait_for_timeout(800)

            quick_ledger = page.locator('.card:has-text("项目信息台账"), a:has-text("项目信息台账")').first
            if quick_ledger.count():
                quick_ledger.click()
                page.wait_for_timeout(1000)
                assert "#/project_ledger" in page.evaluate("location.hash"), \
                    "快捷入口项目信息台账跳转失败"

            # ===================== §5 受限用户菜单收敛 =====================
            # 受限用户有数据（admin 会话已造好 project_ledger 数据用于隐式放行测试）
            seed_pl = page.evaluate(r"""async () => {
              const call = async (app, svc, params) => {
                const r = await fetch(`/api/apps/${app}/call/${svc}`, {
                  method: "POST", headers: {"Content-Type": "application/json"},
                  body: JSON.stringify(params || {})
                });
                const text = await r.text();
                if (!r.ok) throw new Error(`${app}.${svc} HTTP ${r.status}`);
                let data = null;
                try { data = text ? JSON.parse(text) : null; } catch (e) {}
                return data;
              };
              await call("project_ledger", "create", {
                project_no: "LIM-PRJ-001", part_no: "LIM-PART-001", oem_code: "OEM-A",
                plant_code: "PLANT-1", veh_model: "LIM-MODEL-A", part_kind: "专用",
                sop: "2025-01", owner_sales: "S001"
              });
              return {seeded: true};
            }""")
            assert seed_pl and seed_pl.get("seeded"), "受限用户前置造数失败"

            limited_ctx = browser.new_context()
            limited_page = limited_ctx.new_page()
            attach(limited_page)

            state["limited"] = True

            limited_page.goto(f"{base}/login")
            limited_page.fill('input[name="username"]', LIMITED_USER)
            limited_page.fill('input[name="password"]', LIMITED_PWD)
            limited_page.click('button[type="submit"]')
            limited_page.wait_for_url("**/", timeout=15000)

            limited_page.goto(f"{base}/view/parts-fc/")
            limited_page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            limited_page.wait_for_timeout(800)

            limited_menu_txt = limited_page.locator(".rail, .menu, nav").first.inner_text()

            # 菜单收敛：授权页可见，未授权页不可见
            for item in LIMITED_MENU:
                assert item in limited_menu_txt, f"受限菜单缺授权页：{item}"
            forbidden = ["需求收集", "需求加工", "基线借用", "独立事件", "策略拟合",
                         "通用件汇总", "牛鞭修正", "需求发布", "预测考核"]
            for item in forbidden:
                assert item not in limited_menu_txt, f"受限菜单泄漏未授权页：{item}"

            # 直访无授权路由回落
            limited_page.evaluate("location.hash = '#/demand_collection'")
            limited_page.wait_for_timeout(1200)
            header_txt = limited_page.locator("header.top h1").first.inner_text()
            assert ("首页看板" in header_txt) or ("需求预测总览" in header_txt), \
                f"受限用户直访 demand_collection 应回落看板：{header_txt[:120]}"

            # 授权页隐式放行有数据
            limited_page.evaluate("location.hash = '#/project_ledger'")
            limited_page.wait_for_timeout(3000)
            try:
                limited_page.wait_for_selector("table tbody tr", timeout=15000)
            except Exception:
                pass
            row_count = limited_page.locator("table tbody tr").count()
            assert row_count >= 1, "受限用户 project_ledger 隐式放行无数据"

            # ===================== §6 组级会话 0 报错 =====================
            assert not errors, f"组级会话前端报错：{errors[:5]}"
            print("VERIFY_VIEW_parts_fc: PASS —— 壳/菜单序/dashboard/受限用户/0报错")

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
        print(f"FAIL: {e}")
        sys.exit(1)
