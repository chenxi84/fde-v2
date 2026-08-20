"""e2e 前端验收 - psc:inventory_strategy（库存策略）
断言：路由渲染防粘滞 → 造数后列表有数据 → 详情模态全字段 → 计算入口落库回显
（单物料 / 批量 / 行内重算 / 必填校验 / 非法物料，自动参考创建豁免表单）
→ 全程 0 console error / 0 pageerror / 0 HTTP≥400。
运行：python app/psc/tests/verify_view_psc_inventory_strategy.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit, re


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
# 与 verify_view_psc 其余逐应用脚本一致，先在隔离后的 config/auth.db 置 1 放行。
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


# §0 自足造数：V202608 月度版本 + M1/M2 物料（预计算主数据）+ 预计算 M1。
# M2 只造主数据、不 calc —— 供 §4「计算入口」UI 触发计算（自动参考创建豁免表单）。
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

  await call("psc/md_monthly_version", "create", {
    version_no: "202608", anchor_period: "2026-08", opening_date: "2026-08-01"
  });
  await call("psc/md_material", "create", {
    material_no: "M1", material_name: "物料A",
    prod_days: 10, logistics_days: 5, service_level: 0.95, batch_window: 28
  });
  await call("psc/md_material", "create", {
    material_no: "M2", material_name: "物料B",
    prod_days: 10, logistics_days: 5, service_level: 0.95, batch_window: 28
  });
  await call("psc/inventory_strategy", "calc", {version_no: "202608", material_no: "M1"});

  return {seeded: true};
}"""


STEP = "init"


def step(name):
    global STEP
    STEP = name
    print(f"[step] {name}")


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


def read_total(page):
    """读分页条「共 N 条」的总数（用于断言重算/校验不新增行）。"""
    t = page.locator('span.muted:has-text("共")').first.inner_text()
    m = re.search(r"(\d+)", t)
    return int(m.group(1)) if m else -1


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
            step("§0 造数（V202608 + M1/M2 + 预计算 M1）")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"inventory_strategy 造数失败：{seed}"

            # ===================== §1 本页渲染（防粘滞）=====================
            step("§1 路由渲染防粘滞")
            page.evaluate("location.hash = '#/inventory_strategy'")
            try:
                page.wait_for_selector("main .card", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator("main").inner_text().strip(), "inventory_strategy 页面无内容"
            assert page.locator("main .card").count() > 0, "inventory_strategy 未渲染 card"
            assert page.locator(".kpi:visible").count() == 0, "inventory_strategy 挂载未重建（残留看板）"
            title = page.locator("header.top h1").first.inner_text()
            assert "库存策略" in title, f"页面标题应为「库存策略」：{title[:120]}"

            # ===================== §2 造数后列表有数据 =====================
            step("§2 VT-LIST-01 列表含预计算策略行（M1 / 202608 / 库存 / 28 天）")
            rows = page.locator("table.tbl tr.data")
            assert rows.count() >= 1, f"库存策略列表无数据：{rows.count()}"
            m1_row = rows.filter(has_text="M1")
            assert m1_row.count() == 1, "列表未见 M1 策略行"
            row_txt = m1_row.first.inner_text()
            assert "202608" in row_txt, "M1 行缺版本 202608"
            assert "库存" in row_txt, "M1 行对冲工具徽章应为 库存"
            assert "28 天" in row_txt, "M1 行组批窗口应渲染 28 天"

            ledger = page.locator('.card:has-text("库存策略台账")')

            step("§2 VT-LIST-02 版本筛选生效（202608）")
            ledger.locator("select").first.select_option(value="202608")
            page.wait_for_timeout(500)
            assert page.locator('table.tbl tr.data:has-text("M1")').count() == 1, "版本筛选 202608 后仍应含 M1"

            step("§2 VT-LIST-03 对冲工具 chips 筛选生效 + 空态")
            ledger.locator('.fchip:has-text("库存")').first.click()
            page.wait_for_timeout(500)
            assert page.locator('table.tbl tr.data:has-text("M1")').count() == 1, "chips 库存 on 时应含 M1"
            ledger.locator('.fchip:has-text("速度")').first.click()
            page.wait_for_timeout(500)
            assert page.locator("table.tbl tr.data").count() == 0, "chips 速度 on 时列表应为空"
            empty = page.locator("table.tbl tr td.empty")
            assert empty.count() > 0 and "无匹配数据" in empty.first.inner_text(), "chips 速度 空态文案应为 无匹配数据"

            step("§2 VT-LIST-04 物料 autocomplete 筛选生效（重置 → 选 M1）")
            ledger.locator('button:has-text("重置")').first.click()
            page.wait_for_timeout(400)
            ledger.locator('input[placeholder*="物料"]').first.click()
            page.wait_for_timeout(300)
            ledger.locator('div[style*="position:relative"] .mono:has-text("M1")').first.click()
            page.wait_for_timeout(500)
            assert page.locator('table.tbl tr.data:has-text("M1")').count() == 1, "物料筛选 M1 后应仅含 M1"
            assert page.locator('table.tbl tr.data:has-text("M2")').count() == 0, "物料筛选 M1 后不应出现 M2"

            # 还原过滤态，供 §3 详情模态定位 M1
            ledger.locator('button:has-text("重置")').first.click()
            page.wait_for_timeout(400)

            # ===================== §3 模态全字段 =====================
            step("§3 VT-MODAL-01 详情模态全字段（M1 / 202608）")
            page.locator('table.tbl tr.data .b-link:has-text("M1")').first.click()
            modal = wait_modal(page)
            txt = modal.inner_text()

            for label in ["月度版本", "物料号", "对冲工具", "最低水位 A", "安全水位 C", "组批水位 B",
                          "下限 A+C", "上限 A+C+B", "服务系数", "响应窗口波动 σ_L", "组批窗口",
                          "设定依据", "原始数据"]:
                assert label in txt, f"详情模态缺字段标签：{label}"
            for val in ["202608", "M1", "库存", "1.65", "28 天"]:
                assert val in txt, f"详情模态缺字段值：{val}"
            assert "无历史数据" in txt, "详情模态 basis 未注明无历史数据"
            assert "派生值 · 不单独存储" in txt, "详情模态缺派生值注明"

            raw = modal.locator("details.raw summary")
            assert raw.count() == 1 and "原始数据" in raw.first.inner_text(), "详情模态缺「原始数据」折叠区"

            ft = modal.locator(".modal-ft")
            assert ft.locator('button:visible:has-text("重算")').count() == 1, "详情模态页脚缺【重算】按钮"
            close_modal(page, modal)

            # ===================== §4 计算入口落库回显（表单豁免 · 自动参考创建）=====================
            calc = page.locator('.card:has-text("计算入口")')

            step("§4 VT-CALC-01 单物料计算落库回显（M2）")
            calc.locator("select").first.select_option(value="202608")
            calc.locator('input[placeholder*="物料"]').first.click()
            page.wait_for_timeout(300)
            calc.locator('div[style*="position:relative"] .mono:has-text("M2")').first.click()
            page.wait_for_timeout(300)
            calc.locator('button.b-pri:has-text("计算")').first.click()
            expect_toast(page, "已计算 · M2")
            page.wait_for_timeout(700)
            assert page.locator('table.tbl tr.data:has-text("M2")').count() == 1, "计算后列表应含 M2 策略行"
            m2_row = page.locator('table.tbl tr.data:has-text("M2")').first
            assert "库存" in m2_row.inner_text(), "M2 行对冲工具应为 库存"

            step("§4 VT-CALC-02 批量计算（整版本 202608）")
            calc.locator('input[placeholder*="物料"]').first.fill("")
            calc.locator('button.b-ghost:has-text("批量计算")').first.click()
            expect_toast(page, "批量计算完成：成功 2 / 失败 0")
            page.wait_for_timeout(700)
            assert page.locator('table.tbl tr.data:has-text("M1")').count() == 1, "批量计算后应含 M1"
            assert page.locator('table.tbl tr.data:has-text("M2")').count() == 1, "批量计算后应含 M2"

            step("§4 VT-CALC-03 行内重算覆盖（M1，不新增行）")
            total_before = read_total(page)
            m1_row = page.locator('table.tbl tr.data:has-text("M1")').first
            m1_row.locator('button:has-text("重算")').first.click()
            expect_toast(page, "已重算 · M1")
            page.wait_for_timeout(700)
            total_after = read_total(page)
            assert total_after == total_before, f"重算覆盖更新不应新增行（{total_before} → {total_after}）"
            assert page.locator('table.tbl tr.data:has-text("M1")').count() == 1, "重算后 M1 行仍应存在"

            step("§4 VT-CALC-04 必填校验（空版本 → 警告 toast 不发请求）")
            total_before = read_total(page)
            calc.locator("select").first.select_option(value="")
            calc.locator('input[placeholder*="物料"]').first.fill("M1")
            calc.locator('button.b-pri:has-text("计算")').first.click()
            expect_toast(page, "请选择月度版本")
            page.wait_for_timeout(300)
            assert read_total(page) == total_before, "空版本校验不应新增行"

            step("§4 VT-CALC-05 必填校验（空物料 → 警告 toast 不发请求）")
            total_before = read_total(page)
            calc.locator("select").first.select_option(value="202608")
            calc.locator('input[placeholder*="物料"]').first.fill("")
            calc.locator('button.b-pri:has-text("计算")').first.click()
            expect_toast(page, "请选择物料")
            page.wait_for_timeout(300)
            assert read_total(page) == total_before, "空物料校验不应新增行"

            step("§4 VT-CALC-06 非法物料计算 → 后端 FdeError toast（HTTP 200 非 ≥400）")
            total_before = read_total(page)
            calc.locator('input[placeholder*="物料"]').first.fill("NONEXIST")
            calc.locator('button.b-pri:has-text("计算")').first.click()
            expect_toast(page, "物料记录不存在")
            page.wait_for_timeout(300)
            assert read_total(page) == total_before, "非法物料计算不应新增行"

            # ===================== §6 0 报错红线 =====================
            step("§6 会话 0 报错")
            assert not errors, f"inventory_strategy 会话前端报错：{errors[:5]}"
            print("VERIFY_VIEW_psc_inventory_strategy: PASS")

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
        print(f"VERIFY_VIEW_psc_inventory_strategy: FAIL @ {STEP}: {e}")
        sys.exit(1)
