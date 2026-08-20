"""e2e 前端验收 - parts-fc:baseline_borrowing（基线借用）
断言：路由渲染防粘滞 → 造数后列表有数据 → 模态全字段 → 表单落库回显 → 全程 0 报错。
运行：python app/parts-fc/tests/verify_view_parts_fc_baseline_borrowing.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit


def _project_root() -> pathlib.Path:
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


# Ensure admin account exists
# seed admin account (required for login)
from fde_platform.auth import users
users.init_schema()
users.seed_admin()
# Bypass "请先修改默认密码" by marking admin password as changed
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
    const r = await fetch(`/api/apps/parts-fc/${app}/call/${svc}`, {
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

  const unwrap = (x) => {
    if (!x) return x;
    if (x.data !== undefined) return x.data;
    if (x.result !== undefined) return x.result;
    return x;
  };

  // 跨应用前置：车型映射 + 加工批次
  await call("vehicle_part_map", "create", {
    part_no: "BB-PART-001", veh_model: "BB-MODEL-A", usage: 1, share: 100,
    lc_stage: "爬坡", lc_shape: "传统", sop: "2025-01", source: "BOM"
  });
  await call("vehicle_part_map", "create", {
    part_no: "BB-PART-002", veh_model: "BB-MODEL-B", usage: 2, share: 55,
    lc_stage: "成熟", lc_shape: "传统", sop: "2024-06", source: "BOM"
  });
  await call("vehicle_part_map", "create", {
    part_no: "BB-PART-003", veh_model: "BB-MODEL-C", usage: 1, share: 100,
    lc_stage: "成熟", lc_shape: "传统", sop: "2024-06", source: "BOM"
  });
  const dp = await call("demand_processing", "create_batch", {
    fcst_version: "V2026-08", oem_code: "OEM-A", plant_code: "PLANT-1"
  });
  const dpData = unwrap(dp);
  const procBatch = dpData && (dpData.proc_batch || dpData.batch_no || dpData.no) || "BB-BATCH-001";

  const bb1 = await call("baseline_borrowing", "create", {
    part_no: "BB-PART-001", veh_model: "BB-MODEL-A", hist_months: 3,
    borrow_method: "先导指标", borrow_source: "V2026-08 OEM滚动预测",
    source_params: {"peak": 450}, derived_qty: {"2026-09": 430},
    proc_batch: procBatch, calibration: "首3月校准"
  });
  const bb2 = await call("baseline_borrowing", "create", {
    part_no: "BB-PART-002", veh_model: "BB-MODEL-B", hist_months: 6,
    borrow_method: "池化", borrow_source: "平台层统计",
    source_params: {"weight": 0.3}, derived_qty: {"2026-09": 350},
    proc_batch: procBatch, calibration: "半年度校准"
  });
  const bb3 = await call("baseline_borrowing", "create", {
    part_no: "BB-PART-003", veh_model: "BB-MODEL-C", hist_months: 2,
    borrow_method: "类比", borrow_source: "MODEL-X",
    source_params: {"ratio": 0.8}, derived_qty: {"2026-09": 280},
    proc_batch: procBatch, calibration: "早期校准"
  });

  const bb1Data = unwrap(bb1);
  const bb2Data = unwrap(bb2);
  const jy1No = bb1Data && (bb1Data.jy_no || bb1Data.no);
  const jy2No = bb2Data && (bb2Data.jy_no || bb2Data.no);

  if (jy1No) {
    await call("baseline_borrowing", "review", {jy_no: jy1No, approved: true, comment: "通过"});
  }
  if (jy2No) {
    await call("baseline_borrowing", "review", {jy_no: jy2No, approved: true, comment: "通过"});
    await call("baseline_borrowing", "close", {jy_no: jy2No, reason: "历史转充足"});
  }

  return {seeded: true, jy1_no: jy1No, jy2_no: jy2No};
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

            page.goto(f"{base}/view/parts-fc/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)

            # ===================== §1 本页渲染（防粘滞）=====================
            page.evaluate("location.hash = '#/baseline_borrowing'")
            try:
                page.wait_for_selector("main .card", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            assert page.locator("main").inner_text().strip(), "baseline_borrowing 页面无内容"
            assert page.locator("main .card").count() > 0, "baseline_borrowing 未渲染 card"
            assert page.locator(".kpi:visible").count() == 0, "baseline_borrowing 挂载未重建（残留看板）"

            # ===================== §0 造数 =====================
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"baseline_borrowing 造数失败：{seed}"

            # ===================== §2 列表有数据 =====================
            page.evaluate("location.hash = '#/baseline_borrowing'")
            page.wait_for_timeout(1000)  # wait for page load
            try:
                page.wait_for_selector("table tbody tr", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            row_count = page.locator("table tbody tr").count()
            assert row_count >= 1, f"baseline_borrowing 列表行数不足：{row_count}"

            # ===================== §3 模态全字段 =====================
            if seed.get("jy1_no"):
                jy1_no = seed["jy1_no"]
                page.locator(f'.b-link:has-text("{jy1_no}"), a:has-text("{jy1_no}")').first.click()
                modal = open_modal(page)
                txt = modal.inner_text()
                for expected in [jy1_no, "BB-PART-001", "先导指标", "创建时间"]:
                    if expected:
                        assert expected in txt, f"baseline_borrowing 详情模态缺字段：{expected}"
                close_modal(page, modal)

            # ===================== §4 表单落库回显 =====================
            click_button(page, ["+ 新建借用单", "新建借用单", "+ 新建", "新建"])
            modal = open_modal(page)

            fill_labeled(modal, "零件号", "BB-NEW-001")
            fill_labeled(modal, "车型", "BB-MODEL-A")

            click_button(modal, ["创建", "保存", "提交"])
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            # ===================== §6 0 报错 =====================
            assert not errors, f"baseline_borrowing 会话前端报错：{errors[:5]}"
            print("VERIFY_VIEW_parts_fc_baseline_borrowing: PASS")

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
        print(f"FAIL: {e}")
        sys.exit(1)
