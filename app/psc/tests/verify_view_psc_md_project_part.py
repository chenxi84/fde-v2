"""e2e 前端验收 - psc:md_project_part（项目零件映射）
断言：路由渲染防粘滞（.kpi==0）→ 造数后列表有数据 → 详情模态全字段 → 创建/编辑表单落库回显
（复合主键 project_no+material_no 编辑态只读 + 项目/物料双 autocomplete 下拉）→ 全程 0 console error
/ 0 pageerror / 0 HTTP≥400。
运行：python app/psc/tests/verify_view_psc_md_project_part.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit, sqlite3


def _project_root() -> pathlib.Path:
    """向上找项目根（含 fde_platform/ 的目录）。不用 parents[N] 定死层级——
    本脚本落在 app/psc/tests/ 下，按标记定位才稳。"""
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

# admin 会话（逐应用脚本单会话）：空库播种 admin/admin 后标记已改密，绕过「请先修改默认密码」。
from fde_platform import users  # noqa: E402
users.init_schema()
users.seed_admin()
try:
    conn = sqlite3.connect(str(ROOT / "config" / "auth.db"))
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
    if (data && data.status === "error") {
      throw new Error(`${app}.${svc} biz ${JSON.stringify(data).slice(0, 160)}`);
    }
    return data;
  };

  // 跨应用前置：项目（车型/份额为项目级信息）/ 物料主数据（§0 字典自足）
  await call("md_project", "create", {project_no: "PRJ-1", project_name: "项目一", owner: "S001", stage: "进行中", veh_model: "车型A", share: 0.8});
  await call("md_project", "create", {project_no: "PRJ-2", project_name: "项目二", owner: "S001", stage: "进行中", veh_model: "车型C", share: 0.6});
  await call("md_material", "create", {material_no: "M1", material_name: "前保险杠总成", status: "正常"});
  await call("md_material", "create", {material_no: "M2", material_name: "后保险杠总成", status: "正常"});

  // 本页主数据：3 条映射（只存单车用量；车型/份额关联项目），复合主键 (project_no, material_no)
  await call("md_project_part", "create", {project_no: "PRJ-1", material_no: "M1", usage: 2});
  await call("md_project_part", "create", {project_no: "PRJ-1", material_no: "M2", usage: 1});
  await call("md_project_part", "create", {project_no: "PRJ-2", material_no: "M1", usage: 3});

  return {seeded: true};
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
    # 页面可能同时挂多个 .modal（详情 + 创建/编辑 + 导入），.last 会取到隐藏的那个；
    # 改为等「可见」的模态，再取可见者中的 last。
    page.locator(".modal:visible, [role='dialog']:visible").first.wait_for(state="visible", timeout=10000)
    return page.locator(".modal:visible, [role='dialog']:visible").last


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


STEP = ""


def step(name):
    global STEP
    STEP = name
    print(f"  → {name}", flush=True)


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
            ctx = browser.new_context()

            # admin 会话
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

            # ===================== §0 造数（跨应用前置自足） =====================
            step("§0 造数（项目/物料/映射）")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"md_project_part 造数失败：{seed}"

            # ===================== §1 本页路由渲染（防粘滞） =====================
            step("§1 路由渲染防粘滞")
            page.evaluate("location.hash = '#/md_project_part'")
            try:
                page.wait_for_selector("main .card", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            assert page.locator("main").inner_text().strip(), "md_project_part 页面无内容"
            assert page.locator("main .card").count() > 0, "md_project_part 未渲染 card"
            assert page.locator(".kpi").count() == 0, "md_project_part 挂载未重建（残留看板）"

            # ===================== §2 列表有数据 =====================
            step("§2 列表有数据")
            try:
                page.wait_for_selector("table tr.data", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(500)
            assert page.locator("table tr.data").count() >= 3, "md_project_part 造数后列表无数据"

            pp1 = page.locator('table tr.data:has-text("PRJ-1"):has-text("M1")').first
            assert pp1.count() > 0, "列表缺 PRJ-1/M1 映射行"
            pp1_txt = pp1.inner_text()
            assert "80%" in pp1_txt, "PP1 share 未按百分比格式化（应 80%）"
            assert "车型A" in pp1_txt and "2" in pp1_txt, "PP1 veh_model/usage 列未回显"

            # ===================== §3 详情模态全字段 =====================
            step("§3 详情模态全字段")
            page.locator('table tr.data:has-text("PRJ-1"):has-text("M1")').first.locator(".b-link").first.click()
            modal = open_modal(page)
            txt = modal.inner_text()
            for expected in ["PRJ-1 × M1", "项目号", "物料号", "车型", "单车用量", "供应份额",
                             "车型A", "2", "80%", "项目一", "前保险杠总成", "原始数据"]:
                assert expected in txt, f"详情模态缺字段：{expected}"

            ft = modal.locator(".modal-ft").first.inner_text()
            assert "编辑" in ft and "关闭" in ft, "详情页脚缺 编辑/关闭 按钮"
            assert "删除" not in ft, "详情页脚不应有删除按钮（契约无 delete）"
            close_modal(page, modal)

            # ===================== §4 表单落库回显（创建 + 编辑） =====================
            step("§4.1 创建表单 autocomplete 下拉 + 落库")
            click_button(page, ["新建映射", "新建"])
            modal = open_modal(page)

            # 项目号 autocomplete：下拉含两个项目，选 PRJ-2
            proj_input = modal.locator('input[placeholder*="项目号"]').first
            proj_input.click()
            page.wait_for_timeout(400)
            assert modal.locator('div.mono:has-text("PRJ-1")').first.is_visible(), "项目下拉缺 PRJ-1"
            assert modal.locator('div.mono:has-text("PRJ-2")').first.is_visible(), "项目下拉缺 PRJ-2"
            modal.locator('div.mono:has-text("PRJ-2")').first.click()
            page.wait_for_timeout(250)

            # 物料号 autocomplete：下拉含两个物料，选 M2
            mat_input = modal.locator('input[placeholder*="物料号"]').first
            mat_input.click()
            page.wait_for_timeout(400)
            assert modal.locator('div.mono:has-text("M1")').first.is_visible(), "物料下拉缺 M1"
            assert modal.locator('div.mono:has-text("M2")').first.is_visible(), "物料下拉缺 M2"
            modal.locator('div.mono:has-text("M2")').first.click()
            page.wait_for_timeout(250)

            fill_labeled(modal, "单车用量", "2")   # 车型/份额关联项目（PRJ-2→车型C/60%），表单不再填写

            click_button(modal, ["创建", "保存", "提交"])
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator('.toast:has-text("项目零件映射创建成功")').count() > 0, "创建成功 toast 缺失"
            page.wait_for_selector('table tr.data:has-text("PRJ-2"):has-text("M2")', timeout=10000)
            new_txt = page.locator('table tr.data:has-text("PRJ-2"):has-text("M2")').first.inner_text()
            assert "车型C" in new_txt, "新建行车型未回显"
            assert "60%" in new_txt, "新建行 share 未按百分比回显（应 60%）"

            step("§4.2 编辑态主键只读 + 变更回显")
            page.locator('table tr.data:has-text("PRJ-1"):has-text("M1")').first.locator('button:has-text("编辑")').first.click()
            modal = open_modal(page)

            assert modal.locator('input[placeholder*="项目号"]').first.is_disabled(), "编辑态 project_no 应只读"
            assert modal.locator('input[placeholder*="物料号"]').first.is_disabled(), "编辑态 material_no 应只读"

            fill_labeled(modal, "单车用量", "7")   # 映射层仅单车用量可编辑
            click_button(modal, ["保存修改", "保存", "提交"])
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator('.toast:has-text("映射更新成功")').count() > 0, "更新成功 toast 缺失"
            page.wait_for_selector('table tr.data:has-text("PRJ-1"):has-text("M1")', timeout=10000)
            edited = page.locator('table tr.data:has-text("PRJ-1"):has-text("M1")').first.inner_text()
            assert "7" in edited, "PP1 编辑后单车用量未回显 7"
            assert "80%" in edited, "PP1 份额应仍关联项目 PRJ-1（80%），不随映射编辑变化"

            # ===================== §6 0 报错红线 =====================
            step("§6 0 报错红线")
            assert not errors, f"md_project_part 会话前端报错：{errors[:5]}"
            print("VERIFY_VIEW_psc_md_project_part: PASS")

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
