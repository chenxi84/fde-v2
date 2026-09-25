"""e2e 前端验收 - nasa_pms:review（评审台账 · 独立创建 + 聚合内子表 + 跨评审查询视图）。

断言：新建入口存在 → 列表 4 行（计划 / 行动项跟踪中 / 已关闭 三态同屏）→
**F-1** 四项必填未齐则提交禁用 → **F-2** 计划态先启动才能出结论 →
**F-3/F-4** 出结论（结论必选 + 有条件通过必须有行动项 + 行动项行必须填全）→
**F-5** 已结论后内容冻结（无保存按钮、加评审项入口消失）→
**F-6** 行动项汇总（查询视图）按状态收敛 + 行内「完成」→
**F-7** 行动项未清零时关闭按钮禁用并给出原因 → **F-8** 筛选收敛 →
**F-9** 动作按钮按状态显隐。
全程 0 console error / 0 pageerror / 0 HTTP≥400。

用例来源：app/nasa_pms/review/前端测试用例.md（§0 造数 + §1..§8）。
运行：python app/nasa_pms/tests/verify_view_nasa_pms_review.py
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
# 个人 UI 偏好是本机状态（如"手动隐藏过某列"）——不清会让列显隐取决于谁在哪台机器上跑过。
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


# §0 自足造数：4 次评审（**计划 / 行动项跟踪中 ×2 / 已关闭** 四态同屏）+ 4 条行动项。
# 走 REST，不经 UI —— 避免用例依赖"新建功能本身"（那是 §2 的覆盖对象）。
# ⚠ REST 路径必须用**组限定名** `nasa_pms/review`（短名 404「应用不存在」）。
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
  const RV = "nasa_pms/review";
  await call(RV, "create", {title: "飞控软件详细设计评审", review_type: "cdr", phase: "c",
                            subject: "飞控软件详细设计", plan_no: "SDP-002", owner: "王五"});
  await call(RV, "create", {title: "飞控系统需求评审", review_type: "srr", phase: "a",
                            subject: "飞控系统需求规格", owner: "李四"});
  await call(RV, "create", {title: "飞控软件测试就绪评审", review_type: "trr", phase: "d",
                            subject: "飞控软件测试方案"});
  await call(RV, "create", {title: "任务概念评审", review_type: "mcr", phase: "pre_a",
                            subject: "任务概念"});
  // RV-001：有条件通过 + 1 条未完成行动项 ⇒ 「行动项跟踪中」
  await call(RV, "add_item", {review_no: "RV-001", item: "气动模型与实测一致", criterion: "偏差 < 5%"});
  await call(RV, "start", {review_no: "RV-001"});
  await call(RV, "conclude", {review_no: "RV-001", conclusion: "conditional",
                              minutes: "2 项通过、1 项留整改",
                              actions: [{content: "重做气动分析", owner: "王五", due_date: "2026-11-15"}]});
  // RV-002：不通过 → 行动项完成后关闭 ⇒ 「已关闭」
  await call(RV, "add_item", {review_no: "RV-002", item: "需求覆盖率", criterion: "基线需求 100% 覆盖"});
  await call(RV, "start", {review_no: "RV-002"});
  await call(RV, "conclude", {review_no: "RV-002", conclusion: "fail",
                              actions: [{content: "补需求追溯矩阵", owner: "李四", due_date: "2026-10-31"}]});
  await call(RV, "close_action", {review_no: "RV-002", seq: 1});
  await call(RV, "close", {review_no: "RV-002", note: "整改闭环"});
  // RV-003：不通过 + 2 条未完成行动项 ⇒ 「行动项跟踪中」（跨评审汇总有多行）
  await call(RV, "add_item", {review_no: "RV-003", item: "测试环境就绪"});
  await call(RV, "start", {review_no: "RV-003"});
  await call(RV, "conclude", {review_no: "RV-003", conclusion: "fail",
                              actions: [{content: "补齐测试台架", owner: "张三", due_date: "2026-12-01"},
                                        {content: "补充测试用例", owner: "李四", due_date: "2026-12-15"}]});
  // RV-004 不处理 ⇒ 「计划」
  await call("nasa_pms/stakeholder", "upsert", {sh_no: "SH-EX1", name: "候选人甲", sh_type: "customer"});
  await call("nasa_pms/stakeholder", "upsert", {sh_no: "SH-EX2", name: "候选人乙", sh_type: "internal_org"});
  await call("nasa_pms/tech_plan", "create", {name: "候选计划甲", plan_type: "semp", phase: "b"});
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

            step("§0 造数（4 次评审：计划 / 跟踪中 ×2 / 已关闭）")
            seed = page.evaluate(SEED_JS)
            rec(bool(seed and seed.get("seeded")),
                "RV-001/003 跟踪中 · RV-002 已关闭 · RV-004 计划")

            def rows():
                return page.locator("table.tbl tr.data")

            def row(no):
                return page.locator("table.tbl tr.data").filter(has_text=no).first

            def open_detail(no, mode="view"):
                row(no).locator('button:has-text("详情")' if mode == "view"
                                else 'button:has-text("编辑")').click()
                page.wait_for_timeout(900)
                return page.locator(".modal-mask:visible").last

            # ── §1 渲染与入口 ────────────────────────────────
            step("§1 渲染与入口（VT-ROUTE-01..VT-ROUTE-04）")
            page.evaluate("location.hash = '#/review'")
            page.wait_for_selector('button:has-text("新建评审")', timeout=10000)
            page.wait_for_timeout(900)
            rec(rows().count() == 4, f"VT-ROUTE-01 列表 {rows().count()} 行（期望 4）")
            heads = page.locator("table.tbl tr").first.inner_text()
            rec(all(h in heads for h in ("评审编号", "标题", "评审类型", "阶段", "评审对象",
                                         "状态", "结论", "行动项 未/总", "责任人")),
                # VT-ROUTE-02 表头完整性
                "VT-ROUTE-02 表头完整")
            rec(page.locator('button:has-text("新建评审"):visible').count() == 1,
                # VT-ROUTE-03 **保留新建入口**
                "VT-ROUTE-03 保留新建入口")
            t1 = row("RV-001").inner_text()
            rec("CDR" in t1 and "C 阶段" in t1 and "有条件通过" in t1 and "1/1" in t1
                and "行动项跟踪中" in t1,
                "VT-ROUTE-04 RV-001 行：CDR / C 阶段 / 有条件通过 / 行动项 1/1 / 跟踪中")
            t2 = row("RV-002").inner_text()
            rec("已关闭" in t2 and "不通过" in t2 and "0/1" in t2,
                "VT-ROUTE-04 RV-002 行：已关闭 / 不通过 / 行动项 0/1")
            rec("计划" in row("RV-004").inner_text(), "VT-ROUTE-04 RV-004 行：计划")

            # ── §2 新建评审（F-1）───────────────────────────
            step("§2 新建评审（VT-FORM-11..VT-FORM-15）")
            page.click('button:has-text("新建评审")')
            page.wait_for_timeout(500)
            form = page.locator(".modal-mask:visible").last
            rec(form.locator("select").count() == 2, "VT-FORM-11 新建模态出现（类型 + 阶段两个下拉）")
            submit = form.locator('button:has-text("提交")')
            # VT-FORM-12 **F-1 四项皆空**
            rec(submit.is_disabled(), "VT-FORM-12 四项必填皆空 → 提交 disabled")
            form.locator("input").first.fill("初始化评审")
            page.wait_for_timeout(200)
            # VT-FORM-13 只填标题 → 选类型与阶段 → 评审对象仍空
            rec(submit.is_disabled(), "VT-FORM-13 只填标题 → 仍 disabled（类型/阶段无默认值）")
            form.locator("select").nth(0).select_option("frr")
            form.locator("select").nth(1).select_option("e")
            page.wait_for_timeout(200)
            rec(submit.is_disabled(), "VT-FORM-13 评审对象仍空 → 仍 disabled")
            form.locator("input").nth(1).fill("飞行就绪条件")
            page.wait_for_timeout(300)
            # VT-FORM-14 四项齐备 → 提交
            rec(not submit.is_disabled(), "VT-FORM-14 四项齐备 → 可提交")
            submit.click()
            page.wait_for_timeout(1200)
            rec(rows().count() == 5, f"VT-FORM-14 新建成功，列表变 {rows().count()} 行")
            page.click('button:has-text("新建评审")')
            page.wait_for_timeout(500)
            form2 = page.locator(".modal-mask:visible").last
            rec(form2.locator("input").first.input_value() == "", "VT-FORM-15 表单已重置")
            form2.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)

            # ── §3 详情 / 评审项子表（F-2 / F-5 前置）────────
            step("§3 详情与评审项（VT-MODAL-21..VT-MODAL-25）")
            m = open_detail("RV-004", "view")
            head = m.locator('[data-role="review-head"]').inner_text()
            # ⚠ 只读信息条用 data-role 定位后单独取文本：整块 inner_text 会把 select 的
            #    全部 option 文本也吃进来，断言会假过（本用例集实测踩过）
            rec("RV-004" in head and "计划" in head and "行动项 0/0" in head,
                "VT-MODAL-21 只读信息条：RV-004 / 计划 / 行动项 0/0")
            rec("评审项清单（0）" in m.locator('[data-role="item-title"]').inner_text(),
                "VT-MODAL-21 评审项清单为空")
            # VT-MODAL-22 只读视图
            rec(m.locator("input").first.is_disabled(), "VT-MODAL-22 只读视图 → 标题 disabled")
            rec(m.locator('button:has-text("保存"):visible').count() == 0,
                "VT-MODAL-22 只读视图无「保存」")
            rec(m.locator('button:has-text("启动评审"):visible').count() == 1,
                "VT-MODAL-22 计划态 → 页脚出现「启动评审」")
            rec(m.locator('button:has-text("关闭评审"):visible').count() == 0,
                "VT-MODAL-22 计划态 → 无「关闭评审」")
            m.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(400)

            m = open_detail("RV-004", "edit")
            # VT-MODAL-23 点「编辑」
            rec(m.locator("input").first.is_enabled(), "VT-MODAL-23 编辑态 → 标题可写")
            addrow = m.locator('input[placeholder*="评审项内容"]')
            rec(addrow.count() == 1, "VT-MODAL-23 未结论 → 出现「加评审项」输入")
            addrow.fill("飞行就绪判据齐备")
            m.locator('input[placeholder*="评审准则"]').fill("判据文件已批准")
            page.wait_for_timeout(300)
            m.locator('button:has-text("加评审项")').click()
            page.wait_for_timeout(1200)
            n_items = m.locator('[data-role="item-row"]').count()
            # VT-MODAL-24 填评审项内容 + 判据 → 点「加评审项」
            rec(n_items == 1, f"VT-MODAL-24 评审项子表 {n_items} 行")
            rec("飞行就绪判据齐备" in m.locator('[data-role="item-row"]').first.inner_text(),
                "VT-MODAL-24 评审项内容落库回显")
            m.locator('button:has-text("保存")').click()
            page.wait_for_timeout(1200)
            rec(page.locator(".modal-mask:visible").count() == 0, "VT-MODAL-25 保存后模态关闭")

            # ── §4 状态机与出结论（F-2 / F-3 / F-4）──────────
            step("§4 状态机与出结论（VT-ACT-31..VT-ACT-38）")
            # ⚠ 动作按钮用 x-show 隐藏（display:none 但仍在 DOM）→ 断言存在性必须带 `:visible`
            r4 = row("RV-004")
            rec(r4.locator('button:has-text("启动评审"):visible').count() == 1
                and r4.locator('button:has-text("出结论"):visible').count() == 0
                and r4.locator('button:has-text("关闭评审"):visible').count() == 0,
                "VT-ACT-31 计划行：有「启动评审」，无「出结论」「关闭评审」")
            r4.locator('button:has-text("启动评审"):visible').click()
            page.wait_for_timeout(1200)
            r4 = row("RV-004")
            rec("进行中" in r4.inner_text() and r4.locator('button:has-text("出结论"):visible').count() == 1,
                "VT-ACT-32 启动后：状态「进行中」+ 出现「出结论」")

            r4.locator('button:has-text("出结论"):visible').click()
            page.wait_for_timeout(600)
            cm = page.locator(".modal-mask:visible").last
            csubmit = cm.locator('button:has-text("提交结论")')
            # VT-ACT-33 点「出结论」
            rec(cm.locator("select").count() == 1, "VT-ACT-33 出结论模态出现")
            rec(csubmit.is_disabled(), "VT-ACT-33 结论未选 → 提交 disabled")
            cm.locator("select").first.select_option("conditional")
            page.wait_for_timeout(300)
            # VT-ACT-34 选「有条件通过」但无行动项
            rec(csubmit.is_disabled(), "VT-ACT-34 「有条件通过」但无行动项 → 仍 disabled（BR-01）")
            rec("必须给出行动项" in cm.inner_text(), "VT-ACT-34 提示「有条件通过必须有行动项」")
            cm.locator('button:has-text("添加行动项")').click()
            page.wait_for_timeout(300)
            # VT-ACT-35 点「+ 添加行动项」→ 只填内容
            rec(cm.locator('[data-role="cm-action-row"]').count() == 1, "VT-ACT-35 行动项行出现")
            ar = cm.locator('[data-role="cm-action-row"]').first
            ar.locator("input").nth(0).fill("补齐判据文件")
            page.wait_for_timeout(300)
            rec(csubmit.is_disabled(), "VT-ACT-35 行动项只填内容 → 仍 disabled（BR-02：责任人与期限也要）")
            ar.locator("input").nth(1).fill("王五")
            ar.locator("input").nth(2).fill("2027-01-15")
            page.wait_for_timeout(300)
            # VT-ACT-36 行动项填全（内容/责任人/期限）
            rec(not csubmit.is_disabled(), "VT-ACT-36 结论 + 行动项填全 → 可提交")
            csubmit.click()
            page.wait_for_timeout(1300)
            r4 = row("RV-004")
            rec("行动项跟踪中" in r4.inner_text() and "1/1" in r4.inner_text(),
                # VT-ACT-37 提交结论
                "VT-ACT-37 出结论后：状态「行动项跟踪中」+ 行动项 1/1")

            # VT-ACT-38 已结论后内容冻结（BR-06）：行内「编辑」入口消失 —— 这是最强的前端表达
            # （后端的拒绝另有链测试兜底；前端不该给用户一个"全灰但能点进去"的编辑表单）
            rec(r4.locator('button:has-text("编辑"):visible').count() == 0,
                "VT-ACT-38 已结论 → 行内「编辑」入口消失（BR-06）")
            m = open_detail("RV-004", "view")
            hint = m.locator('[data-role="frozen-hint"]')
            rec(hint.count() == 1 and "冻结" in hint.inner_text(),
                "VT-ACT-38 详情提示「已出结论（结论是快照）—— 内容与评审项清单已冻结」")
            rec(m.locator('button:has-text("保存"):visible').count() == 0,
                "VT-ACT-38 详情无「保存」入口")
            rec(m.locator('input[placeholder*="评审项内容"]:visible').count() == 0,
                "VT-ACT-38 详情无「加评审项」入口")
            m.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(400)

            # ── §5 跨评审行动项汇总（F-6）────────────────────
            step("§5 行动项汇总（VT-SUB-51..VT-SUB-54）")
            srows = page.locator('[data-role="action-row"]')
            rec(srows.count() == 4,
                f"VT-SUB-51 未完成汇总 {srows.count()} 行（RV-001 ×1 + RV-003 ×2 + RV-004 ×1）")
            one = srows.filter(has_text="RV-003").first
            rec(one.locator('[data-role="act-owner"]').inner_text() == "张三"
                and one.locator('[data-role="act-due"]').inner_text() == "2026-12-01",
                # VT-SUB-52 行内容
                "VT-SUB-52 汇总行带出责任人 / 期限")
            page.locator('.fchip:has-text("已完成")').click()
            page.wait_for_timeout(900)
            rec(srows.count() == 1 and "RV-002" in srows.first.inner_text(),
                # VT-SUB-53 切到「已完成」 / 切回「未完成」
                f"VT-SUB-53 已完成 → {srows.count()} 行（RV-002）")
            page.locator('.fchip:has-text("未完成")').click()
            page.wait_for_timeout(900)
            rec(srows.count() == 4, "VT-SUB-53 切回未完成 → 4 行")

            page.on("dialog", lambda d: d.accept())      # 行内「完成」二次确认
            # ⚠ 「完成」按钮用 x-show（已完成的行仍在 DOM 里）→ 必须点 `:visible` 的那个
            srows.filter(has_text="RV-003").first.locator('button:has-text("完成"):visible').click()
            page.wait_for_timeout(1400)
            rec(srows.count() == 3 and "1/2" in row("RV-003").inner_text(),
                f"VT-SUB-54 完成 1 条后汇总 {srows.count()} 行，主列表 RV-003 变 1/2")

            # ── §6 关闭评审（F-7）───────────────────────────
            step("§6 关闭评审（VT-ACT-61..VT-ACT-65）")
            r3 = row("RV-003")
            rec(r3.locator('button:has-text("关闭评审"):visible').count() == 1
                and r3.locator('button:has-text("关闭评审"):visible').first.is_disabled(),
                "VT-ACT-61 还有未完成行动项 → 「关闭评审」禁用（BR-07）")
            m = open_detail("RV-003", "view")
            block = m.locator('[data-role="close-block-hint"]:visible')
            rec(block.count() == 1 and "还有 1 条行动项未完成" in block.inner_text(),
                # VT-ACT-62 打开详情
                "VT-ACT-62 详情给出原因「还有 1 条行动项未完成」")
            m.locator('[data-role="modal-action-row"]').filter(
                has_text="补充测试用例").first.locator('button:has-text("完成"):visible').click()
            page.wait_for_timeout(1400)
            # ⚠ 提示是 x-show 隐藏的，`count()` 照样数得到 → 必须用 `:visible`
            rec(m.locator('[data-role="close-block-hint"]:visible').count() == 0
                and not m.locator('button:has-text("关闭评审"):visible').first.is_disabled(),
                # VT-ACT-63 在详情里完成最后一条行动项
                "VT-ACT-63 行动项清零 → 遮蔽提示消失、关闭按钮可点")
            m.locator('button:has-text("关闭评审"):visible').first.click()
            page.wait_for_timeout(1400)
            r3 = row("RV-003")
            rec("已关闭" in r3.inner_text() and "0/2" in r3.inner_text(),
                # VT-ACT-64 点「关闭评审」（二次确认）
                "VT-ACT-64 关闭后：状态「已关闭」+ 行动项 0/2")
            rec(r3.locator('button:has-text("关闭评审"):visible').count() == 0
                and r3.locator('button:has-text("编辑"):visible').count() == 0,
                "VT-ACT-64 已关闭行：无「关闭评审」「编辑」（终态）")
            rec(row("RV-002").locator('button:has-text("关闭评审"):visible').count() == 0
                and row("RV-002").locator('button:has-text("编辑"):visible').count() == 0,
                "VT-ACT-64 已关闭的 RV-002 同样无动作按钮")

            m = open_detail("RV-003", "view")
            hint2 = m.locator('[data-role="frozen-hint"]')
            rec(hint2.count() == 1 and "已关闭（终态）" in hint2.inner_text(),
                # VT-ACT-65 已关闭详情
                "VT-ACT-65 已关闭详情提示「已关闭（终态）—— 不能再修改」")
            m.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(400)

            # ── §7 筛选 ─────────────────────────────────────
            step("§7 筛选（VT-FILTER-71..VT-FILTER-74）")
            page.locator("select").first.select_option("srr")
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "RV-002" in rows().first.inner_text(),
                f"VT-FILTER-71 类型=系统需求评审 → {rows().count()} 行（RV-002）")
            page.locator("select").first.select_option("")
            page.wait_for_timeout(600)
            page.locator("select").nth(1).select_option("c")          # 阶段
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "RV-001" in rows().first.inner_text(),
                # VT-FILTER-72 清类型，阶段筛「C 阶段」
                f"VT-FILTER-72 阶段=C 阶段 → {rows().count()} 行（RV-001）")
            page.locator("select").nth(1).select_option("")
            page.wait_for_timeout(600)
            page.locator("select").nth(2).select_option("tracking")   # 状态
            page.wait_for_timeout(900)
            # VT-FILTER-73 清阶段，状态筛「行动项跟踪中」
            rec(rows().count() == 2, f"VT-FILTER-73 状态=行动项跟踪中 → {rows().count()} 行")
            page.locator("select").nth(2).select_option("")
            page.wait_for_timeout(600)
            page.locator("select").nth(3).select_option("fail")       # 结论
            page.wait_for_timeout(900)
            rec(rows().count() == 2, f"VT-FILTER-74 结论=不通过 → {rows().count()} 行")
            page.locator("select").nth(3).select_option("")
            page.wait_for_timeout(600)

            # ── §7b 依据计划 / 责任人候选（datalist ← tech_plan.list / stakeholder.list）──
            step("§7b 依据计划与责任人候选（VT-SUG-75..VT-SUG-79）")
            page.click('button:has-text("新建评审")')
            page.wait_for_timeout(500)
            f3 = page.locator(".modal-mask:visible").last
            tp = f3.locator("datalist#tp-options-form option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            sh = f3.locator("datalist#sh-options-form option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            rec(len(tp) >= 1, f"VT-SUG-75 新建表单「依据计划」候选 {len(tp)} 项（来自 tech_plan.list）")
            rec(any(v.startswith("PLAN-") for v in tp), f"VT-SUG-75 候选值=计划编号、标签含名称：{tp[:2]}")
            # VT-SUG-76 新建表单：读 `datalist#sh-options-form`
            rec(len(sh) >= 2, f"VT-SUG-76 新建表单「责任人」候选 {len(sh)} 项（来自 stakeholder.list）")
            rec(f3.locator('input[list="tp-options-form"]').count() == 1
                and f3.locator('input[list="sh-options-form"]').count() == 1,
                # VT-SUG-77 两处控件类型
                "VT-SUG-77 两处仍是**文本输入**（不是 select）")
            f3.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)
            page.locator("table.tbl tr.data button.b-link").first.click()
            page.wait_for_timeout(900)
            m2 = page.locator(".modal-mask:visible").last
            tp2 = m2.locator("datalist#tp-options-modal option").count()
            sh2 = m2.locator("datalist#sh-options-modal option").count()
            # VT-SUG-78 详情模态：读两个 `…-modal` datalist
            rec(tp2 >= 1 and sh2 >= 2, f"VT-SUG-78 详情模态候选：计划 {tp2} 项 / 责任人 {sh2} 项")
            rec(m2.locator('input[list="tp-options-modal"]').count() == 1
                and m2.locator('input[list="sh-options-modal"]').count() == 1,
                "VT-SUG-79 详情两处同样为文本输入 + 候选")
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

    # ── §8 硬件指标 ────────────────────────────────────────
    step("§8 硬件指标（VT-HW-90..VT-HW-91）")
    rec(not errors, f"0 console error / 0 pageerror / 0 HTTP≥400（实际 {len(errors)}）")
    for e in errors[:8]:
        print("      [X]", e)

    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
