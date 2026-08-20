"""e2e 前端验收 · psc/需求池（demand_pool，playwright，可直接运行）。
断言：本页路由渲染（.kpi==0 防粘滞）→ 造数后列表有数据 → 模态全字段 →
状态机操作（自动参考创建，无表单豁免 + 无创建入口）→ 全程 0 console error /
0 pageerror / 0 HTTP≥400。
运行：python app/psc/tests/verify_view_psc_demand_pool.py
"""
import sqlite3
import os, pathlib, socket, subprocess, sys, time, http.client, atexit


def _project_root() -> pathlib.Path:
    """向上找项目根（含 fde_platform/ 的目录），按标记定位，不写死层级。"""
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
try:
    _auth_db = ROOT / "config" / "auth.db"
    if _auth_db.exists():
        _conn = sqlite3.connect(str(_auth_db))
        _conn.execute("UPDATE users SET password_changed = 1 WHERE username = 'admin'")
        _conn.commit()
        _conn.close()
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


# 造数链（§0 数据字典）：md_material.create(M1) + demand_pool.create(RP1~RP7) + 状态机推进。
# replenish_no 为系统生成，从返回捕获串联；应用名用组限定名（与 view/api.js 的 svc 解析一致）。
SEED_JS = r"""async () => {
  const call = async (app, svc, params) => {
    const r = await fetch(`/api/apps/${app}/call/${svc}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(params || {})
    });
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) {}
    if (!r.ok || (data && data.status === "error")) {
      throw new Error(`${app}.${svc} HTTP ${r.status} ${text.slice(0, 160)}`);
    }
    return (data && data.data !== undefined) ? data.data : data;
  };
  const no = (x) => (x && x.replenish_no) || null;

  await call("psc/md_material", "create", { material_no: "M1", material_name: "物料A" });

  const rp1 = await call("psc/demand_pool", "create", {
    material_no: "M1", replenish_type: "缺货补库", replenish_qty: 100, required_inbound: "2026-08-20"
  });
  const rp2 = await call("psc/demand_pool", "create", {
    material_no: "M1", replenish_type: "最低库存补库", replenish_qty: 200, required_inbound: "2026-08-21"
  });
  const rp3 = await call("psc/demand_pool", "create", {
    material_no: "M1", replenish_type: "安全库存补库", replenish_qty: 300, required_inbound: "2026-08-22"
  });
  const rp4 = await call("psc/demand_pool", "create", {
    material_no: "M1", replenish_type: "缺货补库", replenish_qty: 110, required_inbound: "2026-08-23"
  });
  const rp5 = await call("psc/demand_pool", "create", {
    material_no: "M1", replenish_type: "缺货补库", replenish_qty: 120, required_inbound: "2026-08-24"
  });
  const rp6 = await call("psc/demand_pool", "create", {
    material_no: "M1", replenish_type: "缺货补库", replenish_qty: 130, required_inbound: "2026-08-25"
  });
  const rp7 = await call("psc/demand_pool", "create", {
    material_no: "M1", replenish_type: "安全库存补库", replenish_qty: 310, required_inbound: "2026-08-26"
  });

  const n1 = no(rp1), n2 = no(rp2), n3 = no(rp3);
  const n4 = no(rp4), n5 = no(rp5), n6 = no(rp6), n7 = no(rp7);

  await call("psc/demand_pool", "release", { replenish_no: n4, promised_inbound: "2026-08-20" });
  await call("psc/demand_pool", "release", { replenish_no: n5 });
  await call("psc/demand_pool", "on_workorder_started", { replenish_no: n5 });
  await call("psc/demand_pool", "release", { replenish_no: n6 });
  await call("psc/demand_pool", "on_workorder_started", { replenish_no: n6 });
  await call("psc/demand_pool", "on_inbound", { replenish_no: n6 });
  await call("psc/demand_pool", "cancel", { replenish_no: n7 });

  return {
    seeded: true, material: "M1",
    RP1: n1, RP2: n2, RP3: n3, RP4: n4, RP5: n5, RP6: n6, RP7: n7
  };
}"""


STEP = "启动"


def step(name):
    global STEP
    STEP = name


def wait_modal(page, timeout=10000):
    """等可见模态出现，且 .loadbox 载入消失后再读（pitfalls #16）；多 mask 仅一个可见。"""
    page.locator(".modal-mask:visible .modal").first.wait_for(state="visible", timeout=timeout)
    try:
        page.locator(".modal-mask:visible .loadbox").wait_for(state="hidden", timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(200)
    return page.locator(".modal-mask:visible .modal").last


def close_modal(page):
    x = page.locator(".modal-mask:visible button.x").first
    if x.count():
        x.click()
    else:
        page.keyboard.press("Escape")
    page.wait_for_timeout(250)


def data_row(page, no):
    return page.locator("table.tbl tr.data").filter(has_text=no).first


def chip(page, text):
    page.locator(".fchip").filter(has_text=text).first.click()
    page.wait_for_timeout(300)


def field_value(modal, label):
    cell = modal.locator(".modal-bd .kv > div").filter(has_text=label).first
    if cell.count() == 0:
        return None
    return cell.locator(".v").first.inner_text().strip()


def wait_rows(page, n, timeout=10000):
    page.wait_for_function(
        f"document.querySelectorAll('table.tbl tr.data').length === {n}", timeout=timeout
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

            # ===================== §1 本页路由渲染（防粘滞） =====================
            step("§1 路由渲染")
            page.evaluate("location.hash = '#/demand_pool'")
            try:
                page.wait_for_selector("main .card", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator("main .card").count() > 0, "demand_pool 页面未渲染 .card"
            assert page.locator(".kpi").count() == 0, "demand_pool 页残留看板 .kpi（挂载未重建）"
            main_txt = page.locator("main").inner_text()
            assert "需求池台账" in main_txt, "主区未含「需求池台账」"
            assert "上一页" in main_txt and "下一页" in main_txt, "分页条缺失 上一页/下一页"

            # ===================== §0 造数 =====================
            step("§0 造数")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"造数失败：{seed}"
            RP1 = seed["RP1"]; RP2 = seed["RP2"]; RP3 = seed["RP3"]
            RP4 = seed["RP4"]; RP5 = seed["RP5"]; RP6 = seed["RP6"]; RP7 = seed["RP7"]
            for k, v in seed.items():
                if k.startswith("RP"):
                    assert v, f"造数未返回 {k} 的 replenish_no"

            # 造数后 reload：重扫注册表 + 页面重拉列表（pitfalls #6）
            page.reload()
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.wait_for_function(
                "document.querySelectorAll('table.tbl tr.data').length >= 7", timeout=15000
            )
            page.wait_for_timeout(400)

            # ===================== §2 列表 =====================
            step("§2 列表有数据")
            header_txt = page.locator("table.tbl tr").first.inner_text()
            for label in ["补库单号", "补库类型", "状态", "物料号", "补库数量", "要求入库时间", "承诺入库时间"]:
                assert label in header_txt, f"表头缺列：{label}"

            row1 = data_row(page, RP1)
            assert row1.count() > 0, f"列表未含 RP1（{RP1}）"
            r1_txt = row1.inner_text()
            assert RP1 in r1_txt, "RP1 行未回显单号"
            assert "缺货补库" in r1_txt, "RP1 行未回显补库类型"
            assert "待下达" in r1_txt, "RP1 行未回显状态"
            assert "100" in r1_txt, "RP1 行未回显补库数量"

            # VT-LIST-02 物料号过滤（M1）
            step("§2 物料过滤")
            mat = page.locator('input[placeholder*="全部物料"]').first
            mat.click()
            mat.fill("M1")
            page.wait_for_timeout(300)
            opt = page.locator('div[x-show="materialOpen"] > div').filter(has_text="M1").first
            opt.wait_for(state="visible", timeout=5000)
            opt.click()
            wait_rows(page, 7)
            # 清空物料过滤（✕ 按钮）
            clear = page.locator('button:has-text("✕")').first
            if clear.count():
                clear.click()
                page.wait_for_timeout(400)

            # VT-LIST-03 补库类型过滤（缺货补库）
            step("§2 类型过滤")
            chip(page, "缺货补库")
            wait_rows(page, 4)
            tbl_txt = page.locator("table.tbl").inner_text()
            assert "最低库存补库" not in tbl_txt and "安全库存补库" not in tbl_txt, \
                "缺货补库过滤混入最低/安全库存补库行"

            # VT-LIST-04 状态过滤（待下达）
            step("§2 状态过滤")
            chip(page, "全部类型")
            chip(page, "待下达")
            wait_rows(page, 3)
            tbl_txt = page.locator("table.tbl").inner_text()
            for s in ["已下达", "生产中", "已完成", "已取消"]:
                assert s not in tbl_txt, f"待下达过滤混入 {s} 行"

            # VT-LIST-05 组合过滤 + 无匹配空态
            step("§2 组合过滤+空态")
            chip(page, "缺货补库")   # type=缺货补库 + status=待下达
            wait_rows(page, 1)
            assert RP1 in page.locator("table.tbl tr.data").first.inner_text(), \
                "缺货补库+待下达应仅回显 RP1"
            chip(page, "已取消")     # type=缺货补库 + status=已取消 → 空态
            wait_rows(page, 0)
            assert page.locator("td.empty").filter(has_text="无匹配数据").count() == 1, \
                "组合无匹配未显示空态「无匹配数据」"

            # 过滤状态复位（reload 全量列表）
            page.reload()
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.wait_for_function(
                "document.querySelectorAll('table.tbl tr.data').length >= 7", timeout=15000
            )
            page.wait_for_timeout(400)

            # ===================== §3 模态全字段 =====================
            # VT-MODAL-01 RP4 详情模态全字段（含 promised_inbound）
            step("§3 模态全字段")
            data_row(page, RP4).locator("button.b-link.mono").first.click()
            modal = wait_modal(page)
            txt = modal.inner_text()
            for label in ["补库单号", "状态", "补库类型", "物料号", "补库数量", "要求入库时间", "承诺入库时间"]:
                assert label in txt, f"详情模态缺字段：{label}"
            for val in [RP4, "已下达", "缺货补库", "M1", "110", "2026-08-23", "2026-08-20"]:
                assert val in txt, f"详情模态缺值：{val}"
            assert modal.locator(".modal-bd details.raw summary").count() > 0, \
                "详情模态缺「原始数据」"
            close_modal(page)

            # VT-MODAL-02 RP1 待下达：页脚 下达 + 取消 可见，promised_inbound 为 —
            step("§3 待下达页脚")
            data_row(page, RP1).locator("button.b-link.mono").first.click()
            modal = wait_modal(page)
            btns = modal.locator(".modal-ft button:visible").all_inner_texts()
            assert any("下达" in t for t in btns), "待下达模态页脚缺「下达」"
            assert any("取消" in t for t in btns), "待下达模态页脚缺「取消」"
            assert field_value(modal, "承诺入库时间") == "—", "待下达模态 promised_inbound 应为 —"
            close_modal(page)

            # VT-MODAL-03 RP4 已下达：页脚仅 取消，无 下达
            step("§3 已下达页脚")
            data_row(page, RP4).locator("button.b-link.mono").first.click()
            modal = wait_modal(page)
            btns = modal.locator(".modal-ft button:visible").all_inner_texts()
            assert not any("下达" in t for t in btns), "已下达模态不应出现「下达」"
            assert any("取消" in t for t in btns), "已下达模态应保留「取消」"
            close_modal(page)

            # VT-MODAL-04 终态（生产中/已完成/已取消）：无可用操作
            step("§3 终态无操作")
            for rp in [RP5, RP6, RP7]:
                data_row(page, rp).locator("button.b-link.mono").first.click()
                modal = wait_modal(page)
                assert "无可用操作" in modal.inner_text(), f"{rp} 终态模态缺「无可用操作」"
                btns = modal.locator(".modal-ft button:visible").all_inner_texts()
                assert not any(("下达" in t or "取消" in t) for t in btns), \
                    f"{rp} 终态模态不应出现动作按钮"
                close_modal(page)

            # ===================== §4 状态机（表单豁免 + 无创建入口） =====================
            # VT-STATE-01 下达：RP1 待下达 → 已下达（toast 回显 + 模态 promised 回显）
            step("§4 下达")
            data_row(page, RP1).locator("button", has_text="下达").first.click()
            date_input = page.locator(".modal-mask:visible input[type=date]").first
            date_input.wait_for(state="visible", timeout=5000)
            date_input.fill("2026-08-20")
            page.locator(".modal-mask:visible button:has-text('确认下达')").first.click()
            toast = page.locator(".toast").filter(has_text="已下达").first
            toast.wait_for(state="visible", timeout=5000)
            assert RP1 in toast.inner_text(), f"下达 toast 未含 {RP1}"
            page.wait_for_timeout(600)
            row1 = data_row(page, RP1)
            assert "已下达" in row1.inner_text(), "RP1 下达后行状态未变 已下达"
            row1.locator("button.b-link.mono").first.click()
            modal = wait_modal(page)
            assert "已下达" in modal.inner_text(), "RP1 下达后模态未显示 已下达"
            assert field_value(modal, "承诺入库时间") == "2026-08-20", \
                "RP1 下达后模态 promised_inbound 应为 2026-08-20"
            close_modal(page)

            # VT-STATE-02 取消：RP3 待下达 → 已取消（toast 回显）
            step("§4 取消")
            data_row(page, RP3).locator("button", has_text="取消").first.click()
            page.locator(".modal-mask:visible button:has-text('确认取消')").first.click()
            toast = page.locator(".toast").filter(has_text="已取消").first
            toast.wait_for(state="visible", timeout=5000)
            assert RP3 in toast.inner_text(), f"取消 toast 未含 {RP3}"
            page.wait_for_timeout(600)
            assert "已取消" in data_row(page, RP3).inner_text(), "RP3 取消后行状态未变 已取消"

            # VT-STATE-03 已下达行按钮集：仅 取消，无 下达
            step("§4 已下达行按钮")
            btns = data_row(page, RP4).locator(".rowact button:visible").all_inner_texts()
            assert not any("下达" in t for t in btns), "已下达行不应出现「下达」"
            assert any("取消" in t for t in btns), "已下达行应保留「取消」"

            # VT-STATE-04 终态行无操作按钮
            step("§4 终态行无按钮")
            for rp in [RP5, RP6, RP7]:
                assert data_row(page, rp).locator(".rowact button:visible").count() == 0, \
                    f"{rp} 终态行不应出现操作按钮"

            # VT-STATE-05 无创建入口（自动参考创建铁律）
            step("§4 无创建入口")
            main_btns = page.locator("main button:visible, main a:visible").all_inner_texts()
            for f in ["新建", "创建", "批量导入", "添加"]:
                assert not any(f in t for t in main_btns), f"自动参考创建页不应出现「{f}」入口"

            # ===================== §6 0 报错红线 =====================
            step("§6 0报错")
            assert not errors, f"前端报错：{errors[:5]}"
            print("VERIFY_VIEW_psc_demand_pool: PASS")

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
        print(f"VERIFY_VIEW_psc_demand_pool: FAIL @ {STEP}")
        print(f"  {e}")
        sys.exit(1)
