"""e2e 前端验收 - nasa_pms:change_request（变更请求台账 · 独立创建）。

断言：提出入口存在 → 4 行（四态同屏）→ **F-1** 标题/申请方/影响范围三者齐备才可提交 →
**F-3** 编号为纯文本只读 → **F-4** 内容只在「已提交」可编辑（审批中禁用）→
**F-7** 影响分析非空才能提交 → **F-8** 审批意见未填则批准/拒绝都禁用 →
**F-9** 动作按钮按状态显隐（含终态行零动作）→ **F-10** 筛选收敛 →
全程 0 console error / 0 pageerror / 0 HTTP≥400。

用例来源：app/nasa_pms/change_request/前端测试用例.md（§0 造数 + §1..§6）。
运行：python app/nasa_pms/tests/verify_view_nasa_pms_change_request.py
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


# §0 自足造数：**本页是跨应用页** —— 影响范围必须落在真实存在的配置项 / 需求上，
# 故先造配置项与需求（走 REST，不经 UI），再造四态齐备的变更请求。
# ⚠ REST 路径必须用**组限定名** `nasa_pms/change_request`（短名 404「应用不存在」）。
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
  const REQ = "nasa_pms/requirement";
  const CR = "nasa_pms/change_request";
  // 影响范围的靶子：两个配置项（CI-001 已发布 / CI-002 受控）+ 两条需求
  await call(CI, "create", {name: "飞控软件", ci_type: "software", owner: "张三"});
  await call(CI, "create", {name: "接口控制文档", ci_type: "document", owner: "李四"});
  await call(CI, "control", {ci_no: "CI-001"});
  await call(CI, "release", {ci_no: "CI-001"});
  await call(REQ, "create", {title: "系统应支持 1000 并发用户", statement: "8vCPU/32GB 下 P95 ≤ 2s",
                             req_type: "technical", verify_method: "test"});
  await call(REQ, "create", {title: "接口应符合 ICD-001", statement: "数据项与 ICD-001 一致",
                             req_type: "interface", verify_method: "inspection"});
  // CR-001 已提交（张三）
  await call(CR, "create", {title: "飞控软件并发指标上调", requester: "张三",
                            ci_nos: ["CI-001"], req_nos: ["REQ-001"],
                            description: "并发指标 1000 → 1200"});
  // CR-002 审批中（李四）
  await call(CR, "create", {title: "接口定义调整", requester: "李四", ci_nos: ["CI-002"]});
  await call(CR, "analyze", {cr_no: "CR-002", impact_analysis: "只影响 ICD 文档，改动量小"});
  await call(CR, "submit_review", {cr_no: "CR-002"});
  // CR-003 已批准（张三）
  await call(CR, "create", {title: "需求正文补充验证口径", requester: "张三",
                            ci_nos: ["CI-001"], req_nos: ["REQ-001"]});
  await call(CR, "analyze", {cr_no: "CR-003", impact_analysis: "只补正文措辞"});
  await call(CR, "submit_review", {cr_no: "CR-003"});
  await call(CR, "approve", {cr_no: "CR-003", comment: "CCB 通过", approver: "CCB-主席"});
  // CR-004 已拒绝（李四）
  await call(CR, "create", {title: "临时取消接口评审", requester: "李四", ci_nos: ["CI-002"]});
  await call(CR, "analyze", {cr_no: "CR-004", impact_analysis: "无实质影响"});
  await call(CR, "submit_review", {cr_no: "CR-004"});
  await call(CR, "reject", {cr_no: "CR-004", comment: "证据不足，退回补充", approver: "CCB-主席"});
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
            page.on("dialog", lambda d: d.accept())     # 提交审批的二次确认

            step("§0 造数（配置项 2 + 需求 2 + 变更请求 4，覆盖四态）")
            seed = page.evaluate(SEED_JS)
            rec(bool(seed and seed.get("seeded")),
                "CR-001 已提交 / CR-002 审批中 / CR-003 已批准 / CR-004 已拒绝")

            # ── §1 渲染与入口 ────────────────────────────────
            # VT-ROUTE-01 打开 `#/change_request`
            # VT-ROUTE-04 首行内容
            step("§1 渲染与入口（VT-ROUTE-01..VT-ROUTE-04）")
            page.evaluate("location.hash = '#/change_request'")
            page.wait_for_selector('button:has-text("提出变更")', timeout=10000)
            page.wait_for_timeout(800)
            body = page.locator("main").inner_text()
            rec("变更请求台账" in body, "VT-ROUTE-01 标题「变更请求台账」可见")
            rows = page.locator("table.tbl tr.data")
            rec(rows.count() == 4, f"VT-ROUTE-01 列表 {rows.count()} 行（期望 4）")
            heads = page.locator("table.tbl tr").first.inner_text()
            rec(all(h in heads for h in ("变更请求编号", "标题", "申请方", "影响的配置项", "影响的需求", "状态")),
                # VT-ROUTE-02 表头
                "VT-ROUTE-02 表头完整")
            # VT-ROUTE-03 **保留提出入口**
            rec(page.locator('button:has-text("提出变更")').count() > 0, "VT-ROUTE-03 保留提出入口")
            r1 = page.locator("table.tbl tr.data").filter(has_text="CR-001").first
            # ⚠ 状态断言定位到徽标本身（data-role）：行文本里含按钮文字（「提交影响分析」含「提交」…），
            #    `"已提交" in row.inner_text()` 这类断言会被按钮文本干扰而假过
            rec(r1.locator('[data-role="cr-status"]').inner_text() == "已提交"
                and r1.locator('[data-role="row-ci"]').inner_text() == "CI-001"
                and r1.locator('[data-role="row-req"]').inner_text() == "REQ-001",
                "VT-ROUTE-04 首行：已提交 / CI-001 / REQ-001")

            # ── §2 提出变更表单（F-1 / F-2）────────────────────
            # VT-FORM-11 打开提出
            # VT-FORM-16 关掉重开
            step("§2 提出变更表单（VT-FORM-11..VT-FORM-16）")
            page.click('button:has-text("提出变更")')
            page.wait_for_timeout(400)
            form = page.locator(".modal-mask:visible").last
            rec(form.locator("select").count() == 2, "VT-FORM-11 提出模态出现，影响范围是两个多选下拉")
            submit = form.locator('button:has-text("提交")')
            # VT-FORM-12 全空
            rec(submit.is_disabled(), "VT-FORM-12 全空 → 提交 disabled")
            form.locator("input").first.fill("临时变更")
            form.locator("input").nth(1).fill("王五")
            page.wait_for_timeout(250)
            # VT-FORM-13 标题 + 申请方齐备、**范围仍空**
            rec(submit.is_disabled(), "VT-FORM-13 标题+申请方齐备、影响范围仍空 → 仍 disabled（BR-01）")
            form.locator("select").first.select_option(["CI-001"])
            page.wait_for_timeout(300)
            # VT-FORM-14 选中一个影响配置项
            rec(not submit.is_disabled(), "VT-FORM-14 选中影响配置项 → 可提交")
            submit.click()
            page.wait_for_timeout(1200)
            # VT-FORM-15 点提交
            rec(page.locator("table.tbl tr.data").count() == 5, "VT-FORM-15 提交成功，列表变 5 行")
            page.click('button:has-text("提出变更")')
            page.wait_for_timeout(400)
            form2 = page.locator(".modal-mask:visible").last
            rec(form2.locator("input").first.input_value() == ""
                and form2.locator("select").first.evaluate("el => el.selectedOptions.length") == 0,
                "VT-FORM-16 表单已重置（含多选）")
            form2.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)

            # ── §3 详情 / 编辑（F-3 / F-4）────────────────────
            # VT-MODAL-21 点 `CR-001`（已提交）的「编辑」
            # VT-MODAL-24 关闭模态
            step("§3 详情与编辑（VT-MODAL-21..VT-MODAL-24）")
            # CR-001 已提交 → 可编辑
            row1 = page.locator("table.tbl tr.data").filter(has_text="CR-001").first
            row1.locator('button:text-is("编辑")').click()
            page.wait_for_timeout(900)
            m = page.locator(".modal-mask:visible").last
            rec(not m.locator("input").first.is_disabled(), "VT-MODAL-21 已提交 → 标题可编辑")
            rec(m.locator("select").count() == 2, "VT-MODAL-21 编辑态出现两个多选下拉（影响范围可改）")
            m.locator('button:text-is("关闭")').first.click()
            page.wait_for_timeout(400)
            # CR-002 审批中 → 内容锁定（BR-06）
            row2 = page.locator("table.tbl tr.data").filter(has_text="CR-002").first
            row2.locator('button:text-is("详情")').click()
            page.wait_for_timeout(900)
            m = page.locator(".modal-mask:visible").last
            rec(m.locator("input").first.is_disabled() and m.locator("textarea").first.is_disabled(),
                # VT-MODAL-22 点 `CR-002`（审批中）的「详情」
                "VT-MODAL-22 审批中 → 标题与变更说明均 disabled（BR-06）")
            rec(m.locator('[data-role="scope-ci"]').count() == 1
                and m.locator('[data-role="scope-ci"]').inner_text() == "CI-002",
                "VT-MODAL-22 只读态影响范围是纯文本 CI-002（不是 select）")
            # F-3：编号是纯文本（无输入框承载它）
            n_input = m.locator("input").evaluate_all(
                "els => els.filter(e => e.value === 'CR-002').length")
            rec(n_input == 0 and "CR-002" in m.locator('[data-role="cr-head"]').inner_text(),
                # VT-MODAL-23 **F-3 编号只读**
                "VT-MODAL-23 编号 CR-002 以纯文本回显（无输入框，BR-03）")
            m.locator('button:text-is("关闭")').first.click()
            page.wait_for_timeout(400)
            rec(page.locator("table.tbl tr.data").count() == 5, "VT-MODAL-24 关闭后列表未变")

            # ── §4 状态机动作（F-6 / F-7 / F-8 / F-9）──────────
            # VT-ACT-31 **F-6 按钮按状态显隐**
            # VT-ACT-40 **F-9 终态行**
            step("§4 状态机动作（VT-ACT-31..VT-ACT-40）")
            # ⚠ 动作按钮用 x-show 隐藏（display:none 但仍在 DOM）⇒ 计数必须带 `:visible`，
            #   否则隐藏按钮照样被 count() 数到，断言永远假红
            r1 = page.locator("table.tbl tr.data").filter(has_text="CR-001").first
            r3 = page.locator("table.tbl tr.data").filter(has_text="CR-003").first
            r4 = page.locator("table.tbl tr.data").filter(has_text="CR-004").first
            rec(r1.locator('button:text-is("提交影响分析"):visible').count() == 1
                and r1.locator('button:text-is("审批"):visible').count() == 0
                and r1.locator('button:text-is("实施"):visible').count() == 0,
                "VT-ACT-31 已提交行：有「提交影响分析」，无「审批」「实施」")
            rec(r3.locator('button:text-is("实施"):visible').count() == 1
                and r3.locator('button:text-is("提交影响分析"):visible').count() == 0,
                "VT-ACT-31 已批准行：有「实施」无「提交影响分析」")
            rec(all(r4.locator(f'button:text-is("{t}"):visible').count() == 0
                    for t in ("编辑", "提交影响分析", "提交审批", "审批", "实施")),
                "VT-ACT-31 已拒绝行：动作按钮全隐（终态 BR-04）")
            # F-7：影响分析模态
            r1.locator('button:text-is("提交影响分析"):visible').click()
            page.wait_for_timeout(700)
            m = page.locator(".modal-mask:visible").last
            a_ok = m.locator('button:text-is("提交影响分析")')
            # VT-ACT-33 点 `CR-001`「提交影响分析」
            rec(a_ok.is_disabled(), "VT-ACT-33 影响分析为空 → 提交 disabled（BR-02）")
            m.locator('textarea[placeholder*="改动波及"]').fill("影响 CI-001 与 REQ-001 的验证用例")
            page.wait_for_timeout(300)
            # VT-ACT-34 填写影响分析 → 提交
            rec(not a_ok.is_disabled(), "VT-ACT-34 填了影响分析 → 可提交")
            a_ok.click()
            page.wait_for_timeout(1200)
            r1 = page.locator("table.tbl tr.data").filter(has_text="CR-001").first
            rec(r1.locator('[data-role="cr-status"]').inner_text() == "影响分析",
                "VT-ACT-34 CR-001 → 影响分析")
            # 提交审批（单键动作 + 二次确认，已在会话上注册 accept）
            r1.locator('button:text-is("提交审批"):visible').click()
            page.wait_for_timeout(1200)
            r1 = page.locator("table.tbl tr.data").filter(has_text="CR-001").first
            rec(r1.locator('[data-role="cr-status"]').inner_text() == "审批中"
                and r1.locator('button:text-is("审批"):visible').count() == 1,
                # VT-ACT-35 点「提交审批」（二次确认）
                "VT-ACT-35 CR-001 → 审批中，出现「审批」")
            # F-8：审批意见未填，批准与拒绝都禁用
            r1.locator('button:text-is("审批"):visible').click()
            page.wait_for_timeout(700)
            m = page.locator(".modal-mask:visible").last
            ok_btn = m.locator('button:text-is("确认批准")')
            no_btn = m.locator('button:text-is("确认拒绝")')
            rec(ok_btn.is_disabled() and no_btn.is_disabled(),
                # VT-ACT-36 点「审批」
                "VT-ACT-36 审批意见为空 → 「确认批准」「确认拒绝」都 disabled（BR-02）")
            m.locator('textarea[placeholder*="批准或拒绝"]').fill("CCB 2026-09 第 3 次会议通过")
            page.wait_for_timeout(300)
            # VT-ACT-37 填写审批意见
            rec(not ok_btn.is_disabled() and not no_btn.is_disabled(), "VT-ACT-37 填意见 → 两键均可点")
            ok_btn.click()
            page.wait_for_timeout(1200)
            r1 = page.locator("table.tbl tr.data").filter(has_text="CR-001").first
            rec(r1.locator('[data-role="cr-status"]').inner_text() == "已批准"
                and r1.locator('button:text-is("实施"):visible').count() == 1,
                # VT-ACT-38 点「确认批准」
                "VT-ACT-38 CR-001 → 已批准，出现「实施」")
            # 实施（终态）
            r1.locator('button:text-is("实施"):visible').click()
            page.wait_for_timeout(700)
            m = page.locator(".modal-mask:visible").last
            m.locator('input[placeholder*="版本变更"]').fill("CI-001 已在配置项侧变更到 v2")
            m.locator('button:text-is("确认实施")').click()
            page.wait_for_timeout(1200)
            r1 = page.locator("table.tbl tr.data").filter(has_text="CR-001").first
            rec(r1.locator('[data-role="cr-status"]').inner_text() == "已实施",
                # VT-ACT-39 点「实施」→「确认实施」
                "VT-ACT-39 CR-001 → 已实施")
            rec(all(r1.locator(f'button:text-is("{t}"):visible').count() == 0
                    for t in ("编辑", "提交影响分析", "提交审批", "审批", "实施"))
                and r1.locator('button:text-is("详情"):visible').count() == 1,
                "VT-ACT-40 已实施是终态：只剩「详情」")

            # ── §5 筛选（F-10）───────────────────────────────
            # VT-FILTER-61 状态筛「已拒绝」
            # VT-FILTER-63 清配置项，申请方填「张三」回车
            step("§5 筛选（VT-FILTER-61..VT-FILTER-63）")
            fsel = page.locator("main .card").first.locator("select")
            fsel.nth(0).select_option("rejected")          # 状态
            page.wait_for_timeout(900)
            n = page.locator("table.tbl tr.data").count()
            rec(n == 1 and "CR-004" in page.locator("table.tbl tr.data").first.inner_text(),
                f"VT-FILTER-61 状态=已拒绝 → {n} 行")
            fsel.nth(0).select_option("")                  # 清状态
            page.wait_for_timeout(600)
            fsel.nth(1).select_option("CI-002")            # 影响配置项
            page.wait_for_timeout(900)
            n2 = page.locator("table.tbl tr.data").count()
            # VT-FILTER-62 清状态，影响配置项筛 `CI-002`
            rec(n2 == 2, f"VT-FILTER-62 影响配置项=CI-002 → {n2} 行（CR-002 / CR-004）")
            fsel.nth(1).select_option("")                  # 清配置项
            page.wait_for_timeout(600)
            fin = page.locator("main .card").first.locator('input[placeholder*="申请方"]')
            fin.fill("张三")
            fin.press("Enter")
            page.wait_for_timeout(900)
            n3 = page.locator("table.tbl tr.data").count()
            rec(n3 == 2, f"VT-FILTER-63 申请方=张三 → {n3} 行（CR-001 / CR-003）")
            fin.fill("")
            fin.press("Enter")
            page.wait_for_timeout(600)

            # ── §6b 申请方候选（datalist ← stakeholder.list）────────
            # 跨应用只读候选：**值仍是文本姓名**（不落 sh_no，全组一致口径），
            # 故断言两件事 —— 候选确有数据 + 控件仍是文本输入（不是 select）。
            # VT-SUG-64 新建表单：读 `datalist#sh-options-form` 选项
            # VT-SUG-65 控件类型 + 详情模态候选
            step("§6b 申请方候选（VT-SUG-64..VT-SUG-65）")
            page.click('button:has-text("提出变更")')
            page.wait_for_timeout(500)
            f3 = page.locator(".modal-mask:visible").last
            vals = f3.locator("datalist#sh-options-form option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            rec(len(vals) >= 2, f"VT-SUG-64 新建表单「申请方」候选 {len(vals)} 项（≥2，来自 stakeholder.list）")
            rec(any(v.startswith("候选人甲|") for v in vals), f"VT-SUG-64 候选值=姓名、标签含编号：{vals[:2]}")
            rec(f3.locator('input[list="sh-options-form"]').count() == 1,
                "VT-SUG-65 申请方仍是**文本输入**（不是 select —— 值即文本、回填天然正确）")
            f3.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)
            page.locator("table.tbl tr.data button.b-link").first.click()
            page.wait_for_timeout(900)
            m2 = page.locator(".modal-mask:visible").last
            vals2 = m2.locator("datalist#sh-options-modal option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            rec(len(vals2) >= 2, f"VT-SUG-65 详情模态「申请方」候选 {len(vals2)} 项")
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
    # VT-HW-90 全程 console / pageerror
    # VT-HW-91 全程 HTTP 状态
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
