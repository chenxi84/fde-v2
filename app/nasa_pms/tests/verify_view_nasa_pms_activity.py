"""e2e 前端验收 - nasa_pms:activity（进度活动台账 · 活动网络 + 派生排程 + 基线/实绩分离）。

断言：列表与入口 → **网络体检**（开口端报出来）→ **排程视图**（派生日期正推、浮时、关键路径）
→ 新建活动（挂靠必须是叶子 / 里程碑工期必须 0 / 名称唯一）→ 连前置（冗余被拒）→
基线（冻结派生日期、锁住计划字段）→ 发起修订（候选只列已批准）→ **回填实绩不动基线** →
全程 0 console error / 0 pageerror / 0 HTTP≥400。

用例来源：app/nasa_pms/activity/前端测试用例.md（§0 造数 + §1..§7）。
运行：python app/nasa_pms/tests/verify_view_nasa_pms_activity.py
"""
import atexit
import http.client
import os
import pathlib
import re
import socket
import sqlite3
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent


def _project_root() -> pathlib.Path:
    p = HERE
    while not (p / "fde_platform").is_dir():
        if p.parent == p:
            raise RuntimeError("无法定位项目根目录（未找到 fde_platform/）")
        p = p.parent
    return p


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from fde_platform.shadowdb import (  # noqa: E402
    auth_db_path, shadow_clear, shadow_clear_prefs, shadow_dbs,
)
from fde_platform.view_watchdog import install_watchdog  # noqa: E402

# 影子库：业务库与平台库**都**复制到副本 → 真库零字节接触，**不用停 dev server**。
_shadow = shadow_dbs(env=True, inprocess=False, config=True)
_shadow.__enter__()
shadow_clear("nasa_pms")
shadow_clear_prefs()
atexit.register(_shadow.__exit__, None, None, None)

from fde_platform import users  # noqa: E402

# 输出编码：控制台代码页在本机默认是 GBK，而断言文案里有 ⇒ / ✓ / ✗ / ⚠ / − 这类**非 GBK 码位** ——
# 不钉住编码的话，print 自己会抛 UnicodeEncodeError（崩在打印结果那一步）。
# 由 scripts/verify_test_script_encoding.py 守住这一行别被删。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

users.init_schema()
users.seed_admin()
try:
    _auth = auth_db_path()
    if _auth.exists():
        _c = sqlite3.connect(str(_auth))
        _c.execute("UPDATE users SET password_changed = 1 WHERE username = 'admin'")
        _c.commit()
        _c.close()
except Exception:
    pass


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_up(port, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("GET", "/api/groups")
            conn.getresponse().read()
            return True
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("platform 未在限定时间内启动")


# §0 自足造数（走 REST，不经 UI）：
#   WBS：父 900000（**故意留着有子元素**，供"挂父元素被拒"的负例）+ 两个叶子
#   一条已批准的变更（供「发起修订」）
#   一条单链网络：起始里程碑 → 活动 5d → 活动 3d → 完成里程碑；外加一条**开口端**活动
# ⚠ REST 路径必须用**组限定名** `nasa_pms/activity`（短名 404「应用不存在」）。
SEED_JS = r"""async () => {
  const call = async (app, svc, params) => {
    const r = await fetch(`/api/apps/${app}/call/${svc}`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(params || {})
    });
    const text = await r.text();
    let data = null; try { data = text ? JSON.parse(text) : null; } catch (e) {}
    if (!r.ok) throw new Error(`${app}.${svc} HTTP ${r.status} ${text.slice(0,160)}`);
    if (data && data.status === "error") throw new Error(`${app}.${svc} ${data.message || text.slice(0,160)}`);
    return data && data.data !== undefined ? data.data : data;
  };
  const WBS = "nasa_pms/wbs", ACT = "nasa_pms/activity";
  const CI = "nasa_pms/configuration_item", CR = "nasa_pms/change_request";

  await call(WBS, "create", {wbs_no: "900000", title: "进度系统", scope_ref: "SOW §9"});
  await call(WBS, "add_child", {parent_no: "900000", title: "结构分系统"});
  await call(WBS, "add_child", {parent_no: "900000", title: "热控分系统"});
  await call(WBS, "update", {wbs_no: "900000.01", scope_ref: "SOW §9.1"});
  await call(WBS, "update", {wbs_no: "900000.02", scope_ref: "SOW §9.2"});

  const ci = await call(CI, "create", {name: "进度基线对象", ci_type: "document"});
  const cr = await call(CR, "create", {title: "进度调整", requester: "进度组",
    ci_nos: ci.ci_no, description: "舱段装配工期调整"});
  await call(CR, "analyze", {cr_no: cr.cr_no, impact_analysis: "影响舱段装配活动工期"});
  await call(CR, "submit_review", {cr_no: cr.cr_no});
  await call(CR, "approve", {cr_no: cr.cr_no, comment: "同意", approver: "项目经理"});

  const L = "900000.01";
  await call(ACT, "add_milestone", {name: "装配启动", wbs_no: L, phase: "start", owner: "结构组"});
  await call(ACT, "create", {name: "装配舱板", wbs_no: L, duration_days: 5,
    predecessors: "ACT-001", owner: "结构组"});
  await call(ACT, "create", {name: "测试舱板", wbs_no: L, duration_days: 3,
    predecessors: "ACT-002", owner: "测试组"});
  await call(ACT, "add_milestone", {name: "舱段交付", wbs_no: L, predecessors: "ACT-003",
    phase: "finish"});
  await call(ACT, "create", {name: "待连线的活动", wbs_no: "900000.02", duration_days: 2});
  return {seeded: true, cr_no: cr.cr_no};
}"""

STEP = ""
RESULTS = []


def step(name):
    global STEP
    STEP = name
    print(f"[step] {name}", flush=True)


def rec(ok, note=""):
    RESULTS.append((STEP, ok, note))
    print(f"    {'[OK]' if ok else '[FAIL]'} {note}" if note else f"    {'[OK]' if ok else '[FAIL]'}",
          flush=True)


def wait_text(loc, want, timeout=8000):
    end = time.time() + timeout / 1000.0
    last = ""
    while time.time() < end:
        try:
            last = loc.inner_text()
        except Exception:
            last = ""
        if want in last:
            return last
        time.sleep(0.15)
    return last


def wait_rows(page, n, timeout=8000):
    end = time.time() + timeout / 1000.0
    c = 0
    while time.time() < end:
        c = page.locator(f"{LIST_SEL} tr.data").count()   # ⚠ 限定台账表（见 LIST_SEL 的注释）
        if c == n:
            return c
        time.sleep(0.15)
    return c


def drain_toasts(page, timeout=7000):
    """等当前吐司消散 —— 不排空就断言"吐司含某某"会被**陈旧吐司**喂饱（假过）。"""
    end = time.time() + timeout / 1000.0
    while time.time() < end:
        try:
            if not page.locator(".toasts").inner_text().strip():
                return True
        except Exception:
            return True
        time.sleep(0.2)
    return False


def wait_toast(page, want="", timeout=6000):
    end = time.time() + timeout / 1000.0
    last = ""
    while time.time() < end:
        try:
            last = page.locator(".toasts").inner_text()
        except Exception:
            last = ""
        if last.strip() and (not want or want in last):
            return last
        time.sleep(0.15)
    return last


def close_modal(page, timeout=8000):
    """关掉当前可见模态。⚠ 负例之后**必须显式关**：提交被拒时模态故意保持打开。"""
    end = time.time() + timeout / 1000.0
    while time.time() < end:
        vis = page.locator(".modal-mask:visible")
        if vis.count() == 0:
            return True
        box = vis.last
        for label in ("取消", "关闭"):
            btn = box.locator(f'button:has-text("{label}")')
            if btn.count():
                try:
                    btn.first.click(timeout=1500)
                    break
                except Exception:
                    pass
        time.sleep(0.2)
    return page.locator(".modal-mask:visible").count() == 0


# ⚠ 页面上有**两张** `table.tbl`（台账 + 排程），排程那张 `x-show` 隐藏但**仍在 DOM** ——
#   行数统计与行内定位都必须限定在台账表内，否则行数翻倍、`row_of` 还可能挑到隐藏表那行
#   （那行没有动作按钮，点它会一路超时）。实测踩过。
LIST_SEL = ".scroll-x table.tbl"


def rows(page):
    return page.locator(f"{LIST_SEL} tr.data")


def row_of(page, act_no):
    return page.locator(f"{LIST_SEL} tr.data").filter(has_text=act_no).first


def main():
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        env={**os.environ, "PLATFORM_PORT": str(port), "PORT": str(port)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    errors, ignored = [], []
    install_watchdog(errors, step_getter=lambda: STEP)

    def attach(page):
        def on_console(m):
            if m.type == "error":
                errors.append(m.text[:140])

        def on_pageerror(e):
            errors.append(str(e)[:140])

        def on_response(r):
            if r.status >= 400:
                if "/favicon.ico" in r.url or r.url.endswith(".map"):
                    ignored.append(f"HTTP {r.status} {r.url}")
                    return
                errors.append(f"HTTP {r.status} {r.url}")

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
            lp = ctx.new_page()
            attach(lp)
            lp.goto(f"{base}/login")
            lp.fill('input[name="username"]', "admin")
            lp.fill('input[name="password"]', "admin")
            lp.click('button[type="submit"]')
            lp.wait_for_url("**/", timeout=15000)

            page = ctx.new_page()
            attach(page)
            page.goto(f"{base}/view/nasa_pms/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            page.evaluate("() => localStorage.setItem('fde.agent.rail','0')")

            step("§0 造数（WBS 树 + 已批准变更 + 单链网络 + 一条开口端）")
            seed = page.evaluate(SEED_JS)
            # VT-ROUTE-01 标题「进度活动台账」可见
            rec(bool(seed and seed.get("seeded")),
               "900000（父）/ 900000.01 / 900000.02；CR 已批准；ACT-001..005（含一条开口端）")

            # ── §1 渲染与入口 ────────────────────────────────
            step("§1 渲染与入口（VT-ROUTE-01..04）")
            page.evaluate("location.hash = '#/activity'")
            page.wait_for_selector('button:has-text("新建活动")', timeout=10000)
            page.wait_for_timeout(900)
            body = page.locator("main").inner_text()
            # VT-ROUTE-01 列表 {rows
            rec("进度活动台账" in body, "VT-ROUTE-01 标题「进度活动台账」可见")
            rec(rows(page).count() == 5, f"VT-ROUTE-01 列表 {rows(page).count()} 行（期望 5）")
            heads = page.locator(f"{LIST_SEL} tr").first.inner_text()
            # VT-ROUTE-02 表头完整
            # VT-ROUTE-03 「{b}」入口可见
            rec(all(h in heads for h in ("活动编号", "名称", "类型", "挂靠元素", "工期", "前置",
                                         "状态", "完成", "基线", "责任方")),
                "VT-ROUTE-02 表头完整")
            for b in ("新建活动", "新建里程碑", "网络体检", "排程视图"):
                rec(page.locator(f'button:has-text("{b}")').count() > 0, f"VT-ROUTE-03 「{b}」入口可见")
            r4 = row_of(page, "ACT-004").inner_text()
            # VT-ROUTE-04 ACT-004
            # VT-CHECK-11 问题合计 = {total.strip
            rec("里程碑" in r4 and "计划" in r4 and "未基线" in r4,
                "VT-ROUTE-04 ACT-004：里程碑 / 计划 / 未基线")

            # ── §2 网络体检 ─────────────────────────────────
            step("§2 网络体检（VT-CHECK-11..12）")
            page.click('button:has-text("网络体检")')
            page.wait_for_selector('[data-role="network-check"]:visible', timeout=8000)
            total = wait_text(page.locator('[data-role="check-total"]'), "2", timeout=6000)
            # VT-CHECK-12 开口端点名 ACT-005
            rec(total.strip() == "2", f"VT-CHECK-11 问题合计 = {total.strip()}（ACT-005 缺前置 + 缺后续）")
            oe = page.locator('[data-role="check-open-ends"]').inner_text()
            # VT-SCH-21 派生日期非空且形如 YYYY-MM-DD
            rec("ACT-005" in oe, f"VT-CHECK-12 开口端点名 ACT-005：{oe[:60]}")

            # ── §3 排程视图（派生）────────────────────────────
            step("§3 排程视图（VT-SCH-21..24）")
            page.click('button:has-text("排程视图")')
            page.wait_for_selector('[data-role="schedule"]:visible', timeout=8000)
            page.wait_for_timeout(600)
            sch = page.locator('[data-role="schedule"]')
            s1 = sch.locator('[data-role="sch-start"]').first.inner_text()
            # VT-SCH-22 链内日期递增
            rec(len(s1) == 10 and s1[4] == "-", f"VT-SCH-21 派生日期非空且形如 YYYY-MM-DD：{s1}")
            # ⚠ 别断言"全部日期递增"：开口端那条从项目起始日开工，本来就会更早 —— 要按**链内**判
            rows_i = sch.locator("tr.data")
            by = {}
            for i in range(rows_i.count()):
                txt = rows_i.nth(i).inner_text()
                by[txt.split()[0]] = (
                    rows_i.nth(i).locator('[data-role="sch-start"]').inner_text(),
                    rows_i.nth(i).locator('[data-role="sch-float"]').inner_text(),
                    rows_i.nth(i).locator('[data-role="sch-critical"]').inner_text())
            chain_ok = (by["ACT-001"][0] <= by["ACT-002"][0] <= by["ACT-003"][0] <= by["ACT-004"][0])
            rec(chain_ok, f"VT-SCH-22 链内日期递增（正推）："
                          f"{[by[k][0] for k in ('ACT-001','ACT-002','ACT-003','ACT-004')]}")
            # VT-SCH-23 单链四条浮时全 0
            rec(all(by[k][1] == "0" and "关键路径" in by[k][2]
                    for k in ("ACT-001", "ACT-002", "ACT-003", "ACT-004"))
                and by["ACT-005"][1] != "0" and "关键路径" not in by["ACT-005"][2],
                f"VT-SCH-23 单链四条浮时全 0（关键路径）；开口端那条不在关键路径上（浮时 {by['ACT-005'][1]}）")
            # VT-SCH-24 标注「派生排程」
            rec(page.locator('[data-role="schedule"]').inner_text().count("派生排程") == 1,
                # VT-FORM-31 不挂元素被拒且行数不变
                "VT-SCH-24 标注「派生排程」（日期由工期与逻辑链正推）")
            page.click('button:has-text("台账视图")')
            page.wait_for_selector("table.tbl tr.data", timeout=8000)

            # ── §4 新建（活动 / 里程碑）──────────────────────
            step("§4 新建活动与里程碑（VT-FORM-31..35）")
            page.click('button:has-text("新建活动")')
            page.wait_for_selector('.modal-mask:visible [data-role="form-name"]', timeout=8000)
            page.fill('[data-role="form-name"]', "没有挂靠的活动")
            page.fill('[data-role="form-wbs"]', "")
            drain_toasts(page)
            page.click('[data-role="form-submit"]')
            t = wait_toast(page, "挂靠")
            # VT-FORM-32 BR-05 挂父元素被拒
            rec("挂靠" in t and rows(page).count() == 5, f"VT-FORM-31 不挂元素被拒且行数不变：{t[:34]}")
            page.fill('[data-role="form-wbs"]', "900000")        # 父元素（有子元素）
            drain_toasts(page)
            page.click('[data-role="form-submit"]')
            t = wait_toast(page, "最底层元素")
            rec("最底层元素" in t, f"VT-FORM-32 BR-05 挂父元素被拒：{t[:40]}")
            page.fill('[data-role="form-wbs"]', "900000.02")
            page.fill('[data-role="form-name"]', "热控涂层")
            page.fill('[data-role="form-duration"]', "2")
            drain_toasts(page)
            page.click('[data-role="form-submit"]')
            n = wait_rows(page, 6)
            # VT-FORM-33 新建活动成功
            # VT-FORM-34 BR-04 里程碑带工期被拒
            rec(n == 6 and "ACT-006" in page.locator(LIST_SEL).inner_text(),
                f"VT-FORM-33 新建活动成功，列表 {n} 行")

            page.click('button:has-text("新建里程碑")')
            page.wait_for_selector('.modal-mask:visible [data-role="form-duration"]', timeout=8000)
            page.fill('[data-role="form-name"]', "带工期的里程碑")
            page.fill('[data-role="form-wbs"]', "900000.02")
            page.fill('[data-role="form-duration"]', "3")
            drain_toasts(page)
            page.click('[data-role="form-submit"]')
            t = wait_toast(page, "必须为 0")
            # VT-FORM-35 BR-06 名称重复被拒
            rec("必须为 0" in t and rows(page).count() == 6, f"VT-FORM-34 BR-04 里程碑带工期被拒：{t[:40]}")
            page.fill('[data-role="form-duration"]', "0")
            page.fill('[data-role="form-name"]', "热控涂层")
            drain_toasts(page)
            page.click('[data-role="form-submit"]')
            t = wait_toast(page, "同名活动")
            # VT-LINK-41 前置列出现 ACT-001
            rec("同名活动" in t, f"VT-FORM-35 BR-06 名称重复被拒：{t[:40]}")
            close_modal(page)

            # ── §5 连前置（冗余被拒）────────────────────────
            step("§5 连前置（VT-LINK-41..42）")
            row_of(page, "ACT-005").locator('button:has-text("连前置")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="link-pred"]', timeout=8000)
            page.fill('[data-role="link-pred"]', "ACT-001")
            drain_toasts(page)
            page.click('[data-role="link-submit"]')
            n = wait_toast(page, "已给 ACT-005 连上前置")
            r = wait_text(row_of(page, "ACT-005"), "ACT-001", timeout=6000)
            # VT-LINK-42 BR-02 冗余链接被拒
            rec("ACT-001" in r, "VT-LINK-41 前置列出现 ACT-001")
            row_of(page, "ACT-003").locator('button:has-text("连前置")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="link-pred"]', timeout=8000)
            page.fill('[data-role="link-pred"]', "ACT-001")
            drain_toasts(page)
            page.click('[data-role="link-submit"]')
            t = wait_toast(page, "冗余链接")
            # VT-ACT-51 基线动作有回执
            rec("冗余链接" in t, f"VT-LINK-42 BR-02 冗余链接被拒（A→B→C 时 A→C）：{t[:44]}")
            close_modal(page)

            # ── §6 基线 / 修订 / 实绩 ───────────────────────
            step("§6 基线 / 修订 / 实绩（VT-ACT-51..57）")
            drain_toasts(page)
            row_of(page, "ACT-002").locator('button:has-text("基线")').click()
            t = wait_toast(page)
            print(f"      （基线 toast：{t[:80]!r}）", flush=True)
            rec("基线" in t, f"VT-ACT-51 基线动作有回执：{t[:50]}")
            r = wait_text(row_of(page, "ACT-002"), "-", timeout=6000)
            base_col = row_of(page, "ACT-002").locator('[data-role="baseline"]').inner_text()
            # VT-ACT-51 基线列出现日期区间
            rec("→" in base_col and "未基线" not in base_col,
                f"VT-ACT-51 基线列出现日期区间：{base_col}")
            # VT-ACT-52 已基线后「基线」消失、「发起修订」出现
            rec(row_of(page, "ACT-002").locator('button:has-text("基线")').is_visible() is False
                and row_of(page, "ACT-002").locator('button:has-text("发起修订")').is_visible(),
                "VT-ACT-52 已基线后「基线」消失、「发起修订」出现")
            row_of(page, "ACT-002").locator('button:has-text("详情")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="act-head"]', timeout=8000)
            form = page.locator(".modal-mask:visible").last
            # VT-ACT-53 已基线活动在详情里**看不到**「编辑」
            rec(form.locator('button:has-text("编辑")').is_visible() is False,
                "VT-ACT-53 已基线活动在详情里**看不到**「编辑」（要走变更流程）")
            # VT-ACT-54 变更号候选只列已批准
            rec("发起修订" in form.inner_text(), "VT-ACT-53 提示语指向「发起修订」")
            close_modal(page)

            row_of(page, "ACT-002").locator('button:has-text("发起修订")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="change-cr"]', timeout=8000)
            opts = page.locator("#act-cr-options option").all_inner_texts()
            # VT-ACT-55 变更号列出现 CR-001
            rec(any("CR-001" in o for o in opts), f"VT-ACT-54 变更号候选只列已批准：{opts[:2]}")
            page.fill('[data-role="change-cr"]', "CR-001")
            drain_toasts(page)
            page.click('[data-role="change-submit"]')
            t = wait_toast(page, "已挂上变更")
            r = wait_text(row_of(page, "ACT-002"), "CR-001", timeout=6000)
            # VT-ACT-56 回填 100% 后状态「已完成」
            rec("CR-001" in r, "VT-ACT-55 变更号列出现 CR-001")

            before = row_of(page, "ACT-002").locator('[data-role="baseline"]').inner_text()
            row_of(page, "ACT-002").locator('button:has-text("回填实绩")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="progress-pct"]', timeout=8000)
            page.fill('[data-role="progress-pct"]', "100")
            page.fill('[data-role="progress-start"]', "2026-10-06")
            page.fill('[data-role="progress-finish"]', "2026-10-14")
            drain_toasts(page)
            page.click('[data-role="progress-submit"]')
            t = wait_toast(page, "实绩已回填")
            r = wait_text(row_of(page, "ACT-002"), "已完成", timeout=6000)
            rec("已完成" in r and "100%" in r, f"VT-ACT-56 回填 100% 后状态「已完成」")
            after = row_of(page, "ACT-002").locator('[data-role="baseline"]').inner_text()
            # VT-ACT-57 BR-08 回填实绩**不动基线**
            rec(after == before,
                f"VT-ACT-57 BR-08 回填实绩**不动基线**：{before} → {after}")

            # ── §8 甘特视图（2026-09-26 增补）──────────────────
            step("§8 甘特视图（VT-GANTT-71..74）")
            # VT-GANTT-71 切到甘特
            page.click('[data-role="to-gantt"]')
            page.wait_for_selector('[data-role="gantt"]:visible', timeout=8000)
            page.wait_for_timeout(600)
            n_l = rows(page).count()
            rec(page.locator('[data-role="gantt-row"]').count() == n_l,
                f"VT-GANTT-71 甘特行数 = 台账行数（{n_l}）")
            # VT-GANTT-72 每条都画出了条形（宽度 > 0）
            bars = page.locator('[data-role="gantt-bar"]')
            # ⚠ `page.evaluate` 收的是 **ElementHandle**，不是 Locator —— 传 Locator 会报
            #   "Cannot read properties of undefined (reading 'style')"（实测）。读 style 属性再解析更省事。
            def _bar_w(i):
                st = bars.nth(i).get_attribute("style") or ""
                m = re.search(r"width:\s*([\d.]+)%", st)
                return float(m.group(1)) if m else 0.0
            widths = [_bar_w(i) for i in range(bars.count())]
            rec(len(widths) == n_l and all(w > 0 for w in widths),
                f"VT-GANTT-72 每条都有条形（宽度 {[round(w,1) for w in widths[:4]]}…）")
            # VT-GANTT-73 关键路径用 data-crit 标出
            crit_n = sum(1 for i in range(bars.count())
                         if bars.nth(i).get_attribute("data-crit") == "1")
            rec(0 < crit_n < bars.count(), f"VT-GANTT-73 关键路径标出 {crit_n}/{bars.count()} 条")
            # VT-GANTT-74 切回台账
            page.click('button:has-text("台账视图")')
            page.wait_for_selector(".scroll-x table.tbl", timeout=8000)
            rec(rows(page).count() == n_l, "VT-GANTT-74 切回台账视图正常")

            # ── §9 四种关系 / 滞后 / 日历（2026-09-26 增补）──────
            step("§9 四种关系与日历（VT-REL-81..83 / VT-CAL-91..92）")
            # VT-REL-81 关系类型是四值枚举（静态 option）
            row_of(page, "ACT-005").locator('button:has-text("连前置")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="link-type"]', timeout=8000)
            opts = page.locator('[data-role="link-type"] option').all_inner_texts()
            rec(len(opts) == 4 and all(k in " ".join(opts) for k in ("FS", "SS", "FF", "SF")),
                # VT-REL-81 四种关系模型
                f"VT-REL-81 关系类型四个选项：{opts}")
            # VT-REL-82 非 FS 不带理由 → 被拒
            # ⚠ 选 ACT-006（热控涂层，独立分支）当候选：挑 ACT-003 会被后端判**冗余链接**
            #   （ACT-001 已通过 ACT-002、ACT-003 间接前置了 ACT-005）—— 那是闸门正确，不是 bug
            page.select_option('[data-role="link-type"]', "SS")
            page.fill('[data-role="link-pred"]', "ACT-006")
            page.fill('[data-role="link-reason"]', "")
            drain_toasts(page)
            page.click('[data-role="link-submit"]')
            t = wait_toast(page, "必须写明理由")
            rec("必须写明理由" in t, f"VT-REL-82 非 FS 缺理由被拒（§5.5.8.2）：{t[:44]}")
            # VT-REL-83 带上滞后与理由 → 连上，前置列显示关系与滞后
            page.fill('[data-role="link-lag"]', "2")
            page.fill('[data-role="link-reason"]', "与它并行启动，等资源到位")
            drain_toasts(page)
            page.click('[data-role="link-submit"]')
            t = wait_toast(page, "SS")
            rec("SS" in t, f"VT-REL-83 连上有回执（含关系类型）：{t[:44]}")
            r = wait_text(row_of(page, "ACT-005").locator('[data-role="rels"]'), "SS+2", timeout=6000)
            rec("SS+2" in r, f"VT-REL-83 前置列显示关系与滞后：{r[:40]}")
            close_modal(page)
            # VT-CAL-91 日历候选取自服务，默认日历已就位
            cal_opts = page.evaluate(
                "() => Array.from(document.querySelectorAll('#act-cal-options option')).map(o => o.value)")
            rec(len(cal_opts) >= 1 and page.input_value('[data-role="cal-pick"]') == cal_opts[0],
                f"VT-CAL-91 日历候选 {cal_opts}，输入框已选 {page.input_value('[data-role="cal-pick"]')}")
            # VT-CAL-92 排程视图标出工期口径与日历
            page.click('button:has-text("排程视图")')
            page.wait_for_selector('[data-role="sch-cal"]', timeout=8000)
            txt = wait_text(page.locator('[data-role="sch-cal"]'), "口径", timeout=6000)
            rec("口径" in txt and "CAL-" in txt, f"VT-CAL-92 排程标注口径与日历：{txt[:60]}")
            page.click('button:has-text("台账视图")')
            page.wait_for_selector(".scroll-x table.tbl", timeout=8000)

            # 豁免清单受检（V5）
            for _ig in ignored:
                rec(("/favicon.ico" in _ig or ".map" in _ig), f"豁免理由成立：{_ig[:90]}")

            step("§7 硬件指标（VT-HW-90）")
            rec(not errors, f"0 console error / 0 pageerror / 0 HTTP≥400（实际 {len(errors)}）")
            for e in errors[:6]:
                print("      ✗", e)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
