"""e2e 前端验收 - psc:md_customer（客户主数据）
断言：路由渲染防粘滞（.kpi==0）→ 造数后列表有数据 → 详情模态全字段 →
表单落库回显（创建/必填校验/编辑锁定/批量导入）→ 全程 0 console error / 0 pageerror / 0 HTTP≥400。
运行：python app/psc/tests/verify_view_psc_md_customer.py
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

# admin 账号（登录用）：隔离后空库播种，并预标记「已改密」跳过首次强制改密
# （否则 password_changed=0 会挡登录与 /api 调用，见 fde_platform/auth.py gate ②.5）。
from fde_platform import users  # noqa: E402
users.init_schema()
users.seed_admin()
try:
    _auth_db = ROOT / "config" / "auth.db"
    if _auth_db.exists():
        _conn = sqlite3.connect(str(_auth_db))
        _conn.execute("UPDATE users SET password_changed = 1 WHERE username = 'admin'")
        _conn.commit()
        _conn.close()
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
    if (data && (data.ok === false || data.error)) {
      throw new Error(`${app}.${svc} biz ${JSON.stringify(data).slice(0, 160)}`);
    }
    return data;
  };

  // §0 字典：C001（列表/模态/编辑锚点）+ C1001（过滤抽样命中）
  await call("md_customer", "create", {
    customer_no: "C001", customer_name: "客户A", settle_mode: "现售",
    credit_code: "91110000710931000M",
    line_stock_days: 3, transfer_lead_days: 2
  });
  await call("md_customer", "create", {
    customer_no: "C1001", customer_name: "汽车零部件公司", settle_mode: "寄售",
    line_stock_days: 5, transfer_lead_days: 1
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
    # 页面可能同时挂多个 .modal（详情 + 表单 + 导入），.last 会取到隐藏的那个；
    # 改为等「可见」的模态，再取可见者中的 last。
    page.locator(".modal:visible, [role='dialog']:visible").first.wait_for(state="visible", timeout=10000)
    return page.locator(".modal:visible, [role='dialog']:visible").last


def wait_modal(page, timeout=10000):
    """轮询 .modal-mask:visible .loadbox 消失（pitfalls #16）。"""
    end = time.time() + timeout
    while time.time() < end:
        if page.locator(".modal-mask:visible .loadbox").count() == 0:
            return True
        page.wait_for_timeout(200)
    raise AssertionError("模态载入超时：.loadbox 未消失")


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


def main():
    global STEP
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

            # ===================== §0 造数（真实 REST，带会话 Cookie）=====================
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"造数失败：{seed}"

            # ===================== §1 本页渲染（防粘滞）=====================
            STEP = "§1 路由渲染"
            page.evaluate("location.hash = '#/md_customer'")
            page.wait_for_selector("main table.tbl", timeout=10000)
            page.wait_for_timeout(700)

            main_txt = page.locator("main").inner_text()
            assert main_txt.strip(), "md_customer 页面无内容"
            assert page.locator("main .card").count() > 0, "md_customer 未渲染 card"
            assert page.locator(".kpi").count() == 0, "md_customer 挂载未重建（残留看板）"
            # 列表三段式：过滤条 / 表头 / 分页条
            assert "客户列表" in main_txt, "过滤条缺「客户列表」"
            th = page.locator("main table.tbl").first.inner_text()
            for col in ["客户编码", "客户名称", "统一社会信用代码", "结算模式", "线边库存天数", "调拨提前期"]:
                assert col in th, f"表头缺列：{col}"
            assert "共" in main_txt and "条" in main_txt, "分页条缺「共 … 条」"
            # 表头「?」字段释义：悬停线边库存天数问号 → 提示条出现且含释义关键词
            qmark = page.locator("main table.tbl th span:has-text('?')").first
            qmark.hover()
            page.wait_for_timeout(300)
            assert "最低库存 A" in page.locator("main").inner_text(), "线边库存天数「?」悬停应显示释义"
            page.mouse.move(0, 0)
            page.wait_for_timeout(300)

            # ===================== §2 列表有数据 + 搜索抽样 =====================
            STEP = "§2 列表有数据"
            page.wait_for_selector('table tbody tr:has-text("C001")', timeout=10000)
            page.wait_for_timeout(400)

            c001_row = page.locator('table tbody tr:has-text("C001")').first
            row_txt = c001_row.inner_text()
            for v in ["C001", "客户A", "91110000710931000M", "现售", "3", "2"]:
                assert v in row_txt, f"C001 行缺值：{v}（实际 {row_txt!r}）"
            assert "共 2 条" in page.locator("main").inner_text(), "造数后应「共 2 条」"

            # VT-LIST-02：customer_no 模糊 C10 → 收敛为 C1001，不含 C001
            STEP = "§2 搜索 customer_no=C10"
            page.locator('input[placeholder="客户编码"]').first.fill("C10")
            page.locator('input[placeholder="客户编码"]').first.press("Enter")
            page.wait_for_selector('table tbody tr:has-text("C1001")', timeout=10000)
            page.wait_for_timeout(400)
            assert page.locator('table tbody tr:has-text("C1001")').count() == 1, "搜索 C10 应恰好 1 条 C1001"
            assert page.locator('table tbody tr:has-text("C001")').count() == 0, "搜索 C10 不应含 C001"
            assert "共 1 条" in page.locator("main").inner_text(), "搜索 C10 后应「共 1 条」"

            # VT-LIST-02b：credit_code 模糊（小写输入 → 后端大写化匹配）→ 命中 C001 不含 C1001
            STEP = "§2 搜索 credit_code=710931000m"
            page.locator('input[placeholder="客户编码"]').first.fill("")
            page.locator('input[placeholder="统一社会信用代码"]').first.fill("710931000m")
            page.locator('input[placeholder="统一社会信用代码"]').first.press("Enter")
            page.wait_for_selector('table tbody tr:has-text("C001")', timeout=10000)
            page.wait_for_timeout(400)
            assert page.locator('table tbody tr:has-text("C001")').count() == 1, "搜索信用代码应命中 C001"
            assert page.locator('table tbody tr:has-text("C1001")').count() == 0, "搜索信用代码不应含 C1001"
            assert "共 1 条" in page.locator("main").inner_text(), "搜索信用代码后应「共 1 条」"

            # VT-LIST-03：customer_name 模糊 汽车 → 含 C1001 不含 C001；不存在 → 空态
            STEP = "§2 搜索 customer_name=汽车"
            page.locator('input[placeholder="客户编码"]').first.fill("")
            page.locator('input[placeholder="统一社会信用代码"]').first.fill("")
            page.locator('input[placeholder="客户名称"]').first.fill("汽车")
            page.locator('input[placeholder="客户名称"]').first.press("Enter")
            page.wait_for_timeout(600)
            assert page.locator('table tbody tr:has-text("C1001")').count() == 1, "搜索 汽车 应含 C1001"
            assert page.locator('table tbody tr:has-text("C001")').count() == 0, "搜索 汽车 不应含 C001"

            STEP = "§2 空态"
            page.locator('input[placeholder="客户名称"]').first.fill("不存在XYZ")
            page.locator('input[placeholder="客户名称"]').first.press("Enter")
            page.wait_for_timeout(600)
            empty = page.locator("table td.empty")
            assert empty.count() == 1, "空态行未渲染"
            assert "无符合条件的客户" in empty.first.inner_text(), "空态文案不符"

            # 重置过滤回全量
            page.locator('input[placeholder="客户编码"]').first.fill("")
            page.locator('input[placeholder="客户名称"]').first.fill("")
            page.locator('input[placeholder="统一社会信用代码"]').first.fill("")
            page.locator('input[placeholder="客户名称"]').first.press("Enter")
            page.wait_for_selector('table tbody tr:has-text("C001")', timeout=10000)
            page.wait_for_timeout(400)

            # VT-LIST-05 平台列排序（自动装饰 data-sort，点击重取：升→降→默认序）
            # 点击表头文字区（偏移定位）：「?」释义徽标自带点击行为，平台装饰对其让路（设计如此）
            STEP = "§2 列排序"
            page.wait_for_selector('main table.tbl th[data-sort="line_stock_days"]', timeout=10000)
            ths = page.locator('main table.tbl th[data-sort="line_stock_days"]')
            ths.first.click(position={"x": 24, "y": 14})        # 升序：C001(3) 在 C1001(5) 前
            page.wait_for_timeout(700)
            first_row = page.locator("table tbody tr.data").first.inner_text()
            assert "C001" in first_row, f"线边天数升序首行应为 C001（3<5），实际 {first_row!r}"
            assert "共 2 条" in page.locator("main").inner_text(), "排序后 total 应保持「共 2 条」"
            ths.first.click(position={"x": 24, "y": 14})        # 降序：C1001(5) 在前
            page.wait_for_timeout(700)
            first_row = page.locator("table tbody tr.data").first.inner_text()
            assert "C1001" in first_row, f"线边天数降序首行应为 C1001（5>3），实际 {first_row!r}"
            ths.first.click(position={"x": 24, "y": 14})        # 第三击恢复默认序（customer_no 升序）
            page.wait_for_timeout(700)
            first_row = page.locator("table tbody tr.data").first.inner_text()
            assert "C001" in first_row, f"默认序应为 customer_no 升序（C001 首行），实际 {first_row!r}"

            # ===================== §3 详情模态全字段 =====================
            STEP = "§3 详情模态"
            page.locator('table tbody tr:has-text("C001") .b-link').first.click()
            modal = open_modal(page)
            wait_modal(page)
            # 详情内容（.kv）仅在 !loading && d 时渲染，等它出现确保载入完成
            modal.locator(".modal-bd .kv").first.wait_for(state="visible", timeout=10000)

            bd_txt = modal.locator(".modal-bd").first.inner_text()
            for label in ["客户编码", "客户名称", "统一社会信用代码", "结算模式", "线边库存天数", "调拨提前期"]:
                assert label in bd_txt, f"详情模态缺字段标签：{label}"
            for v in ["C001", "客户A", "91110000710931000M", "现售", "3", "2"]:
                assert v in bd_txt, f"详情模态缺字段值：{v}"

            docno = modal.locator(".docno").first.inner_text()
            assert "客户详情 · C001" in docno, f"详情头带缺 docno：{docno!r}"
            assert modal.locator("details.raw").count() == 1, "详情缺「原始数据」折叠块"
            assert modal.locator("details.raw[open]").count() == 0, "「原始数据」应默认收起"

            ft_txt = modal.locator(".modal-ft").first.inner_text()
            assert "编辑" in ft_txt and "关闭" in ft_txt, f"详情页脚缺【编辑】【关闭】：{ft_txt!r}"
            close_modal(page, modal)

            # ===================== §4 表单落库回显 =====================
            # VT-FORM-01 创建
            STEP = "§4 创建表单"
            click_button(page, ["+ 新建客户", "新建客户", "创建客户", "新建"])
            modal = open_modal(page)

            fill_labeled(modal, "客户编码", "NEW01")
            fill_labeled(modal, "客户名称", "新客户")
            fill_labeled(modal, "统一社会信用代码", "91350100M000100C4G")
            modal.locator('xpath=.//label[contains(normalize-space(.), "结算模式")]/following::select[1]') \
                .select_option("寄售")
            fill_labeled(modal, "线边库存天数", "2")
            fill_labeled(modal, "调拨提前期", "4")

            click_button(modal, ["创建", "保存", "提交"])
            page.wait_for_selector('.toast:has-text("客户主数据创建成功")', timeout=5000)
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(500)

            page.wait_for_selector('table tbody tr:has-text("NEW01")', timeout=10000)
            page.wait_for_timeout(400)

            # 重开 NEW01 详情五字段回显
            page.locator('table tbody tr:has-text("NEW01") .b-link').first.click()
            modal = open_modal(page)
            wait_modal(page)
            modal.locator(".modal-bd .kv").first.wait_for(state="visible", timeout=10000)
            bd_txt = modal.locator(".modal-bd").first.inner_text()
            for v in ["NEW01", "新客户", "91350100M000100C4G", "寄售", "2", "4"]:
                assert v in bd_txt, f"NEW01 详情回显缺：{v}"
            close_modal(page, modal)

            # VT-FORM-02 创建必填校验（前端拦，不发请求）
            STEP = "§4 必填校验"
            click_button(page, ["+ 新建客户", "新建客户", "创建客户", "新建"])
            modal = open_modal(page)

            create_reqs = []
            def on_request(req):
                if req.method == "POST" and "/call/create" in req.url and "md_customer" in req.url:
                    create_reqs.append(req.url)
            page.on("request", on_request)

            click_button(modal, ["创建", "保存", "提交"])
            page.wait_for_timeout(400)
            page.remove_listener("request", on_request)

            assert not create_reqs, f"必填校验不应发出 create 请求：{create_reqs}"
            page.wait_for_selector('.toast:has-text("客户编码与客户名称必填")', timeout=5000)
            assert modal.is_visible(), "必填校验后模态应保持打开"
            close_modal(page, modal)

            # VT-FORM-03 编辑态（customer_no 锁定 + 变更回显）
            STEP = "§4 编辑表单"
            page.locator('table tbody tr:has-text("C001") button:has-text("编辑")').first.click()
            modal = open_modal(page)

            no_input = modal.locator('input[placeholder="如 C1001"]').first
            assert no_input.count() > 0, "编辑态未找到 customer_no 输入框"
            assert no_input.is_disabled(), "编辑态 customer_no 应锁定（disabled）"
            assert "编辑客户 · C001" in modal.locator(".docno").first.inner_text(), "编辑态标题不符"

            fill_labeled(modal, "线边库存天数", "7")
            click_button(modal, ["保存修改", "保存", "提交"])
            page.wait_for_selector('.toast:has-text("客户主数据更新成功")', timeout=5000)
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(500)

            page.wait_for_selector('table tbody tr:has-text("C001")', timeout=10000)
            page.wait_for_timeout(400)
            c001_row_txt = page.locator('table tbody tr:has-text("C001")').first.inner_text()
            assert "7" in c001_row_txt, "C001 行 line_stock_days 未更新为 7"

            # 重开 C001 详情回显 7
            page.locator('table tbody tr:has-text("C001") .b-link').first.click()
            modal = open_modal(page)
            wait_modal(page)
            modal.locator(".modal-bd .kv").first.wait_for(state="visible", timeout=10000)
            assert "7" in modal.locator(".modal-bd").first.inner_text(), "C001 详情未回显 7"
            close_modal(page, modal)

            # VT-FORM-04 批量导入（import_batch upsert）
            STEP = "§4 批量导入"
            click_button(page, ["批量导入", "导入"])
            modal = open_modal(page)
            modal.locator("textarea").first.fill("IMP01,导入客户,91350100M000100C4G,现售,1,2")
            click_button(modal, ["批量导入"])

            page.wait_for_selector('.toast:has-text("导入完成")', timeout=5000)
            page.wait_for_timeout(500)
            imp_txt = modal.locator(".modal-bd").first.inner_text()
            assert "成功 1 条" in imp_txt, "导入摘要缺「成功 1 条」"
            assert "失败 0 条" in imp_txt, "导入摘要缺「失败 0 条」"
            assert "共 1 条" in imp_txt, "导入摘要缺「共 1 条」"
            close_modal(page, modal)

            page.wait_for_selector('table tbody tr:has-text("IMP01")', timeout=10000)
            page.wait_for_timeout(400)

            # ===================== §6 0 报错 =====================
            STEP = "§6 0 报错"
            assert not errors, f"md_customer 会话前端报错：{errors[:5]}"
            print("VERIFY_VIEW_psc_md_customer: PASS")

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
