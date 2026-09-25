"""e2e 前端验收 - nasa_pms:technical_measure（技术度量台账 · 独立创建 + 聚合内两子表 + 跨度量查询视图）。

断言：新建入口存在 → 列表 4 行（超阈值 / 度量中 / 定义 / 已关闭 四态同屏）→
**F-1** 五项必填未齐则提交禁用 → **F-2** 定义态判定口径可改（本页语义差）→
**F-3** 基线化冻结口径并开测 → **F-4** 记实测值（超阈值同事务出告警、前端给判定提示）→
**F-5** 未了结告警时关闭按钮可见但禁用 + 给出原因 → **F-6** 纠正了结告警后关闭可点 →
**F-7** 已关闭为硬终态（编辑入口消失、终态提示）→ **F-8** 判定口径冻结 + 解锁须走变更 →
**F-9** 告警汇总（查询视图）按状态收敛 → **F-10** 筛选收敛 → **F-11** 动作按钮按状态显隐。
全程 0 console error / 0 pageerror / 0 HTTP≥400。

用例来源：app/nasa_pms/technical_measure/前端测试用例.md（§0 造数 + §1..§8）。
运行：python app/nasa_pms/tests/verify_view_nasa_pms_technical_measure.py
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


# §0 自足造数：1 条需求（供弱引用）+ 4 条度量（**超阈值 / 度量中 / 定义 / 已关闭** 四态同屏）+ 3 条告警。
# 走 REST，不经 UI —— 避免用例依赖"新建功能本身"（那是 §2 的覆盖对象）。
# ⚠ REST 路径必须用**组限定名** `nasa_pms/technical_measure`（短名 404「应用不存在」）。
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
  const TM = "nasa_pms/technical_measure";
  const RQ = "nasa_pms/requirement";
  // 先造一条需求（度量侧的弱引用要能查到 —— 这是本组唯一一处跨应用调用）
  await call(RQ, "create", {title: "推进剂余量不低于 10%",
                            statement: "全任务周期内推进剂余量不低于 10%",
                            req_type: "technical", verify_method: "analysis", owner: "张三"});
  // TPM-001 推进剂余量：在阈内一期 + 超阈值一期 ⇒ 「超阈值」（1 条未了结告警，弱引用 REQ-001）
  await call(TM, "create", {name: "推进剂余量", category: "tpm", direction: "higher",
                            target_value: 15, threshold_value: 10, unit: "%",
                            req_no: "REQ-001", owner: "张三"});
  await call(TM, "baseline", {tpm_no: "TPM-001"});
  await call(TM, "record", {tpm_no: "TPM-001", period: "2026-Q1", measured_value: 12.5});
  await call(TM, "record", {tpm_no: "TPM-001", period: "2026-Q2", measured_value: 8.2});
  // TPM-002 整星质量：超阈值 → 纠正 → 再测 ⇒ 「度量中」（1 条**已了结**告警）
  await call(TM, "create", {name: "整星质量", category: "mop", direction: "lower",
                            target_value: 1200, threshold_value: 1250, unit: "kg", owner: "李四"});
  await call(TM, "baseline", {tpm_no: "TPM-002"});
  await call(TM, "record", {tpm_no: "TPM-002", period: "2026-Q1", measured_value: 1280});
  await call(TM, "correct", {tpm_no: "TPM-002", corrective_action: "更换轻质材料"});
  await call(TM, "record", {tpm_no: "TPM-002", period: "2026-Q2", measured_value: 1210});
  // TPM-003 遥测数据完整率：**定义态**（§3 起由 UI 走完 基线化 → 记实测值 → 纠正 → 关闭）
  await call(TM, "create", {name: "遥测数据完整率", category: "kpp", direction: "higher",
                            target_value: 99, threshold_value: 95, unit: "%"});
  // TPM-004 姿态控制精度：**已关闭**（硬终态，用于 F-7）
  await call(TM, "create", {name: "姿态控制精度", category: "kpp", direction: "lower",
                            target_value: 0.05, threshold_value: 0.1, unit: "deg"});
  await call(TM, "baseline", {tpm_no: "TPM-004"});
  await call(TM, "record", {tpm_no: "TPM-004", period: "2026-Q1", measured_value: 0.04});
  await call(TM, "close", {tpm_no: "TPM-004", note: "首飞达标"});
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
            # 基线化 / 关闭度量都要二次确认 —— 挂上自动接受（默认行为是**驳回**，动作会静默不发生）
            page.on("dialog", lambda d: d.accept())
            page.goto(f"{base}/view/nasa_pms/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)

            step("§0 造数（4 条度量：超阈值 / 度量中 / 定义 / 已关闭 + 3 条告警）")
            seed = page.evaluate(SEED_JS)
            rec(bool(seed and seed.get("seeded")),
                "TPM-001 超阈值 · TPM-002 度量中 · TPM-003 定义 · TPM-004 已关闭")

            def rows():
                return page.locator("table.tbl tr.data")

            def row(no):
                return page.locator("table.tbl tr.data").filter(has_text=no).first

            def open_detail(no, mode="view"):
                row(no).locator('button:has-text("详情")' if mode == "view"
                                else 'button:has-text("编辑")').click()
                page.wait_for_timeout(1000)
                return page.locator(".modal-mask:visible").last

            def close_all_modals():
                page.wait_for_timeout(200)
                for _ in range(4):
                    btns = page.locator('.modal-mask:visible button:has-text("关闭"),'
                                        ' .modal-mask:visible button:has-text("取消")')
                    n = btns.count()
                    if not n:
                        break
                    try:
                        btns.first.click(timeout=1500)
                    except Exception:
                        break
                    page.wait_for_timeout(400)

            # ── §1 渲染与入口 ────────────────────────────────
            step("§1 渲染与入口（VT-ROUTE-01..VT-ROUTE-05）")
            page.evaluate("location.hash = '#/technical_measure'")
            page.wait_for_selector('button:has-text("新建度量")', timeout=10000)
            page.wait_for_timeout(1000)
            rec(rows().count() == 4, f"VT-ROUTE-01 列表 {rows().count()} 行（期望 4）")
            heads = page.locator("table.tbl tr").first.inner_text()
            rec(all(h in heads for h in ("度量编号", "名称", "类别", "优化方向", "目标值", "阈值",
                                         "当前实测值", "度量期次", "状态", "告警 未/总")),
                # VT-ROUTE-02 表头完整性
                "VT-ROUTE-02 表头完整")
            rec(page.locator('button:has-text("新建度量"):visible').count() == 1,
                # VT-ROUTE-03 **保留新建入口**
                "VT-ROUTE-03 保留新建入口")
            # ⚠ 页面上的可见 `<select>` **不止**本页的三个：平台壳的 Agent 右栏还有一个
            #    会话选择器（`view/pages/agent_rail.html` 的 `<select class="agent-rail-sel">`）——
            #    它在 DOM 里排在主区**之后**，所以 nth(0..2) 仍是本页的三个筛选下拉。
            #    这里不数「一共几个」（那会被壳的实现变更搞红），而是**按语义钉住前三个的序号**：
            #    §11 的 `select:visible` 下标完全依赖这个事实，钉不住就会静默筛错维度。
            flt0 = page.locator("select:visible")
            cat0 = flt0.nth(0).locator("option").all_inner_texts()
            st1 = flt0.nth(1).locator("option").all_inner_texts()
            dir2 = flt0.nth(2).locator("option").all_inner_texts()
            # VT-ROUTE-04 **筛选下拉的序号按语义钉住**
            rec(len(cat0) == 4 and cat0[0] == "全部类别", "VT-ROUTE-04 第 1 个下拉是「类别」")
            rec(len(st1) == 6 and st1[0] == "全部状态", "VT-ROUTE-04 第 2 个下拉是「状态」")
            rec(len(dir2) == 3 and dir2[0] == "全部方向", "VT-ROUTE-04 第 3 个下拉是「方向」")
            t1 = row("TPM-001").inner_text()
            rec("超阈值" in t1 and "1/1" in t1 and "8.2" in t1 and "2026-Q2" in t1
                and "越大越好" in t1,
                "VT-ROUTE-05 TPM-001 行：超阈值 / 告警 1/1 / 实测 8.2 @ 2026-Q2 / 越大越好")
            t2 = row("TPM-002").inner_text()
            rec("度量中" in t2 and "0/1" in t2 and "越小越好" in t2,
                "VT-ROUTE-05 TPM-002 行：度量中 / 告警 0/1 / 越小越好（1280 已纠正、1210 在阈内）")
            rec("定义" in row("TPM-003").inner_text() and "0/0" in row("TPM-003").inner_text(),
                "VT-ROUTE-05 TPM-003 行：定义 / 告警 0/0")
            t4 = row("TPM-004").inner_text()
            rec("已关闭" in t4, "VT-ROUTE-05 TPM-004 行：已关闭")

            # ── §2 新建度量（F-1）───────────────────────────
            step("§2 新建度量（VT-FORM-11..VT-FORM-15）")
            page.click('button:has-text("新建度量")')
            page.wait_for_timeout(500)
            form = page.locator(".modal-mask:visible").last
            rec(form.locator("select").count() == 2, "VT-FORM-11 新建模态出现（类别 + 方向两个下拉）")
            submit = form.locator('button:has-text("提交")')
            # VT-FORM-12 **F-1 五项皆空**
            rec(submit.is_disabled(), "VT-FORM-12 五项必填皆空 → 提交 disabled")
            form.locator("input").first.fill("姿控推力器效率")
            page.wait_for_timeout(200)
            # VT-FORM-13 只填目标值
            rec(submit.is_disabled(), "VT-FORM-13 只填名称 → 仍 disabled（类别/方向无默认值）")
            form.locator("select").nth(0).select_option("tpm")
            form.locator("select").nth(1).select_option("higher")
            page.wait_for_timeout(200)
            rec(submit.is_disabled(), "VT-FORM-13 目标值 / 阈值仍空 → 仍 disabled")
            form.locator('input[type="number"]').nth(0).fill("95")
            page.wait_for_timeout(200)
            rec(submit.is_disabled(), "VT-FORM-13 只填目标值 → 仍 disabled（阈值也要）")
            form.locator('input[type="number"]').nth(1).fill("90")
            page.wait_for_timeout(300)
            # VT-FORM-14 五项齐备 → 提交
            rec(not submit.is_disabled(), "VT-FORM-14 五项齐备 → 可提交")
            submit.click()
            page.wait_for_timeout(1300)
            rec(rows().count() == 5, f"VT-FORM-14 新建成功，列表变 {rows().count()} 行（TPM-005）")
            rec("定义" in row("TPM-005").inner_text() and "0/0" in row("TPM-005").inner_text(),
                "VT-FORM-14 新度量以「定义」态落库（TPM-005）")
            page.click('button:has-text("新建度量")')
            page.wait_for_timeout(500)
            form2 = page.locator(".modal-mask:visible").last
            # VT-FORM-15 关掉重开
            rec(form2.locator("input").first.input_value() == "", "VT-FORM-15 表单已重置")
            form2.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)

            # ── §3 详情 · 定义态判定口径可改（F-2 / F-8 的前半）────
            step("§3 详情（定义态）与判定口径可改（VT-MODAL-21..VT-MODAL-25）")
            m = open_detail("TPM-003", "view")
            head = m.locator('[data-role="tpm-head"]').inner_text()
            # ⚠ 只读信息条用 data-role 定位后单独取文本：整块 inner_text 会把 select 的
            #    全部 option 文本也吃进来，断言会假过（本组实测踩过）
            rec("TPM-003" in head and "定义" in head and "告警 0/0" in head,
                "VT-MODAL-21 只读信息条：TPM-003 / 定义 / 告警 0/0")
            rec("实测值序列（0 期）" in m.locator('[data-role="reading-title"]').inner_text(),
                "VT-MODAL-21 实测值序列为空")
            # VT-MODAL-22 只读视图
            rec(m.locator("input").first.is_disabled(), "VT-MODAL-22 只读视图 → 名称 disabled")
            rec(m.locator('button:has-text("保存"):visible').count() == 0,
                "VT-MODAL-22 只读视图无「保存」")
            rec(m.locator('button:has-text("基线化"):visible').count() == 1,
                "VT-MODAL-22 定义态 → 页脚出现「基线化」")
            rec(m.locator('button:has-text("记实测值"):visible').count() == 0
                and m.locator('button:has-text("关闭度量"):visible').count() == 0,
                "VT-MODAL-22 定义态 → 无「记实测值」「关闭度量」")
            m.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(400)

            m = open_detail("TPM-003", "edit")
            # VT-MODAL-23 点「编辑」
            rec(m.locator("input").first.is_enabled(), "VT-MODAL-23 编辑态 → 名称可写")
            rec(m.locator('input[type="number"]').first.is_enabled(),
                "VT-MODAL-23 **定义态判定口径可改**（目标值可写 —— 本页与同组其它页的语义差）")
            rec(m.locator('[data-role="spec-frozen-hint"]:visible').count() == 0,
                "VT-MODAL-23 定义态无「口径已冻结」提示")
            m.locator('input[type="number"]').first.fill("98")
            page.wait_for_timeout(300)
            m.locator('button:has-text("保存")').click()
            page.wait_for_timeout(1300)
            # VT-MODAL-24 把目标值改成 98 → 点「保存」
            rec(page.locator(".modal-mask:visible").count() == 0, "VT-MODAL-24 保存后模态关闭")
            rec("98" in row("TPM-003").inner_text(), "VT-MODAL-25 未基线时改目标值已生效（列表显示 98）")

            # ── §4 基线化（F-3 / F-11）──────────────────────
            step("§4 基线化（VT-ACT-31..VT-ACT-33）")
            # ⚠ 动作按钮用 x-show 隐藏（display:none 但仍在 DOM）→ 断言存在性必须带 `:visible`
            r3 = row("TPM-003")
            rec(r3.locator('button:has-text("基线化"):visible').count() == 1
                and r3.locator('button:has-text("记实测值"):visible').count() == 0
                and r3.locator('button:has-text("关闭度量"):visible').count() == 0,
                "VT-ACT-31 定义行：有「基线化」，无「记实测值」「关闭度量」")
            r3.locator('button:has-text("基线化"):visible').click()
            page.wait_for_timeout(1400)
            r3 = row("TPM-003")
            rec("度量中" in r3.inner_text() and "B1" in r3.inner_text()
                and r3.locator('button:has-text("记实测值"):visible').count() == 1,
                "VT-ACT-32 基线化后：状态「度量中」+ 基线 B1 + 出现「记实测值」")
            rec(r3.locator('button:has-text("基线化"):visible').count() == 0,
                "VT-ACT-32 基线化入口消失（每个度量只能基线一次）")
            # F-8：基线后判定口径冻结
            m = open_detail("TPM-003", "edit")
            rec(m.locator('input[type="number"]').first.is_disabled(),
                # VT-ACT-33 打开详情（编辑态）
                "VT-ACT-33 已基线 → 目标值 disabled")
            rec(m.locator('input[type="number"]').nth(1).is_disabled(),
                "VT-ACT-33 已基线 → 阈值 disabled")
            # ⚠ 模态里有两个 select：`nth(0)` 是**度量类别**（描述性，仍可改）、
            #    `nth(1)` 才是**优化方向**（判定口径，冻结）—— 不按下标对齐就会把两者判反
            rec(m.locator("select").nth(1).is_disabled(), "VT-ACT-33 已基线 → 优化方向 disabled")
            rec(m.locator("select").nth(0).is_enabled(),
                "VT-ACT-33 已基线 → 度量类别仍可改（冻结的只是判定口径三件）")
            rec(m.locator('[data-role="spec-frozen-hint"]:visible').count() == 1
                and "须经变更请求" in m.locator('[data-role="spec-frozen-hint"]').inner_text(),
                "VT-ACT-33 提示「判定口径已基线（B1）…须经变更请求」")
            rec(m.locator("input").first.is_enabled(),
                "VT-ACT-33 描述性字段（名称）仍可写（冻结的只是判定口径）")
            close_all_modals()

            # ── §5 记实测值 → 超阈值同事务出告警（F-4）──────
            step("§5 记实测值与超阈值告警（VT-ACT-41..VT-ACT-45）")
            row("TPM-003").locator('button:has-text("记实测值"):visible').click()
            page.wait_for_timeout(700)
            rm = page.locator(".modal-mask:visible").last
            band = rm.locator('[data-role="rm-band"]').inner_text()
            rec("实测值 < 95%" in band, f"VT-ACT-41 判定提示：{band[:40]}…")
            rsubmit = rm.locator('button:has-text("提交读数")')
            # VT-ACT-42 期次与实测值皆空 / 只填期次
            rec(rsubmit.is_disabled(), "VT-ACT-42 期次与实测值皆空 → disabled")
            rm.locator('input[placeholder*="2026-Q3"]').fill("2026-Q3")
            page.wait_for_timeout(200)
            rec(rsubmit.is_disabled(), "VT-ACT-42 只填期次 → 仍 disabled")
            rm.locator('input[type="number"]').first.fill("90")
            page.wait_for_timeout(300)
            # VT-ACT-43 期次 `2026-Q3` + 实测值 `90`
            rec(not rsubmit.is_disabled(), "VT-ACT-43 期次 + 实测值齐备 → 可提交")
            rsubmit.click()
            page.wait_for_timeout(1400)
            r3 = row("TPM-003")
            rec("超阈值" in r3.inner_text() and "1/1" in r3.inner_text(),
                # VT-ACT-44 提交
                "VT-ACT-44 提交后：状态「超阈值」+ 告警 1/1（实测 90 < 阈值 95）")
            m = open_detail("TPM-003", "view")
            rec(m.locator('[data-role="reading-row"]').count() == 1,
                "VT-ACT-44 实测值序列 1 期")
            rec(m.locator('[data-role="alert-row"]').count() == 1, "VT-ACT-44 告警台账 1 条（同事务）")
            arow = m.locator('[data-role="alert-row"]').first
            rec(arow.locator('[data-role="alert-period"]').inner_text() == "2026-Q3"
                and arow.locator('[data-role="alert-deviation"]').inner_text() == "5"
                and "低于阈值 95%" in arow.locator('[data-role="alert-message"]').inner_text()
                and "未了结" in arow.inner_text(),
                "VT-ACT-45 告警带出期次 2026-Q3 / 超出量 5 / 「低于阈值 95%」/ 未了结")

            # ── §6 未了结告警 → 关闭禁用 + 给出原因（F-5）──
            step("§6 关闭禁用与原因文案（VT-ACT-51..VT-ACT-52）")
            r3 = row("TPM-003")
            rec(r3.locator('button:has-text("关闭度量"):visible').count() == 1
                and r3.locator('button:has-text("关闭度量"):visible').first.is_disabled(),
                "VT-ACT-51 还有未了结告警 → 「关闭度量」可见但禁用（BR-06）")
            block = m.locator('[data-role="close-block-hint"]:visible')
            rec(block.count() == 1 and "还有 1 条告警未了结" in block.inner_text(),
                "VT-ACT-52 详情给出原因「还有 1 条告警未了结（超阈值未纠正）…（BR-06）」")
            rec(m.locator('button:has-text("纠正"):visible').count() == 1,
                "VT-ACT-52 超阈值 → 页脚出现「纠正」")
            close_all_modals()

            # ── §7 纠正 → 告警了结、关闭可点（F-6）─────────
            step("§7 纠正（VT-ACT-61..VT-ACT-64）")
            row("TPM-003").locator('button:has-text("纠正"):visible').click()
            page.wait_for_timeout(700)
            cm = page.locator(".modal-mask:visible").last
            csubmit = cm.locator('button:has-text("登记并了结告警")')
            rec(cm.locator("textarea").count() == 1, "VT-ACT-61 纠正模态出现（措施文本域）")
            # VT-ACT-62 措施为空 → 填写后
            rec(csubmit.is_disabled(), "VT-ACT-62 措施为空 → disabled")
            cm.locator("textarea").fill("重新标定遥测链路并补做一次比对")
            page.wait_for_timeout(300)
            rec(not csubmit.is_disabled(), "VT-ACT-62 填了措施 → 可提交")
            csubmit.click()
            page.wait_for_timeout(1400)
            r3 = row("TPM-003")
            rec("已纠正" in r3.inner_text() and "0/1" in r3.inner_text(),
                # VT-ACT-63 提交
                "VT-ACT-63 纠正后：状态「已纠正」+ 告警 0/1（了结但留在台账）")
            rec(not r3.locator('button:has-text("关闭度量"):visible').first.is_disabled(),
                "VT-ACT-63 告警清零 → 「关闭度量」可点")
            m = open_detail("TPM-003", "view")
            # ⚠ 提示是 x-show 隐藏的，`count()` 照样数得到 → 必须用 `:visible`
            rec(m.locator('[data-role="close-block-hint"]:visible').count() == 0,
                "VT-ACT-63 原因文案消失")
            rec(m.locator('[data-role="alert-row"]').count() == 1
                and "已了结" in m.locator('[data-role="alert-row"]').first.inner_text()
                and "重新标定遥测链路" in m.locator('[data-role="alert-row"]').first.inner_text(),
                "VT-ACT-64 告警台账仍 1 条、状态已了结、带纠正措施")
            close_all_modals()

            # ── §8 关闭度量 → 硬终态（F-7）──────────────────
            step("§8 关闭度量（VT-ACT-71..VT-ACT-73）")
            row("TPM-003").locator('button:has-text("关闭度量"):visible').click()
            page.wait_for_timeout(1400)
            r3 = row("TPM-003")
            rec("已关闭" in r3.inner_text() and "0/1" in r3.inner_text(),
                "VT-ACT-71 关闭后：状态「已关闭」+ 告警 0/1")
            rec(r3.locator('button:has-text("关闭度量"):visible').count() == 0
                and r3.locator('button:has-text("编辑"):visible').count() == 0
                and r3.locator('button:has-text("记实测值"):visible').count() == 0,
                "VT-ACT-71 已关闭行：无「关闭度量」「编辑」「记实测值」（终态）")
            rec(row("TPM-004").locator('button:has-text("编辑"):visible').count() == 0,
                "VT-ACT-71 已关闭的 TPM-004 同样无「编辑」")
            m = open_detail("TPM-003", "view")
            locked = m.locator('[data-role="locked-hint"]:visible')
            rec(locked.count() == 1 and "已关闭（终态）" in locked.inner_text(),
                # VT-ACT-72 已关闭详情
                "VT-ACT-72 已关闭详情提示「已关闭（终态）—— 不能再记录 / 纠正 / 修改」")
            rec(m.locator('button:has-text("保存"):visible').count() == 0
                and m.locator('button:has-text("基线化"):visible').count() == 0,
                "VT-ACT-73 终态详情无写入口")
            close_all_modals()

            # ── §9 已基线≠已关闭：判定口径的两种锁定（F-8 的后半）──
            step("§9 判定口径冻结（VT-ACT-81..VT-ACT-81）")
            m = open_detail("TPM-001", "edit")
            rec(m.locator('input[type="number"]').first.is_disabled()
                and m.locator('input[type="number"]').nth(1).is_disabled(),
                "VT-ACT-81 TPM-001（已基线、超阈值）→ 目标值 / 阈值 disabled")
            hint = m.locator('[data-role="spec-frozen-hint"]:visible')
            rec(hint.count() == 1 and "rebaseline" in hint.inner_text(),
                "VT-ACT-81 提示指向 rebaseline（冻结**可解锁**，与终态不同）")
            rec(m.locator('[data-role="locked-hint"]:visible').count() == 0,
                "VT-ACT-81 已基线但未关闭 → **不**出现终态提示（两条锁定轴互不混淆）")
            close_all_modals()

            # ── §10 跨度量告警汇总（F-9）────────────────────
            step("§10 告警汇总（VT-SUB-91..VT-SUB-94）")
            srows = page.locator('[data-role="sum-alert-row"]')
            rec(srows.count() == 1, f"VT-SUB-91 未了结汇总 {srows.count()} 行（TPM-001 ×1）")
            rec("推进剂余量" in srows.first.locator('[data-role="sa-name"]').inner_text()
                and srows.first.locator('[data-role="sa-period"]').inner_text() == "2026-Q2"
                and srows.first.locator('[data-role="sa-deviation"]').inner_text() == "1.8%",
                # VT-SUB-92 行内容
                "VT-SUB-92 汇总行带出名称 / 期次 / 超出量（含计量单位）")
            page.locator('.fchip:has-text("已了结")').click()
            page.wait_for_timeout(900)
            # VT-SUB-93 切到「已了结」
            rec(srows.count() == 2, f"VT-SUB-93 已了结 → {srows.count()} 行（TPM-002 + TPM-003）")
            rec(srows.filter(has_text="更换轻质材料").count() == 1,
                "VT-SUB-93 已了结行带出纠正措施文本")
            page.locator('.fchip:has-text("全部")').click()
            page.wait_for_timeout(900)
            rec(srows.count() == 3, f"VT-SUB-94 全部 → {srows.count()} 行")
            rec("共 3 条告警" in page.locator('[data-role="sum-total"]').inner_text(),
                "VT-SUB-94 汇总条数正确")

            # ── §11 筛选（F-10）─────────────────────────────
            step("§11 筛选（VT-FILTER-101..VT-FILTER-105）")
            flt = page.locator("select:visible")
            flt.nth(1).select_option("exceeded")
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "TPM-001" in rows().first.inner_text(),
                f"VT-FILTER-101 状态=超阈值 → {rows().count()} 行（TPM-001）")
            flt.nth(1).select_option("defined")
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "TPM-005" in rows().first.inner_text(),
                # VT-FILTER-102 状态筛「定义」
                f"VT-FILTER-102 状态=定义 → {rows().count()} 行（TPM-005）")
            flt.nth(1).select_option("")
            page.wait_for_timeout(600)
            flt.nth(0).select_option("kpp")
            page.wait_for_timeout(900)
            # VT-FILTER-103 类别筛「关键性能参数（KPP）」
            rec(rows().count() == 2, f"VT-FILTER-103 类别=关键性能参数（KPP）→ {rows().count()} 行")
            flt.nth(0).select_option("")
            page.wait_for_timeout(600)
            flt.nth(2).select_option("lower")
            page.wait_for_timeout(900)
            # VT-FILTER-104 方向筛「越小越好」
            rec(rows().count() == 2, f"VT-FILTER-104 方向=越小越好 → {rows().count()} 行")
            flt.nth(2).select_option("")
            page.wait_for_timeout(600)
            page.fill('input[placeholder*="关联需求"]', "REQ-001")
            page.keyboard.press("Enter")
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "TPM-001" in rows().first.inner_text(),
                f"VT-FILTER-105 关联需求=REQ-001 → {rows().count()} 行（弱引用可筛）")

            # ── §7b 责任人候选（datalist ← stakeholder.list）────────
            # 跨应用只读候选：**值仍是文本姓名**（不落 sh_no，全组 owner 一致口径），
            # 故断言两件事 —— 候选确有数据 + 控件仍是文本输入（不是 select）。
            step("§7b 责任人候选（VT-SUG-122..VT-SUG-123）")
            page.click('button:has-text("新建度量")')
            page.wait_for_timeout(500)
            f3 = page.locator(".modal-mask:visible").last
            sh = f3.locator("datalist#sh-options-form option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            rec(len(sh) >= 2, f"VT-SUG-122 新建表单「责任人」候选 {len(sh)} 项（≥2，来自 stakeholder.list）")
            rec(any(v.startswith("候选人甲|") for v in sh), f"VT-SUG-122 候选值=姓名、标签含编号：{sh[:2]}")
            rec(f3.locator('input[list="sh-options-form"]').count() == 1,
                "VT-SUG-123 责任人仍是**文本输入**（不是 select —— 值即文本、回填天然正确）")
            f3.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)
            page.locator("table.tbl tr.data button.b-link").first.click()
            page.wait_for_timeout(900)
            m2 = page.locator(".modal-mask:visible").last
            sh2 = m2.locator("datalist#sh-options-modal option").count()
            rec(sh2 >= 2, f"VT-SUG-123 详情模态「责任人」候选 {sh2} 项")
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

    # ── §12 硬件指标 ────────────────────────────────────────
    step("§12 硬件指标（VT-HW-120..VT-HW-121）")
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
