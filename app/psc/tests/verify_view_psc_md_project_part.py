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

from fde_platform.shadowdb import shadow_dbs, shadow_clear, shadow_clear_prefs, auth_db_path  # noqa: E402
from fde_platform.view_watchdog import install_watchdog  # noqa: E402

# 影子库：业务库与平台库**都**复制到副本 → 真库零字节接触，**不用停 dev server**。
# config=True 是必需的：本脚本要播种 admin（写 config/auth.db），不影子化就会污染真库。
_shadow = shadow_dbs(env=True, inprocess=False, config=True)
_shadow.__enter__()
# ⚠ **必须在副本上清表**（2026-09-18 加）：影子库是**真库的拷贝** —— 真演示数据
# （e2e 的 M001/M002、PSC 的各主数据）会被一起复制进来，而本脚本自带的造数会撞主键。
# 此前不写这句也没事，只是因为当时副本落盘在另一个目录、平台读到的其实是**新建空库**；
# 布局修正后"副本是空的"这个隐含假设当场暴露 ⇒ 显式清表，语义与《验证门禁.md》
# §四之二的「view e2e 起点 = 空表」一致。
shadow_clear("psc")
# **个人 UI 偏好也要清**：它是操作者本机状态（如"手动隐藏过某列"），
# 不清就会让用例结果取决于谁在哪台机器上跑（实测：真库里藏了 sales_forecast 的两列）。
shadow_clear_prefs()
atexit.register(_shadow.__exit__, None, None, None)

# admin 会话（逐应用脚本单会话）：空库播种 admin/admin 后标记已改密，绕过「请先修改默认密码」。
from fde_platform import users  # noqa: E402
users.init_schema()
users.seed_admin()
try:
    conn = sqlite3.connect(str(auth_db_path()))
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


def expect_toast(page, text, timeout=5000):
    loc = page.locator(f'.toast:has-text("{text}")')
    try:
        loc.first.wait_for(state="visible", timeout=timeout)
    except Exception:
        raise AssertionError(
            f"未出现预期 toast：{text}（当前：{page.locator('.toasts').inner_text()[:160]}）"
        )


def set_filter(page, placeholder, value):
    """过滤条：填入值 + 点「查询」（本页无「重置」按钮，清空过滤 = 填空串再查）。"""
    page.locator(f'input[placeholder="{placeholder}"]').first.fill(value)
    click_button(page, ["查询"])
    page.wait_for_timeout(600)


def pick_form_option(page, modal, placeholder, value):
    """表单 autocomplete：点输入框展开下拉 → 点下拉项（div.mono 精确值回填编码）。"""
    modal.locator(f'input[placeholder*="{placeholder}"]').first.click()
    page.wait_for_timeout(400)          # 等 x-for 渲染下拉项（Alpine 响应式一拍）
    modal.locator(f'div.mono:has-text("{value}")').first.click()
    page.wait_for_timeout(200)


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
    # 卡住诊断（2026-09-18）：页面冻死/渲染进程崩溃时 playwright 调用不返回 ——
    # 由这个守护线程把「最后完成的步骤 + 已收集的错误」打出来；否则超时被强杀时现场全丢。
    install_watchdog(errors, step_getter=lambda: STEP)

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
            # §0 造数（测试数据字典：非用例，文档未编 VT 编号 —— 仅作后续用例前置）
            step("§0 造数（项目/物料/映射）")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"md_project_part 造数失败：{seed}"

            # ===================== §1 本页路由渲染（防粘滞） =====================
            # §1 VT-ROUTE-01 路由渲染有内容（.card>0 · .kpi==0）
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
            # §2 VT-LIST-01 列表含所造映射（PRJ-1/M1 行 + share 百分比格式化 + veh_model/usage 列）
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

            # §2 VT-LIST-02 project_no 模糊过滤（LIKE %PRJ-1% → 仅 PP1+PP2，PP3 不可见）
            step("§2 VT-LIST-02 project_no 模糊过滤")
            set_filter(page, "项目号", "PRJ-1")
            rows = page.locator("table tr.data")
            assert rows.count() == 2, f"项目号=PRJ-1 应 2 行（PP1+PP2），实际 {rows.count()}"
            assert rows.filter(has_text="PRJ-1").count() == 2, "过滤结果应全为 PRJ-1 行"
            assert rows.filter(has_text="PRJ-2").count() == 0, "project_no 过滤不应含 PRJ-2 行（PP3）"

            # §2 VT-LIST-03 material_no 模糊过滤（LIKE %M1% → PRJ-1/M1 与 PRJ-2/M1，M2 行不可见）
            #   注意：项目号过滤是 AND 条件，须先清空（本页无「重置」按钮，填空串再查）
            step("§2 VT-LIST-03 material_no 模糊过滤")
            set_filter(page, "项目号", "")
            set_filter(page, "物料号", "M1")
            rows = page.locator("table tr.data")
            assert rows.count() == 2, f"物料号=M1 应 2 行（PP1+PP3），实际 {rows.count()}"
            assert rows.filter(has_text="M1").count() == 2, "过滤结果应全含 M1"
            assert rows.filter(has_text="M2").count() == 0, "material_no 过滤不应含 M2 行（PP2）"

            # §2 VT-LIST-04（订正 · 反向断言）本页**无 veh_model 过滤入口**
            #   契约 list(project_no, material_no, page, size) 无 veh_model 参数（_contracts.md），
            #   view.html 过滤条只有「项目号 / 物料号」两个输入 → 断其不存在，不做车型过滤断言。
            step("§2 VT-LIST-04 过滤条仅 项目号/物料号（无车型过滤入口）")
            set_filter(page, "项目号", "")
            set_filter(page, "物料号", "")
            fbar = page.locator("main .card:visible .bd > .tagline").first
            # 只数**文本**输入：平台会把「自定义显示列」的 checkbox 浮层并入工具栏右侧 .right
            # （view/lib/shell.js 的 .colctl），那是列设置、不是过滤控件，须排除。
            phs = fbar.locator(
                'input:not([type="checkbox"]):not([type="file"])'
            ).evaluate_all("els => els.map(e => e.placeholder)")
            assert phs == ["项目号", "物料号"], \
                f"过滤条应恰为「项目号 / 物料号」两个文本输入，实际 {phs}"
            assert fbar.locator('input[placeholder*="车型"]').count() == 0, \
                "本页不应存在车型过滤入口（已随量纲下沉到项目移除）"
            assert page.locator("table tr.data").count() >= 3, "清空过滤后应回全量（≥3 行）"

            # ===================== §3 详情模态全字段 =====================
            # §3 VT-MODAL-01 详情模态全字段（复合主键头带「PRJ-1 × M1」+ 全字段标签/值 + 原始数据区）
            step("§3 详情模态全字段")
            page.locator('table tr.data:has-text("PRJ-1"):has-text("M1")').first.locator(".b-link").first.click()
            modal = open_modal(page)
            txt = modal.inner_text()
            for expected in ["PRJ-1 × M1", "项目号", "物料号", "车型", "单车用量", "供应份额",
                             "车型A", "2", "80%", "项目一", "前保险杠总成", "原始数据"]:
                assert expected in txt, f"详情模态缺字段：{expected}"

            # §3 VT-MODAL-02 页脚按钮可见性（含【编辑】【关闭】，无【删除】）
            ft = modal.locator(".modal-ft").first.inner_text()
            assert "编辑" in ft and "关闭" in ft, "详情页脚缺 编辑/关闭 按钮"
            assert "删除" not in ft, "详情页脚不应有删除按钮（契约无 delete）"
            close_modal(page, modal)

            # ===================== §4 表单落库回显（创建 + 编辑） =====================
            # §4 VT-FORM-01 创建落库（双 autocomplete 选项目/物料）
            #    + VT-FORM-02 autocomplete 下拉交互（选项来源 + 选中回填）
            step("§4.1 创建表单 autocomplete 下拉 + 落库")
            click_button(page, ["新建映射", "新建"])
            modal = open_modal(page)

            # §4 VT-FORM-02 项目号 autocomplete：下拉含两个项目，选 PRJ-2
            proj_input = modal.locator('input[placeholder*="项目号"]').first
            proj_input.click()
            page.wait_for_timeout(400)
            assert modal.locator('div.mono:has-text("PRJ-1")').first.is_visible(), "项目下拉缺 PRJ-1"
            assert modal.locator('div.mono:has-text("PRJ-2")').first.is_visible(), "项目下拉缺 PRJ-2"
            modal.locator('div.mono:has-text("PRJ-2")').first.click()
            page.wait_for_timeout(250)

            # §4 VT-FORM-02 物料号 autocomplete：下拉含两个物料，选 M2
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

            # §4 VT-FORM-01 创建落库：toast + 列表回显新行（车型/份额由项目关联带出）
            assert page.locator('.toast:has-text("项目零件映射创建成功")').count() > 0, "创建成功 toast 缺失"
            page.wait_for_selector('table tr.data:has-text("PRJ-2"):has-text("M2")', timeout=10000)
            new_txt = page.locator('table tr.data:has-text("PRJ-2"):has-text("M2")').first.inner_text()
            assert "车型C" in new_txt, "新建行车型未回显"
            assert "60%" in new_txt, "新建行 share 未按百分比回显（应 60%）"

            # §4 VT-FORM-06 编辑态主键只读 + 变更回显（复合主键 project_no/material_no 只读）
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

            # ===================== §4.3 创建校验 + 批量导入 =====================
            # §4 VT-FORM-03 空必填字段被拒（前端拦截，不发 create 请求，模态保持打开）
            step("§4.3 VT-FORM-03 空必填字段被拒（前端拦截）")
            rows_before = page.locator("table tr.data").count()
            click_button(page, ["新建映射", "新建"])
            modal = open_modal(page)
            click_button(modal, ["创建", "保存"])
            expect_toast(page, "请选择项目")
            assert modal.is_visible(), "空必填被拒后模态应保持打开"
            assert page.locator("table tr.data").count() == rows_before, "空必填不应产生新记录"
            close_modal(page, modal)

            # §4 VT-FORM-04 重复主键后端拒绝（PP1 的 (PRJ-1, M1) 已存在 → FdeError，模态保持打开）
            step("§4.3 VT-FORM-04 重复主键后端拒绝")
            click_button(page, ["新建映射", "新建"])
            modal = open_modal(page)
            pick_form_option(page, modal, "项目号", "PRJ-1")
            pick_form_option(page, modal, "物料号", "M1")
            fill_labeled(modal, "单车用量", "3")
            click_button(modal, ["创建", "保存"])
            expect_toast(page, "该项目-物料映射已存在")
            assert modal.is_visible(), "重复主键被拒后模态应保持打开便于修改重试"
            assert page.locator('table tr.data:has-text("PRJ-1"):has-text("M1")').count() == 1, \
                "重复主键不应产生第二行 PRJ-1/M1"
            close_modal(page, modal)

            # §4 VT-FORM-05 单车用量范围校验（usage=0 → 前端本地拦截「单车用量须大于0」）
            #   订正：**供应份额不在本表单内**（份额/车型为项目级信息，映射表单不收录，
            #   view.html 表单只有 项目号/物料号/单车用量）→ 原「share=1.5」半条无 UI 入口，改断其不存在。
            step("§4.3 VT-FORM-05 单车用量范围校验（usage=0）")
            click_button(page, ["新建映射", "新建"])
            modal = open_modal(page)
            pick_form_option(page, modal, "项目号", "PRJ-2")
            pick_form_option(page, modal, "物料号", "M2")
            fill_labeled(modal, "单车用量", "0")
            click_button(modal, ["创建", "保存"])
            expect_toast(page, "单车用量须大于0")
            assert modal.is_visible(), "范围非法被拒后模态应保持打开"
            assert modal.locator('label:has-text("供应份额")').count() == 0, \
                "映射表单不应含「供应份额」字段（份额为项目级信息，不入映射表单）"
            close_modal(page, modal)

            # §4 VT-FORM-07 批量导入摘要（2026-09-17：UI 缺陷修复后，本用例**恢复为真断言**）

            #   背景：此前 `<template x-if="!imp.result">` 里并列写了「取消」「开始导入」两个根元素，
            #   而 Alpine 的 x-if 只挂载 `el.content.cloneNode(true).firstElementChild`
            #   （view/lib/alpine.esm.js）⇒ **提交按钮被静默丢弃**，批量导入在界面上根本用不了。
            #   本轮已修 view.html（两按钮包进一个 div）—— 于是本用例从"断其不存在"回到"断它能用"。
            step("§4.3 VT-FORM-07 批量导入（提交 → 摘要）")
            click_button(page, ["批量导入"])
            imp_modal = open_modal(page)
            assert imp_modal.locator("textarea").count() == 1, "导入模态应有粘贴数据区"
            imp_btns = imp_modal.locator("button:visible").all_inner_texts()
            assert any("开始导入" in b for b in imp_btns), \
                f"x-if 多根缺陷已修，提交按钮应存在：{imp_btns}"
            # 提交一行合法数据（3 列口径：project_no, material_no, usage —— 车型/份额随项目）
            imp_modal.locator("textarea").first.fill("PRJ-2,M2,4")
            imp_modal.locator('button:has-text("开始导入")').first.click()
            page.wait_for_timeout(900)
            kv = imp_modal.inner_text()
            assert "总数" in kv and "成功" in kv, f"提交后应出现导入摘要：{kv!r}"
            assert imp_modal.locator('div.k:text-is("成功")').count() == 1, "摘要应有「成功」计数"
            close_modal(page, imp_modal)
            page.wait_for_timeout(300)
            # 落库回显：新组合 PRJ-2 × M2 应出现在列表（列表按项目筛选 PRJ-2）
            page.locator('input[placeholder*="项目"]').first.fill("PRJ-2")
            page.locator('button:has-text("查询")').first.click()
            page.wait_for_timeout(600)
            assert page.locator('table tr.data:has-text("M2")').count() >= 1, \
                "批量导入的 PRJ-2×M2 未在列表回显"

            # ===================== §6 0 报错红线 =====================
            # §6 VT-ERR-01 本会话 0 报错
            step("§6 0 报错红线")
            assert not errors, f"md_project_part 会话前端报错：{errors[:5]}"
            # **豁免也要受检**（2026-09-17 补）：`ignored` 收集了却从不校验，等于给「静默吞掉」
            # 开了口子 —— 任何新形态的 4xx/console error 都能混进来而不被任何人发现。
            # 只认 favicon / sourcemap / 403 三种豁免理由，其余一律报出。
            for item in ignored:
                ok = ("/favicon.ico" in item or ".map" in item or "403" in item)
                assert ok, f"豁免理由不成立（既不是 favicon/.map，也不是 403）：{item!r}"
            if ignored:
                print(f"  · 本次豁免 {len(ignored)} 条：{ignored[:3]}")
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
