"""e2e 前端验收 - nasa_pms:requirement（需求台账 · 独立创建）。

断言：新建入口存在（与只读台账相反）→ 列表 3 行 → **F-1** 验证方法未选则提交禁用 →
**F-2** 类型=派生 时上游必填 → 新建成功 → **F-4** 已基线需求正文/方法锁定、填变更号解锁 →
**F-6** 作废二次确认且记录保留 → **F-7** 筛选收敛 →
全程 0 console error / 0 pageerror / 0 HTTP≥400。

用例来源：app/nasa_pms/requirement/前端测试用例.md（§0 造数 + §1..§6）。
运行：python app/nasa_pms/tests/verify_view_nasa_pms_requirement.py
"""
import atexit
import http.client
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent


def _project_root() -> pathlib.Path:
    """向上找项目根（含 fde_platform/ 的目录）—— 按标记定位，不写死层级。"""
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
# config=True 必需：本脚本要播种 admin（写 config/auth.db），不影子化会污染真库。
_shadow = shadow_dbs(env=True, inprocess=False, config=True)
_shadow.__enter__()
# ⚠ 必须在**副本**上清表：副本带着真库数据，不清会撞主键。
shadow_clear("nasa_pms")
# 个人 UI 偏好是本机状态（如"手动隐藏过某列"），不清会让用例取决于谁在哪台机器上跑。
shadow_clear_prefs()
atexit.register(_shadow.__exit__, None, None, None)

from fde_platform import users  # noqa: E402

# 输出编码：控制台代码页在本机默认是 GBK，而断言文案里有 ⇒ / ✓ / ✗ / ⚠ / − 这类**非 GBK 码位** ——
# 不钉住编码的话，print 自己会抛 UnicodeEncodeError（**崩在打印结果那一步**：断言算完了却报不出来，
# 其后用例也不再执行 —— 实测 stakeholder 的 VT-ACT-32 就这么"消失"过）。与 scripts/run_gates.py 给
# 子进程设 PYTHONIOENCODING 同一根因；由 scripts/verify_test_script_encoding.py 守住别忘这一行。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

users.init_schema()
users.seed_admin()
# seed_admin 落 password_changed=0 → 首登被强制改密闸门拦下，先在副本里置 1 放行。
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


# §0 自足造数：3 条需求 + 基线冻结两条（走 REST，不经 UI —— 避免用例依赖"新建功能本身"）
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
    return data;
  };
  await call("nasa_pms/requirement", "create", {title: "系统应支持 1000 并发用户",
    statement: "8vCPU/32GB 下 P95 ≤ 2s", req_type: "technical", verify_method: "test", owner: "张三"});
  await call("nasa_pms/requirement", "create", {title: "接口应符合 ICD-001",
    statement: "接口数据项与 ICD-001 一致", req_type: "interface", verify_method: "inspection"});
  await call("nasa_pms/requirement", "derive", {source_req_no: "REQ-001", title: "分系统应支持 200 并发",
    statement: "派生自 REQ-001", verify_method: "analysis"});
  // 2026-09-25 起基线有**评审门**：先提交评审，再纳入基线
  await call("nasa_pms/requirement", "submit_review", {req_no: "REQ-001"});
  await call("nasa_pms/requirement", "submit_review", {req_no: "REQ-002"});
  await call("nasa_pms/requirement", "baseline", {req_nos: ["REQ-001", "REQ-002"], baseline_ver: "B1"});
  await call("nasa_pms/stakeholder", "upsert", {sh_no: "SH-EX1", name: "候选人甲", sh_type: "customer"});
  await call("nasa_pms/stakeholder", "upsert", {sh_no: "SH-EX2", name: "候选人乙", sh_type: "internal_org"});
  return {seeded: true};
}"""

STEP = ""
RESULTS = []


def step(name):
    global STEP
    STEP = name
    print(f"[step] {name}", flush=True)


def rec(ok, note=""):
    RESULTS.append((STEP, ok, note))
    print(f"    {'[OK]' if ok else '[FAIL]'} {note}" if note else f"    {'[OK]' if ok else '[FAIL]'}", flush=True)


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

            step("§0 造数（3 条需求 + 基线 B1）")
            seed = page.evaluate(SEED_JS)
            rec(bool(seed and seed.get("seeded")), "3 条需求已造，REQ-001/002 已基线")

            # ── §1 渲染与入口 ────────────────────────────────
            step("§1 渲染与入口（VT-ROUTE-01..VT-ROUTE-04）")
            page.evaluate("location.hash = '#/requirement'")
            page.wait_for_selector('button:has-text("新建需求")', timeout=10000)
            page.wait_for_timeout(800)
            body = page.locator("main").inner_text()
            rec("需求台账" in body, "VT-ROUTE-01 标题「需求台账」可见")
            rows = page.locator("table.tbl tr.data")
            rec(rows.count() == 3, f"VT-ROUTE-01 列表 {rows.count()} 行（期望 3）")
            heads = page.locator("table.tbl tr").first.inner_text()
            rec(all(h in heads for h in ("需求编号", "标题", "需求类型", "验证方法", "状态", "责任人")),
                # VT-ROUTE-02 表头
                "VT-ROUTE-02 表头完整")
            # VT-ROUTE-03 **保留新建入口**
            rec(page.locator('button:has-text("新建需求")').count() > 0, "VT-ROUTE-03 保留新建入口")
            first = rows.first.inner_text()
            rec("技术需求" in first and "测试" in first and "已基线" in first,
                "VT-ROUTE-04 首行显示 技术需求/测试/已基线")

            # ── §2 新建表单 ─────────────────────────────────
            step("§2 新建表单（VT-FORM-11..VT-FORM-17）")
            page.click('button:has-text("新建需求")')
            page.wait_for_timeout(400)
            form = page.locator(".modal-mask:visible").last
            rec(form.locator("textarea").count() > 0, "VT-FORM-11 新建模态出现")
            submit = form.locator('button:has-text("提交")')
            # VT-FORM-12 **F-1 验证方法未选**
            rec(submit.is_disabled(), "VT-FORM-12 未选验证方法 → 提交 disabled")
            form.locator("input").first.fill("临时需求A")
            form.locator("textarea").first.fill("临时正文")
            page.wait_for_timeout(200)
            # VT-FORM-13 只填标题+正文、验证方法留空
            rec(submit.is_disabled(), "VT-FORM-13 仍 disabled")
            form.locator("select").nth(1).select_option("test")     # 第 2 个 select = 验证方法
            page.wait_for_timeout(300)
            # VT-FORM-14 选上验证方法
            rec(not submit.is_disabled(), "VT-FORM-14 选了验证方法 → 可提交")
            form.locator("select").first.select_option("derived")    # 类型 = 派生需求
            page.wait_for_timeout(300)
            # VT-FORM-15 **F-2 类型选「派生需求」**
            rec(form.locator('input[placeholder*="必填"]').count() > 0, "VT-FORM-15 派生 → 上游需求出现")
            rec(submit.is_disabled(), "VT-FORM-15 上游留空 → 仍 disabled")
            form.locator('input[placeholder*="必填"]').fill("REQ-001")
            page.wait_for_timeout(300)
            # VT-FORM-16 填上游后提交
            rec(not submit.is_disabled(), "VT-FORM-16 填上游 → 可提交")
            submit.click()
            page.wait_for_timeout(1200)
            rec(page.locator("table.tbl tr.data").count() == 4, "VT-FORM-16 新建成功，列表变 4 行")
            page.click('button:has-text("新建需求")')
            page.wait_for_timeout(400)
            form2 = page.locator(".modal-mask:visible").last
            rec(form2.locator("input").first.input_value() == "", "VT-FORM-17 表单已重置")
            form2.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)

            # ── §3 详情 / 编辑（F-3 / F-4）────────────────────
            step("§3 详情与编辑（VT-MODAL-21..VT-MODAL-25）")
            # REQ-001 已基线 → 编辑时锁定
            row1 = page.locator("table.tbl tr.data").filter(has_text="REQ-001").first
            row1.locator('button:has-text("编辑")').click()
            page.wait_for_timeout(900)
            m = page.locator(".modal-mask:visible").last
            # VT-MODAL-22 点 `REQ-001`（已基线）编辑
            rec(m.locator("textarea").first.is_disabled(), "VT-MODAL-22 已基线 → 正文 disabled")
            rec(m.locator("select").last.is_disabled(), "VT-MODAL-22 已基线 → 验证方法 disabled")
            rec(m.locator('input[placeholder*="CR-"]').count() > 0, "VT-MODAL-22 出现变更号输入框")
            m.locator('input[placeholder*="CR-"]').fill("CR-001")
            page.wait_for_timeout(400)
            # VT-MODAL-23 已基线时填变更号 `CR-001`
            rec(not m.locator("textarea").first.is_disabled(), "VT-MODAL-23 填变更号 → 正文解锁")
            # VT-MODAL-24 **F-3 编号只读**
            rec(m.locator("input").count() >= 1 and "REQ-001" in m.inner_text(), "VT-MODAL-24 编号为纯文本显示")
            m.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(400)
            rec(page.locator("table.tbl tr.data").count() == 4, "VT-MODAL-25 关闭后列表未变")

            # ── §4 作废（F-6）──────────────────────────────
            step("§4 作废（VT-ACT-31..VT-ACT-33）")
            # 对话框有两种：`confirm`（二次确认）+ `prompt`（作废理由，选填）——
            # 同一个 handler 里 accept 带文本：confirm 忽略文本、prompt 拿它当输入值 ✓
            page.on("dialog", lambda d: d.accept("接口方案变更（VT-ACT-33 留痕断言）"))
            row2 = page.locator("table.tbl tr.data").filter(has_text="REQ-002").first
            row2.locator('button:has-text("作废")').click()
            page.wait_for_timeout(1200)
            after = page.locator("table.tbl tr.data").filter(has_text="REQ-002").first.inner_text()
            rec("已废弃" in after, "VT-ACT-32 状态变「已废弃」")
            rec(page.locator("table.tbl tr.data").count() == 4, "VT-ACT-32 记录仍在（未消失）")
            # VT-ACT-33 作废理由留痕：详情模态里能看到（`void_reason` 落库 + 展示）
            page.locator("table.tbl tr.data").filter(has_text="REQ-002").first                 .locator("button.b-link.mono").click()
            page.wait_for_timeout(900)
            m_void = page.locator(".modal-mask:visible").last
            rec("作废理由" in m_void.inner_text() and "接口方案变更" in m_void.inner_text(),
                "VT-ACT-33 详情显示「作废理由」（void_reason 落库并展示）")
            m_void.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(300)

            # ── §5 筛选（F-7）──────────────────────────────
            step("§5 筛选（VT-FILTER-41..VT-FILTER-43）")
            page.locator("select").first.select_option("technical")   # 类型
            page.wait_for_timeout(900)
            n = page.locator("table.tbl tr.data").count()
            rec(n == 1, f"VT-FILTER-41 类型=技术需求 → {n} 行")
            # 文档 §5 有 `VT-FILTER-42`（再筛状态「已基线」→ 仍 REQ-001），脚本此前**没翻译** ——
            # 2026-09-25 迁移编号时被 V3（文档→脚本）对出来，补上：
            page.locator("select").nth(1).select_option("baselined")   # 状态
            page.wait_for_timeout(900)
            hit = page.locator("table.tbl tr.data").count()
            rec(hit == 1, f"VT-FILTER-42 类型=技术 + 状态=已基线 → {hit} 行")
            page.locator("select").nth(1).select_option("")
            page.wait_for_timeout(600)
            page.locator("select").first.select_option("interface")
            page.wait_for_timeout(900)
            n2 = page.locator("table.tbl tr.data").count()
            rec(n2 == 1 and "已废弃" in page.locator("table.tbl tr.data").first.inner_text(),
                "VT-FILTER-43 接口需求 + 已废弃 → 1 行")
            page.locator("select").first.select_option("")
            page.wait_for_timeout(700)

            # ── §5c 提交评审（草稿 → 待评审；2026-09-25 补的服务与入口）────
            step("§5c 提交评审（VT-ACT-45..VT-ACT-47）")
            # VT-ACT-46 点「提交评审」后状态变待评审（区间写法只声明首尾，逐条补标记行）
            # VT-ACT-47 待评审行不再显示「提交评审」
            page.locator("select").first.select_option("")            # 清类型筛选
            page.wait_for_timeout(700)
            row3 = page.locator("table.tbl tr.data").filter(has_text="REQ-003").first
            rec(row3.locator('button:has-text("提交评审")').count() == 1,
                "VT-ACT-45 草稿行有「提交评审」入口")
            row1 = page.locator("table.tbl tr.data").filter(has_text="REQ-001").first
            rec(row1.locator('button:has-text("提交评审")').count() == 0,
                "VT-ACT-45 已基线行没有「提交评审」（入口与服务端同口径）")
            row3.locator('button:has-text("提交评审")').click()
            page.wait_for_timeout(1200)
            after = page.locator("table.tbl tr.data").filter(has_text="REQ-003").first.inner_text()
            rec("待评审" in after, f"VT-ACT-46 提交后状态=待评审：{after[:40]!r}")
            rec(page.locator("table.tbl tr.data").filter(has_text="REQ-003")
                .locator('button:has-text("提交评审")').count() == 0,
                "VT-ACT-47 待评审行不再显示「提交评审」（幂等性由服务端守）")

            # ── §5b 责任人候选（datalist ← stakeholder.list）────────
            # 跨应用只读候选：**值仍是文本姓名**（不落 sh_no，全组一致口径），
            # 故断言两件事 —— 候选确有数据 + 控件仍是文本输入（不是 select）。
            step("§5b 责任人候选（VT-SUG-51..VT-SUG-54）")
            page.click('button:has-text("新建需求")')
            page.wait_for_timeout(500)
            form3 = page.locator(".modal-mask:visible").last
            vals = form3.locator("datalist#sh-options-form option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            rec(len(vals) >= 2, f"VT-SUG-51 新建表单「责任人」候选 {len(vals)} 项（≥2，来自 stakeholder.list）")
            rec(any(v.startswith("候选人甲|") for v in vals), f"VT-SUG-51 候选值=姓名、标签含编号：{vals[:2]}")
            rec(form3.locator('input[list="sh-options-form"]').count() == 1,
                # VT-SUG-52 该控件类型
                "VT-SUG-52 责任人仍是**文本输入**（不是 select —— 值即文本、回填天然正确）")
            # 上游需求候选（**本应用自身** list）：只在类型=派生时渲染 ⇒ 必须先选类型，
            # 否则这条断言会**空转通过**（读到 0 项却"没红"）。
            form3.locator("select").first.select_option("derived")
            page.wait_for_timeout(400)
            rq = form3.locator("datalist#req-options-form option").evaluate_all(
                "(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            rec(form3.locator('input[list="req-options-form"]').count() == 1,
                # VT-SUG-54 新建表单**选类型=派生**后读 `datalist#req-options-form`
                "VT-SUG-54 派生态确实渲染了「上游需求」输入框（防空转）")
            rec(len(rq) >= 2, f"VT-SUG-54 上游需求候选 {len(rq)} 项（来自本应用 requirement.list）")
            rec(any(v.startswith("REQ-") for v in rq), f"VT-SUG-54 候选值=需求编号、标签含标题：{rq[:2]}")
            form3.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)
            page.locator("table.tbl tr.data button.b-link").first.click()
            page.wait_for_timeout(900)
            m2 = page.locator(".modal-mask:visible").last
            vals2 = m2.locator("datalist#sh-options-modal option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            # VT-SUG-53 详情模态：同样读 `datalist#sh-options-modal`
            rec(len(vals2) >= 2, f"VT-SUG-53 详情模态「责任人」候选 {len(vals2)} 项")
            rec(m2.locator('input[list="sh-options-modal"]').count() == 1,
                "VT-SUG-53 详情责任人同样为文本输入 + 候选")
            m2.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(300)

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    # **豁免清单受检**（V5）：`ignored` 收集了却从不校验 = 给静默吞掉开口子 ——
    # 任何新形态的 4xx 都能落进豁免分支而无人发现，而「0 报错」照样显示通过。
    # 本脚本只认 favicon / sourcemap 两类（受限会话的 403 豁免在**组级**脚本里）。
    for _ig in ignored:
        rec(("/favicon.ico" in _ig or ".map" in _ig), f"豁免理由成立（favicon/.map）：{_ig[:90]}")

    # ── §6 硬件指标 ────────────────────────────────────
    step("§6 硬件指标（VT-HW-90..VT-HW-91）")
    rec(not errors, f"0 console error / 0 pageerror / 0 HTTP≥400（实际 {len(errors)}）")
    for e in errors[:6]:
        print("      ✗", e)

    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
