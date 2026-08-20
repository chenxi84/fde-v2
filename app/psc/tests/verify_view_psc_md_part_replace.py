"""e2e 前端验收 · psc:md_part_replace（替换关系）
断言：路由渲染防粘滞 → 造数后列表有数据 → 模态全字段 → 表单落库回显（创建/编辑/设为失效状态机）
→ 全程 0 console error / 0 pageerror / 0 HTTP≥400。
运行：python app/psc/tests/verify_view_psc_md_part_replace.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit, sqlite3


def _project_root() -> pathlib.Path:
    """向上找项目根（含 fde_platform/ 的目录）。脚本落点深度不固定，按标记定位才稳。"""
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

# admin 登录态：在平台子进程启动前经 users 模块播种（平台无建用户端点）。
from fde_platform import users  # noqa: E402
users.init_schema()
users.seed_admin()
# 标记 admin 已改密，跳过 auth gate ②.5 首次登录强制改密（否则 /api/* 收 403）
try:
    auth_db = ROOT / "config" / "auth.db"
    if auth_db.exists():
        conn = sqlite3.connect(str(auth_db))
        conn.execute("UPDATE users SET password_changed = 1 WHERE username = 'admin'")
        conn.commit()
        conn.close()
except Exception:
    pass


STEP = "init"


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

  await call("md_material", "create", {material_no: "M3", material_name: "原件前保险杠"});
  await call("md_material", "create", {material_no: "M4", material_name: "替换件前保险杠B"});
  await call("md_material", "create", {material_no: "M5", material_name: "替换件前保险杠C"});

  const rel1 = unwrap(await call("md_part_replace", "create", {
    old_material_no: "M3", new_material_no: "M4", ecn_no: "ECN-001"
  }));
  const rel2 = unwrap(await call("md_part_replace", "create", {
    old_material_no: "M5", new_material_no: "M4", ecn_no: "ECN-002"
  }));

  return {seeded: true, rel1: rel1 && rel1.rel_no, rel2: rel2 && rel2.rel_no};
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


def wait_modal(page):
    """等可见模态，并等详情态 .loadbox 消失（pitfalls #16）；表单模态无 loadbox 直接返回。"""
    page.locator(".modal:visible, [role='dialog']:visible").first.wait_for(
        state="visible", timeout=10000)
    lb = page.locator(".modal-mask:visible .loadbox")
    if lb.count():
        try:
            lb.first.wait_for(state="hidden", timeout=5000)
        except Exception:
            pass
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


def choose_material(page, modal, label, material_no):
    """在创建/编辑表单模态内，通过物料 autocomplete 选物料号。"""
    wrapper = modal.locator(
        f'xpath=.//label[contains(normalize-space(.), "{label}")]/ancestor::*[1]'
    )
    inp = wrapper.locator("input").first
    inp.click()
    page.wait_for_timeout(250)
    drop = modal.locator(".autocomplete-drop:visible").last
    item = drop.locator(f'.mono:text-is("{material_no}")').first
    item.wait_for(state="visible", timeout=5000)
    item.click()
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
            # 原生 confirm（设为失效）自动点确定
            page.on("dialog", lambda d: d.accept())

            page.goto(f"{base}/view/psc/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)

            # ===================== §1 本页渲染（防粘滞）=====================
            step("§1 本页渲染")
            page.evaluate("location.hash = '#/md_part_replace'")
            try:
                page.wait_for_selector("main .card, main .tbl, main table", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator("main").inner_text().strip(), "md_part_replace 页面无内容"
            assert page.locator("main .card, main .tbl, main table").count() > 0, "md_part_replace 未渲染"
            assert page.locator(".kpi").count() == 0, "md_part_replace 挂载未重建（残留看板）"
            assert page.locator('input[placeholder="原物料号"]').count() >= 1, "缺原物料号过滤输入"
            assert page.locator('input[placeholder="替换物料号"]').count() >= 1, "缺替换物料号过滤输入"
            assert page.locator('.fchip:has-text("生效")').count() >= 1, "缺状态 chips 生效"
            assert page.locator('.fchip:has-text("失效")').count() >= 1, "缺状态 chips 失效"
            assert page.locator('button:has-text("查询")').count() >= 1, "缺查询按钮"
            assert page.locator('button:has-text("重置")').count() >= 1, "缺重置按钮"
            assert page.locator('button:has-text("＋ 新建替换关系")').count() >= 1, "缺新建替换关系按钮"
            assert page.locator('input[placeholder*="关键字"]').count() == 0, "不应有关键字搜索框（契约无 keyword）"

            # ===================== §0 造数（跨应用前置 + 本页主数据）=====================
            step("§0 造数")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"造数失败：{seed}"
            rel1 = seed["rel1"]
            rel2 = seed["rel2"]
            assert rel1 and rel2, f"造数未捕获 rel_no：{seed}"

            # 重载使列表重新拉取（pageable.init 只在挂载时 load）
            page.reload()
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.wait_for_selector(f'table.tbl.tight tr.data:has-text("{rel1}")', timeout=15000)
            page.wait_for_timeout(600)

            # ===================== §2 列表有数据 =====================
            step("§2 VT-LIST-01 列表含所造单号")
            assert page.locator("table.tbl.tight tr.data").count() >= 2, "替换关系造数后列表无数据"
            row1 = page.locator(f'table.tbl.tight tr.data:has-text("{rel1}")').first
            txt1 = row1.inner_text()
            # 关系号(rel_no)默认隐藏（col_default_hidden），不在行文本中断言
            for expected in ["M3", "M4", "ECN-001", "生效", "原件前保险杠", "替换件前保险杠B"]:
                assert expected in txt1, f"REL1 行缺字段：{expected}"
            rel_th = page.locator('table.tbl.tight tr:first-child th', has_text="关系号")
            assert rel_th.count() == 1 and not rel_th.first.is_visible(), "关系号列应默认隐藏"

            step("§2 VT-LIST-02 原物料号过滤收敛")
            page.locator('input[placeholder="原物料号"]').first.fill("M3")
            click_button(page, ["查询"])
            page.wait_for_selector(f'table.tbl.tight tr.data:has-text("{rel1}")', timeout=10000)
            page.wait_for_timeout(400)
            assert page.locator(f'table.tbl.tight tr.data:has-text("{rel1}")').count() >= 1, "过滤 M3 应含 REL1"
            assert page.locator(f'table.tbl.tight tr.data:has-text("{rel2}")').count() == 0, "过滤 M3 不应含 REL2"

            step("§2 VT-LIST-03 替换物料号过滤收敛")
            click_button(page, ["重置"])
            page.wait_for_timeout(400)
            page.locator('input[placeholder="替换物料号"]').first.fill("M4")
            click_button(page, ["查询"])
            page.wait_for_selector(f'table.tbl.tight tr.data:has-text("{rel1}")', timeout=10000)
            page.wait_for_timeout(400)
            assert page.locator(f'table.tbl.tight tr.data:has-text("{rel1}")').count() >= 1, "过滤 M4 应含 REL1"
            assert page.locator(f'table.tbl.tight tr.data:has-text("{rel2}")').count() >= 1, "过滤 M4 应含 REL2"

            step("§2 VT-LIST-04 状态 chips 过滤")
            click_button(page, ["重置"])
            page.wait_for_timeout(400)
            page.locator('.fchip:has-text("生效")').first.click()
            page.wait_for_timeout(500)
            assert page.locator(f'table.tbl.tight tr.data:has-text("{rel1}")').count() >= 1, "chips 生效应含 REL1"
            assert page.locator(f'table.tbl.tight tr.data:has-text("{rel2}")').count() >= 1, "chips 生效应含 REL2"
            page.locator('.fchip:has-text("失效")').first.click()
            page.wait_for_timeout(500)
            assert page.locator("td.empty:has-text('无匹配数据')").count() >= 1, "chips 失效应空态"

            # ===================== §3 模态全字段 =====================
            step("§3 VT-MODAL-01 详情模态全字段")
            click_button(page, ["重置"])
            page.wait_for_timeout(400)
            page.locator(f'table.tbl.tight tr.data:has-text("{rel1}") .b-link.mono').first.click()
            modal = wait_modal(page)
            assert modal.locator(".modal-hd .docno").first.inner_text().strip() == rel1, "详情头带关系号不符"
            assert modal.locator(".modal-hd .st").first.inner_text().strip() == "生效", "详情头带状态不符"
            txt = modal.locator(".modal-bd").first.inner_text()
            for expected in ["关系号", "状态", "原物料号", "替换物料号", "ECN 依据",
                             rel1, "生效", "M3", "M4", "ECN-001", "原件前保险杠", "替换件前保险杠B"]:
                assert expected in txt, f"详情模态缺字段：{expected}"
            ft = modal.locator(".modal-ft").inner_text()
            for expected in ["编辑", "设为失效", "关闭"]:
                assert expected in ft, f"详情页脚缺按钮：{expected}"
            raw = modal.locator("details.raw")
            assert raw.count() >= 1, "详情模态缺原始数据"
            raw.locator("summary").first.click()
            assert rel1 in raw.locator("pre.json").inner_text(), "原始数据未展开全量 JSON"
            close_modal(page, modal)

            # ===================== §4 表单 =====================
            step("§4 VT-FORM-02 必填空值被拒")
            click_button(page, ["＋ 新建替换关系"])
            modal = wait_modal(page)
            click_button(modal, ["创建"])
            page.wait_for_selector('.toast.warn:has-text("请选择原物料号")', timeout=3000)
            choose_material(page, modal, "原物料号", "M3")
            click_button(modal, ["创建"])
            page.wait_for_selector('.toast.warn:has-text("请选择替换物料号")', timeout=3000)
            close_modal(page, modal)

            step("§4 VT-FORM-03 原=替换前端拦截")
            click_button(page, ["＋ 新建替换关系"])
            modal = wait_modal(page)
            choose_material(page, modal, "原物料号", "M3")
            choose_material(page, modal, "替换物料号", "M3")
            click_button(modal, ["创建"])
            page.wait_for_selector('.toast.warn:has-text("原物料号与替换物料号不能相同")', timeout=3000)
            close_modal(page, modal)

            step("§4 VT-FORM-04 组合唯一后端拦截")
            rows_before = page.locator("table.tbl.tight tr.data").count()
            click_button(page, ["＋ 新建替换关系"])
            modal = wait_modal(page)
            choose_material(page, modal, "原物料号", "M3")
            choose_material(page, modal, "替换物料号", "M4")
            click_button(modal, ["创建"])
            page.wait_for_selector('.toast.err:has-text("该原物料+替换物料组合已存在")', timeout=5000)
            close_modal(page, modal)
            assert page.locator("table.tbl.tight tr.data").count() == rows_before, "组合唯一失败不应新增行"

            step("§4 VT-FORM-05 物料 autocomplete 数据源")
            click_button(page, ["＋ 新建替换关系"])
            modal = wait_modal(page)
            wrapper = modal.locator(
                'xpath=.//label[contains(normalize-space(.), "原物料号")]/ancestor::*[1]')
            wrapper.locator("input").first.click()
            page.wait_for_timeout(300)
            drop = modal.locator(".autocomplete-drop:visible").last
            drop_txt = drop.inner_text()
            for expected in ["M3", "M4", "M5", "原件前保险杠", "替换件前保险杠B", "替换件前保险杠C"]:
                assert expected in drop_txt, f"autocomplete 缺物料：{expected}"

            step("§4 VT-FORM-01 创建落库回显")
            choose_material(page, modal, "原物料号", "M4")
            choose_material(page, modal, "替换物料号", "M5")
            more = modal.locator('.more:has-text("更多字段")')
            if more.count():
                more.first.click()
                page.wait_for_timeout(300)
            fill_labeled(modal, "ECN 依据", "ECN-009")
            click_button(modal, ["创建"])
            page.wait_for_selector('.toast:has-text("已创建替换关系")', timeout=5000)
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            page.wait_for_selector('table.tbl.tight tr.data:has-text("ECN-009")', timeout=10000)
            new_row = page.locator('table.tbl.tight tr.data:has-text("ECN-009")').first
            assert new_row.count() >= 1, "创建后列表未回显 ECN-009"
            assert "生效" in new_row.locator(".st").first.inner_text(), "新建关系初始状态应为生效"

            step("§4 VT-FORM-06 编辑回显")
            row1 = page.locator(f'table.tbl.tight tr.data:has-text("{rel1}")').first
            row1.locator('button:has-text("编辑")').first.click()
            modal = wait_modal(page)
            assert f"编辑 · {rel1}" in modal.locator(".modal-hd .docno").first.inner_text(), "编辑模态 docno 不符"
            assert modal.locator("select").count() == 0, "编辑表单不应有 status 下拉（状态仅经 disable 变更）"
            more = modal.locator('.more:has-text("更多字段")')
            if more.count():
                more.first.click()
                page.wait_for_timeout(300)
            fill_labeled(modal, "ECN 依据", "ECN-001-B")
            click_button(modal, ["保存修改"])
            page.wait_for_selector('.toast:has-text("已更新替换关系")', timeout=5000)
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            row1 = page.locator(f'table.tbl.tight tr.data:has-text("{rel1}")').first
            assert "ECN-001-B" in row1.inner_text(), "编辑后列表未回显 ECN-001-B"

            step("§4 VT-FORM-07 设为失效（生效→失效）")
            row1 = page.locator(f'table.tbl.tight tr.data:has-text("{rel1}")').first
            row1.locator('button:has-text("设为失效")').first.click()
            page.wait_for_selector('.toast:has-text("替换关系已设为失效")', timeout=5000)
            page.wait_for_timeout(700)
            row1 = page.locator(f'table.tbl.tight tr.data:has-text("{rel1}")').first
            assert "失效" in row1.locator(".st").first.inner_text(), "REL1 行状态应为失效"
            assert row1.locator('button:has-text("设为失效"):visible').count() == 0, "失效行不应显示设为失效按钮"

            # 失效 chips 复验（VT-LIST-04 失效分支）
            page.locator('.fchip:has-text("失效")').first.click()
            page.wait_for_timeout(500)
            assert page.locator(f'table.tbl.tight tr.data:has-text("{rel1}")').count() >= 1, "失效过滤应含 REL1"

            step("§3 VT-MODAL-02 失效记录页脚无设为失效")
            page.locator(f'table.tbl.tight tr.data:has-text("{rel1}") .b-link.mono').first.click()
            modal = wait_modal(page)
            assert modal.locator(".modal-hd .st").first.inner_text().strip() == "失效", "失效详情状态不符"
            ft = modal.locator(".modal-ft").inner_text()
            assert "编辑" in ft and "关闭" in ft, "失效详情页脚缺编辑/关闭"
            assert modal.locator('.modal-ft button:has-text("设为失效"):visible').count() == 0, \
                "失效详情不应显示设为失效按钮"
            close_modal(page, modal)

            # ===================== §6 0 报错 =====================
            step("§6 0 报错")
            assert not errors, f"前端报错：{errors[:5]}"
            print("VERIFY_VIEW_psc_md_part_replace: PASS")

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
