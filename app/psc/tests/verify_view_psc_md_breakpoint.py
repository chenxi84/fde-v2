"""e2e 前端验收 - psc:md_breakpoint（断点基础数据）
断言：路由渲染防粘滞（.kpi==0）→ 造数后列表有断点 → 详情模态全字段 → 表单
create/update + 停用（disable）+ old≠new 校验 → 全程 0 console error / 0 pageerror / 0 HTTP≥400。
造数走真实 REST（浏览器内 fetch，带会话 Cookie；跨应用前置 md_customer/md_material）。
运行：python app/psc/tests/verify_view_psc_md_breakpoint.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit


def _project_root() -> pathlib.Path:
    """向上找项目根（含 fde_platform/ 的目录）。按标记定位，不写死 parents[N]。"""
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

# admin 账号（登录必需）；seed_admin 落 password_changed=0，首次登录会强制改密，
# 直接置 1 绕开 /change-password 页（与 parts-fc 逐应用脚本同法）。
from fde_platform import users  # noqa: E402

users.init_schema()
users.seed_admin()
import sqlite3

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


# ── 造数（跨应用前置 + 本页主数据；组限定路径 'psc/<短名>'，与 view.js svc() 同构）──
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
      throw new Error(`${app}.${svc} biz ${(data.message || JSON.stringify(data)).slice(0, 160)}`);
    }
    return data;
  };

  const unwrap = (x) => {
    if (!x) return x;
    if (x.data !== undefined) return x.data;
    if (x.result !== undefined) return x.result;
    return x;
  };

  // 跨应用前置：客户 + 原/新物料
  await call("md_customer", "create", { customer_no: "C001", customer_name: "客户C001" });
  await call("md_material", "create", { material_no: "M3", material_name: "旧物料A" });
  await call("md_material", "create", { material_no: "M4", material_name: "新物料B" });

  // 本页主数据 BP1（§2/§3 用）
  const bp1 = unwrap(await call("md_breakpoint", "create", {
    customer_no: "C001",
    old_material_no: "M3",
    new_material_no: "M4",
    switch_time: "2026-09-01",
    ecn_no: "ECN-002"
  }));

  return { seeded: true, bp1_id: bp1 && bp1.bp_id };
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
    # 详情 + 创建/编辑表单各是一个 .modal-mask；取可见者中的 last（同表单并开时表单在后）。
    page.locator(".modal-mask:visible").first.wait_for(state="visible", timeout=10000)
    return page.locator(".modal-mask:visible").last


def close_modal(page, modal):
    btn = modal.locator('button:has-text("关闭"), button:has-text("取消"), button.x')
    if btn.count():
        btn.first.click()
    else:
        page.keyboard.press("Escape")
    try:
        modal.wait_for(state="hidden", timeout=3000)
    except Exception:
        page.keyboard.press("Escape")
    page.wait_for_timeout(250)


def pick_autocomplete(page, modal, placeholder, value):
    """表单 autocomplete：fill 输入触发下拉 → 点可见的匹配项（原/新物料号各有实例，
    用 :visible 限定，避免点到未展开的同名下拉）。"""
    inp = modal.locator(f'input[placeholder*="{placeholder}"]').first
    inp.click()
    inp.fill(value)
    opt = modal.locator(f'.mono:visible:has-text("{value}")').first
    opt.wait_for(state="visible", timeout=5000)
    opt.click()
    page.wait_for_timeout(200)


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

            # admin 单会话（逐应用脚本：仅 admin，无受限会话）
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

            # ===================== §1 本页渲染（防粘滞）=====================
            step("§1 本页渲染（防粘滞）")
            page.evaluate("location.hash = '#/md_breakpoint'")
            try:
                page.wait_for_selector("main .card", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator("main").inner_text().strip(), "md_breakpoint 页面无内容"
            assert page.locator("main .card").count() > 0, "md_breakpoint 未渲染 card"
            assert page.locator("main .tbl, main table").count() > 0, "md_breakpoint 未渲染表格"
            assert page.locator(".kpi").count() == 0, "md_breakpoint 挂载未重建（残留看板）"

            # ===================== §0 造数 =====================
            step("§0 造数（跨应用前置 + BP1）")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"md_breakpoint 造数失败：{seed}"
            bp1_id = str(seed.get("bp1_id"))

            # ===================== §2 造数后列表有数据 =====================
            step("§2 造数后列表有数据")
            page.reload()
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.evaluate("location.hash = '#/md_breakpoint'")
            page.wait_for_selector('table tr:has-text("ECN-002")', timeout=15000)
            page.wait_for_timeout(500)

            row1 = page.locator('table tr:has-text("ECN-002")')
            assert row1.count() == 1, f"md_breakpoint 列表应恰好 1 条 BP1，实际 {row1.count()}"
            row1_txt = row1.first.inner_text()
            # 断点标识(bp_id)默认隐藏（col_default_hidden），不在行文本中断言
            for expected in ["C001", "M3", "M4", "2026-09-01", "ECN-002"]:
                assert expected in row1_txt, f"md_breakpoint 列表行缺字段：{expected}"

            # 表头无「状态」列（后端固定 disabled=0 过滤，无状态筛选维度）
            header_txt = page.locator("table tr").first.inner_text()
            assert "状态" not in header_txt, f"md_breakpoint 表头不应含「状态」列：{header_txt[:80]}"
            # 断点标识列默认隐藏（列设置默认隐藏机制生效）
            bp_th = page.locator('table tr:first-child th', has_text="断点标识")
            assert bp_th.count() == 1 and not bp_th.first.is_visible(), "断点标识列应默认隐藏"

            # ===================== §3 详情模态全字段 =====================
            step("§3 详情模态全字段")
            row1.first.locator(".b-link").first.click()
            modal = open_modal(page)
            try:
                page.locator(".modal-mask:visible .loadbox").first.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass

            txt = modal.inner_text()
            for expected in [
                "断点标识", "停用状态", "客户", "原物料号", "新物料号",
                "切换时间", "变更单号", "原始数据",
                bp1_id, "C001", "M3", "M4", "2026-09-01", "ECN-002", "正常",
            ]:
                assert expected in txt, f"md_breakpoint 详情模态缺字段：{expected}"

            # 页脚含【编辑】【停用】【关闭】
            ft = modal.locator(".modal-ft").first
            for btn in ["编辑", "停用", "关闭"]:
                assert ft.locator(f'button:has-text("{btn}")').count() > 0, \
                    f"md_breakpoint 详情模态页脚缺按钮：{btn}"

            # 「原始数据」折叠区可展开
            raw = modal.locator('details.raw summary:has-text("原始数据")')
            if raw.count():
                raw.first.click()
                page.wait_for_timeout(200)
                assert modal.locator("details.raw pre.json").count() > 0, "原始数据折叠区未展开"

            close_modal(page, modal)

            # ===================== §4 表单落库回显 / 校验 / 停用 =====================
            # VT-FORM-01 创建成功落库回显（BP2）
            step("§4 VT-FORM-01 创建成功落库回显")
            click_button(page, ["新建断点"])
            modal = open_modal(page)

            pick_autocomplete(page, modal, "搜索客户", "C001")
            pick_autocomplete(page, modal, "搜索原物料", "M3")
            pick_autocomplete(page, modal, "搜索新物料", "M4")
            modal.locator('input[type="date"]').first.fill("2026-10-01")

            more = modal.locator('.more:has-text("更多字段")')
            if more.count():
                more.first.click()
                page.wait_for_timeout(250)
            ecn_inp = modal.locator('input[placeholder*="可选"]')
            if ecn_inp.count():
                ecn_inp.first.fill("ECN-FORM")

            click_button(modal, ["创建", "保存", "提交"])
            page.wait_for_selector('.toast:has-text("断点创建成功")', timeout=5000)
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            page.wait_for_selector('table tr:has-text("ECN-FORM")', timeout=10000)
            row2 = page.locator('table tr:has-text("ECN-FORM")')
            assert row2.count() == 1, f"创建后应恰好 1 条 ECN-FORM，实际 {row2.count()}"
            # bp_id 列默认隐藏，改从接口取 ECN-FORM 行的 bp_id
            bp2_id = page.evaluate("""async () => {
              const r = await fetch('/api/apps/psc/md_breakpoint/call/list',
                {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({size: 200})});
              const j = await r.json(); const items = (j.data && j.data.items) || [];
              const row = items.find(x => x.ecn_no === 'ECN-FORM'); return row ? String(row.bp_id) : '';
            }""")
            assert bp2_id, "md_breakpoint 未取到 ECN-FORM 行的 bp_id"
            row2_txt = row2.first.inner_text()
            for expected in [bp2_id, "C001", "M3", "M4", "2026-10-01", "ECN-FORM"]:
                assert expected in row2_txt, f"新建断点行缺字段：{expected}"

            # VT-FORM-02 必填校验（空值拦截，不发请求）
            step("§4 VT-FORM-02 必填校验")
            before_rows = page.locator("table tr.data").count()
            click_button(page, ["新建断点"])
            modal = open_modal(page)
            click_button(modal, ["创建"])
            page.wait_for_selector('.toast.warn:has-text("请选择客户")', timeout=5000)
            assert modal.is_visible(), "必填校验应保持模态打开"
            close_modal(page, modal)
            after_rows = page.locator("table tr.data").count()
            assert after_rows == before_rows, "必填校验不应产生新记录"

            # VT-FORM-03 old=new 校验
            step("§4 VT-FORM-03 old=new 校验")
            click_button(page, ["新建断点"])
            modal = open_modal(page)
            pick_autocomplete(page, modal, "搜索客户", "C001")
            pick_autocomplete(page, modal, "搜索原物料", "M3")
            pick_autocomplete(page, modal, "搜索新物料", "M3")
            modal.locator('input[type="date"]').first.fill("2026-11-01")
            click_button(modal, ["创建"])
            page.wait_for_selector('.toast.warn:has-text("原物料号与新物料号不能相同")', timeout=5000)
            assert page.locator('table tr:has-text("2026-11-01")').count() == 0, "old=new 不应产生新记录"
            close_modal(page, modal)

            # VT-FORM-04 组合唯一（后端 FdeError）
            step("§4 VT-FORM-04 组合唯一")
            click_button(page, ["新建断点"])
            modal = open_modal(page)
            pick_autocomplete(page, modal, "搜索客户", "C001")
            pick_autocomplete(page, modal, "搜索原物料", "M3")
            pick_autocomplete(page, modal, "搜索新物料", "M4")
            modal.locator('input[type="date"]').first.fill("2026-09-01")
            click_button(modal, ["创建"])
            page.wait_for_selector('.toast:has-text("该断点组合已存在")', timeout=5000)
            assert page.locator('table tr:has-text("ECN-002")').count() == 1, "组合唯一不应产生重复行"
            close_modal(page, modal)

            # VT-FORM-05 编辑态回显（bp_id 只读 + ecn_no 变更）
            step("§4 VT-FORM-05 编辑态回显")
            row2 = page.locator('table tr:has-text("ECN-FORM")').first
            row2.locator('button:has-text("编辑")').first.click()
            modal = open_modal(page)

            bp_id_input = modal.locator('input:disabled')
            assert bp_id_input.count() >= 1, "编辑态 bp_id 输入应只读（:disabled）"
            assert bp_id_input.first.input_value() == bp2_id, \
                f"编辑态 bp_id 回显错误：{bp_id_input.first.input_value()} != {bp2_id}"

            more = modal.locator('.more:has-text("更多字段")')
            if more.count():
                more.first.click()
                page.wait_for_timeout(250)
            ecn_inp = modal.locator('input[placeholder*="可选"]')
            ecn_inp.first.fill("ECN-EDIT")

            click_button(modal, ["保存修改", "保存", "更新"])
            page.wait_for_selector('.toast:has-text("断点更新成功")', timeout=5000)
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            page.wait_for_selector('table tr:has-text("ECN-EDIT")', timeout=10000)
            row2b = page.locator('table tr:has-text("ECN-EDIT")')
            assert row2b.count() == 1, f"编辑后应恰好 1 条 ECN-EDIT，实际 {row2b.count()}"
            row2b_txt = row2b.first.inner_text()
            assert "2026-10-01" in row2b_txt, "编辑后 switch_time 应保持 2026-10-01"
            assert "ECN-FORM" not in row2b_txt, "编辑后旧 ecn_no 不应再出现"

            # VT-FORM-06 停用（disable 软失效）
            step("§4 VT-FORM-06 停用")
            row2b = page.locator('table tr:has-text("ECN-EDIT")').first
            page.on("dialog", lambda d: d.accept())
            row2b.locator('button:has-text("停用")').first.click()
            page.wait_for_selector('.toast:has-text("断点已停用")', timeout=5000)
            page.wait_for_timeout(700)
            assert page.locator('table tr:has-text("ECN-EDIT")').count() == 0, "停用后该行应从列表消失"

            # 软失效：get 返回 disabled=1（非物理删除）
            get_result = page.evaluate(
                """async (bp_id) => {
                    const r = await fetch(`/api/apps/psc/md_breakpoint/call/get`, {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({bp_id: bp_id})
                    });
                    const j = await r.json();
                    return (j && j.data !== undefined) ? j.data : j;
                }""",
                int(bp2_id),
            )
            assert get_result and get_result.get("disabled") == 1, \
                f"停用后 get 应返回 disabled=1，实际 {get_result}"

            # ===================== §6 0 报错红线 =====================
            step("§6 0 报错红线")
            assert not errors, f"md_breakpoint 会话前端报错：{errors[:5]}"
            print("VERIFY_VIEW_psc_md_breakpoint: PASS")

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
        print(f"FAIL @ {STEP}: {e}", flush=True)
        sys.exit(1)
