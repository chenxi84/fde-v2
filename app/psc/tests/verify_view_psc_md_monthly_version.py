"""e2e 前端验收 - psc:md_monthly_version（月度版本）
断言：路由渲染防粘滞 → 造数后列表有数据 → 模态全字段 → 状态机（草稿→发布（锁定）→冻结→回退草稿）
+ 创建表单落库/校验 → 全程 0 console error / 0 pageerror / 0 HTTP≥400。
运行：python app/psc/tests/verify_view_psc_md_monthly_version.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit


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

# seed_admin 落 password_changed=0 → 首登被强制改密闸门拦下（auth.py ②.5），
# 与 verify_view_e2e 样板/各逐应用脚本一致，先在隔离后的 config/auth.db 置 1 放行。
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


# §0 自足造数：V202607（冻结态：create→publish→freeze）+ V202608（草稿·当前唯一活跃版本）。
# version_no 纯 YYYYMM；anchor_period 须 YYYY-MM（与历史台账期间一致）；opening_date 为 YYYY-MM-DD。
# 契约无 update / delete → 变更仅经 publish / freeze / unfreeze。
SEED_JS = r"""async () => {
  const call = async (svc, params) => {
    const r = await fetch(`/api/apps/psc/md_monthly_version/call/${svc}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(params || {})
    });
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) {}
    if (!r.ok) throw new Error(`md_monthly_version.${svc} HTTP ${r.status} ${text.slice(0, 160)}`);
    if (data && data.status === "error") {
      throw new Error(`md_monthly_version.${svc} biz ${data.message || JSON.stringify(data).slice(0, 160)}`);
    }
    return data;
  };

  // V202607：先建 → publish → freeze（冻结为归档态、非活跃）
  await call("create", {version_no: "202607", anchor_period: "2026-07", opening_date: "2026-07-01"});
  await call("publish", {version_no: "202607"});
  await call("freeze", {version_no: "202607"});
  // V202608：草稿（当前唯一活跃版本，BR-06 未冻结版本互斥）
  await call("create", {version_no: "202608", anchor_period: "2026-08", opening_date: "2026-08-01"});

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
    """等 .modal-mask:visible 出现、.loadbox 消失（详情模态载入明细），返回可见模态。
    （pitfalls #16；多 .modal-bd 用 .first；页脚按钮读 .modal-mask:visible）"""
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
            # §0 造数（测试数据字典：非用例，文档未编 VT 编号 —— 仅作后续用例前置）
            step("§0 造数（V202607 冻结 + V202608 草稿）")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"md_monthly_version 造数失败：{seed}"

            # ===================== §1 本页渲染（防粘滞）=====================
            # §1 VT-RENDER-01 路由渲染有内容（.card>0 · .kpi==0 · 工具栏「+ 新建版本」）
            step("§1 路由渲染防粘滞")
            page.evaluate("location.hash = '#/md_monthly_version'")
            try:
                page.wait_for_selector("main .card", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator("main").inner_text().strip(), "md_monthly_version 页面无内容"
            assert page.locator("main .card").count() > 0, "md_monthly_version 未渲染 card"
            assert page.locator(".kpi:visible").count() == 0, "md_monthly_version 挂载未重建（残留看板）"
            assert page.locator('button:visible:has-text("新建版本")').count() > 0, "工具栏缺少 ＋ 新建版本"

            # ===================== §2 造数后列表有数据 =====================
            # §2 VT-LIST-01 列表含所造单号（四列回显 + lock_status 徽章 + version_no 降序）
            step("§2 列表含所造单号（202608 草稿 / 202607 冻结 / 降序）")
            rows = page.locator("table.tbl tr.data")
            assert rows.count() >= 2, f"md_monthly_version 列表行数不足：{rows.count()}"
            assert rows.filter(has_text="202608").count() == 1, "列表未见 202608 行"
            assert rows.filter(has_text="202607").count() == 1, "列表未见 202607 行"

            row_608 = rows.filter(has_text="202608").first
            row_607 = rows.filter(has_text="202607").first
            assert "草稿" in row_608.inner_text(), "202608 行 lock_status 应为草稿"
            assert "冻结" in row_607.inner_text(), "202607 行 lock_status 应为冻结"
            for v in ["202608", "2026-08", "2026-08-01", "草稿"]:
                assert v in row_608.inner_text(), f"202608 行四列回显缺失：{v}"

            all_text = page.locator("table.tbl").inner_text()
            assert all_text.index("202608") < all_text.index("202607"), "列表应按 version_no 降序（202608 在 202607 前）"

            # §2 VT-LIST-02 版本号精确过滤（WHERE version_no = ? 精确匹配 → 仅 202608）
            step("§2 VT-LIST-02 版本号精确过滤（202608）")
            page.locator('input[placeholder="版本号 · 如 202608"]').first.fill("202608")
            click_button(page, ["搜索"])
            page.wait_for_timeout(600)
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 1, f"版本号=202608 应仅 1 行，实际 {rows.count()}"
            assert "202608" in rows.first.inner_text(), "版本号过滤结果不含 202608"
            assert rows.filter(has_text="202607").count() == 0, \
                "版本号精确过滤不应命中 202607（等值匹配，非模糊）"

            # §2 VT-LIST-03 锁定状态 chips 过滤（点「冻结」→ 仅 202607 冻结行）
            step("§2 VT-LIST-03 锁定状态 chips 过滤（冻结）")
            click_button(page, ["重置"])
            page.wait_for_timeout(600)
            page.locator('.fchip:visible:has-text("冻结")').first.click()
            page.wait_for_timeout(600)
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 1, f"状态=冻结 应仅 1 行（202607），实际 {rows.count()}"
            assert rows.filter(has_text="202607").count() == 1, "状态=冻结 未命中 202607 行"
            assert rows.filter(has_text="202608").count() == 0, "状态=冻结 不应含草稿行 202608"

            # §2 VT-LIST-04 组合过滤与空态（版本号 AND 状态；无匹配时空态文案，不抛错）
            step("§2 VT-LIST-04 组合过滤与空态（202608+草稿 / 199901 无匹配）")
            page.locator('.fchip:visible:has-text("草稿")').first.click()
            page.wait_for_timeout(400)
            page.locator('input[placeholder="版本号 · 如 202608"]').first.fill("202608")
            click_button(page, ["搜索"])
            page.wait_for_timeout(600)
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 1, f"版本号=202608 且 状态=草稿 应仅 1 行，实际 {rows.count()}"
            assert "202608" in rows.first.inner_text() and "草稿" in rows.first.inner_text(), \
                "组合过滤结果应为 202608 草稿行"

            page.locator('input[placeholder="版本号 · 如 202608"]').first.fill("199901")
            click_button(page, ["搜索"])
            page.wait_for_timeout(600)
            assert page.locator("table.tbl tr.data").count() == 0, "版本号=199901 应无匹配行"
            empty = page.locator("td.empty").first
            assert empty.inner_text().strip() == "无匹配数据", f"空态文案不符：{empty.inner_text()!r}"
            # 空态属正常路径（后端返回空集，非错误）：不得喷「失败/错误」类 toast。
            # 不能断言「页面无任何 toast」—— 平台自身的「agent_service 不可用」提示（本环境不起
            # agent 服务）与列表过滤无关，故逐条读文案、剔除该条后再判失败/错误类。
            bad = [m for m in (t.inner_text() for t in page.locator(".toast:visible").all())
                   if "agent_service" not in m and ("失败" in m or "错误" in m or "不可用" in m)]
            assert not bad, f"无匹配属正常空态，不应喷失败/错误 toast：{bad}"

            # 复位：清空过滤，列表回全量（后续 §3 模态/§4.1 状态机依赖 202607/202608 均可见）
            click_button(page, ["重置"])
            page.wait_for_timeout(600)
            assert page.locator("table.tbl tr.data").count() >= 2, "重置后列表应恢复全量"

            # ===================== §3 模态全字段 =====================
            # §3 VT-MODAL-01 草稿详情模态全字段（标签/值 + 原始数据区 + 页脚含【发布】无【编辑】/【删除】）
            step("§3 草稿详情模态全字段（202608）")
            page.locator('table.tbl tr.data .b-link:has-text("202608")').first.click()
            modal = wait_modal(page)
            txt = modal.inner_text()
            for label in ["版本号", "锁定状态", "锚定期间", "opening 日"]:
                assert label in txt, f"详情模态缺字段标签：{label}"
            for val in ["202608", "草稿", "2026-08", "2026-08-01"]:
                assert val in txt, f"详情模态缺字段值：{val}"
            assert "原始数据" in txt, "详情模态缺「原始数据」折叠区"

            ft = modal.locator(".modal-ft")
            assert ft.locator('button:visible:has-text("发布")').count() == 1, "草稿态页脚应有发布按钮"
            assert ft.locator('button:has-text("编辑")').count() == 0, "草稿态页脚不应有编辑按钮（无 update 服务）"
            assert ft.locator('button:has-text("删除")').count() == 0, "草稿态页脚不应有删除按钮（无 delete 服务）"
            close_modal(page, modal)

            # §3 VT-MODAL-02 冻结态模态含回退按钮（202607；页脚无【发布】/【冻结】）
            step("§3 冻结态详情模态含回退按钮（202607）")
            page.locator('table.tbl tr.data .b-link:has-text("202607")').first.click()
            modal = wait_modal(page)
            txt = modal.inner_text()
            assert "冻结" in txt, "冻结态模态缺状态回显"
            ft = modal.locator(".modal-ft")
            for forbidden in ["发布", "冻结"]:
                assert ft.locator(f'button:visible:has-text("{forbidden}")').count() == 0, \
                    f"冻结态页脚不应出现 {forbidden} 按钮"
            assert ft.locator('button:visible:has-text("回退")').count() == 1, "冻结态页脚应有回退按钮"
            close_modal(page, modal)

            # ===================== §4.1 状态机（草稿→发布（锁定）→冻结，按 lock_status x-show）=====================
            # §4.1 VT-STATE-01 草稿 → 发布（锁定）：行内【发布】+ 模态页脚同一 x-show 判定
            step("§4.1 草稿 → 发布（锁定）：行内【发布】")
            row_608 = page.locator('table.tbl tr.data:has-text("202608")').first
            assert row_608.locator('button:visible:has-text("发布")').count() == 1, "草稿行内应有发布按钮"
            row_608.locator('button:visible:has-text("发布")').first.click()
            expect_toast(page, "版本发布成功，预测已锁定")
            page.wait_for_timeout(700)  # 等 list.load 刷新

            row_608 = page.locator('table.tbl tr.data:has-text("202608")').first
            assert "发布（锁定）" in row_608.inner_text(), "发布后行状态应变为 发布（锁定）"
            assert row_608.locator('button:visible:has-text("发布")').count() == 0, "发布后行内发布按钮应隐藏"
            assert row_608.locator('button:visible:has-text("冻结")').count() == 1, "发布后行内冻结按钮应出现"

            # 模态页脚同一 x-show 判定：发布（锁定）态【冻结】可见、【发布】不可见
            page.locator('table.tbl tr.data .b-link:has-text("202608")').first.click()
            modal = wait_modal(page)
            ft = modal.locator(".modal-ft")
            assert ft.locator('button:visible:has-text("冻结")').count() == 1, "发布（锁定）态页脚应有冻结按钮"
            assert ft.locator('button:visible:has-text("发布")').count() == 0, "发布（锁定）态页脚不应有发布按钮"
            close_modal(page, modal)

            # §4.1 VT-STATE-02 发布（锁定） → 冻结：行内【冻结】
            step("§4.1 发布（锁定） → 冻结：行内【冻结】")
            row_608 = page.locator('table.tbl tr.data:has-text("202608")').first
            assert row_608.locator('button:visible:has-text("冻结")').count() == 1, "发布（锁定）行内应有冻结按钮"
            row_608.locator('button:visible:has-text("冻结")').first.click()
            expect_toast(page, "版本冻结成功")
            page.wait_for_timeout(700)

            row_608 = page.locator('table.tbl tr.data:has-text("202608")').first
            assert "冻结" in row_608.inner_text(), "冻结后行状态应变为 冻结"

            # §4.1 VT-STATE-03 冻结行内仅回退按钮（202607 / 202608 均冻结，无【发布】/【冻结】）
            step("§4.1 冻结行内仅回退按钮（202607 / 202608 均冻结）")
            for no in ["202607", "202608"]:
                r = page.locator(f'table.tbl tr.data:has-text("{no}")').first
                assert r.locator('button:visible:has-text("发布")').count() == 0, f"{no} 冻结态不应有发布按钮"
                assert r.locator('button:visible:has-text("冻结")').count() == 0, f"{no} 冻结态不应有冻结按钮"
                assert r.locator('button:visible:has-text("回退")').count() == 1, f"{no} 冻结态应有回退按钮"

            # §4.1 VT-STATE-04 冻结 → 草稿（回退）：行内【回退】202608
            step("§4.1 冻结 → 草稿（回退）：行内【回退】202608")
            row_608 = page.locator('table.tbl tr.data:has-text("202608")').first
            assert row_608.locator('button:visible:has-text("回退")').count() == 1, "冻结行内应有回退按钮"
            row_608.locator('button:visible:has-text("回退")').first.click()
            expect_toast(page, "版本已回退到草稿")
            page.wait_for_timeout(700)
            row_608 = page.locator('table.tbl tr.data:has-text("202608")').first
            assert "草稿" in row_608.inner_text(), "回退后行状态应变为 草稿"
            assert row_608.locator('button:visible:has-text("发布")').count() == 1, "回退后行内发布按钮应出现"
            assert row_608.locator('button:visible:has-text("回退")').count() == 0, "回退后行内回退按钮应隐藏"

            # 恢复：回退后 202608 重新成为活跃版本，重新 publish→freeze 归位，
            # 以维持 §4.2「创建 202609」所需的「全库无活跃版本」前提。
            # §4.1 恢复性前置操作（**无对应用例**：把 202608 重新 publish→freeze 归位，
            #   仅为满足 §4.2「全库无活跃版本」前提，不属文档任何 VT 条目）
            step("§4.1 回退后重新冻结 202608（恢复无活跃，供 §4.2 创建 202609）")
            row_608 = page.locator('table.tbl tr.data:has-text("202608")').first
            row_608.locator('button:visible:has-text("发布")').first.click()
            expect_toast(page, "版本发布成功，预测已锁定")
            page.wait_for_timeout(700)
            row_608 = page.locator('table.tbl tr.data:has-text("202608")').first
            row_608.locator('button:visible:has-text("冻结")').first.click()
            expect_toast(page, "版本冻结成功")
            page.wait_for_timeout(700)
            # 前置恢复步的状态断言（**无对应用例**）：202608 必须真的回到「冻结」，否则 §4.2
            # 「全库无活跃版本」前提不成立 —— 后续用例会以「活跃版本冲突」之类的假象失败，
            # 掩盖真正的原因（恢复步没生效）。
            row_608 = page.locator('table.tbl tr.data:has-text("202608")').first
            assert "冻结" in row_608.inner_text(), \
                f"恢复步失败：202608 重新冻结后 lock_status 应为 冻结，实际 {row_608.inner_text()[:80]}"
            assert row_608.locator('button:visible:has-text("发布")').count() == 0, \
                "恢复步失败：202608 仍显示发布按钮（说明仍是活跃版本）"

            # ===================== §4.2 创建表单落库与校验 =====================
            # §4.2 VT-FORM-01 空必填被拒（纯前端校验，模态保持打开）
            step("§4.2 空必填被拒（纯前端校验，模态保持打开）")
            click_button(page, ["新建版本"])
            modal = wait_modal(page)
            click_button(modal, ["创建版本"])
            expect_toast(page, "请填写版本号")
            assert modal.is_visible(), "空必填被拒后模态应保持打开"

            # §4.2 VT-FORM-02 重复版本号被拒（202607 已存在）
            step("§4.2 重复版本号被拒（202607 已存在）")
            rows_before = page.locator("table.tbl tr.data").count()
            fill_labeled(modal, "版本号", "202607")
            fill_labeled(modal, "锚定期间", "2026-07")
            fill_labeled(modal, "opening 日", "2026-07-01")
            click_button(modal, ["创建版本"])
            expect_toast(page, "该版本号已存在")
            # 用例 §4.2 VT-FORM-02 断言：后端 FdeError toast + **列表不新增行**（没有多出重复行）
            assert modal.is_visible(), "重复版本号被拒后模态应保持打开"
            rows_after = page.locator("table.tbl tr.data").count()
            assert rows_after == rows_before, \
                f"重复版本号被拒不应新增行：{rows_before} → {rows_after}"
            assert page.locator('table.tbl tr.data:has-text("202607")').count() == 1, \
                "重复版本号被拒后 202607 应仍恰 1 行（未落重复行）"
            close_modal(page, modal)

            # §4.2 VT-FORM-03 创建落库（202609，草稿）
            step("§4.2 创建落库（202609，草稿）")
            click_button(page, ["新建版本"])
            modal = wait_modal(page)
            fill_labeled(modal, "版本号", "202609")
            fill_labeled(modal, "锚定期间", "2026-09")
            fill_labeled(modal, "opening 日", "2026-09-01")
            click_button(modal, ["创建版本"])
            expect_toast(page, "月度版本创建成功")
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            rows = page.locator("table.tbl tr.data")
            assert rows.filter(has_text="202609").count() == 1, "创建后列表应含 202609 行"
            assert "草稿" in rows.filter(has_text="202609").first.inner_text(), "202609 初始状态应为草稿"

            # §4.2 VT-FORM-04 活跃版本冲突（202610 被拒，BR-06）
            step("§4.2 活跃版本冲突（202610 被拒，BR-06）")
            rows_before = page.locator("table.tbl tr.data").count()
            click_button(page, ["新建版本"])
            modal = wait_modal(page)
            fill_labeled(modal, "版本号", "202610")
            fill_labeled(modal, "锚定期间", "2026-10")
            fill_labeled(modal, "opening 日", "2026-10-01")
            click_button(modal, ["创建版本"])
            expect_toast(page, "已存在活跃版本")
            close_modal(page, modal)
            assert page.locator("table.tbl tr.data").filter(has_text="202610").count() == 0, \
                "活跃版本冲突时列表不应新增 202610"
            assert page.locator("table.tbl tr.data").count() == rows_before, \
                "活跃版本冲突时列表行数不应变化（未落任何新版本行）"

            # ===================== §6 0 报错红线 =====================
            # §6 VT-ERR-01 本会话 0 报错
            step("§6 会话 0 报错")
            assert not errors, f"md_monthly_version 会话前端报错：{errors[:5]}"
            # **豁免也要受检**（2026-09-17 补）：`ignored` 收集了却从不校验，等于给「静默吞掉」
            # 开了口子 —— 任何新形态的 4xx/console error 都能混进来而不被任何人发现。
            # 只认 favicon / sourcemap / 403 三种豁免理由，其余一律报出。
            for item in ignored:
                ok = ("/favicon.ico" in item or ".map" in item or "403" in item)
                assert ok, f"豁免理由不成立（既不是 favicon/.map，也不是 403）：{item!r}"
            if ignored:
                print(f"  · 本次豁免 {len(ignored)} 条：{ignored[:3]}")
            print("VERIFY_VIEW_psc_md_monthly_version: PASS")

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
        print(f"VERIFY_VIEW_psc_md_monthly_version: FAIL @ {STEP}: {e}")
        sys.exit(1)
