"""e2e 前端验收 - psc:attainment（达成率与置信度 · 只读台账）。
断言：路由渲染防粘滞（无 .kpi / 无新建 / 无操作列）→ 造数后列表有数据 →
客户/物料/组合过滤收敛 + 空态 → 主数据名称回显 → 详情模态全字段 + 少报负值 →
全程 0 console error / 0 pageerror / 0 HTTP≥400。
用例来源：app/psc/attainment/前端测试用例.md（§0 自足字典 + §1/§2/§3/§6；§4 豁免——无表单）。
运行：python app/psc/tests/verify_view_psc_attainment.py
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

from fde_platform.dbguard import isolate_dbs  # noqa: E402

_iso = isolate_dbs()
_iso.__enter__()
atexit.register(_iso.__exit__, None, None, None)

from fde_platform import users  # noqa: E402
users.init_schema()
users.seed_admin()

# seed_admin 落 password_changed=0 → 首登被强制改密闸门拦下（auth.py ②.5），
# 与逐应用脚本一致，先在隔离后的 config/auth.db 置 1 放行。
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


# §0 自足造数（跨应用前置）：C001/C002（客户）+ M1/M2（物料）→
# ATTN1(C001×M1, mape=0.12, bias=0.08 多报为正) / ATTN2(C001×M2, bias=-0.03 少报为负) /
# ATTN3(C002×M1, mape=0.20, bias=0.10)。契约无 create/update/delete → 数据经
# attainment.upsert（ERP 回写口径）REST 直调造入（pitfalls #18）。
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
    if (!r.ok) throw new Error(`${app}.${svc} HTTP ${r.status} ${text.slice(0, 160)}`);
    if (data && data.status === "error") {
      throw new Error(`${app}.${svc} biz ${data.message || JSON.stringify(data).slice(0, 160)}`);
    }
    return data;
  };

  // 主数据（跨应用前置，先于达成率）
  await call("psc/md_customer", "create", {customer_no: "C001", customer_name: "客户A"});
  await call("psc/md_customer", "create", {customer_no: "C002", customer_name: "客户B"});
  await call("psc/md_material", "create", {material_no: "M1", material_name: "物料A"});
  await call("psc/md_material", "create", {material_no: "M2", material_name: "物料B"});

  // 达成率主数据（依赖主数据）
  await call("psc/attainment", "upsert", {customer_no: "C001", material_no: "M1", mape: 0.12, bias: 0.08});
  await call("psc/attainment", "upsert", {customer_no: "C001", material_no: "M2", mape: 0.05, bias: -0.03});
  await call("psc/attainment", "upsert", {customer_no: "C002", material_no: "M1", mape: 0.20, bias: 0.10});

  return {seeded: true};
}"""


STEP = "init"


def step(name):
    global STEP
    STEP = name
    print(f"[step] {name}")


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


def pick_customer(page, no):
    """客户 autocomplete：输入编码 → 点内联匹配项（回填 customer_no 并触发搜索）。"""
    page.locator('input[placeholder*="客户编码"]').fill(no)
    page.wait_for_timeout(400)
    opt = page.locator(f'div[x-show="custOpen"] span.mono:has-text("{no}")')
    assert opt.count() >= 1, f"客户 autocomplete 无选项：{no}"
    opt.first.wait_for(state="visible", timeout=5000)
    opt.first.click()
    page.wait_for_timeout(700)


def pick_material(page, no):
    """物料 autocomplete：输入物料号 → 点内联匹配项。"""
    page.locator('input[placeholder*="物料号"]').fill(no)
    page.wait_for_timeout(400)
    opt = page.locator(f'div[x-show="matOpen"] span.mono:has-text("{no}")')
    assert opt.count() >= 1, f"物料 autocomplete 无选项：{no}"
    opt.first.wait_for(state="visible", timeout=5000)
    opt.first.click()
    page.wait_for_timeout(700)


def clear_filter(page, title):
    btn = page.locator(f'button[title="{title}"]')
    if btn.count() and btn.is_visible():
        btn.first.click()
        page.wait_for_timeout(700)


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
            step("§0 造数（C001/C002/M1/M2 + 3 条达成率）")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"attainment 造数失败：{seed}"

            # ===================== §1 本页渲染（防粘滞）=====================
            step("§1 路由渲染防粘滞（#/attainment）")
            page.evaluate("location.hash = '#/attainment'")
            page.wait_for_selector('input[placeholder*="客户编码"]', timeout=10000)
            page.wait_for_timeout(700)

            assert page.locator("main").inner_text().strip(), "attainment 页面无内容"
            assert page.locator("main .card").count() > 0, "attainment 未渲染 card"
            assert page.locator(".kpi").count() == 0, "attainment 挂载未重建（残留看板）"
            assert page.locator('button:visible:has-text("新建")').count() == 0, \
                "只读页工具栏不应有「新建」按钮（BR-05）"

            header_row = page.locator("table.tbl tr").first
            assert "操作" not in header_row.inner_text(), "只读列表不应有行内操作列"
            assert page.locator("table.tbl th").count() == 4, \
                f"只读列表应为 4 列（客户/物料/mape/bias），实际 {page.locator('table.tbl th').count()}"

            # ===================== §2 造数后列表有数据 =====================
            step("§2 列表含所造数据（3 行，C001×M1 渲染 12% / +8%）")
            page.wait_for_selector("table.tbl tr.data", timeout=10000)
            page.wait_for_timeout(500)

            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 3, f"列表应 3 行，实际 {rows.count()}"

            attn1_rows = rows.filter(has_text="C001").filter(has_text="M1")
            assert attn1_rows.count() == 1, "未见 C001×M1 行（ATTN1）"
            txt1 = attn1_rows.first.inner_text()
            assert "12%" in txt1, f"C001×M1 行 mape 应为 12%，实际 {txt1!r}"
            assert "+8%" in txt1, f"C001×M1 行 bias 应为 +8%，实际 {txt1!r}"

            step("§2 客户过滤 C001（收敛 2 行，无 C002）")
            pick_customer(page, "C001")
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 2, f"客户 C001 过滤应 2 行，实际 {rows.count()}"
            assert rows.filter(has_text="C002").count() == 0, "客户过滤结果不应含 C002"

            step("§2 物料过滤 M1（收敛 2 行，无 M2）")
            clear_filter(page, "清除客户筛选")
            pick_material(page, "M1")
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 2, f"物料 M1 过滤应 2 行，实际 {rows.count()}"
            assert rows.filter(has_text="M2").count() == 0, "物料过滤结果不应含 M2"

            step("§2 组合过滤 C001×M1（AND 收敛 1 行）")
            pick_customer(page, "C001")
            rows = page.locator("table.tbl tr.data")
            assert rows.count() == 1, f"C001×M1 组合应 1 行，实际 {rows.count()}"
            comb_txt = rows.first.inner_text()
            assert "C001" in comb_txt and "M1" in comb_txt, "组合过滤结果非 C001×M1"

            step("§2 组合过滤 C002×M2（空态文案，无 toast 错误）")
            clear_filter(page, "清除客户筛选")
            clear_filter(page, "清除物料筛选")
            pick_customer(page, "C002")
            pick_material(page, "M2")
            empty = page.locator("table.tbl td.empty")
            assert empty.count() == 1, "C002×M2 组合应显示空态"
            assert "无符合条件的达成率数据" in empty.first.inner_text(), "空态文案不符"

            step("§2 主数据名称回显（C001×M1 附 客户A / 物料A）")
            clear_filter(page, "清除客户筛选")
            clear_filter(page, "清除物料筛选")
            page.wait_for_selector("table.tbl tr.data", timeout=10000)
            page.wait_for_timeout(500)

            name_row = page.locator("table.tbl tr.data").filter(has_text="C001").filter(has_text="M1").first
            name_txt = name_row.inner_text()
            assert "客户A" in name_txt, f"C001×M1 行未回显客户名称 客户A：{name_txt!r}"
            assert "物料A" in name_txt, f"C001×M1 行未回显物料名称 物料A：{name_txt!r}"

            # ===================== §3 模态全字段 =====================
            step("§3 详情模态全字段（C001×M1）")
            page.locator("table.tbl tr.data").filter(has_text="C001").filter(has_text="M1") \
                .first.locator(".b-link").first.click()
            modal = wait_modal(page)
            txt = modal.locator(".modal-bd").first.inner_text()
            for label in ["客户编码", "物料号", "客户名称", "物料名称",
                          "平均绝对百分比误差", "预测偏差", "原始数据"]:
                assert label in txt, f"详情模态缺字段标签：{label}"
            for val in ["C001", "M1", "客户A", "物料A", "12%", "+8%"]:
                assert val in txt, f"详情模态缺字段值：{val}"

            # 原始数据折叠区可展开
            raw = modal.locator("details.raw")
            assert raw.count() == 1, "详情模态缺「原始数据」折叠区"
            raw.locator("summary").first.click()
            page.wait_for_timeout(250)
            pre = modal.locator("pre.json")
            assert pre.count() >= 1, "原始数据展开后应有 JSON pre"
            assert '"customer_no"' in pre.first.inner_text(), "原始数据 JSON 未含 customer_no"

            # 页脚仅「关闭」，无写操作按钮（只读，BR-05）
            ft = modal.locator(".modal-ft")
            assert ft.locator('button:visible:has-text("关闭")').count() == 1, "页脚应有且仅有关闭按钮"
            for forbidden in ["新建", "编辑", "删除", "保存", "提交"]:
                assert ft.locator(f'button:visible:has-text("{forbidden}")').count() == 0, \
                    f"只读页脚不应有 {forbidden} 按钮"
            close_modal(page, modal)

            step("§3 少报负值渲染（C001×M2，bias=-3%）")
            page.locator("table.tbl tr.data").filter(has_text="C001").filter(has_text="M2") \
                .first.locator(".b-link").first.click()
            modal = wait_modal(page)
            txt2 = modal.locator(".modal-bd").first.inner_text()
            assert "5%" in txt2, f"C001×M2 模态 mape 应 5%，实际 {txt2!r}"
            assert "-3%" in txt2, f"C001×M2 模态 bias 应 -3%（少报为负），实际 {txt2!r}"
            close_modal(page, modal)

            # ===================== §4 表单落库回显 —— 豁免 =====================
            # 数据来源类型「自动参考创建」：MAPE/bias 由 ERP 统计回写 upsert，契约无
            # create/update/delete 写服务，前端不提供 upsert 入口 → 本页只读，无表单用例。
            # 只读正面断言已并入 §1（无新建/无操作列）与 §3（页脚仅关闭）。

            # ===================== §6 0 报错红线 =====================
            step("§6 会话 0 报错")
            assert not errors, f"attainment 会话前端报错：{errors[:5]}"
            print("VERIFY_VIEW_psc_attainment: PASS")

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
        print(f"VERIFY_VIEW_psc_attainment: FAIL @ {STEP}: {e}")
        sys.exit(1)
