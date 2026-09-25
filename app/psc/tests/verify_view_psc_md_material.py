"""e2e 前端验收 · psc:md_material（物料主数据）
断言：路由渲染防粘滞（.kpi==0）→ 造数后列表有数据（含搜索/状态 chips）→ 模态全字段
（base_params tryParse 结构化、status 只读）→ 表单落库回显（create/update + import_batch，
material_no 只读、status 不进表单）→ 全程 0 console error / 0 pageerror / 0 HTTP≥400。
运行：python app/psc/tests/verify_view_psc_md_material.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit


def _project_root() -> pathlib.Path:
    """向上找项目根（含 fde_platform/ 的目录）。本脚本落点在 tests/ 下，按标记定位才稳。"""
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

from fde_platform import users  # noqa: E402

users.init_schema()
users.seed_admin()

# 首次登录强制改密（password_changed=0）会把 admin 拦去 /change-password；
# 测试会话提前标记已改密，登录后直达首页。
import sqlite3  # noqa: E402

# 输出编码：控制台代码页在本机默认是 GBK，而断言文案里有 ⇒ / ✓ / ✗ / ⚠ / − 这类**非 GBK 码位** ——
# 不钉住编码的话，print 自己会抛 UnicodeEncodeError（**崩在打印结果那一步**：断言算完了却报不出来，
# 其后用例也不再执行 —— 实测 nasa_pms 的 stakeholder 脚本里有一条断言就这么"消失"过）。与 scripts/run_gates.py 给
# 子进程设 PYTHONIOENCODING 同一根因；由 scripts/verify_test_script_encoding.py 守住别忘这一行。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    auth_db = auth_db_path()
    if auth_db.exists():
        conn = sqlite3.connect(str(auth_db))
        conn.execute("UPDATE users SET password_changed = 1 WHERE username = 'admin'")
        conn.commit()
        conn.close()
except Exception:
    pass

STEP = ""


def step(name):
    global STEP
    STEP = name
    print(f"  → {name}", flush=True)


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
      throw new Error(`${app}.${svc} biz ${data.message || JSON.stringify(data).slice(0, 160)}`);
    }
    return data;
  };

  // M1 全字段主测样例（移动平均 window=6）
  await call("md_material", "create", {
    material_no: "M1", material_name: "螺栓-标准", status: "正常",
    unit_value: 12.50, value_class: "高", change_cost: 300.50,
    prod_days: 10, logistics_days: 5, change_risk: "低",
    service_level: 0.95, batch_window: 28,
    base_method: "移动平均", base_params: '{"window": 6}'
  });
  // M2 EOP（指数平滑）
  await call("md_material", "create", {
    material_no: "M2", material_name: "垫圈-停产", status: "EOP",
    value_class: "低", change_risk: "高",
    base_method: "指数平滑", base_params: '{"alpha": 0.3, "trend": false}'
  });
  // M3 停用（阶跃检测）
  await call("md_material", "create", {
    material_no: "M3", material_name: "螺母-停用", status: "停用",
    base_method: "阶跃检测", base_params: '{"threshold": 0.3, "confirm_periods": 2, "lookback": 6}'
  });
  // M4 正常（借用参考 M1，须在 M1 之后）
  await call("md_material", "create", {
    material_no: "M4", material_name: "套筒-参考", status: "正常",
    base_method: "借用参考", base_params: '{"ref_material": "M1", "scale": 1.0, "mode": "trend"}'
  });

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


def choose_option(scope, label, value=None, text=None):
    loc = scope.locator(
        f'xpath=.//label[contains(normalize-space(.), "{label}")]/following::select[1]'
    )
    if not loc.count():
        loc = scope.locator(
            f'xpath=.//*[contains(normalize-space(.), "{label}")]/ancestor::*'
            f'[contains(@class,"field") or contains(@class,"frow") or contains(@class,"filter") '
            f'or contains(@class,"form")][1]//select'
        )
    if not loc.count():
        loc = scope.locator("select")

    if not loc.count():
        raise AssertionError(f"未找到下拉：{label}")

    sel = loc.first

    if value:
        try:
            sel.select_option(value=value)
            return
        except Exception:
            pass

    if text:
        try:
            sel.select_option(label=text)
            return
        except Exception:
            pass

    ok = sel.evaluate(
        """(el, opt) => {
          const opts = Array.from(el.options || []);
          let hit = null;
          if (opt.value) hit = opts.find(o => o.value === opt.value);
          if (!hit && opt.text) hit = opts.find(o => (o.text || '').includes(opt.text));
          if (!hit) return false;
          el.value = hit.value;
          el.dispatchEvent(new Event('change', {bubbles: true}));
          el.dispatchEvent(new Event('input', {bubbles: true}));
          return true;
        }""",
        {"value": value, "text": text},
    )
    if not ok:
        raise AssertionError(f"下拉选择失败：{label} value={value} text={text}")


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

            # ===================== §1 本页渲染（防粘滞 · 空库先于造数）=====================
            # §1 VT-ROUTE-01 路由渲染（防粘滞 · 空库先于造数）
            step("§1 路由渲染 + .kpi==0")
            page.evaluate("location.hash = '#/md_material'")
            try:
                page.wait_for_selector("main .card", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator("main").inner_text().strip(), "md_material 页面无内容"
            assert page.locator("main .card").count() > 0, "md_material 未渲染 card"
            assert page.locator(".kpi").count() == 0, "md_material 挂载未重建（残留看板 .kpi）"

            # ===================== §0 造数（M1–M4）=====================
            # §0 造数（测试数据字典：非用例，文档未编 VT 编号 —— 仅作后续用例前置）
            step("§0 造数 M1–M4")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"md_material 造数失败：{seed}"

            # ===================== §2 列表有数据 =====================
            # §2 VT-LIST-01 列表含所造单号（含行内名称/状态徽章回显）
            step("§2 列表含 M1")
            page.reload()
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.evaluate("location.hash = '#/md_material'")
            try:
                page.wait_for_selector('table tr.data:has-text("M1")', timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(600)

            assert page.locator("button.b-link:has-text('M1')").count() >= 1, "列表未渲染 M1 物料号链接"
            assert page.locator("table tr.data").count() >= 4, "md_material 造数后列表数据行不足"
            m1_row = page.locator('table tr.data:has-text("M1")').first
            m1_txt = m1_row.inner_text()
            assert "螺栓-标准" in m1_txt, "M1 行缺物料名称回显"
            assert "正常" in m1_txt, "M1 行缺状态徽章回显"

            # §2 VT-LIST-02 物料号模糊搜索
            step("§2 物料号模糊搜索")
            page.locator('input[placeholder="物料号"]').first.fill("M1")
            click_button(page, ["查询", "搜索"])
            page.wait_for_timeout(700)
            assert page.locator('table tr.data:has-text("M1")').count() == 1, "物料号搜索 M1 应恰好 1 条"
            assert page.locator('table tr.data:has-text("M2")').count() == 0, "物料号搜索泄漏 M2"
            assert page.locator('table tr.data:has-text("M3")').count() == 0, "物料号搜索泄漏 M3"
            assert page.locator('table tr.data:has-text("M4")').count() == 0, "物料号搜索泄漏 M4"

            # §2 VT-LIST-03 状态 chips 精确过滤
            step("§2 状态 chips 精确过滤")
            page.locator('input[placeholder="物料号"]').first.fill("")
            page.locator('.fchip:has-text("正常")').first.click()
            page.wait_for_timeout(700)
            assert page.locator('table tr.data:has-text("M1")').count() >= 1, "正常态过滤缺 M1"
            assert page.locator('table tr.data:has-text("M4")').count() >= 1, "正常态过滤缺 M4"
            assert page.locator('table tr.data:has-text("M2")').count() == 0, "正常态过滤泄漏 M2(EOP)"
            assert page.locator('table tr.data:has-text("M3")').count() == 0, "正常态过滤泄漏 M3(停用)"
            # 用例 §2 VT-LIST-03 断言「结果含 M1、M4，不含 M2、M3」——「含 M1/M4 + 不含 M2/M3」
            # 只约束了四个已知单号，若混入第五行（或某行被重复渲染）则看不出来；补行数闭合。
            assert page.locator("table tr.data").count() == 2, \
                f"正常态过滤应恰 2 行（M1/M4），实际 {page.locator('table tr.data').count()}"

            # §2 VT-LIST-04 物料名称模糊搜索（含清空过滤后命中 M1–M4 全量）
            step("§2 物料名称模糊搜索")
            page.locator('.fchip:has-text("全部")').first.click()
            page.locator('input[placeholder="物料名称"]').first.fill("螺栓")
            click_button(page, ["查询", "搜索"])
            page.wait_for_timeout(700)
            assert page.locator('table tr.data:has-text("M1")').count() >= 1, "名称搜索螺栓缺 M1"
            assert page.locator('table tr.data:has-text("M2")').count() == 0, "名称搜索泄漏 M2"
            assert page.locator('table tr.data:has-text("M3")').count() == 0, "名称搜索泄漏 M3"
            assert page.locator('table tr.data:has-text("M4")').count() == 0, "名称搜索泄漏 M4"

            page.locator('input[placeholder="物料名称"]').first.fill("")
            click_button(page, ["查询", "搜索"])
            page.wait_for_timeout(700)
            assert page.locator("table tr.data").count() >= 4, "清空过滤后应命中 M1–M4 全量"

            # ===================== §3 模态全字段 =====================
            # §3 VT-MODAL-01 详情模态全字段（16 项标签/值 + tryParse 结构化 + status 只读 + 页脚无状态机按钮）
            step("§3 详情模态全字段")
            page.locator('button.b-link:has-text("M1")').first.click()
            modal = open_modal(page)
            try:
                page.wait_for_selector('.modal:visible .docno:has-text("物料详情 · M1")', timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(300)
            txt = modal.inner_text()

            for label in ["物料号", "物料名称", "前序物料", "状态", "单位货值", "价值分类", "切线成本",
                          "生产时间", "物流时间", "变更风险", "满足率目标", "组批窗口",
                          "基线方法", "基线参数", "拟合版本", "生效时间"]:
                assert label in txt, f"md_material 详情模态缺字段标签：{label}"

            for expected in ["M1", "螺栓-标准", "正常", "高", "低", "12.5", "300.5",
                             "0.95", "28 天", "≈ 4 周", "移动平均", "window"]:
                assert expected in txt, f"md_material 详情模态缺字段值：{expected}"

            # base_params tryParse 结构化：window = 6
            assert "window" in txt and "6" in txt, "base_params 未结构化展示 window=6"
            # fit_version / fit_effective_at 空值 dash
            assert "—" in txt, "fit_version/fit_effective_at 空值未渲染 dash"
            # status 只读 + 页脚无状态机流转按钮
            assert "外部维护" in txt and "只读" in txt, "status 只读说明缺失"
            ft = modal.locator(".modal-ft").first.inner_text()
            assert "编辑" in ft and "关闭" in ft, "详情模态页脚缺编辑/关闭按钮"
            for forbidden in ["启动", "完成", "退回"]:
                assert forbidden not in ft, f"详情模态不应出现状态机按钮 {forbidden}"
            close_modal(page, modal)

            # ===================== §4 表单落库回显 =====================
            # §4 VT-FORM-01 创建（全字段 + status 不进表单）
            step("§4 创建（status 不进表单）")
            click_button(page, ["+ 新建物料", "新建物料"])
            form_modal = open_modal(page)
            assert form_modal.locator('label:has-text("状态")').count() == 0, "创建表单不应含 status 字段"

            fill_labeled(form_modal, "物料号", "M-NEW")
            fill_labeled(form_modal, "物料名称", "新物料")
            fill_labeled(form_modal, "单位货值（元/件）", "5")
            choose_option(form_modal, "价值分类", value="低")
            fill_labeled(form_modal, "切线成本（元/次）", "100")
            fill_labeled(form_modal, "生产时间（天）", "3")
            fill_labeled(form_modal, "物流时间（天）", "2")
            choose_option(form_modal, "变更风险", value="高")
            fill_labeled(form_modal, "满足率目标（0~1）", "0.9")
            fill_labeled(form_modal, "组批窗口（天）", "14")
            # 基线方法下拉现在只列**自动拟合会产出**的 6 个：移动平均/指数平滑/阶跃检测/借用参考
            # 已退役（不再可选）。这里选一个在册的方法，参数也换成它的。
            choose_option(form_modal, "基线方法", value="AutoTheta")
            fill_labeled(form_modal, "基线参数（JSON）", '{"season_length": 12}', tags=("textarea",))

            click_button(form_modal, ["创建"])
            try:
                page.wait_for_selector('.toast:has-text("创建成功")', timeout=8000)
            except Exception:
                pass
            try:
                form_modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            try:
                page.wait_for_selector('table tr.data:has-text("M-NEW")', timeout=10000)
            except Exception:
                pass
            mnew_row = page.locator('table tr.data:has-text("M-NEW")').first
            assert mnew_row.count() == 1, "创建后列表未回显 M-NEW"
            mnew_txt = mnew_row.inner_text()
            assert "新物料" in mnew_txt, "M-NEW 行缺物料名称回显"
            assert "正常" in mnew_txt, "M-NEW 行缺默认状态徽章（正常）"

            # §4 VT-FORM-02 创建空必填校验（前端拦截）
            step("§4 空必填校验（前端拦截）")
            click_button(page, ["+ 新建物料", "新建物料"])
            form_modal = open_modal(page)
            click_button(form_modal, ["创建"])
            toast_seen = False
            try:
                page.wait_for_selector('.toast:has-text("必填")', timeout=8000)
                toast_seen = True
            except Exception:
                pass
            assert toast_seen, "空必填未提示 warn toast"
            assert form_modal.count() == 1, "空必填后创建表单应保持打开"
            close_modal(page, form_modal)

            # §4 VT-FORM-03 编辑态（material_no 只读 · status 不进表单 · 更新回显 + 详情同步）
            step("§4 编辑态（material_no 只读 · status 不进表单）")
            m1_row = page.locator('table tr.data:has-text("M1")').first
            m1_row.locator('button:has-text("编辑")').first.click()
            form_modal = open_modal(page)

            mat_no_input = form_modal.locator('input[placeholder="如 M10001"]')
            assert mat_no_input.count() == 1, "编辑态未渲染 material_no 输入框"
            assert mat_no_input.is_disabled(), "编辑态 material_no 应只读（:disabled）"
            assert form_modal.locator('label:has-text("状态")').count() == 0, "编辑表单不应含 status 字段"

            fill_labeled(form_modal, "物料名称", "螺栓-标准-改")
            click_button(form_modal, ["保存修改", "保存", "提交"])
            try:
                page.wait_for_selector('.toast:has-text("更新成功")', timeout=8000)
            except Exception:
                pass
            try:
                form_modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            try:
                page.wait_for_selector('table tr.data:has-text("螺栓-标准-改")', timeout=10000)
            except Exception:
                pass
            m1_row2 = page.locator('table tr.data:has-text("M1")').first
            assert "螺栓-标准-改" in m1_row2.inner_text(), "编辑后列表未回显新名称"

            page.locator('button.b-link:has-text("M1")').first.click()
            modal = open_modal(page)
            try:
                page.wait_for_selector('.modal:visible .docno:has-text("物料详情 · M1")', timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(300)
            assert "螺栓-标准-改" in modal.inner_text(), "重开详情模态物料名称未同步"
            close_modal(page, modal)

            # §4 VT-FORM-04 批量导入（摘要 + 错误明细 + 列表回显）
            step("§4 批量导入（摘要 + 错误明细）")
            click_button(page, ["批量导入"])
            imp_modal = open_modal(page)

            header = "material_no,material_name,status,unit_value,value_class,change_cost,prod_days,logistics_days,change_risk,service_level,batch_window,base_method,base_params"
            row_ok = ",".join(["M-IMP", "导入件", "正常"] + [""] * 10)
            row_bad = ",".join(["", "无物料号", "正常"] + [""] * 10)
            csv_content = "\n".join([header, row_ok, row_bad]) + "\n"

            file_input = imp_modal.locator('input[type="file"]')
            file_input.set_input_files(
                {"name": "md_material_import.csv", "mimeType": "text/csv",
                 "buffer": csv_content.encode("utf-8")}
            )
            try:
                page.wait_for_selector('.modal:visible:has-text("已选择")', timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(300)

            click_button(imp_modal, ["开始导入"])
            try:
                page.wait_for_selector('.modal:visible:has-text("物料号不能为空")', timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(300)
            summary_txt = imp_modal.inner_text()
            assert "导入摘要" in summary_txt, "导入摘要未展示"
            assert "成功" in summary_txt and "失败" in summary_txt, "导入摘要缺成功/失败计数"
            assert "物料号不能为空" in summary_txt, "导入错误明细缺「物料号不能为空」"

            click_button(imp_modal, ["完成", "关闭", "取消"])
            try:
                imp_modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            try:
                page.wait_for_selector('table tr.data:has-text("M-IMP")', timeout=10000)
            except Exception:
                pass
            mimp_row = page.locator('table tr.data:has-text("M-IMP")').first
            assert mimp_row.count() == 1, "导入后列表未回显 M-IMP"
            mimp_txt = mimp_row.inner_text()
            assert "导入件" in mimp_txt, "M-IMP 行缺物料名称回显"
            assert "正常" in mimp_txt, "M-IMP 行缺状态徽章回显"

            # §4 VT-FORM-05 前序物料选择器（autocomplete）：输入「螺」→ 下拉命中 M1 → 落库 → 详情回显
            #   下拉源自 md_material.list 全量（含停用/EOP）；M1 的名称在 VT-FORM-03 已改为「螺栓-标准-改」，
            #   故下拉/回显小字以**当前名**为准。
            step("§4 前序物料 autocomplete（选 M1 → 落库 → 详情回显 M1）")
            click_button(page, ["+ 新建物料", "新建物料"])
            form_modal = open_modal(page)

            pred_input = form_modal.locator('input[placeholder="搜索前序物料…"]').first
            pred_input.click()
            pred_input.fill("螺")
            page.wait_for_timeout(300)
            # 下拉项与表格行同为 div.mono：限定在输入框同容器内且 :visible（pitfalls #14）
            pred_box = pred_input.locator("xpath=..")
            opt = pred_box.locator('.mono:visible:has-text("M1")').first
            opt.wait_for(state="visible", timeout=5000)
            opt.click()
            page.wait_for_timeout(200)
            assert pred_input.input_value() == "M1", \
                f"前序物料选中后未回填编码：{pred_input.input_value()!r}"

            fill_labeled(form_modal, "物料号", "M-NEW2")
            fill_labeled(form_modal, "物料名称", "新一代螺栓")
            click_button(form_modal, ["创建"])
            try:
                page.wait_for_selector('.toast:has-text("创建成功")', timeout=8000)
            except Exception:
                pass
            try:
                form_modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            try:
                page.wait_for_selector('table tr.data:has-text("M-NEW2")', timeout=10000)
            except Exception:
                pass
            assert page.locator('table tr.data:has-text("M-NEW2")').count() == 1, \
                "前序物料创建后列表未回显 M-NEW2"
            mnew2_txt = page.locator('table tr.data:has-text("M-NEW2")').first.inner_text()
            # 小字为 materialMap 回显；materialMap 由 loadMaterialOptions() 在页面 init 时抓一次，
            # VT-FORM-03 改名后**不刷新**，故此处仍是旧名「螺栓-标准」（与文档一致）
            assert "M1" in mnew2_txt and "螺栓-标准" in mnew2_txt, \
                f"M-NEW2 行前序物料列未回显 M1 + 物料名：{mnew2_txt[:80]}"

            # 重开详情模态：predecessor_material_no = M1，且附前序物料名称（materialName 命中）
            page.locator('button.b-link:has-text("M-NEW2")').first.click()
            modal = open_modal(page)
            try:
                page.wait_for_selector('.modal:visible .docno:has-text("M-NEW2")', timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(300)
            pred_cell = modal.locator('div.k', has_text="前序物料").first \
                .locator("xpath=..").inner_text()
            assert "M1" in pred_cell, f"详情模态前序物料值应为 M1：{pred_cell!r}"
            assert "螺栓-标准" in pred_cell, f"详情模态缺前序物料名称回显：{pred_cell!r}"
            close_modal(page, modal)

            # ===================== §6 0 报错 =====================
            # §6 0 报错红线（本会话；文档 §6 该条未编 VT 编号，无对应 VT-ERR 条目）
            step("§6 0 报错")
            assert not errors, f"md_material 会话前端报错：{errors[:5]}"
            # **豁免也要受检**（2026-09-17 补）：`ignored` 收集了却从不校验，等于给「静默吞掉」
            # 开了口子 —— 任何新形态的 4xx/console error 都能混进来而不被任何人发现。
            # 只认 favicon / sourcemap / 403 三种豁免理由，其余一律报出。
            for item in ignored:
                ok = ("/favicon.ico" in item or ".map" in item or "403" in item)
                assert ok, f"豁免理由不成立（既不是 favicon/.map，也不是 403）：{item!r}"
            if ignored:
                print(f"  · 本次豁免 {len(ignored)} 条：{ignored[:3]}")
            print("VERIFY_VIEW_psc_md_material: PASS")

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
