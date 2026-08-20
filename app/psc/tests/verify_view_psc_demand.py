"""e2e 前端验收 · psc/demand「毛需求与净需求」（playwright，可直接运行）。

对照 app/psc/demand/前端测试用例.md 第⑧步用例（数据来源类型 = 手工参考创建：契约无
create/update/delete，单据变更仅经版本级操作 build_gross / publish / calc_net / export_net）。
断言：§1 本页渲染（.kpi==0 防粘滞）→ §0 造数（主数据 + 业务链）→ §2 列表有数据
（gross_qty/net_qty 列）→ §3 详情模态全字段（毛需求/净需求分层拆解）→ §4 操作区
（草稿 → 发布（锁定） → 冻结 状态机 x-show）→ §6 全程 0 console error / 0 pageerror / 0 HTTP≥400。
运行：python app/psc/tests/verify_view_psc_demand.py
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

# admin 账户：隔离空库后播种，并预标记「已改密」跳过首次强制改密（否则 password_changed=0 挡登录）。
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


def step(name):
    global STEP
    STEP = name


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


# §0 造数链（照用例 §0 冻结字典；组限定名 psc/<应用> 直连 REST，pitfalls #18）：
#   md_monthly_version.create(202608) + md_material.create(M1 正常 / M2 停用)
#   + md_customer.create(C001) + attainment.upsert(bias=0.05)
#   + sales_forecast.open_version/fill_customer/decide/summarize
#   + inventory_strategy.calc + demand.build_gross → 落 3 行 demand。
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
    if (!r.ok) throw new Error(`psc/${app}.${svc} HTTP ${r.status} ${text.slice(0, 160)}`);
    if (data && data.status === "error") {
      throw new Error(`psc/${app}.${svc} biz ${(data.message || '').slice(0, 160)}`);
    }
    return (data && data.data !== undefined) ? data.data : data;
  };

  // 主数据（跨应用前置）
  await call("md_monthly_version", "create", {
    version_no: "202608", anchor_period: "2026-08", opening_date: "2026-08-01"
  });
  await call("md_material", "create", {
    material_no: "M1", material_name: "物料A", status: "正常",
    prod_days: 10, logistics_days: 5, service_level: 0.95, batch_window: 28,
    base_method: "移动平均", base_params: '{"window":6}'
  });
  await call("md_material", "create", {
    material_no: "M2", material_name: "物料B", status: "停用"
  });
  await call("md_customer", "create", {
    customer_no: "C001", customer_name: "客户A"
  });
  await call("attainment", "upsert", {
    customer_no: "C001", material_no: "M1", mape: 0.10, bias: 0.05
  });
  // 历史台账：让 M1 有采购客户 C001（open_version 按物料收窄，无历史则客户为空）。
  // qty=0 保持历史月均需求=0 → 库存策略水位=0 → 毛需求仍为 950。
  await call("sales_history", "import_batch", {
    rows: [{ material_no: "M1", customer_no: "C001", period: "2026-01", qty: 0 }]
  });

  // 业务链（sales_forecast → inventory_strategy → demand）
  await call("sales_forecast", "open_version", {version_no: "202608"});
  for (const rm of ["N+1", "N+2", "N+3"]) {
    await call("sales_forecast", "fill_customer", {
      version_no: "202608", material_no: "M1", customer_no: "C001",
      rolling_month: rm, orig_qty: 1000
    });
  }
  for (const rm of ["N+1", "N+2", "N+3"]) {
    // 基线未计算（base_event_qty=None）→ final_qty = adj_qty = 950
    await call("sales_forecast", "decide", {
      version_no: "202608", material_no: "M1", customer_no: "C001", rolling_month: rm
    });
  }
  await call("sales_forecast", "summarize", {version_no: "202608"});
  await call("inventory_strategy", "calc", {
    version_no: "202608", material_no: "M1", customer_no: "C001"
  });
  await call("demand", "build_gross", {version_no: "202608"});

  return {seeded: true};
}"""


def goto_demand(page):
    """切到 #/demand 并等本页实例重建（shell 单一挂载点，route 变化即换新 page-in）。"""
    page.evaluate("location.hash = '#/demand'")
    page.wait_for_selector('select[x-model="fVersion"]', timeout=15000)
    page.wait_for_function(
        "() => (document.querySelector('header.top h1')||{}).textContent?.includes('毛需求与净需求')",
        timeout=15000,
    )


def wait_modal(page):
    """等可见模态 + 轮询 .loadbox 消失（详情加载完成，pitfalls #16）。"""
    mask = page.locator(".modal-mask:visible").first
    mask.wait_for(state="visible", timeout=10000)
    end = time.time() + 10
    while time.time() < end:
        if page.locator(".modal-mask:visible .loadbox:visible").count() == 0:
            break
        page.wait_for_timeout(100)
    page.wait_for_timeout(150)
    return mask


def close_modal(page):
    x = page.locator(".modal-mask:visible .modal-hd button.x")
    if x.count():
        x.first.click()
    else:
        page.keyboard.press("Escape")
    try:
        page.locator(".modal-mask:visible").first.wait_for(state="hidden", timeout=3000)
    except Exception:
        page.keyboard.press("Escape")
    page.wait_for_timeout(250)


def visible_button_texts(page):
    return page.locator("button:visible").all_inner_texts()


def select_version(page, version_no):
    page.locator('select[x-model="fVersion"]').select_option(value=version_no)
    page.wait_for_timeout(300)


def choose_material(page, material_no):
    inp = page.locator('input[placeholder="物料号 / 名称…"]').first
    inp.click()
    page.wait_for_selector(".autocomplete-drop:visible", timeout=5000)
    page.locator(f'.autocomplete-drop div.mono:text-is("{material_no}")').first.click()
    page.wait_for_timeout(300)


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
            # 发布操作触发原生 confirm，须显式接受（否则默认拒绝 → 不发布）
            page.on("dialog", lambda d: d.accept())

            # ===================== §1 本页渲染（无数据 · 防粘滞） =====================
            step("§1 渲染")
            page.goto(f"{base}/view/psc/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.wait_for_timeout(400)
            goto_demand(page)
            page.wait_for_selector("main .card", timeout=10000)
            page.wait_for_timeout(500)

            assert page.locator("main .card").count() > 0, "demand 页面未渲染卡片"
            assert page.locator(".kpi").count() == 0, "demand 非看板页残留 .kpi（挂载粘滞）"

            h1 = page.locator("header.top h1").first.inner_text().strip()
            assert "毛需求与净需求" in h1, f"页头 title 不符：{h1}"
            crumb = page.locator("header.top .crumb").first.inner_text()
            assert "净需求运算" in crumb, f"页头副题缺「净需求运算」：{crumb}"

            sel_txt = page.locator('select[x-model="fVersion"]').first.inner_text()
            assert "全部版本" in sel_txt, f"版本下拉缺「全部版本」：{sel_txt}"
            assert "暂无月度版本" in sel_txt, f"无版本时缺禁用项「暂无月度版本」：{sel_txt}"
            assert page.locator('button:has-text("上游数据摘要")').count() > 0, "缺折叠按钮「上游数据摘要」"
            assert page.locator('input[placeholder="物料号 / 名称…"]').count() > 0, "缺物料 autocomplete"

            chips = page.locator("span.fchip").all_inner_texts()
            for c in ["全部", "N+1", "N+2", "N+3"]:
                assert any(c == t.strip() for t in chips), f"滚动月度 chips 缺 {c}：{chips}"
            assert page.locator('button:has-text("重置")').count() > 0, "缺「重置」按钮"

            assert page.locator("main table.tbl th").count() == 10, "表格表头非 10 列"
            page.wait_for_selector('main table.tbl td.empty:has-text("无匹配数据")', timeout=8000)
            assert page.locator('text=请选择月度版本后，按版本状态执行对应操作').count() > 0, "缺版本操作提示"

            # ===================== §0 造数 =====================
            step("§0 造数")
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"造数失败：{seed}"

            # ===================== §2 列表有数据 =====================
            step("§2 列表")
            page.reload()
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            goto_demand(page)
            page.wait_for_selector("main table.tbl tr.data", timeout=15000)
            page.wait_for_timeout(500)

            rows = page.locator("main table.tbl tr.data")
            assert rows.count() == 3, f"造数后列表应 3 行，实际 {rows.count()}"
            body = page.locator("main table.tbl").first.inner_text()
            for token in ["202608", "M1", "N+1", "N+2", "N+3"]:
                assert token in body, f"列表缺 {token}"

            # N+1 行关键列：gross_qty=950（草稿），net_qty=0（草稿未运算）
            row1 = rows.filter(has_text="N+1").first
            cells1 = row1.locator("td").all_inner_texts()
            assert cells1[0] == "202608", f"N+1 行版本列错：{cells1}"
            assert cells1[1] == "M1", f"N+1 行物料列错：{cells1}"
            assert cells1[2] == "N+1", f"N+1 行滚动月度列错：{cells1}"
            assert cells1[5] == "950", f"N+1 行毛需求列应为 950：{cells1}"
            assert cells1[9] == "0", f"N+1 行净需求列应为 0（草稿未运算）：{cells1}"

            # 版本下拉过滤（选项含 lock_status 徽章「草稿」）
            opt = page.locator('select option[value="202608"]').first
            assert opt.count() > 0, "版本下拉无 202608 选项"
            assert "草稿" in opt.inner_text(), f"版本选项未带「草稿」徽章：{opt.inner_text()}"
            select_version(page, "202608")
            page.wait_for_selector("main table.tbl tr.data", timeout=10000)
            assert page.locator("main table.tbl tr.data").count() == 3, "选版本 202608 应 3 行"

            # 物料 autocomplete 精确过滤
            choose_material(page, "M1")
            page.wait_for_selector("main table.tbl tr.data", timeout=10000)
            mrows = page.locator("main table.tbl tr.data")
            assert mrows.count() == 3, f"选物料 M1 应 3 行，实际 {mrows.count()}"
            assert page.locator('input[placeholder="物料号 / 名称…"]').first.input_value() == "M1", "物料输入框未回填 M1"

            # 滚动月度 chips 过滤
            page.locator('span.fchip:has-text("N+3")').first.click()
            page.wait_for_timeout(800)
            crows = page.locator("main table.tbl tr.data")
            assert crows.count() == 1, f"chip N+3 应 1 行，实际 {crows.count()}"
            assert "N+3" in crows.first.inner_text(), "chip N+3 行未收敛到 N+3"

            # 重置 → 回 3 行
            page.locator('button:has-text("重置")').first.click()
            page.wait_for_selector("main table.tbl tr.data", timeout=10000)
            page.wait_for_timeout(300)
            assert page.locator("main table.tbl tr.data").count() == 3, "重置后应回 3 行"

            # 停用物料 M2 空态（不进 open_version → 无 demand 行）
            choose_material(page, "M2")
            page.wait_for_selector('main table.tbl td.empty:has-text("无匹配数据")', timeout=10000)
            assert page.locator("main table.tbl tr.data").count() == 0, "M2 应无 demand 行"
            assert "共 0 条" in page.locator("main").inner_text(), "M2 空态分页应为「共 0 条」"

            # ===================== §3 详情模态全字段 =====================
            step("§3 模态")
            page.locator('button:has-text("重置")').first.click()
            page.wait_for_selector("main table.tbl tr.data", timeout=10000)
            page.wait_for_timeout(300)
            assert page.locator("main table.tbl tr.data").count() == 3, "模态前置应 3 行"

            page.locator("main table.tbl tr.data button.b-link").first.click()
            wait_modal(page)

            docno = page.locator(".modal-mask:visible .docno").first.inner_text().strip()
            assert docno == "202608 · M1 · N+1", f"模态 docno 错：{docno}"
            badge = page.locator(".modal-mask:visible .modal-hd .st").first.inner_text().strip()
            assert badge == "草稿", f"模态版本徽章应为草稿：{badge}"

            txt = page.locator(".modal-mask:visible .modal-bd").first.inner_text()
            for expected in [
                "基本标识", "版本", "202608", "物料", "M1", "滚动月度", "N+1",
                "标识 = 版本 + 物料 + 滚动月度唯一",
                "毛需求拆解", "预测", "950", "库存策略", "毛需求",
                "每个滚动月度", "系统计算 · 禁止手工改",
                "净需求拆解", "未发", "库存", "在途", "净需求",
                "自有仓 + 寄售仓", "系统计算 · 各层非负", "原始数据",
            ]:
                assert expected in txt, f"模态缺字段：{expected}"

            # 页脚按钮：草稿态含【合成毛需求】【发布】，不含【运算净需求】【导出净需求】
            ft = page.locator(".modal-mask:visible .modal-ft button:visible").all_inner_texts()
            assert any("合成毛需求" in t for t in ft), f"草稿模态页脚缺合成毛需求：{ft}"
            assert any("发布" in t for t in ft), f"草稿模态页脚缺发布：{ft}"
            assert not any("运算净需求" in t for t in ft), f"草稿模态页脚不应见运算净需求：{ft}"
            assert not any("导出净需求" in t for t in ft), f"草稿模态页脚不应见导出净需求：{ft}"

            close_modal(page)

            # ===================== §4 操作区（版本状态机 x-show） =====================
            step("§4 操作区-草稿态")
            select_version(page, "202608")
            page.wait_for_selector('button:visible:has-text("合成毛需求")', timeout=8000)
            btns = visible_button_texts(page)
            assert any("合成毛需求" in t for t in btns), f"草稿态缺合成毛需求：{btns}"
            assert any("发布" in t for t in btns), f"草稿态缺发布：{btns}"
            assert not any("运算净需求" in t for t in btns), f"草稿态不应见运算净需求：{btns}"
            assert not any("导出净需求" in t for t in btns), f"草稿态不应见导出净需求：{btns}"

            step("§4 合成毛需求")
            page.locator('button:visible:has-text("合成毛需求")').first.click()
            page.wait_for_selector('.toast:has-text("毛需求合成成功")', timeout=8000)
            page.wait_for_selector("main table.tbl tr.data", timeout=10000)
            assert page.locator("main table.tbl tr.data").count() == 3, "幂等重算后仍应 3 行"

            step("§4 发布")
            page.locator('button:visible:has-text("发布")').first.click()
            page.wait_for_selector('.toast:has-text("毛需求发布成功")', timeout=8000)
            page.wait_for_function(
                "() => (document.querySelector('select option[value=\"202608\"]')||{}).textContent?.includes('发布（锁定）')",
                timeout=8000,
            )
            btns = visible_button_texts(page)
            assert any("运算净需求" in t for t in btns), f"发布后缺运算净需求：{btns}"
            assert not any("合成毛需求" in t for t in btns), f"发布后不应见合成毛需求：{btns}"
            assert not any("发布" in t for t in btns), f"发布（锁定）态不应见发布按钮：{btns}"
            assert not any("导出净需求" in t for t in btns), f"发布后不应见导出净需求：{btns}"

            step("§4 运算净需求")
            page.locator('button:visible:has-text("运算净需求")').first.click()
            page.wait_for_selector('.toast:has-text("净需求运算成功")', timeout=8000)
            page.wait_for_function(
                "() => (document.querySelector('select option[value=\"202608\"]')||{}).textContent?.includes('冻结')",
                timeout=8000,
            )
            page.wait_for_selector("main table.tbl tr.data", timeout=10000)
            net_row = page.locator("main table.tbl tr.data").filter(has_text="N+1").first
            net_cells = net_row.locator("td").all_inner_texts()
            assert net_cells[9] == "950", f"运算后净需求列应为 950：{net_cells}"

            btns = visible_button_texts(page)
            assert any("导出净需求" in t for t in btns), f"冻结态缺导出净需求：{btns}"
            assert not any("合成毛需求" in t for t in btns), f"冻结态不应见合成毛需求：{btns}"
            assert not any("发布" in t for t in btns), f"冻结态不应见发布：{btns}"
            assert not any("运算净需求" in t for t in btns), f"冻结态不应见运算净需求：{btns}"

            step("§4 导出净需求")
            with page.expect_download(timeout=10000) as dl_info:
                page.locator('button:visible:has-text("导出净需求")').first.click()
            page.wait_for_selector('.toast:has-text("已导出 3 行净需求")', timeout=8000)
            dl = dl_info.value
            assert "net_demand_202608.csv" in dl.suggested_filename, f"下载文件名错：{dl.suggested_filename}"
            csv_text = pathlib.Path(str(dl.path())).read_text(encoding="utf-8-sig")
            csv_lines = [l for l in csv_text.splitlines() if l.strip()]
            assert len(csv_lines) == 4, f"CSV 应为 4 行（表头+3 数据），实际 {len(csv_lines)}"
            assert "net_qty" in csv_lines[0], f"CSV 表头缺 net_qty：{csv_lines[0]}"

            # ===================== §6 0 报错红线 =====================
            step("§6 0 报错")
            assert not errors, f"前端报错：{errors[:5]}"
            print("VERIFY_VIEW_psc_demand: PASS")

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
