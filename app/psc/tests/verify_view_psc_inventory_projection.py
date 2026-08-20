"""e2e 前端验收 · psc:inventory_projection（库存推移表，playwright，可直接运行）。
断言：本页路由渲染（非看板页 .kpi==0 防粘滞）→ 预警六态 chips → 造数后列表有推移表行
→ 详情模态全字段 + 原始数据折叠 → 豁免表单（无新建/编辑/删除）+ 两个计算触发按钮（refresh/
refresh_batch，扫描预警已移除前端入口、由批量刷新内部联动）弹窗字段 + 批量刷新摘要 + 刷新提交落库回显
→ 全程 0 console error / 0 pageerror / 0 HTTP>=400。
运行：python app/psc/tests/verify_view_psc_inventory_projection.py
"""
import sqlite3
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

# admin 账户：必须在平台子进程启动前经 users 模块建好（隔离库为空）。
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

STEP = ""

# BR-11 历史隐藏：未选日期时列表只显示 biz_date>=今日 的行。
# 造数起点 2026-08-15 推演 90 日，默认视图条数 = 窗口内 >= 今日 的天数（随运行日变化）。
from datetime import date, timedelta  # noqa: E402
_SEED_START = date(2026, 8, 15)
EXPECTED_VISIBLE = sum(
    1 for i in range(90) if _SEED_START + timedelta(days=i) >= date.today()
)


def step(name):
    global STEP
    STEP = name
    print(f"── {name} ──")


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


# 造数链（§0 自足字典）：md_material.create(M1) → inventory_projection.refresh(M1, "2026-08-15", opening_stock=0)
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
    if (data && (data.ok === false || data.error || data.status === "error")) {
      throw new Error(`${app}.${svc} biz ${JSON.stringify(data).slice(0, 160)}`);
    }
    return data;
  };
  const unwrap = (x) => {
    if (!x) return x;
    if (x.data !== undefined) return x.data;
    if (x.result !== undefined) return x.result;
    return x;
  };

  await call("md_material", "create", {
    material_no: "M1",
    material_name: "测试物料A",
    status: "正常"
  });
  const ip = unwrap(await call("inventory_projection", "refresh", {
    material_no: "M1",
    biz_date: "2026-08-15",
    opening_stock: 0
  }));

  return { seeded: true, generated: (ip && ip.generated) || null, material_no: "M1" };
}"""


def click_button(scope, text):
    loc = scope.locator(f'button:visible:has-text("{text}")')
    assert loc.count() > 0, f"未找到按钮：{text}"
    loc.first.click()


def wait_modal(page, timeout=10000):
    """等可见模态出现，并等详情模态 loading 的 .loadbox 消失再返回（pitfalls #16）。"""
    page.locator(".modal-mask:visible").first.wait_for(state="visible", timeout=timeout)
    end = time.time() + 8
    while time.time() < end:
        if page.locator(".modal-mask:visible .loadbox:visible").count() == 0:
            break
        page.wait_for_timeout(120)
    return page.locator(".modal-mask:visible").last


def close_modal(page, modal):
    for sel in ['button:has-text("关闭")', 'button:has-text("取消")', "button.x"]:
        btn = modal.locator(sel)
        if btn.count():
            btn.first.click()
            break
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
        page.on("console", lambda m: errors.append(m.text[:140]) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)[:140]))

        def on_response(resp):
            if resp.status >= 400:
                url = resp.url
                if "/favicon.ico" in url or url.endswith(".map"):
                    ignored.append(f"HTTP {resp.status} {url}")
                    return
                errors.append(f"HTTP {resp.status} {url}")

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

            # ── §1 本页路由渲染（防粘滞） ──
            step("§1 路由渲染")
            page.evaluate("location.hash = '#/inventory_projection'")
            page.wait_for_selector("main .card", timeout=15000)
            page.wait_for_timeout(700)

            assert page.locator("main .card").count() > 0, "库存推移表未渲染卡片"
            assert page.locator("main").inner_text().strip(), "库存推移表无内容"
            assert page.locator(".kpi").count() == 0, "非看板页残留看板 .kpi（挂载未重建）"

            # 视图切换 chips（列表 / 日历）—— 等数据行渲染后再断言，避免 x-for 动态渲染早抢跑
            page.wait_for_selector(".fchip", timeout=15000)
            # 默认日历视图
            assert page.locator(".cal-tbl:visible").count() > 0, "默认应为日历视图（.cal-tbl 可见）"

            # ── 造数（真实 REST，带会话 Cookie）──
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"造数失败：{seed}"
            assert seed.get("generated") == 90, f"refresh 应推演 90 日，实际 {seed.get('generated')}"

            # 重扫注册表 mtime（pitfalls #6）
            page.reload()
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.evaluate("location.hash = '#/inventory_projection'")
            page.wait_for_selector(".fchip", timeout=15000)
            # 默认日历 → 先切列表视图做台账断言
            page.locator('.fchip', has_text="列表").first.click()
            page.wait_for_timeout(400)
            page.locator("table tr.data", has_text="M1").first.wait_for(state="visible", timeout=15000)
            page.wait_for_timeout(600)

            # ── §2 造数后列表有数据 ──
            step("§2 列表推移表行")
            # 默认隐藏历史快照（biz_date<今日）；回看 2026-08-15 需先选具体日期
            page.locator('input[placeholder="YYYY-MM-DD"]').first.fill("2026-08-15")
            page.locator('button:has-text("查询")').first.click()
            page.wait_for_timeout(600)
            row = page.locator("table tr.data", has_text="M1").filter(has_text="2026-08-15").first
            assert row.count() > 0, "列表未含 M1 推移表行"
            row_txt = row.inner_text()
            assert "M1" in row_txt and "2026-08-15" in row_txt, "M1 行未回显物料号/业务日期"
            nums = [t.strip() for t in row.locator("td.num").all_inner_texts()]
            assert nums == ["0", "0", "0"], f"数值列 inbound/outbound/balance 应均 0，实际 {nums}"
            st = row.locator(".st").first
            assert st.inner_text().strip() == "无", "预警徽章文本应为「无」"
            assert "st-slate" in (st.get_attribute("class") or ""), "预警徽章应含 st-slate"

            # ── §3 详情模态全字段 ──
            step("§3 模态全字段")
            page.locator("table tr.data", has_text="M1").first.locator("button.b-link").first.click()
            modal = wait_modal(page)

            assert modal.locator(".docno").first.inner_text().strip() == "M1", "详情头带 .docno 应为 M1"
            bd = modal.locator(".modal-bd").first.inner_text()
            for label in ["物料号", "M1", "业务日期", "2026-08-15",
                          "预计入库量", "预计出库量", "库存余额", "预警类型", "无", "原始数据"]:
                assert label in bd, f"详情模态缺字段：{label}"
            st = modal.locator(".st").first
            assert st.inner_text().strip() == "无", "详情预警徽章文本应为「无」"
            assert "st-slate" in (st.get_attribute("class") or ""), "详情预警徽章应含 st-slate"
            ft = modal.locator(".modal-ft").first.inner_text()
            assert "扫描预警" not in ft and "关闭" in ft, "详情页脚应仅含【关闭】（扫描预警入口已移除）"

            # 原始数据折叠展开（get 全量 JSON）
            summary = modal.locator("details.raw summary")
            assert summary.count() > 0, "缺「原始数据」折叠 summary"
            summary.first.click()
            page.wait_for_timeout(300)
            pre = modal.locator("details.raw pre.json")
            assert pre.count() > 0, "原始数据 pre.json 未展开"
            raw = pre.first.inner_text()
            assert '"material_no": "M1"' in raw, "原始数据缺 material_no"
            assert '"biz_date": "2026-08-15"' in raw, "原始数据缺 biz_date"

            close_modal(page, modal)

            # ── §4 豁免（无表单）+ 计算触发按钮 ──
            step("§4 豁免（无表单）+ 刷新/批量刷新按钮")
            for forbidden in ["新建", "编辑", "删除"]:
                assert page.locator(f'button:visible:has-text("{forbidden}")').count() == 0, \
                    f"自动参考创建页不应出现「{forbidden}」入口"
            for btn in ["查询", "重置", "🌊 刷新", "🌊 批量刷新"]:
                assert page.locator(f'button:visible:has-text("{btn}")').count() > 0, \
                    f"工具栏缺按钮：{btn}"
            assert page.locator('button:visible:has-text("🌊 扫描预警")').count() == 0, \
                "工具栏不应再出现「🌊 扫描预警」"

            # 刷新按钮 → 弹窗字段（物料下拉可选到 M1）
            step("§4 刷新弹窗字段")
            click_button(page, "🌊 刷新")
            modal = wait_modal(page)
            assert "单物料刷新" in modal.locator(".docno").first.inner_text(), "刷新弹窗头应「单物料刷新」"
            bd = modal.locator(".modal-bd").first.inner_text()
            for label in ["物料", "推演起始日期", "期初库存"]:
                assert label in bd, f"刷新弹窗缺字段：{label}"
            mat_input = modal.locator('input[placeholder*="搜索物料号"]')
            assert mat_input.count() > 0, "刷新弹窗缺物料 autocomplete 输入"
            mat_input.click()
            page.wait_for_timeout(200)
            mat_input.fill("M1")
            page.wait_for_timeout(200)
            assert modal.locator('div:has-text("测试物料A")').count() > 0, "物料下拉未可选到 M1"
            close_modal(page, modal)

            # 批量刷新按钮 → 免输入弹窗（自动当天 + 全量物料）+ 提交回显摘要
            step("§4 批量刷新弹窗（自动口径，无输入项）")
            click_button(page, "🌊 批量刷新")
            modal = wait_modal(page)
            assert "批量刷新" in modal.locator(".docno").first.inner_text(), "批量刷新弹窗头应「批量刷新」"
            bd = modal.locator(".modal-bd").first.inner_text()
            for label in ["当天", "全量", "自动创建需求池补库单"]:
                assert label in bd, f"批量刷新弹窗缺自动口径说明：{label}"
            assert modal.locator('input[type="date"]').count() == 0, "批量刷新不应再要求推演起始日期"
            assert modal.locator("textarea").count() == 0, "批量刷新不应再要求物料号列表"

            step("§4 批量刷新提交 → 摘要（成功/失败/触发补库物料）")
            modal.locator('button:has-text("批量刷新")').last.click()
            page.wait_for_timeout(900)
            bd = modal.locator(".modal-bd").first.inner_text()
            assert "刷新结果摘要" in bd, "批量刷新后应显示结果摘要"
            for label in ["物料总数", "成功", "失败", "自动补库单", "成功物料", "失败物料", "触发补库的物料"]:
                assert label in bd, f"批量刷新摘要缺字段：{label}"
            assert "M1" in bd, "摘要成功物料应含 M1（隔离库唯一正常物料）"
            close_modal(page, modal)

            # 刷新提交落库回显（US-01-AC1：90 行）
            step("§4 刷新提交落库回显")
            click_button(page, "🌊 刷新")
            modal = wait_modal(page)
            mat_input = modal.locator('input[placeholder*="搜索物料号"]')
            mat_input.click()
            page.wait_for_timeout(200)
            mat_input.fill("M1")
            page.wait_for_timeout(200)
            modal.locator('div:has-text("测试物料A")').first.click()
            page.wait_for_timeout(200)
            modal.locator('input[type="date"]').fill("2026-08-15")
            modal.locator('input[type="number"]').fill("0")
            modal.locator('button:has-text("开始推演")').click()

            page.locator('.toast:has-text("已推演 90 日 · M1")').first.wait_for(state="visible", timeout=10000)
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)
            # 清掉 §2 遗留的日期过滤 → 默认视图：从当天开始（历史隐藏），升序
            page.locator('button:has-text("重置")').first.click()
            page.wait_for_timeout(700)
            assert f"共 {EXPECTED_VISIBLE} 条" in page.locator("main").inner_text(), \
                f"重置后应显示当日及以后共 {EXPECTED_VISIBLE} 条（历史隐藏）"
            # 默认按日期从早到晚：首行日期 = 今日
            first_cells = page.locator("table tr.data td.mono").all_inner_texts()
            dates = [t.strip() for t in first_cells if t.strip() >= "2000-"]
            assert dates and dates[0] == date.today().strftime("%Y-%m-%d"), \
                f"默认首行应为今日，实际 {dates[:3]}"

            # ── §5 日历视图（单物料月历：余额 + 入/出小字，按预警上色） ──
            step("§5 日历视图（单物料月历）")
            page.locator('.fchip', has_text="日历").first.click()
            page.wait_for_timeout(300)
            assert page.locator(".cal-tbl").count() > 0, "日历视图应显示月历表格 .cal-tbl"
            assert page.locator('table.tbl tr th', has_text="周一").count() > 0, "日历表头应含周一~周日"

            cal_input = page.locator('input[placeholder="搜索物料号 / 名称…"]').first
            cal_input.fill("M1")
            cal_input.press("Enter")
            page.wait_for_timeout(700)

            # 三层水位行（选料后自动显示；隔离库无库存策略 → 显示暂无）
            main_txt = page.locator("main").inner_text()
            assert "库存水位" in main_txt, "选料后应显示库存水位行"
            for label in ["最低", "安全", "组批上限"]:
                assert label in main_txt, f"水位行缺标签：{label}"
            assert "暂无库存策略水位" in main_txt, "无库存策略时应显示暂无提示"

            today_str = date.today().strftime("%Y-%m-%d")
            today_cell = page.locator(".cal-cell.cal-today").first
            assert today_cell.count() > 0, "当前月应含今日高亮单元格"
            txt = today_cell.inner_text()
            for label in ["预计库存量", "预计入库量", "预计出库量"]:
                assert label in txt, f"今日单元格缺中文标签：{label}，实际 {txt}"
            assert "0" in txt, f"今日单元格应显示数值 0，实际 {txt}"

            # 点今日 → 详情模态（复用 viewX）
            today_cell.locator(".cal-inner").first.click()
            modal = wait_modal(page)
            assert "M1" in modal.locator(".docno").first.inner_text(), "日历点今日应打开 M1 详情"
            close_modal(page, modal)

            # 月份导航：上月 → 回到本月
            def month_label_text():
                labels = page.locator(".mono:visible").all_inner_texts()
                ys = [t.strip() for t in labels if len(t.strip()) == 7 and t.strip()[4] == "-"]
                assert ys, f"未找到月份标签，可见 .mono：{labels}"
                return ys[0]

            m_before = month_label_text()
            page.locator('button:has-text("◀ 上月")').first.click()
            page.wait_for_timeout(300)
            assert month_label_text() != m_before, "上月导航后月份应变化"
            page.locator('button:has-text("回到本月")').first.click()
            page.wait_for_timeout(300)
            assert page.locator(".cal-cell.cal-today").count() > 0, "回到本月后应回到含今日的当月"

            # 切回列表视图
            page.locator('.fchip', has_text="列表").first.click()
            page.wait_for_timeout(300)
            assert page.locator('table.tbl tr th', has_text="物料号").count() > 0, "切回列表应恢复台账表"

            # ── §6 0 报错红线 ──
            step("§6 0 报错")
            assert not errors, f"前端报错：{errors[:5]}"
            print("VERIFY_VIEW_psc_inventory_projection: PASS")

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
