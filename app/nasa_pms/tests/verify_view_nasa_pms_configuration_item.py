"""e2e 前端验收 - nasa_pms:configuration_item（配置项台账 · 独立创建）。

断言：登记入口存在（与只读台账相反）→ 列表 3 行 → **F-1** 名称/类型未选则提交禁用 →
**F-2/F-3** 当前版本与编号为纯文本只读 → **F-4** 已发布配置项内容锁定、填变更号解锁 →
**F-8** 版本变更模态（新版本须大于当前 + 变更号必填）→ **F-9** 动作按钮按状态显隐 →
**F-6** 归档二次确认且记录保留 → **F-7** 筛选收敛 →
全程 0 console error / 0 pageerror / 0 HTTP≥400。

用例来源：app/nasa_pms/configuration_item/前端测试用例.md（§0 造数 + §1..§7）。
运行：python app/nasa_pms/tests/verify_view_nasa_pms_configuration_item.py
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
# 其后用例也不再执行 —— 实测 nasa_pms 的 stakeholder 脚本里有一条断言就这么"消失"过）。与 scripts/run_gates.py 给
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


# §0 自足造数：3 个配置项（覆盖 draft / controlled / released 三态）
# 走 REST，不经 UI —— 避免用例依赖"登记功能本身"（那是 §2 的覆盖对象）。
# ⚠ REST 路径必须用**组限定名** `nasa_pms/configuration_item`（短名 404「应用不存在」）。
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
  const CI = "nasa_pms/configuration_item";
  await call(CI, "create", {name: "飞控软件", ci_type: "software", owner: "张三"});
  await call(CI, "create", {name: "系统规范", ci_type: "document", owner: "李四"});
  await call(CI, "create", {name: "仿真模型", ci_type: "model"});
  await call(CI, "control", {ci_no: "CI-001"});
  await call(CI, "assign_baseline", {ci_no: "CI-001", baseline: "product", baseline_ver: "B1"});
  await call(CI, "release", {ci_no: "CI-001"});
  await call(CI, "control", {ci_no: "CI-002"});
  await call("nasa_pms/stakeholder", "upsert", {sh_no: "SH-EX1", name: "候选人甲", sh_type: "customer"});
  await call("nasa_pms/stakeholder", "upsert", {sh_no: "SH-EX2", name: "候选人乙", sh_type: "internal_org"});
  await call("nasa_pms/change_request", "create", {title: "候选变更甲", requester: "候选人甲", ci_nos: ["CI-001"]});   // BR-01：变更必须至少指定一个受影响配置项
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

            step("§0 造数（3 个配置项：已发布 / 受控 / 草稿）")
            seed = page.evaluate(SEED_JS)
            rec(bool(seed and seed.get("seeded")), "CI-001 已发布 / CI-002 受控 / CI-003 草稿")

            # ── §1 渲染与入口 ────────────────────────────────
            step("§1 渲染与入口（VT-ROUTE-01..VT-ROUTE-04）")
            page.evaluate("location.hash = '#/configuration_item'")
            page.wait_for_selector('button:has-text("登记配置项")', timeout=10000)
            page.wait_for_timeout(800)
            body = page.locator("main").inner_text()
            rec("配置项台账" in body, "VT-ROUTE-01 标题「配置项台账」可见")
            rows = page.locator("table.tbl tr.data")
            rec(rows.count() == 3, f"VT-ROUTE-01 列表 {rows.count()} 行（期望 3）")
            heads = page.locator("table.tbl tr").first.inner_text()
            rec(all(h in heads for h in ("配置项编号", "名称", "类型", "当前版本", "所属基线", "状态", "责任人")),
                # VT-ROUTE-02 表头
                "VT-ROUTE-02 表头完整")
            # VT-ROUTE-03 **保留登记入口**
            rec(page.locator('button:has-text("登记配置项")').count() > 0, "VT-ROUTE-03 保留登记入口")
            first = rows.first.inner_text()
            rec("软件" in first and "v1" in first and "产品基线" in first and "已发布" in first,
                "VT-ROUTE-04 首行显示 软件/v1/产品基线/已发布")

            # ── §2 登记表单（F-1）─────────────────────────────
            step("§2 登记表单（VT-FORM-11..VT-FORM-15）")
            page.click('button:has-text("登记配置项")')
            page.wait_for_timeout(400)
            form = page.locator(".modal-mask:visible").last
            rec(form.locator("select").count() > 0, "VT-FORM-11 登记模态出现")
            submit = form.locator('button:has-text("提交")')
            # VT-FORM-12 **F-1 名称为空**
            rec(submit.is_disabled(), "VT-FORM-12 名称空 → 提交 disabled")
            form.locator("input").first.fill("临时配置项A")
            page.wait_for_timeout(250)
            # VT-FORM-13 只填名称、类型未选
            rec(submit.is_disabled(), "VT-FORM-13 类型未选 → 仍 disabled（F-1 类型必选）")
            form.locator("select").first.select_option("data")
            page.wait_for_timeout(300)
            # VT-FORM-14 名称+类型齐备 → 提交
            rec(not submit.is_disabled(), "VT-FORM-14 名称+类型齐备 → 可提交")
            submit.click()
            page.wait_for_timeout(1200)
            rec(page.locator("table.tbl tr.data").count() == 4, "VT-FORM-14 登记成功，列表变 4 行")
            page.click('button:has-text("登记配置项")')
            page.wait_for_timeout(400)
            form2 = page.locator(".modal-mask:visible").last
            rec(form2.locator("input").first.input_value() == "", "VT-FORM-15 表单已重置")
            form2.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)

            # ── §3 详情 / 编辑（F-2 / F-3 / F-4）─────────────
            step("§3 详情与编辑（VT-MODAL-22..VT-MODAL-25）")
            # CI-001 已发布 → 内容锁定（BR-02）
            row1 = page.locator("table.tbl tr.data").filter(has_text="CI-001").first
            row1.locator('button:has-text("编辑")').click()
            page.wait_for_timeout(900)
            m = page.locator(".modal-mask:visible").last
            # VT-MODAL-22 点 `CI-001`（已发布）编辑
            rec(m.locator("input").first.is_disabled(), "VT-MODAL-22 已发布 → 名称 disabled")
            rec(m.locator("select").last.is_disabled(), "VT-MODAL-22 已发布 → 类型 disabled")
            rec(m.locator('input[placeholder*="CR-"]').count() > 0, "VT-MODAL-22 出现变更号输入框")
            m.locator('input[placeholder*="CR-"]').fill("CR-001")
            page.wait_for_timeout(400)
            # VT-MODAL-23 已发布时填变更号 `CR-001`
            rec(not m.locator("input").first.is_disabled(), "VT-MODAL-23 填变更号 → 名称解锁")
            # F-2/F-3：当前版本与编号是纯文本只读（在网格里是 div，不是 input）
            rec(m.locator('input[placeholder*="CR-"]').count() == 1, "变更号输入框唯一")
            # VT-MODAL-24 **F-2 版本只读 / F-3 编号只读**
            rec(m.locator('input[type="number"]').count() == 0, "VT-MODAL-24 当前版本非数字输入框（纯文本只读）")
            rec("CI-001" in m.inner_text() and "v1" in m.inner_text(), "VT-MODAL-24 编号与版本以文本回显")
            m.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(400)
            # VT-MODAL-25 关闭模态
            rec(page.locator("table.tbl tr.data").count() == 4, "VT-MODAL-25 关闭后列表未变")

            # ── §4 状态机动作（F-8 / F-9）─────────────────────
            step("§4 状态机动作（VT-ACT-31..VT-ACT-37）")
            # F-9：按钮按状态显隐（⚠ 动作按钮用 x-show 隐藏 → 计数必须带 `:visible`，
            #     否则 display:none 的元素照样被 count() 数到，断言永远假红）
            r1 = page.locator("table.tbl tr.data").filter(has_text="CI-001").first
            r3 = page.locator("table.tbl tr.data").filter(has_text="CI-003").first
            rec(r1.locator('button:has-text("归档"):visible').count() == 1
                and r1.locator('button:has-text("发版"):visible').count() == 0,
                "VT-ACT-31 已发布行：有「归档」无「发版」")
            rec(r3.locator('button:has-text("提交受控"):visible').count() == 1
                and r3.locator('button:has-text("归档"):visible').count() == 0,
                "VT-ACT-31 草稿行：有「提交受控」无「归档」")
            # 提交受控：草稿 → 受控
            r3.locator('button:has-text("提交受控"):visible').click()
            page.wait_for_timeout(1200)
            r3 = page.locator("table.tbl tr.data").filter(has_text="CI-003").first
            # VT-ACT-32 点 `CI-003`（草稿）的「提交受控」
            rec("受控" in r3.inner_text(), "VT-ACT-32 CI-003 → 已受控")
            rec(r3.locator('button:has-text("发版"):visible').count() == 1, "VT-ACT-32 受控行出现「发版」")
            # F-8：版本变更模态 —— 新版本须大于当前版本（BR-01）+ 变更号必填（BR-03）
            r2 = page.locator("table.tbl tr.data").filter(has_text="CI-002").first
            r2.locator('button:has-text("版本变更")').click()
            page.wait_for_timeout(600)
            am = page.locator(".modal-mask:visible").last
            # VT-ACT-33 点 `CI-002`（受控）的「版本变更」
            rec(am.locator('input[type="number"]').count() == 1, "VT-ACT-33 版本变更模态出现（含新版本号）")
            a_submit = am.locator('button:has-text("提交")')
            rec(a_submit.is_disabled(), "VT-ACT-33 变更号未填 → 提交 disabled（BR-03）")
            am.locator('input[type="number"]').fill("1")
            am.locator('input[placeholder*="CR-"]').fill("CR-002")
            page.wait_for_timeout(300)
            # VT-ACT-34 新版本号填 `1`（不大于当前 v1）
            rec(a_submit.is_disabled(), "VT-ACT-34 新版本 v1 不大于当前 v1 → 仍 disabled（BR-01）")
            am.locator('input[type="number"]').fill("2")
            page.wait_for_timeout(300)
            # VT-ACT-35 新版本号填 `2` + 变更号 `CR-002`
            rec(not a_submit.is_disabled(), "VT-ACT-35 新版本 v2 + 变更号 → 可提交")
            a_submit.click()
            page.wait_for_timeout(1200)
            r2 = page.locator("table.tbl tr.data").filter(has_text="CI-002").first
            t2 = r2.inner_text()
            # VT-ACT-36 提交后
            rec("v2" in t2 and "受控" in t2, "VT-ACT-36 版本变 v2 且状态回落「受控」")
            # 纳入基线：CI-002 → 功能基线
            r2.locator('button:has-text("纳入基线")').click()
            page.wait_for_timeout(600)
            bm = page.locator(".modal-mask:visible").last
            bm.locator("select").first.select_option("functional")
            bm.locator('input[placeholder*="B1"]').fill("B2")
            page.wait_for_timeout(300)
            bm.locator('button:has-text("提交")').click()
            page.wait_for_timeout(1200)
            r2 = page.locator("table.tbl tr.data").filter(has_text="CI-002").first
            rec("功能基线" in r2.inner_text() and "B2" in r2.inner_text(),
                # VT-ACT-37 点「纳入基线」→ 选功能基线 + `B2`
                "VT-ACT-37 CI-002 纳入功能基线 B2")

            # ⚠ 本段必须在 §5「归档」**之前**跑：变更号输入框只在 `mode==='edit' &&
            #   status==='released'` 时渲染，而 §5 会把 CI-001 归档 ⇒ 那之后再断言必然空转。
            # ── §6b 变更号 / 责任人候选（datalist ← change_request.list / stakeholder.list）──
            step("§6b 变更号与责任人候选（VT-SUG-64..VT-SUG-66）")
            page.click('button:has-text("登记配置项")')
            page.wait_for_timeout(500)
            f3 = page.locator(".modal-mask:visible").last
            sh = f3.locator("datalist#sh-options-form option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            rec(len(sh) >= 2, f"VT-SUG-64 新建表单「责任人」候选 {len(sh)} 项（来自 stakeholder.list）")
            rec(f3.locator('input[list="sh-options-form"]').count() == 1
                and f3.locator('input[list="cr-options-modal"]').count() == 0,
                "VT-SUG-64 责任人仍是**文本输入**（不是 select）")
            f3.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)
            # 变更号输入框（modal.changeNo）**只在编辑态且已发布**时渲染 —— 必须真的进编辑态，
            # 否则这条断言会**空转通过**（实测踩到：走详情态时它读到 0 项却"通过"了）。
            row_ci = page.locator("table.tbl tr.data").filter(has_text="CI-001").first
            row_ci.locator('button:has-text("编辑")').click()
            page.wait_for_timeout(900)
            m2 = page.locator(".modal-mask:visible").last
            cr_box = m2.locator("input[list='cr-options-modal']")
            cr = m2.locator("datalist#cr-options-modal option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            # VT-SUG-65 编辑态变更号框：读 `datalist#cr-options-modal`
            rec(cr_box.count() == 1, "VT-SUG-65 已发布配置项的**编辑态**确实渲染了变更号输入框（防空转）")
            rec(len(cr) >= 1, f"VT-SUG-65 变更号候选 {len(cr)} 项（来自 change_request.list）")
            rec(any(v.startswith("CR-") for v in cr), f"VT-SUG-65 候选值=变更单号、标签含标题：{cr[:2]}")
            m2.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(300)


            # ── §5 归档（F-6）─────────────────────────────
            step("§5 归档（VT-ACT-51..VT-ACT-53）")
            page.on("dialog", lambda d: d.accept())     # 二次确认
            row1 = page.locator("table.tbl tr.data").filter(has_text="CI-001").first
            row1.locator('button:has-text("归档")').click()
            page.wait_for_timeout(1400)
            after = page.locator("table.tbl tr.data").filter(has_text="CI-001").first
            # VT-ACT-52 确认后
            rec("已归档" in after.inner_text(), "VT-ACT-52 状态变「已归档」")
            rec(page.locator("table.tbl tr.data").count() == 4, "VT-ACT-52 记录仍在（未消失）")
            rec(after.locator('button:has-text("归档"):visible').count() == 0
                and after.locator('button:has-text("版本变更"):visible').count() == 0
                and after.locator('button:has-text("纳入基线"):visible').count() == 0,
                "VT-ACT-53 已归档行不再显示「归档」「版本变更」「纳入基线」（终态）")

            # ── §6 筛选（F-7）──────────────────────────────
            step("§6 筛选（VT-FILTER-61..VT-FILTER-63）")
            page.locator("select").first.select_option("document")     # 类型
            page.wait_for_timeout(900)
            n = page.locator("table.tbl tr.data").count()
            rec(n == 1 and "CI-002" in page.locator("table.tbl tr.data").first.inner_text(),
                f"VT-FILTER-61 类型=文档 → {n} 行")
            page.locator("select").first.select_option("")             # 清类型
            page.wait_for_timeout(600)
            page.locator("select").nth(1).select_option("archived")    # 状态
            page.wait_for_timeout(900)
            n2 = page.locator("table.tbl tr.data").count()
            rec(n2 == 1 and "CI-001" in page.locator("table.tbl tr.data").first.inner_text(),
                # VT-FILTER-62 清类型，状态筛「已归档」
                f"VT-FILTER-62 状态=已归档 → {n2} 行")
            page.locator("select").nth(1).select_option("")            # 清状态
            page.wait_for_timeout(600)
            page.locator("select").nth(2).select_option("product")     # 基线
            page.wait_for_timeout(900)
            n3 = page.locator("table.tbl tr.data").count()
            rec(n3 == 1 and "CI-001" in page.locator("table.tbl tr.data").first.inner_text(),
                f"VT-FILTER-63 基线=产品基线 → {n3} 行")
            page.locator("select").nth(2).select_option("")
            page.wait_for_timeout(600)


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

    # ── §7 硬件指标 ────────────────────────────────────
    step("§7 硬件指标（VT-HW-90..VT-HW-91）")
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
