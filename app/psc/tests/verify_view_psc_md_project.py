"""e2e 前端验收 - psc:md_project（项目台账）
断言：路由渲染防粘滞 → 造数后列表有数据（含阶段 chips / 项目号 / 项目名称模糊搜索与空态）
→ 详情模态全字段 + 页脚按钮按阶段状态 → 表单落库 / 前端校验 / 后端校验
+ 编辑态主键只读 / 阶段单向推进（进行中→SOP→EOP）+ 批量导入 → 全程 0 console error /
0 pageerror / 0 HTTP≥400。
运行：python app/psc/tests/verify_view_psc_md_project.py
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

# seed_admin 落 password_changed=0 → 首登被强制改密闸门拦下（auth.py ②.5），
# 与 verify_view_e2e 样板/各逐应用脚本一致，先在隔离后的 config/auth.db 置 1 放行。
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


# §0 自足造数：PRJ-1（进行中·含日期）/ PRJ-2（进行中·无日期，供推进）/ PRJ-SOP（SOP）
# / PRJ-EOP（EOP 终态）。create 仅允许初始阶段「进行中」，故 SOP/EOP 一律 create 后经
# update 按状态机单向推进（进行中→SOP→EOP）得到。
SEED_JS = r"""async () => {
  const call = async (svc, params) => {
    const r = await fetch(`/api/apps/psc/md_project/call/${svc}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(params || {})
    });
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) {}
    if (!r.ok) throw new Error(`md_project.${svc} HTTP ${r.status} ${text.slice(0, 160)}`);
    if (data && data.status === "error") {
      throw new Error(`md_project.${svc} biz ${data.message || JSON.stringify(data).slice(0, 160)}`);
    }
    return data;
  };

  await call("create", {project_no: "PRJ-1", project_name: "项目1", owner: "S001", sop_date: "2026-01-01", eop_date: "2027-12-31"});
  await call("create", {project_no: "PRJ-2", project_name: "项目2", owner: "S002"});
  await call("create", {project_no: "PRJ-SOP", project_name: "项目SOP", owner: "S003"});
  await call("update", {project_no: "PRJ-SOP", stage: "SOP", sop_date: "2026-06-01"});
  await call("create", {project_no: "PRJ-EOP", project_name: "项目EOP", owner: "S004"});
  await call("update", {project_no: "PRJ-EOP", stage: "SOP", sop_date: "2026-06-01"});
  await call("update", {project_no: "PRJ-EOP", stage: "EOP", eop_date: "2029-12-31"});

  return {seeded: true};
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
    """等 .modal-mask:visible 出现、.loadbox 消失（详情模态载入明细），返回可见模态。"""
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


def row_by_no(page, no):
    """按项目号精确定位数据行（has_text 子串定位；本字典单号互不为子串）。"""
    return page.locator("table.tbl tr.data", has_text=no)


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
            step("§0 造数（PRJ-1 / PRJ-2 / PRJ-SOP / PRJ-EOP）")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"md_project 造数失败：{seed}"

            # ===================== §1 本页渲染（防粘滞）=====================
            step("§1 路由渲染防粘滞")
            page.evaluate("location.hash = '#/md_project'")
            try:
                page.wait_for_selector("main .card", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator("main").inner_text().strip(), "md_project 页面无内容"
            assert page.locator("main .card").count() > 0, "md_project 未渲染 card"
            assert page.locator(".kpi:visible").count() == 0, "md_project 挂载未重建（残留看板）"
            assert page.locator('button:visible:has-text("+ 新建项目")').count() > 0, "工具栏缺「+ 新建项目」"
            assert page.locator('button:visible:has-text("批量导入")').count() > 0, "工具栏缺「批量导入」"
            assert page.locator("table.tbl").count() > 0, "缺 .tbl 表格"
            assert "共" in page.locator("main").inner_text(), "缺分页条"

            # ===================== §2 造数后列表有数据 =====================
            step("§2 LIST-01 列表含所造单号")
            rows = page.locator("table.tbl tr.data")
            assert rows.count() >= 4, f"md_project 造数后列表行数不足：{rows.count()}"
            prj1 = rows.filter(has_text="PRJ-1")
            assert prj1.count() == 1, "列表未见 PRJ-1 行"
            row_txt = prj1.first.inner_text()
            assert "项目1" in row_txt, "PRJ-1 行 project_name 应为 项目1"
            assert "进行中" in row_txt, "PRJ-1 行 stage 徽章应为 进行中"
            assert "S001" in row_txt, "PRJ-1 行 owner 应为 S001"

            step("§2 LIST-02 阶段 chips 过滤（SOP）")
            page.locator(".fchip", has_text="SOP").first.click()
            page.wait_for_timeout(700)
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 1, f"SOP 过滤应仅 1 条，实际 {rows.count()}"
            assert rows.filter(has_text="PRJ-SOP").count() == 1, "SOP 过滤应含 PRJ-SOP"
            for no in ["PRJ-1", "PRJ-2", "PRJ-EOP"]:
                assert rows.filter(has_text=no).count() == 0, f"SOP 过滤不应含 {no}"
            page.locator(".fchip", has_text="全部").first.click()
            page.wait_for_timeout(700)

            step("§2 LIST-03 项目号模糊搜索（PRJ-）")
            no_input = page.locator('input[placeholder="项目号"]').first
            no_input.fill("PRJ-")
            click_button(page, ["查询"])
            page.wait_for_timeout(700)
            rows = page.locator("table.tbl tr.data")
            for no in ["PRJ-1", "PRJ-2", "PRJ-SOP", "PRJ-EOP"]:
                assert rows.filter(has_text=no).count() == 1, f"项目号 PRJ- 搜索应含 {no}"
            no_input.fill("")
            click_button(page, ["查询"])
            page.wait_for_timeout(700)

            step("§2 LIST-04 项目名称模糊搜索 + 空态")
            name_input = page.locator('input[placeholder="项目名称"]').first
            name_input.fill("项目1")
            click_button(page, ["查询"])
            page.wait_for_timeout(700)
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 1, f"项目名称 项目1 搜索应仅 1 条，实际 {rows.count()}"
            assert rows.filter(has_text="PRJ-1").count() == 1, "项目名称 项目1 搜索应命中 PRJ-1"
            name_input.fill("不存在XYZ")
            click_button(page, ["查询"])
            page.wait_for_timeout(700)
            empty = page.locator(".tbl .empty")
            assert empty.count() > 0, "项目名称搜索空态应显示 .tbl .empty"
            assert "无符合条件的项目" in empty.inner_text(), "空态文案应为「无符合条件的项目」"
            name_input.fill("")
            click_button(page, ["查询"])
            page.wait_for_timeout(700)

            # ===================== §3 模态全字段 =====================
            step("§3 MODAL-01 详情模态全字段 + 进行中页脚推进按钮（PRJ-1）")
            page.locator("table.tbl tr.data .b-link", has_text="PRJ-1").first.click()
            modal = wait_modal(page)
            txt = modal.inner_text()
            for label in ["项目号", "项目名称", "阶段", "SOP 时间", "EOP 时间", "责任销售"]:
                assert label in txt, f"详情模态缺字段标签：{label}"
            for val in ["PRJ-1", "项目1", "进行中", "2026-01-01", "2027-12-31", "S001"]:
                assert val in txt, f"详情模态缺字段值：{val}"
            assert "原始数据" in txt, "详情模态缺「原始数据」折叠区"
            ft = modal.locator(".modal-ft")
            assert ft.locator('button:visible:has-text("推进至 SOP")').count() == 1, "进行中态页脚应有「推进至 SOP」"
            assert ft.locator('button:visible:has-text("编辑")').count() == 1, "进行中态页脚应有「编辑」"
            assert ft.locator('button:visible:has-text("关闭")').count() == 1, "进行中态页脚应有「关闭」"
            close_modal(page, modal)

            step("§3 MODAL-02 页脚按钮按状态可见性（PRJ-SOP / PRJ-EOP）")
            page.locator("table.tbl tr.data .b-link", has_text="PRJ-SOP").first.click()
            modal = wait_modal(page)
            ft = modal.locator(".modal-ft")
            assert ft.locator('button:visible:has-text("推进至 EOP")').count() == 1, "SOP 态页脚应有「推进至 EOP」"
            assert ft.locator('button:visible:has-text("推进至 SOP")').count() == 0, "SOP 态页脚不应有「推进至 SOP」"
            assert ft.locator('button:visible:has-text("编辑")').count() == 1, "SOP 态页脚应有「编辑」"
            close_modal(page, modal)

            page.locator("table.tbl tr.data .b-link", has_text="PRJ-EOP").first.click()
            modal = wait_modal(page)
            ft = modal.locator(".modal-ft")
            assert "EOP 终态 · 阶段不可推进" in ft.inner_text(), "EOP 态页脚缺终态文案"
            assert ft.locator('button:visible:has-text("推进至 SOP")').count() == 0, "EOP 态不应有「推进至 SOP」"
            assert ft.locator('button:visible:has-text("推进至 EOP")').count() == 0, "EOP 态不应有「推进至 EOP」"
            assert ft.locator('button:visible:has-text("编辑")').count() == 1, "EOP 态页脚应有「编辑」"
            close_modal(page, modal)

            # ===================== §4 表单落库回显 =====================
            step("§4 FORM-01 创建落库（PRJ-NEW，stage=进行中）")
            click_button(page, ["+ 新建项目"])
            modal = wait_modal(page)
            fill_labeled(modal, "项目号", "PRJ-NEW")
            fill_labeled(modal, "项目名称", "项目新建")
            fill_labeled(modal, "责任销售", "S009")
            click_button(modal, ["更多字段"])
            page.wait_for_timeout(400)
            fill_labeled(modal, "SOP 时间", "2026-10-01")
            click_button(modal, ["创建"])
            expect_toast(page, "项目台账创建成功")
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            row = row_by_no(page, "PRJ-NEW").first
            row_txt = row.inner_text()
            assert "进行中" in row_txt, "PRJ-NEW 初始 stage 应为 进行中"
            assert "2026-10-01" in row_txt, "PRJ-NEW sop_date 应回显 2026-10-01"

            step("§4 FORM-02 空 project_no 被拒（前端校验）")
            click_button(page, ["+ 新建项目"])
            modal = wait_modal(page)
            fill_labeled(modal, "项目名称", "项目号空")
            fill_labeled(modal, "责任销售", "S999")
            # project_no 留空
            click_button(modal, ["创建"])
            expect_toast(page, "项目号必填")
            assert modal.is_visible(), "空 project_no 被拒后模态应保持打开"
            close_modal(page, modal)
            assert row_by_no(page, "项目号空").count() == 0, "空 project_no 不应新增行"

            step("§4 FORM-03 重复 project_no 后端拒绝（BR-01）")
            click_button(page, ["+ 新建项目"])
            modal = wait_modal(page)
            fill_labeled(modal, "项目号", "PRJ-1")
            fill_labeled(modal, "项目名称", "重复项目")
            fill_labeled(modal, "责任销售", "S100")
            click_button(modal, ["创建"])
            expect_toast(page, "该项目号已存在")
            assert modal.is_visible(), "重复 project_no 被拒后模态应保持打开"
            close_modal(page, modal)
            assert row_by_no(page, "PRJ-1").count() == 1, "重复 PRJ-1 列表仍应仅 1 条"

            step("§4 FORM-04 编辑态 project_no 只读 + 字段更新回显 + stage 选项单向")
            row_by_no(page, "PRJ-1").first.locator('button:has-text("编辑")').first.click()
            modal = wait_modal(page)

            no_field = modal.locator('xpath=.//label[contains(normalize-space(.), "项目号")]/following::input[1]')
            assert no_field.count() == 1, "编辑态应有 project_no 输入框"
            assert no_field.first.is_disabled(), "编辑态 project_no 应为只读（主键不可改）"
            assert no_field.first.input_value() == "PRJ-1", "编辑态 project_no 应回填 PRJ-1"

            sel = modal.locator("select").first
            options = sel.evaluate("el => Array.from(el.options).map(o => o.textContent)")
            assert options == ["进行中", "SOP"], f"编辑态 stage 选项应为 [进行中, SOP]，实际 {options}"

            fill_labeled(modal, "项目名称", "项目1-改")
            fill_labeled(modal, "责任销售", "S011")
            click_button(modal, ["保存修改"])
            expect_toast(page, "项目台账更新成功")
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            row_txt = row_by_no(page, "PRJ-1").first.inner_text()
            assert "项目1-改" in row_txt, "PRJ-1 编辑后 project_name 应为 项目1-改"
            assert "S011" in row_txt, "PRJ-1 编辑后 owner 应为 S011"

            step("§4 FORM-05 阶段推进（进行中 → SOP）")
            row_by_no(page, "PRJ-2").first.locator('button:has-text("推进至 SOP")').first.click()
            modal = wait_modal(page)
            assert "阶段推进 · PRJ-2 → SOP" in modal.inner_text(), "阶段推进标题不符"
            stage_field = modal.locator('xpath=.//label[contains(normalize-space(.), "阶段")]/following::input[1]')
            assert stage_field.count() == 1, "阶段推进态应有只读 stage 输入"
            assert stage_field.first.is_disabled(), "阶段推进态 stage 应只读锁定"
            assert stage_field.first.input_value() == "SOP", "阶段推进态 stage 应锁定 SOP"
            fill_labeled(modal, "SOP 时间", "2026-09-30")
            click_button(modal, ["确认推进"])
            expect_toast(page, "已推进至 SOP · PRJ-2")
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            row_txt = row_by_no(page, "PRJ-2").first.inner_text()
            assert "SOP" in row_txt, "PRJ-2 推进后 stage 应为 SOP"
            assert "2026-09-30" in row_txt, "PRJ-2 推进后 sop_date 应为 2026-09-30"

            step("§4 FORM-06 阶段推进（SOP → EOP）+ 推进日期必填前端校验")
            row_by_no(page, "PRJ-SOP").first.locator('button:has-text("推进至 EOP")').first.click()
            modal = wait_modal(page)
            click_button(modal, ["确认推进"])
            expect_toast(page, "推进到 EOP 阶段须填写 EOP 时间")
            assert modal.is_visible(), "缺 eop_date 被拒后模态应保持打开"
            fill_labeled(modal, "EOP 时间", "2029-12-31")
            click_button(modal, ["确认推进"])
            expect_toast(page, "已推进至 EOP · PRJ-SOP")
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            row_txt = row_by_no(page, "PRJ-SOP").first.inner_text()
            assert "EOP" in row_txt, "PRJ-SOP 推进后 stage 应为 EOP"
            assert "2029-12-31" in row_txt, "PRJ-SOP 推进后 eop_date 应为 2029-12-31"

            step("§4 FORM-07 日期先后后端校验（BR-05）")
            click_button(page, ["+ 新建项目"])
            modal = wait_modal(page)
            fill_labeled(modal, "项目号", "PRJ-DATE")
            fill_labeled(modal, "项目名称", "日期项目")
            fill_labeled(modal, "责任销售", "S013")
            click_button(modal, ["更多字段"])
            page.wait_for_timeout(400)
            fill_labeled(modal, "SOP 时间", "2026-09-30")
            fill_labeled(modal, "EOP 时间", "2026-08-31")
            click_button(modal, ["创建"])
            expect_toast(page, "EOP 时间须晚于 SOP 时间")
            assert modal.is_visible(), "日期先后错误后模态应保持打开"
            close_modal(page, modal)
            assert row_by_no(page, "PRJ-DATE").count() == 0, "日期错误不应新增 PRJ-DATE"

            step("§4 FORM-08 批量导入（新增 + 冲突 upsert + 失败明细）")
            click_button(page, ["批量导入"])
            modal = wait_modal(page)
            csv_text = ("project_no,project_name,stage,sop_date,eop_date,owner\n"
                        "PRJ-IMP-1,导入项目1,进行中,,,S010\n"
                        "PRJ-1,项目1导入改,进行中,,,S001\n"
                        "PRJ-IMP-BAD,,进行中,,,S012")
            fill_labeled(modal, "或直接粘贴 CSV", csv_text, tags=("textarea",))
            click_button(modal, ["导入"])
            expect_toast(page, "导入完成 · 成功 2 条 / 失败 1 条")
            page.wait_for_timeout(400)
            txt = modal.inner_text()
            assert "总行数" in txt and "成功" in txt and "失败" in txt and "新增 / 更新" in txt, \
                "导入结果摘要缺字段"
            assert "1 / 1" in txt, "导入结果 created/updated 应为 1 / 1"
            assert "项目名称不能为空" in txt, "导入错误明细缺「项目名称不能为空」"
            close_modal(page, modal)
            page.wait_for_timeout(700)
            assert row_by_no(page, "PRJ-IMP-1").count() == 1, "导入后列表应含 PRJ-IMP-1"
            row_txt = row_by_no(page, "PRJ-1").first.inner_text()
            assert "项目1导入改" in row_txt, "PRJ-1 导入 upsert 后 project_name 应变为 项目1导入改"

            # ===================== §6 0 报错红线 =====================
            step("§6 会话 0 报错")
            assert not errors, f"md_project 会话前端报错：{errors[:5]}"
            print("VERIFY_VIEW_psc_md_project: PASS")

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
        print(f"VERIFY_VIEW_psc_md_project: FAIL @ {STEP}: {e}")
        sys.exit(1)
