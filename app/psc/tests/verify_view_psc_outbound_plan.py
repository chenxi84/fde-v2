"""e2e 前端验收 - psc:outbound_plan（出库计划）
断言：路由渲染防粘滞 → 造数后列表有数据（状态 chips / 待出库与已关闭徽章）
→ 详情模态全字段 → 新建落库（客户下拉 + 物料 autocomplete）+ 前端校验
→ 已关闭计划编辑延期恢复待出库 → 删除（仅待出库，confirm）→ 全程 0 console error /
0 pageerror / 0 HTTP≥400。
运行：python app/psc/tests/verify_view_psc_outbound_plan.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit, sqlite3


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

# seed_admin 落 password_changed=0 → 首登被强制改密闸门拦下（auth.py ②.5），先置 1 放行。
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


# §0 自足造数：md_material M1 + md_customer C001 + 两条出库计划
# （未来日期 → 待出库；过去日期 → 创建即已关闭，供延期恢复用例）
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
    if (data && (data.ok === false || data.error || data.status === "error")) {
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

  await call("md_material", "create", {material_no: "M1", material_name: "测试物料A", status: "正常"});
  await call("md_customer", "create", {customer_no: "C001", customer_name: "客户A"});
  const open = unwrap(await call("outbound_plan", "create", {
    customer_no: "C001", material_no: "M1", qty: 300, out_date: "2026-09-20"
  }));
  const closed = unwrap(await call("outbound_plan", "create", {
    customer_no: "C001", material_no: "M1", qty: 50, out_date: "2026-08-10"
  }));

  return {
    seeded: true,
    open_no: (open && open.plan_no) || null,
    closed_no: (closed && closed.plan_no) || null,
    closed_status: (closed && closed.status) || null
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
    """等 .modal-mask:visible 出现、.loadbox 消失，返回可见模态。"""
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
            step("§0 造数（M1 / C001 / 待出库 + 已关闭出库计划）")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"outbound_plan 造数失败：{seed}"
            assert seed.get("open_no"), f"待出库计划号缺失：{seed}"
            assert seed.get("closed_status") == "已关闭", f"过去日期计划应创建即已关闭：{seed}"
            open_no = seed["open_no"]
            closed_no = seed["closed_no"]

            # ===================== §1 本页渲染（防粘滞）=====================
            step("§1 路由渲染防粘滞")
            page.evaluate("location.hash = '#/outbound_plan'")
            try:
                page.wait_for_selector("main .card", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator("main").inner_text().strip(), "outbound_plan 页面无内容"
            assert page.locator("main .card").count() > 0, "outbound_plan 未渲染 card"
            assert page.locator(".kpi:visible").count() == 0, "outbound_plan 挂载未重建（残留看板）"
            assert page.locator('button:visible:has-text("+ 新建出库计划")').count() > 0, "工具栏缺「+ 新建出库计划」"
            assert page.locator('button:visible:has-text("查询")').count() > 0, "工具栏缺「查询」"
            assert page.locator('button:visible:has-text("重置")').count() > 0, "工具栏缺「重置」"
            assert page.locator("table.tbl").count() > 0, "缺 .tbl 表格"
            assert "共" in page.locator("main").inner_text(), "缺分页条"
            page.wait_for_selector(".fchip", timeout=10000)

            # ===================== §2 造数后列表有数据 =====================
            step("§2 LIST-01 列表含所造计划（状态徽章）")
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 2, f"造数后列表应为 2 条，实际 {rows.count()}"
            open_row = rows.filter(has_text=open_no).first
            open_txt = open_row.inner_text()
            assert "M1" in open_txt and "C001" in open_txt, "待出库行应回显物料/客户"
            assert "300" in open_txt, "待出库行应回显数量 300"
            assert "2026-09-20" in open_txt, "待出库行应回显计划出库日期"
            assert "待出库" in open_txt, "待出库行状态徽章应为 待出库"
            assert open_row.locator('button:visible:has-text("删除")').count() == 1, "待出库行应有删除入口"
            closed_row = rows.filter(has_text=closed_no).first
            assert "已关闭" in closed_row.inner_text(), "过去日期行状态徽章应为 已关闭"
            # x-show 隐藏不销毁 DOM，按可见性断言
            assert closed_row.locator('button:visible:has-text("删除")').count() == 0, "已关闭行不应有删除入口"

            step("§2 LIST-02 状态 chips 过滤")
            page.locator(".fchip", has_text="已关闭").first.click()
            page.wait_for_timeout(700)
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 1, f"已关闭过滤应仅 1 条，实际 {rows.count()}"
            assert rows.filter(has_text=closed_no).count() == 1, "已关闭过滤应含到期计划"
            page.locator(".fchip", has_text="待出库").first.click()
            page.wait_for_timeout(700)
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 1, f"待出库过滤应仅 1 条，实际 {rows.count()}"
            page.locator(".fchip", has_text="全部").first.click()
            page.wait_for_timeout(700)

            # ===================== §3 模态全字段 =====================
            step("§3 MODAL-01 详情模态全字段")
            page.locator("table.tbl tr.data .b-link", has_text=open_no).first.click()
            modal = wait_modal(page)
            txt = modal.inner_text()
            for label in ["计划号", "客户", "物料", "数量", "计划出库日期", "实际出库单号", "原始数据"]:
                assert label in txt, f"详情模态缺字段标签：{label}"
            for val in [open_no, "C001", "客户A", "M1", "测试物料A", "300", "2026-09-20", "待出库"]:
                assert val in txt, f"详情模态缺字段值：{val}"
            ft = modal.locator(".modal-ft")
            assert ft.locator('button:visible:has-text("编辑")').count() == 1, "详情页脚应有「编辑」"
            close_modal(page, modal)

            # ===================== §4 表单 =====================
            step("§4 FORM-01 新建落库（客户下拉 + 物料 autocomplete）")
            click_button(page, ["+ 新建出库计划"])
            modal = wait_modal(page)
            assert "新建出库计划" in modal.inner_text(), "新建弹窗标题不符"
            modal.locator("select").first.select_option(value="C001")
            mat_input = modal.locator('input[placeholder*="搜索物料号"]').first
            mat_input.click()
            page.wait_for_timeout(200)
            mat_input.fill("M1")
            page.wait_for_timeout(300)
            modal.locator('.autocomplete-drop div:has-text("测试物料A")').first.click()
            page.wait_for_timeout(200)
            fill_labeled(modal, "数量", "120")
            fill_labeled(modal, "计划出库日期", "2026-10-10")
            fill_labeled(modal, "实际出库单号", "OUT-0001")
            click_button(modal, ["创建"])
            expect_toast(page, "出库计划创建成功")
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 3, f"新建后列表应为 3 条，实际 {rows.count()}"
            new_row = rows.filter(has_text="2026-10-10").first
            new_txt = new_row.inner_text()
            assert "120" in new_txt and "OUT-0001" in new_txt and "待出库" in new_txt, \
                f"新建行回显不符：{new_txt}"
            new_no = new_row.locator(".b-link").first.inner_text().strip()

            step("§4 FORM-02 数量缺失前端校验")
            click_button(page, ["+ 新建出库计划"])
            modal = wait_modal(page)
            modal.locator("select").first.select_option(value="C001")
            mat_input = modal.locator('input[placeholder*="搜索物料号"]').first
            mat_input.click()
            page.wait_for_timeout(200)
            mat_input.fill("M1")
            page.wait_for_timeout(300)
            modal.locator('.autocomplete-drop div:has-text("测试物料A")').first.click()
            fill_labeled(modal, "计划出库日期", "2026-10-12")
            # 数量留空
            click_button(modal, ["创建"])
            expect_toast(page, "出库数量必须大于 0")
            assert modal.is_visible(), "数量缺失被拒后模态应保持打开"
            close_modal(page, modal)

            step("§4 FORM-03 后端校验：物料不存在（直接输入非法物料号）")
            click_button(page, ["+ 新建出库计划"])
            modal = wait_modal(page)
            modal.locator("select").first.select_option(value="C001")
            mat_input = modal.locator('input[placeholder*="搜索物料号"]').first
            mat_input.fill("NO_SUCH_MAT")
            page.wait_for_timeout(200)
            fill_labeled(modal, "数量", "10")
            fill_labeled(modal, "计划出库日期", "2026-10-12")
            click_button(modal, ["创建"])
            expect_toast(page, "物料记录不存在")
            assert modal.is_visible(), "非法物料被拒后模态应保持打开"
            close_modal(page, modal)

            # ===================== §5 延期恢复 + 删除 =====================
            step("§5 EDIT-01 已关闭计划编辑延期 → 恢复待出库")
            page.locator("table.tbl tr.data", has_text=closed_no).first.locator('button:has-text("编辑")').first.click()
            modal = wait_modal(page)
            assert "编辑出库计划" in modal.inner_text(), "编辑弹窗标题不符"
            fill_labeled(modal, "计划出库日期", "2026-11-01")
            click_button(modal, ["保存修改"])
            expect_toast(page, "出库计划已更新")
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            row_txt = page.locator("table.tbl tr.data", has_text=closed_no).first.inner_text()
            assert "2026-11-01" in row_txt, "延期后日期应回显 2026-11-01"
            assert "待出库" in row_txt, "延期到未来后状态应恢复 待出库"

            step("§5 DEL-01 删除待出库计划（confirm）")
            dialogs = []
            page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
            page.locator("table.tbl tr.data", has_text=new_no).first.locator('button:has-text("删除")').first.click()
            page.wait_for_timeout(700)
            assert len(dialogs) == 1, f"删除应触发 confirm，实际 {len(dialogs)}"
            assert page.locator("table.tbl tr.data", has_text=new_no).count() == 0, "删除后该行应消失"
            assert page.locator("table.tbl tr.data").count() == 2, "删除后列表应为 2 条"

            # ===================== §6 0 报错红线 =====================
            step("§6 会话 0 报错")
            assert not errors, f"outbound_plan 会话前端报错：{errors[:5]}"
            print("VERIFY_VIEW_psc_outbound_plan: PASS")

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
        print(f"VERIFY_VIEW_psc_outbound_plan: FAIL @ {STEP}: {e}")
        sys.exit(1)
