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

from fde_platform.dbguard import isolate_dbs  # noqa: E402

_iso = isolate_dbs()
_iso.__enter__()
atexit.register(_iso.__exit__, None, None, None)

from fde_platform import users  # noqa: E402

users.init_schema()
users.seed_admin()

# 首次登录强制改密（password_changed=0）会把 admin 拦去 /change-password；
# 测试会话提前标记已改密，登录后直达首页。
import sqlite3  # noqa: E402
try:
    auth_db = ROOT / "config" / "auth.db"
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
            step("§0 造数 M1–M4")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"md_material 造数失败：{seed}"

            # ===================== §2 列表有数据 =====================
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

            step("§2 物料号模糊搜索")
            page.locator('input[placeholder="物料号"]').first.fill("M1")
            click_button(page, ["查询", "搜索"])
            page.wait_for_timeout(700)
            assert page.locator('table tr.data:has-text("M1")').count() == 1, "物料号搜索 M1 应恰好 1 条"
            assert page.locator('table tr.data:has-text("M2")').count() == 0, "物料号搜索泄漏 M2"
            assert page.locator('table tr.data:has-text("M3")').count() == 0, "物料号搜索泄漏 M3"
            assert page.locator('table tr.data:has-text("M4")').count() == 0, "物料号搜索泄漏 M4"

            step("§2 状态 chips 精确过滤")
            page.locator('input[placeholder="物料号"]').first.fill("")
            page.locator('.fchip:has-text("正常")').first.click()
            page.wait_for_timeout(700)
            assert page.locator('table tr.data:has-text("M1")').count() >= 1, "正常态过滤缺 M1"
            assert page.locator('table tr.data:has-text("M4")').count() >= 1, "正常态过滤缺 M4"
            assert page.locator('table tr.data:has-text("M2")').count() == 0, "正常态过滤泄漏 M2(EOP)"
            assert page.locator('table tr.data:has-text("M3")').count() == 0, "正常态过滤泄漏 M3(停用)"

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
            step("§3 详情模态全字段")
            page.locator('button.b-link:has-text("M1")').first.click()
            modal = open_modal(page)
            try:
                page.wait_for_selector('.modal:visible .docno:has-text("物料详情 · M1")', timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(300)
            txt = modal.inner_text()

            for label in ["物料号", "物料名称", "状态", "单位货值", "价值分类", "切线成本",
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
            choose_option(form_modal, "基线方法", value="移动平均")
            fill_labeled(form_modal, "基线参数（JSON）", '{"window": 4}', tags=("textarea",))

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

            # ===================== §6 0 报错 =====================
            step("§6 0 报错")
            assert not errors, f"md_material 会话前端报错：{errors[:5]}"
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
