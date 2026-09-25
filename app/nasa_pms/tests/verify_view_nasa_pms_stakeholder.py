"""e2e 前端验收 - nasa_pms:stakeholder（利益相关者台账 · 主数据 · 外部同步 + 期望随相关方维护）。

断言：**主数据形态**（无「新建」、无删除、无状态徽标 —— 卡片 11 没有状态机）→ 三态同屏渲染 →
**F-1** 同步表单三项必填未齐则提交禁用 → **F-2** 期望三项必填联动 →
**F-3** 类别选 MOE 必须给度量口径（BR-06 前端镜像）→ **F-4** 已获承诺的期望冻结 →
**F-5** 冻结**可解锁**（取消勾选即刻解锁、撤回与改写一次保存，本页语义差）→
**F-6** 维护入口的编号锁定 + 同步幂等（同编号不产生第二行）→ **F-7** 两处派生计数随子表刷新 →
**F-8** 筛选收敛。全程 0 console error / 0 pageerror / 0 HTTP>=400。

用例来源：app/nasa_pms/stakeholder/前端测试用例.md（§0 造数 + §1..§8）。
运行：python app/nasa_pms/tests/verify_view_nasa_pms_stakeholder.py
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


# §0 自足造数：3 条相关方（客户 / 承包商 / 内部组织）+ 4 条期望（1 条**已获承诺**的 MOE）。
# 走 REST，不经 UI —— 避免用例依赖"同步功能本身"（那是 §5 的覆盖对象）。
# ⚠ REST 路径必须用**组限定名** `nasa_pms/stakeholder`（短名 404「应用不存在」）。
SEED_JS = r"""async () => {
  const call = async (app, svc, params) => {
    const r = await fetch(`/api/apps/${app}/call/${svc}`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(params || {})
    });
    const text = await r.text();
    let data = null; try { data = JSON.parse(text); } catch (e) {}
    if (!r.ok) throw new Error(`${app}.${svc} HTTP ${r.status} ${text.slice(0,160)}`);
    if (data && data.status === "error") throw new Error(`${app}.${svc} ${data.message || text.slice(0,160)}`);
    return data;
  };
  const SH = "nasa_pms/stakeholder";
  // SH-001 客户：3 条期望（need / goal / **已获承诺的 MOE**）⇒ 列表显示「期望 1/3」
  await call(SH, "upsert", {sh_no: "SH-001", name: "航天科技集团", sh_type: "customer",
                            duty: "用户方", org: "航天科技集团", contact: "张工 138****",
                            project_no: "P-2026-01"});
  await call(SH, "add_expectation", {sh_no: "SH-001", statement: "全任务周期内可靠运行",
                                     kind: "need", source: "访谈"});
  await call(SH, "add_expectation", {sh_no: "SH-001", statement: "2026 年内完成首飞",
                                     kind: "goal", source: "SOW"});
  await call(SH, "add_expectation", {sh_no: "SH-001", statement: "数据交付完整率",
                                     kind: "moe", source: "SOW", moe: ">= 99.9%",
                                     committed: true, note: "已列入验证计划"});
  // SH-002 承包商：1 条未承诺的 objective ⇒ 「期望 0/1」
  await call(SH, "upsert", {sh_no: "SH-002", name: "星辰电子", sh_type: "contractor",
                            duty: "分系统承制", org: "星辰电子"});
  await call(SH, "add_expectation", {sh_no: "SH-002", statement: "单机功耗不高于 45W",
                                     kind: "objective", source: "承包商会议"});
  // SH-003 内部组织：**没有期望** ⇒ 「期望 0/0」（§3 起由 UI 走完「加期望」）
  await call(SH, "upsert", {sh_no: "SH-003", name: "总体设计部", sh_type: "internal_org",
                            duty: "总体设计"});
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
    print(f"    {'[OK]' if ok else '[FAIL]'} {note}" if note else f"    {'[OK]' if ok else '[FAIL]'}",
          flush=True)


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

            step("§0 造数（3 条相关方 + 4 条期望，其中 1 条已获承诺）")
            seed = page.evaluate(SEED_JS)
            rec(bool(seed and seed.get("seeded")),
                "SH-001 客户（期望 1/3）· SH-002 承包商（0/1）· SH-003 内部组织（0/0）")

            def rows():
                return page.locator("table.tbl tr.data")

            def row(no):
                return page.locator("table.tbl tr.data").filter(has_text=no).first

            def detail():
                return page.locator('[data-role="detail-modal"]:visible')

            def open_detail(no, mode="view"):
                row(no).locator('button:has-text("详情")' if mode == "view"
                                else 'button:has-text("维护")').click()
                page.wait_for_timeout(900)
                return detail()

            def close_modals():
                """自**上而下**关（本页最多三层：详情 ← 同步 / 期望）。
                ⚠ 逗号分隔的 locator 按**文档序**返回，不是按选择器书写顺序 ——
                  详情模态在 HTML 里写在最前面，`.first` 会去点被上层遮罩挡住的「关闭」，
                  于是 Playwright 等 30s 超时（本轮实测踩到）。栈顶 = 文档序**最后**的那个，
                  所以一律用 `.last`，循环把栈逐层弹空。
                本期页面**没有二次确认弹窗**（主数据不删除），故不需要 dialog handler。"""
                page.wait_for_timeout(200)
                for _ in range(6):
                    btns = page.locator(
                        '[data-role="exp-modal"]:visible button:has-text("取消"),'
                        ' [data-role="sync-modal"]:visible button:has-text("取消"),'
                        ' [data-role="detail-modal"]:visible button:has-text("关闭")')
                    if not btns.count():
                        break
                    btns.last.click()
                    page.wait_for_timeout(350)

            # ── §1 渲染与入口（含主数据形态）─────────────────
            step("§1 渲染与入口（VT-ROUTE-01..VT-ROUTE-05）")
            page.evaluate("location.hash = '#/stakeholder'")
            page.wait_for_selector('[data-role="btn-sync"]', timeout=10000)
            page.wait_for_timeout(900)
            rec(rows().count() == 3, f"VT-ROUTE-01 列表 {rows().count()} 行（期望 3）")
            heads = page.locator("table.tbl tr").first.inner_text()
            rec(all(h in heads for h in ("相关方编号", "名称", "类型", "所属机构", "期望 已承诺/总")),
                # VT-ROUTE-02 表头完整性
                "VT-ROUTE-02 表头完整")
            rec(page.locator('[data-role="btn-sync"]:visible').count() == 1,
                # VT-ROUTE-03 **主数据形态**（三条"没有"）
                "VT-ROUTE-03 有「同步相关方」入口（= upsert，唯一写主档的入口）")
            # ⚠ 主数据形态是**规格的一部分**：没有「新建」、没有删除 —— 不是"藏起来"，是页面里就没有
            rec(page.locator('button:has-text("新建"):visible').count() == 0,
                "VT-ROUTE-03 **没有「新建」按钮**（数据来源=外部同步，卡片 11）")
            rec(page.locator('button:has-text("删除"):visible').count() == 0,
                "VT-ROUTE-03 **没有「删除」**（相关方只读引用，不维护源数据）")
            # ⚠ 筛选下拉按 data-role 定位，**不按 `select:visible` 的下标** ——
            #    平台壳的 Agent 右栏自带一个可见 `<select>`（会话选择器），总数与下标都会跟着壳变
            ty = page.locator('[data-role="f-type"]')
            tysel = ty.locator("option").all_inner_texts()
            rec(len(tysel) == 4 and tysel[0] == "全部类型",
                f"类型下拉（静态 option）{tysel}")
            t1 = row("SH-001").inner_text()
            rec("CUSTOMER" in t1 and "客户" in t1 and "1/3" in t1 and "航天科技集团" in t1,
                # VT-ROUTE-05 行内容
                "VT-ROUTE-05 SH-001 行：CUSTOMER / 客户 / 期望 1/3 / 所属机构")
            t3 = row("SH-003").inner_text()
            rec("INTERNAL_ORG" in t3 and "内部组织" in t3 and "0/0" in t3,
                "VT-ROUTE-05 SH-003 行：INTERNAL_ORG / 内部组织 / 期望 0/0")
            rec("CONTRACTOR" in row("SH-002").inner_text() and "0/1" in row("SH-002").inner_text(),
                "VT-ROUTE-05 SH-002 行：CONTRACTOR / 期望 0/1")

            # ── §2 详情（只读）与期望子表 ────────────────────
            step("§2 详情与期望子表（VT-MODAL-11..VT-MODAL-14）")
            m = open_detail("SH-001")
            head = m.locator('[data-role="sh-head"]').inner_text()
            # ⚠ 只读信息条用 data-role 定位后单独取文本：整块 inner_text 会把 select 的
            #    全部 option 文本也吃进来，断言会假过（本组实测踩过）
            rec("SH-001" in head and "CUSTOMER" in head and "客户" in head
                and "期望 1/3" in head and "航天科技集团" in head,
                "VT-MODAL-11 只读信息条：SH-001 / CUSTOMER 客户 / 期望 1/3 / 所属机构")
            # ⚠ 主数据**没有状态位**：这一条是刻意的语义差断言（卡片 11「状态机：无」）
            rec(m.locator('[data-role="sh-head"] .st').count() == 0,
                "VT-MODAL-11 信息条里**没有**状态徽标（主数据无状态机）")
            rec("外部同步" in m.locator('[data-role="readonly-hint"]').inner_text(),
                "VT-MODAL-11 提示相关方本体来自外部同步、本系统只维护其期望")
            rec("期望清单（3 条 · 已获承诺 1 条）"
                in m.locator('[data-role="exp-title"]').inner_text(),
                # VT-MODAL-12 子表与派生计数
                "VT-MODAL-12 期望清单标题带派生计数（3 条 / 已承诺 1 条）")
            rec(m.locator('[data-role="exp-row"]').count() == 3, "VT-MODAL-12 期望子表 3 行")
            e1 = m.locator('[data-role="exp-row"]').nth(0)
            e3 = m.locator('[data-role="exp-row"]').nth(2)
            rec(e1.locator('[data-role="exp-kind"]').inner_text() == "NEED"
                and "需要" in e1.inner_text()
                and e1.locator('[data-role="exp-source"]').inner_text() == "访谈",
                # VT-MODAL-13 行内容
                "VT-MODAL-13 第 1 条：NEED / 需要 / 来源=访谈")
            rec(e3.locator('[data-role="exp-kind"]').inner_text() == "MOE"
                and e3.locator('[data-role="exp-moe"]').inner_text() == ">= 99.9%"
                and "已承诺" in e3.locator('[data-role="exp-committed"]').inner_text()
                and "已列入验证计划" in e3.locator('[data-role="exp-note"]').inner_text(),
                "VT-MODAL-13 第 3 条：MOE / 口径 >= 99.9% / 已承诺 / 备注")
            rec("未承诺" in e1.locator('[data-role="exp-committed"]').inner_text(),
                "VT-MODAL-13 第 1 条未承诺（承诺是**逐条**的，不是整条相关方的状态）")
            # VT-MODAL-14 只读态
            rec(m.locator("input").first.is_disabled(), "VT-MODAL-14 只读视图 → 名称 disabled")
            rec(m.locator('button:has-text("保存"):visible').count() == 0, "VT-MODAL-14 只读视图无「保存」")
            rec(m.locator('button:has-text("维护"):visible').count() == 1
                and m.locator('button:has-text("加期望"):visible').count() == 1,
                "VT-MODAL-14 只读视图页脚有「维护」「加期望」")
            close_modals()

            # ── §3 登记期望（F-2 / F-3 / F-7）───────────────
            step("§3 登记期望与 MOE 联动（VT-FORM-21..VT-FORM-26）")
            rec(row("SH-003").locator('button:has-text("加期望"):visible').count() == 1,
                "VT-FORM-21 行内「加期望」入口存在")
            row("SH-003").locator('button:has-text("加期望"):visible').click()
            page.wait_for_timeout(700)
            em = page.locator('[data-role="exp-modal"]:visible')
            rec(em.count() == 1, "VT-FORM-21 期望模态出现")
            rec(em.locator('b:has-text("登记期望")').count() == 1, "VT-FORM-21 标题为「登记期望」")
            submit = em.locator('[data-role="em-submit"]')
            # VT-FORM-22 三项必填皆空 → 只填陈述
            rec(submit.is_disabled(), "VT-FORM-22 三项必填皆空 → 提交 disabled")
            em.locator('[data-role="em-statement"]').fill("发射场测控覆盖率不低于 98%")
            page.wait_for_timeout(200)
            rec(submit.is_disabled(), "VT-FORM-22 只填陈述 → 仍 disabled")
            em.locator('[data-role="em-kind"]').select_option("moe")
            page.wait_for_timeout(250)
            rec(submit.is_disabled() and em.locator('[data-role="em-moe-hint"]:visible').count() == 1,
                # VT-FORM-23 类别选「度量有效性（MOE）」
                "VT-FORM-23 类别选 MOE → 提交仍 disabled + 出现口径必填提示（BR-06）")
            em.locator('[data-role="em-kind"]').select_option("objective")
            page.wait_for_timeout(250)
            rec(em.locator('[data-role="em-moe-hint"]:visible').count() == 0,
                "VT-FORM-23 换回非 MOE 类别 → 口径提示消失（口径非必填）")
            em.locator('[data-role="em-source"]').fill("总体评审会")
            page.wait_for_timeout(250)
            # VT-FORM-24 填来源
            rec(not submit.is_disabled(), "VT-FORM-24 陈述 / 类别 / 来源齐备 → 可提交")
            submit.click()
            page.wait_for_timeout(1300)
            # VT-FORM-25 提交
            rec(page.locator('[data-role="exp-modal"]:visible').count() == 0, "VT-FORM-25 提交后模态关闭")
            # F-7：期望是聚合内子表 —— 列表的派生计数必须跟着变（SH-003 从 0/0 变 0/1；
            # ⚠ 派生计数是**每条相关方自己的**「已承诺/总」，不是全局累计 ——
            #    期望值必须按实际动作序列重算，别照着"加了第 4 条期望"去凑数字）
            rec("0/1" in row("SH-003").inner_text()
                and "1/3" in row("SH-001").inner_text(),
                "VT-FORM-25 列表 SH-003 变 0/1（本行自己的计数），SH-001 仍是 1/3")
            m = open_detail("SH-003")
            # VT-FORM-26 详情同步
            rec(m.locator('[data-role="exp-row"]').count() == 1, "VT-FORM-26 详情子表 1 行")
            rec(m.locator('[data-role="exp-title"]').inner_text()
                == "期望清单（1 条 · 已获承诺 0 条）",
                "VT-FORM-26 详情标题同步为「1 条 · 已获承诺 0 条」")
            close_modals()

            # ── §4 承诺冻结与解锁（F-4 / F-5，本页语义枢纽）──
            step("§4 承诺冻结与解锁（VT-ACT-31..VT-ACT-34）")
            m = open_detail("SH-001")
            m.locator('[data-role="exp-row"]').nth(2).locator('[data-role="exp-edit"]').click()
            page.wait_for_timeout(800)
            em = page.locator('[data-role="exp-modal"]:visible')
            rec(em.locator('b:has-text("编辑期望")').count() == 1
                and em.locator('[data-role="em-committed"]').is_checked(),
                "VT-ACT-31 打开已承诺期望的编辑态（勾选框为已勾选）")
            rec(em.locator('[data-role="em-statement"]').is_disabled()
                and em.locator('[data-role="em-kind"]').is_disabled()
                and em.locator('[data-role="em-source"]').is_disabled()
                and em.locator('[data-role="em-moe"]').is_disabled(),
                "VT-ACT-32 **已获承诺 ⇒ 陈述 / 类别 / 来源 / 度量口径全部 disabled**（BR-07）")
            hint = em.locator('[data-role="em-frozen-hint"]:visible')
            rec(hint.count() == 1 and "已获相关方承诺" in hint.inner_text()
                and "取消勾选" in hint.inner_text(),
                "VT-ACT-32 提示「已获相关方承诺…要改请先取消勾选」（**冻结可解锁**，与终态不同）")
            rec(em.locator('[data-role="em-note"]').is_enabled(),
                # VT-ACT-33 备注独可写
                "VT-ACT-33 备注**不受冻结影响**（承诺之后还要能留痕）")
            rec(em.locator('[data-role="em-statement"]').input_value() == "数据交付完整率",
                "VT-ACT-33 陈述回填（textarea 用 input_value 读，inner_text 读不到表单值）")
            em.locator('[data-role="em-note"]').fill("已列入验证计划 V-007")
            page.wait_for_timeout(200)
            em.locator('[data-role="em-submit"]').click()
            page.wait_for_timeout(1300)
            rec(page.locator('[data-role="exp-modal"]:visible').count() == 0
                and "V-007" in detail().locator('[data-role="exp-row"]').nth(2).inner_text(),
                # VT-ACT-34 只改备注 → 保存
                "VT-ACT-34 只改备注可保存（承诺仍在）")
            rec("已承诺" in detail().locator('[data-role="exp-row"]').nth(2)
                .locator('[data-role="exp-committed"]').inner_text(),
                "VT-ACT-34 该条仍是「已承诺」")
            close_modals()

            step("§5 冻结解锁：取消勾选即刻解锁，撤回与改写一次保存（VT-ACT-35..VT-ACT-39）")
            m = open_detail("SH-001")
            m.locator('[data-role="exp-row"]').nth(2).locator('[data-role="exp-edit"]').click()
            page.wait_for_timeout(800)
            em = page.locator('[data-role="exp-modal"]:visible')
            em.locator('[data-role="em-committed"]').uncheck()
            page.wait_for_timeout(300)
            rec(em.locator('[data-role="em-statement"]').is_enabled()
                and em.locator('[data-role="em-kind"]').is_enabled()
                and em.locator('[data-role="em-moe"]').is_enabled(),
                # VT-ACT-35 取消勾选「已获相关方承诺」
                "VT-ACT-35 取消勾选「已获相关方承诺」→ 四个字段**立刻解锁**")
            rec(em.locator('[data-role="em-frozen-hint"]:visible').count() == 0,
                "VT-ACT-35 冻结提示消失")
            em.locator('[data-role="em-statement"]').fill("数据交付完整率（修订）")
            page.wait_for_timeout(200)
            em.locator('[data-role="em-submit"]').click()
            page.wait_for_timeout(1300)
            # VT-ACT-36 改陈述 + 保存
            rec(page.locator('[data-role="exp-modal"]:visible').count() == 0, "VT-ACT-36 保存后模态关闭")
            r3 = detail().locator('[data-role="exp-row"]').nth(2)
            rec(r3.locator('[data-role="exp-statement"]').inner_text() == "数据交付完整率（修订）"
                and "未承诺" in r3.locator('[data-role="exp-committed"]').inner_text(),
                "VT-ACT-36 撤回与改写**在同一次调用**完成（陈述已改、承诺已撤）")
            # 先关掉详情模态再断列表 —— 列表行在遮罩下虽然还在渲染，但"等条件与断言对象是同一个东西"
            # （pitfalls #42）比"隔着遮罩读文本"更稳
            close_modals()
            rec("0/3" in row("SH-001").inner_text(),
                # VT-ACT-37 列表计数
                "VT-ACT-37 列表派生计数跟着变（已承诺 1/3 → 0/3）")
            # 再把承诺勾回去 ⇒ 冻结回归（解锁不是单向破坏，是可往复的）
            m = open_detail("SH-001")
            m.locator('[data-role="exp-row"]').nth(2).locator('[data-role="exp-edit"]').click()
            page.wait_for_timeout(800)
            em = page.locator('[data-role="exp-modal"]:visible')
            em.locator('[data-role="em-committed"]').check()
            page.wait_for_timeout(250)
            em.locator('[data-role="em-submit"]').click()
            page.wait_for_timeout(1300)
            # VT-ACT-38 再勾选承诺 + 保存
            rec("1/3" in row("SH-001").inner_text(), "VT-ACT-38 重新勾选承诺并保存 → 计数回到 1/3")
            # ⚠ 详情模态**一直开着**（saveExp 已 refreshDetail）—— 别再调 open_detail：
            #    那会去点被遮罩挡住的列表行按钮，Playwright 等 30s 然后超时（本轮实测踩到）
            m.locator('[data-role="exp-row"]').nth(2).locator('[data-role="exp-edit"]').click()
            page.wait_for_timeout(800)
            em = page.locator('[data-role="exp-modal"]:visible')
            rec(em.locator('[data-role="em-statement"]').is_disabled()
                and "数据交付完整率（修订）"
                == em.locator('[data-role="em-statement"]').input_value(),
                "VT-ACT-39 冻结回归：重新承诺后陈述又 disabled（改动已落库并冻结）")
            close_modals()

            # ── §6 同步与维护主档（F-1 / F-6）───────────────
            step("§6 同步与维护主档（VT-SYNC-41..VT-SYNC-47）")
            page.click('[data-role="btn-sync"]')
            page.wait_for_timeout(600)
            sm = page.locator('[data-role="sync-modal"]:visible')
            rec(sm.count() == 1 and sm.locator('b:has-text("同步相关方")').count() == 1,
                "VT-SYNC-41 同步模态出现")
            ssubmit = sm.locator('[data-role="sync-submit"]')
            rec(ssubmit.is_disabled(), "VT-SYNC-41 三项必填皆空 → 提交 disabled")
            sm.locator('input[placeholder*="SH-001"]').fill("SH-004")
            sm.locator('input[placeholder*="机构名或人员名"]').fill("深空探测中心")
            page.wait_for_timeout(250)
            # VT-SYNC-42 填编号 `SH-004` + 名称
            rec(ssubmit.is_disabled(), "VT-SYNC-42 只填编号 + 名称 → 仍 disabled（类型不给默认值）")
            sm.locator("select").nth(0).select_option("customer")
            page.wait_for_timeout(250)
            rec(not ssubmit.is_disabled(), "VT-SYNC-42 三项齐备 → 可提交")
            ssubmit.click()
            page.wait_for_timeout(1300)
            # VT-SYNC-43 提交
            rec(rows().count() == 4, f"VT-SYNC-43 同步成功，列表变 {rows().count()} 行（SH-004）")
            rec("0/0" in row("SH-004").inner_text(), "VT-SYNC-43 新同步的相关方没有期望（0/0）")

            step("§7 维护入口的编号锁定与同步幂等（VT-FILTER-51..VT-FILTER-55）")
            row("SH-004").locator('button:has-text("维护"):visible').click()
            page.wait_for_timeout(700)
            sm = page.locator('[data-role="sync-modal"]:visible')
            sh_in = sm.locator('input[placeholder*="SH-001"]')
            # ⚠ 表单回显用 input_value()：inner_text() 读不到 <input> 的值（本组实测踩过）
            rec(sh_in.input_value() == "SH-004" and sh_in.is_disabled(),
                # VT-SYNC-44 行内「维护」（`SH-004`）
                "VT-SYNC-44 「维护」预填编号且**编号锁定**（编号由外部来源给定，落库不可变 BR-01）")
            rec(sm.locator('input[placeholder*="机构名或人员名"]').input_value() == "深空探测中心",
                "VT-SYNC-44 名称已回填")
            # ⚠ 这里改**所属机构**而不是职责：职责列在 col_default_hidden 里（默认隐藏），
            #    改它就得先开列；所属机构列是可见的，改完能在列表上直接读到（两种坑都避开）
            sm.locator('input[placeholder*="选填"]').nth(1).fill("第一研究院")
            page.wait_for_timeout(200)
            sm.locator('[data-role="sync-submit"]').click()
            page.wait_for_timeout(1300)
            rec("第一研究院" in row("SH-004").inner_text(),
                # VT-SYNC-45 只改**所属机构** → 保存
                "VT-SYNC-45 维护只改了所属机构，列表同步显示（upsert 幂等更新）")
            page.click('[data-role="btn-sync"]')
            page.wait_for_timeout(600)
            sm = page.locator('[data-role="sync-modal"]:visible')
            sm.locator('input[placeholder*="SH-001"]').fill("SH-004")
            sm.locator('input[placeholder*="机构名或人员名"]').fill("深空探测中心（更名）")
            sm.locator("select").nth(0).select_option("internal_org")
            page.wait_for_timeout(200)
            sm.locator('[data-role="sync-submit"]').click()
            page.wait_for_timeout(1300)
            rec(rows().count() == 4,
                # VT-SYNC-46 用「同步相关方」再输同一编号 `SH-004`（改名 + 改类型）
                f"VT-SYNC-46 同一编号再次同步 → 列表仍 {rows().count()} 行（**幂等，不产生第二行**）")
            rec("深空探测中心（更名）" in row("SH-004").inner_text()
                and "INTERNAL_ORG" in row("SH-004").inner_text(),
                "VT-SYNC-46 名称与类型已更新（upsert = 存在即更新）")
            rec(page.locator('button:has-text("删除"):visible').count() == 0,
                # VT-SYNC-47 全程
                "VT-SYNC-47 全流程中**始终没有**删除入口（相关方与期望都不删）")

            # ── §8 筛选（F-8）───────────────────────────────
            step("§8 筛选（VT-HW-90..VT-HW-90）")
            ty = page.locator('[data-role="f-type"]')
            ty.select_option("contractor")
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "SH-002" in rows().first.inner_text(),
                f"VT-FILTER-51 类型=承包商 → {rows().count()} 行（SH-002）")
            ty.select_option("")
            page.wait_for_timeout(600)
            kw = page.locator('[data-role="f-keyword"]')
            kw.fill("航天")
            page.keyboard.press("Enter")
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "SH-001" in rows().first.inner_text(),
                # VT-FILTER-52 关键字「航天」回车
                f"VT-FILTER-52 关键字=航天（命中所属机构）→ {rows().count()} 行")
            kw.fill("总体设计")
            page.keyboard.press("Enter")
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "SH-003" in rows().first.inner_text(),
                # VT-FILTER-53 关键字「总体设计」回车
                f"VT-FILTER-53 关键字=总体设计（命中职责）→ {rows().count()} 行")
            kw.fill("SH-00")
            page.keyboard.press("Enter")
            page.wait_for_timeout(900)
            # VT-FILTER-54 关键字「SH-00」回车
            rec(rows().count() == 4, f"VT-FILTER-54 关键字=SH-00（命中编号）→ {rows().count()} 行")
            kw.fill("")
            page.keyboard.press("Enter")
            page.wait_for_timeout(900)
            rec(rows().count() == 4, f"VT-FILTER-55 清空关键字 → 恢复 {rows().count()} 行")

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

    # ── §9 硬件指标 ────────────────────────────────────────
    step("§9 硬件指标（VT-HW-90 / ）")
    rec(not errors, f"0 console error / 0 pageerror / 0 HTTP>=400（实际 {len(errors)}）")
    for e in errors[:8]:
        print("      [X]", e)

    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    for s, ok, note in bad:
        print(f"    [X] {s} :: {note}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
