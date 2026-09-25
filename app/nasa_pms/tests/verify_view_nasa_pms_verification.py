"""e2e 前端验收 - nasa_pms:verification（验证矩阵 · 跨应用派生）。

断言：规划入口存在 → 列表 5 行（四种状态同屏）→ **I-1** 覆盖读数 → **F-1** 需求/方法/阶段未选齐则
提交禁用 → **F-3** 对应需求强关联只读 → **F-5** 已判定后验证方法与阶段锁定、成功判据仍可补 →
**F-4** 记录判定（证据必填 + 不通过须后续处置）→ **F-2** 动作按钮按状态显隐 → **F-6** 关闭为终态
→ **F-7** 筛选收敛 → 全程 0 console error / 0 pageerror / 0 HTTP≥400。

用例来源：app/nasa_pms/verification/前端测试用例.md（§0 造数 + §1..§6）。
运行：python app/nasa_pms/tests/verify_view_nasa_pms_verification.py
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


# §0 自足造数（走 REST，不经 UI）：
#   3 条需求（全部纳入基线 B1）→ 验证矩阵的"需求侧"分母；REQ-003 **故意不挂验证项** ⇒ 覆盖缺口 1
#   4 条验证项，覆盖状态机的四种中间状态：closed / executing / planned / failed
# ⚠ REST 路径必须用**组限定名** `nasa_pms/verification`（短名 404「应用不存在」）。
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
  const REQ = "nasa_pms/requirement";
  const VER = "nasa_pms/verification";
  await call(REQ, "create", {title: "系统应支持 1000 并发用户",
    statement: "8vCPU/32GB 下 P95 响应 ≤ 2s", req_type: "technical", verify_method: "test"});
  await call(REQ, "create", {title: "星上存储器容量不小于 2Tb",
    statement: "在轨 5 年内不出现容量不足", req_type: "system", verify_method: "analysis"});
  await call(REQ, "create", {title: "遥测帧率不低于 1Hz",
    statement: "全程遥测下传帧率不低于 1Hz", req_type: "technical", verify_method: "test"});
  // 2026-09-25 起基线有评审门：先提交评审再纳入基线
  await call(REQ, "submit_review", {req_no: "REQ-001"});
  await call(REQ, "submit_review", {req_no: "REQ-002"});
  await call(REQ, "submit_review", {req_no: "REQ-003"});
  await call(REQ, "baseline", {req_nos: ["REQ-001", "REQ-002", "REQ-003"], baseline_ver: "B1"});

  await call(VER, "create", {req_no: "REQ-001", method: "test", phase: "system_functional",
    criteria: "P95 ≤ 2s", owner: "张三"});
  await call(VER, "start", {ver_no: "VER-001"});
  await call(VER, "record_result", {ver_no: "VER-001", result: "pass",
    evidence: "性能测试报告 TR-001 §4.2"});
  // 关闭说明现在会**落库**（close_note）并在详情显示 —— 造数带上，供 VT-MODAL-26 断言
  await call(VER, "close", {ver_no: "VER-001", note: "结论已纳入验证矩阵报告"});

  await call(VER, "create", {req_no: "REQ-002", method: "analysis", phase: "box_functional",
    owner: "李四"});
  await call(VER, "start", {ver_no: "VER-002"});

  await call(VER, "create", {req_no: "REQ-001", method: "inspection", phase: "end_to_end"});

  await call(VER, "create", {req_no: "REQ-002", method: "demonstration", phase: "on_orbit"});
  await call(VER, "start", {ver_no: "VER-004"});
  await call(VER, "record_result", {ver_no: "VER-004", result: "fail",
    evidence: "热真空试验报告 TR-002", follow_up: "更换器件后复验"});
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


def wait_text(loc, want, timeout=8000):
    """轮询等待 loc 的文本收敛到含 want，**返回等到的那个快照**。

    ⚠ 断言必须用返回值（等到的快照），不要等完再重新求值 —— 状态单元格与动作按钮是两处独立绑定，
    重渲染不在同一拍上；两次求值会得到"期望与实际看起来一样"的自相矛盾报错（pitfalls #42）。
    """
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
        c = page.locator("table.tbl tr.data").count()
        if c == n:
            return c
        time.sleep(0.15)
    return c


def wait_modal_hidden(page, timeout=8000):
    end = time.time() + timeout / 1000.0
    while time.time() < end:
        if page.locator(".modal-mask:visible").count() == 0:
            return True
        time.sleep(0.15)
    return False


def row_of(page, ver_no):
    return page.locator("table.tbl tr.data").filter(has_text=ver_no).first


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

            step("§0 造数（3 需求入基线 + 4 验证项：关闭 / 执行中 / 规划 / 不通过）")
            seed = page.evaluate(SEED_JS)
            rec(bool(seed and seed.get("seeded")),
                "REQ-001..003 已基线 B1；VER-001 关闭 / VER-002 执行中 / VER-003 规划 / VER-004 不通过")

            # ── §1 渲染与入口 ────────────────────────────────
            step("§1 渲染与入口（VT-ROUTE-01..VT-ROUTE-05）")
            page.evaluate("location.hash = '#/verification'")
            page.wait_for_selector('button:has-text("规划验证项")', timeout=10000)
            page.wait_for_timeout(900)
            body = page.locator("main").inner_text()
            rec("验证矩阵" in body, "VT-ROUTE-01 标题「验证矩阵」可见")
            rows = page.locator("table.tbl tr.data")
            rec(rows.count() == 4, f"VT-ROUTE-01 列表 {rows.count()} 行（期望 4）")
            heads = page.locator("table.tbl tr").first.inner_text()
            rec(all(h in heads for h in ("验证项编号", "对应需求", "验证方法", "验证阶段",
                                         "状态", "判定结果", "责任人")),
                # VT-ROUTE-02 表头
                "VT-ROUTE-02 表头完整")
            # VT-ROUTE-03 **保留规划入口**
            rec(page.locator('button:has-text("规划验证项")').count() > 0, "VT-ROUTE-03 保留规划入口")
            first = rows.first.inner_text()
            rec("VER-001" in first and "REQ-001" in first and "测试" in first
                and "系统功能级" in first and "关闭" in first and "通过" in first,
                # VT-ROUTE-04 首行内容
                "VT-ROUTE-04 首行 VER-001：REQ-001 / 测试 / 系统功能级 / 关闭 / 通过")
            # ⚠ 只读信息条一律加 data-role，别用整卡 inner_text —— select 会把全部 option 文本
            #   也算进去，断言会假过（本组实测踩过）
            cov = page.locator('[data-role="coverage"]').inner_text()
            rec("已基线需求 3 条" in cov and "已覆盖 2 条" in cov and "缺口 1 条" in cov,
                f"VT-ROUTE-05 I-1 覆盖读数：{cov}")

            # ── §2 规划验证项（F-1）──────────────────────────
            step("§2 规划验证项（VT-FORM-11..VT-FORM-16）")
            page.click('button:has-text("规划验证项")')
            page.wait_for_selector('.modal-mask:visible [data-role="form-req"]', timeout=8000)
            form = page.locator(".modal-mask:visible").last
            submit = form.locator('[data-role="form-submit"]')
            rec(form.locator("select").count() == 3, "VT-FORM-11 规划模态出现（需求/方法/阶段三个下拉）")
            # VT-FORM-12 **F-1 三项皆未选**
            rec(submit.is_disabled(), "VT-FORM-12 三项皆未选 → 提交 disabled")
            form.locator('[data-role="form-req"]').select_option("REQ-001")
            page.wait_for_timeout(250)
            # VT-FORM-13 只选对应需求
            rec(submit.is_disabled(), "VT-FORM-13 只选需求 → 仍 disabled（F-1）")
            form.locator('[data-role="form-method"]').select_option("test")
            page.wait_for_timeout(250)
            # VT-FORM-14 需求 + 方法齐备
            rec(submit.is_disabled(), "VT-FORM-14 需求+方法 → 仍 disabled（阶段必选）")
            form.locator('[data-role="form-phase"]').select_option("box_environmental")
            form.locator('[data-role="form-owner"]').fill("赵六")
            page.wait_for_timeout(300)
            # VT-FORM-15 三者齐备 → 提交
            rec(not submit.is_disabled(), "VT-FORM-15 三者齐备 → 可提交")
            submit.click()
            rec(wait_rows(page, 5) == 5, "VT-FORM-15 规划成功，列表变 5 行")
            page.click('button:has-text("规划验证项")')
            page.wait_for_selector('.modal-mask:visible [data-role="form-req"]', timeout=8000)
            form2 = page.locator(".modal-mask:visible").last
            rec(form2.locator('[data-role="form-req"]').input_value() == "", "VT-FORM-16 表单已重置")
            form2.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)

            # ── §3 详情 / 编辑（强关联只读 + 已判定锁定）───────
            step("§3 详情与编辑（VT-MODAL-21..VT-MODAL-25）")
            r3 = row_of(page, "VER-003")
            r3.locator('button:has-text("编辑"):visible').click()
            page.wait_for_selector('.modal-mask:visible [data-role="ver-req"]', timeout=8000)
            m = page.locator(".modal-mask:visible").last
            rec("REQ-001" in m.locator('[data-role="ver-req"]').inner_text(),
                "VT-MODAL-21 对应需求以纯文本回显（强关联只读，无下拉可改）")
            rec(m.locator('[data-role="ver-method"]').is_enabled()
                and m.locator('[data-role="ver-phase"]').is_enabled(),
                "VT-MODAL-21 规划中 → 验证方法与阶段可编辑")
            got_m = m.locator('[data-role="ver-method"]').input_value()
            got_p = m.locator('[data-role="ver-phase"]').input_value()
            rec(got_m == "inspection" and got_p == "end_to_end",
                f"VT-MODAL-21 方法/阶段回显 inspection / end_to_end（实际 {got_m} / {got_p}）")
            m.locator('button:has-text("关闭"):visible').first.click()
            wait_modal_hidden(page)

            # VER-004 已判定（不通过）→ 方法/阶段锁定，成功判据仍可补（BR-03 的语义差）
            r4 = row_of(page, "VER-004")
            r4.locator('button:has-text("编辑"):visible').click()
            page.wait_for_selector('.modal-mask:visible [data-role="ver-req"]', timeout=8000)
            m4 = page.locator(".modal-mask:visible").last
            rec(m4.locator('[data-role="ver-method"]').is_disabled()
                and m4.locator('[data-role="ver-phase"]').is_disabled(),
                # VT-MODAL-22 点 `VER-004`（不通过，已判定）编辑
                "VT-MODAL-22 已判定 → 验证方法与阶段锁定（BR-03）")
            rec(m4.locator('[data-role="ver-criteria"]').is_enabled(),
                "VT-MODAL-22 已判定 → 成功判据仍可补")
            m4.locator('[data-role="ver-criteria"]').fill("更换器件后复验合格")
            m4.locator('[data-role="edit-save"]').click()
            wait_modal_hidden(page)
            r4 = row_of(page, "VER-004")
            r4.locator('button:has-text("编辑"):visible').click()
            page.wait_for_selector('.modal-mask:visible [data-role="ver-req"]', timeout=8000)
            m4b = page.locator(".modal-mask:visible").last
            rec(m4b.locator('[data-role="ver-criteria"]').input_value() == "更换器件后复验合格",
                "VT-MODAL-22 成功判据已落库回显")
            m4b.locator('button:has-text("关闭"):visible').first.click()
            wait_modal_hidden(page)

            # 详情（view）：判定结果/证据是纯文本，「记录判定」控件不出现在 view 模式
            r1 = row_of(page, "VER-001")
            r1.locator('button:has-text("详情"):visible').click()
            page.wait_for_selector('.modal-mask:visible [data-role="ver-head"]', timeout=8000)
            m1 = page.locator(".modal-mask:visible").last
            rec(m1.locator('[data-role="record-result"]').count() == 0,
                # VT-MODAL-23 点 `VER-001` 详情
                "VT-MODAL-23 详情模式无「判定结果」编辑控件（判定只能经动作产生）")
            head = m1.locator('[data-role="ver-head"]').inner_text()
            rec("VER-001" in head and "关闭" in head and "通过" in head,
                # VT-MODAL-24 只读信息条
                f"VT-MODAL-24 只读信息条：{head}")
            rec("性能测试报告 TR-001" in m1.locator('[data-role="ver-evidence"]').inner_text(),
                "VT-MODAL-24 证据以纯文本回显")
            rec(m1.locator('[data-role="ver-followup"]').count() == 1
                and m1.locator('[data-role="ver-followup"]').inner_text() == "—",
                "VT-MODAL-24 后续处置字段存在（判定通过时为空，显示 —）")
            # VT-MODAL-26 关闭说明留痕（close_note 落库 + 详情展示）
            rec(m1.locator('[data-role="ver-close-note"]').count() == 1
                and "结论已纳入验证矩阵报告" in m1.locator('[data-role="ver-close-note"]').inner_text(),
                "VT-MODAL-26 详情显示「关闭说明」（close_note 落库并展示）")
            m1.locator('button:has-text("关闭"):visible').first.click()
            wait_modal_hidden(page)
            # VT-MODAL-25 关闭模态
            rec(page.locator("table.tbl tr.data").count() == 5, "VT-MODAL-25 关闭后列表未变")

            # ── §4 状态机动作（F-2 / F-4 / F-6）─────────────
            step("§4 状态机动作（VT-ACT-31..VT-ACT-39）")
            # ⚠ 动作按钮用 x-show 隐藏（元素仍在 DOM，仅 display:none）⇒ 存在性断言**必须带 `:visible`**，
            #   否则 count() 会把隐藏按钮也数进去、断言假红（同组实测踩过）
            r1 = row_of(page, "VER-001")   # closed
            r2 = row_of(page, "VER-002")   # executing
            r3 = row_of(page, "VER-003")   # planned
            r4 = row_of(page, "VER-004")   # failed
            rec(r3.locator('button:has-text("开始执行"):visible').count() == 1
                and r3.locator('button:has-text("记录判定"):visible').count() == 0
                and r3.locator('button:has-text("关闭"):visible').count() == 0,
                "VT-ACT-31 规划行：有「开始执行」，无「记录判定」「关闭」")
            rec(r2.locator('button:has-text("记录判定"):visible').count() == 1
                and r2.locator('button:has-text("开始执行"):visible').count() == 0,
                "VT-ACT-31 执行中行：有「记录判定」，无「开始执行」")
            rec(r4.locator('button:has-text("关闭"):visible').count() == 1
                and r4.locator('button:has-text("记录判定"):visible').count() == 0,
                "VT-ACT-31 不通过行：有「关闭」，无「记录判定」")
            rec(r1.locator('button:has-text("编辑"):visible').count() == 0
                and r1.locator('button:has-text("开始执行"):visible').count() == 0
                and r1.locator('button:has-text("记录判定"):visible').count() == 0
                and r1.locator('button:has-text("关闭"):visible').count() == 0,
                "VT-ACT-31 关闭行：动作按钮全部收起（终态）")

            # 开始执行：规划 → 执行中
            r3.locator('button:has-text("开始执行"):visible').click()
            r3 = row_of(page, "VER-003")
            t = wait_text(r3.locator("td").nth(4), "执行中")
            rec("执行中" in t, f"VT-ACT-32 VER-003 → 执行中（读到：{t}）")
            rec(r3.locator('button:has-text("记录判定"):visible').count() == 1,
                "VT-ACT-32 执行中行出现「记录判定」")

            # 记录判定：F-4（结果必选 + 证据必填）
            r3.locator('button:has-text("记录判定"):visible').click()
            page.wait_for_selector('.modal-mask:visible [data-role="record-result"]', timeout=8000)
            rm = page.locator(".modal-mask:visible").last
            # VT-ACT-33 点「记录判定」
            rec(rm.locator('[data-role="record-result"]').count() == 1, "VT-ACT-33 记录判定模态出现")
            rec(rm.locator('[data-role="record-submit"]').is_disabled(),
                "VT-ACT-33 未选判定结果 → 提交 disabled")
            rm.locator('[data-role="record-result"]').select_option("pass")
            page.wait_for_timeout(250)
            rec(rm.locator('[data-role="record-submit"]').is_disabled(),
                # VT-ACT-34 **F-4** 选「通过」但证据为空
                "VT-ACT-34 选「通过」但证据为空 → 仍 disabled（BR-02）")
            rm.locator('[data-role="record-evidence"]').fill("外观检验记录 IN-001：标识齐全")
            page.wait_for_timeout(300)
            rec(not rm.locator('[data-role="record-submit"]').is_disabled(),
                # VT-ACT-35 填证据 `外观检验记录 IN-001`
                "VT-ACT-35 证据齐备 → 可提交")
            rm.locator('[data-role="record-submit"]').click()
            r3 = row_of(page, "VER-003")
            t = wait_text(r3.locator("td").nth(4), "通过")
            # VT-ACT-36 提交后
            rec("通过" in t, f"VT-ACT-36 状态变「通过」（读到：{t}）")
            rec("通过" in r3.locator("td").nth(5).inner_text(), "VT-ACT-36 判定结果列变「通过」")

            # 记录判定：判定「不通过」必须同时给后续处置（BR-02 的语义差）
            r2 = row_of(page, "VER-002")
            r2.locator('button:has-text("记录判定"):visible').click()
            page.wait_for_selector('.modal-mask:visible [data-role="record-result"]', timeout=8000)
            rm2 = page.locator(".modal-mask:visible").last
            rm2.locator('[data-role="record-result"]').select_option("fail")
            rm2.locator('[data-role="record-evidence"]').fill("热真空试验报告 TR-003：-40℃ 写入失败")
            page.wait_for_timeout(300)
            rec(rm2.locator('[data-role="record-submit"]').is_disabled(),
                # VT-ACT-37 **F-4** 对 `VER-002`（执行中）判「不通过」：选 fail + 填证据
                "VT-ACT-37 判定「不通过」未填后续处置 → disabled（BR-02）")
            rm2.locator('[data-role="record-followup"]').fill("更换存储器件后复验")
            page.wait_for_timeout(300)
            rec(not rm2.locator('[data-role="record-submit"]').is_disabled(),
                "VT-ACT-37 补上后续处置 → 可提交")
            rm2.locator('[data-role="record-submit"]').click()
            r2 = row_of(page, "VER-002")
            t = wait_text(r2.locator("td").nth(4), "不通过")
            rec("不通过" in t, f"VT-ACT-37 VER-002 → 不通过（读到：{t}）")

            # 关闭：已判定 → 关闭（终态）
            r4 = row_of(page, "VER-004")
            r4.locator('button:has-text("关闭"):visible').click()
            page.wait_for_selector('.modal-mask:visible [data-role="close-submit"]', timeout=8000)
            cm = page.locator(".modal-mask:visible").last
            cm.locator('[data-role="close-submit"]').click()
            r4 = row_of(page, "VER-004")
            t = wait_text(r4.locator("td").nth(4), "关闭")
            # VT-ACT-38 点 `VER-004`（不通过）的「关闭」→ 确认
            rec("关闭" in t, f"VT-ACT-38 VER-004 → 关闭（读到：{t}）")
            rec(page.locator("table.tbl tr.data").count() == 5, "VT-ACT-38 记录仍在（未消失）")
            rec(r4.locator('button:has-text("编辑"):visible').count() == 0
                and r4.locator('button:has-text("关闭"):visible').count() == 0
                and r4.locator('button:has-text("记录判定"):visible').count() == 0,
                "VT-ACT-39 关闭行不再显示「编辑」「记录判定」「关闭」（终态）")

            # ── §5 筛选（F-7）──────────────────────────────
            step("§5 筛选（VT-FILTER-61..VT-FILTER-63）")
            page.locator('[data-role="f-method"]').select_option("analysis")
            page.wait_for_timeout(900)
            n = page.locator("table.tbl tr.data").count()
            rec(n == 1 and "VER-002" in page.locator("table.tbl tr.data").first.inner_text(),
                f"VT-FILTER-61 方法=分析 → {n} 行")
            page.locator('[data-role="f-method"]').select_option("")
            page.wait_for_timeout(600)
            page.locator('[data-role="f-status"]').select_option("planned")
            page.wait_for_timeout(900)
            n2 = page.locator("table.tbl tr.data").count()
            rec(n2 == 1 and "VER-005" in page.locator("table.tbl tr.data").first.inner_text(),
                # VT-FILTER-62 清方法，状态筛「规划」
                f"VT-FILTER-62 状态=规划 → {n2} 行")
            page.locator('[data-role="f-status"]').select_option("")
            page.wait_for_timeout(600)
            page.locator('[data-role="f-req"]').select_option("REQ-001")
            page.wait_for_timeout(900)
            n3 = page.locator("table.tbl tr.data").count()
            rec(n3 == 3, f"VT-FILTER-63 需求=REQ-001 → {n3} 行（VER-001/003/005）")
            page.locator('[data-role="f-req"]').select_option("")
            page.wait_for_timeout(600)

            # ── §7b 责任人候选（datalist ← stakeholder.list）────────
            step("§7b 责任人候选（VT-SUG-64..VT-SUG-65）")
            page.click('button:has-text("规划验证项")')
            page.wait_for_timeout(500)
            f3 = page.locator(".modal-mask:visible").last
            sh = f3.locator("datalist#sh-options-form option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            rec(len(sh) >= 2, f"VT-SUG-64 新建表单「责任人」候选 {len(sh)} 项（≥2，来自 stakeholder.list）")
            rec(any(v.startswith("候选人甲|") for v in sh), f"VT-SUG-64 候选值=姓名、标签含编号：{sh[:2]}")
            rec(f3.locator('[data-role="form-owner"]').count() == 1
                and f3.locator('input[list="sh-options-form"]').count() == 1,
                "VT-SUG-65 责任人仍是**文本输入**（不是 select）")
            f3.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)
            page.locator("table.tbl tr.data button.b-link").first.click()
            page.wait_for_timeout(900)
            m2 = page.locator(".modal-mask:visible").last
            sh2 = m2.locator("datalist#sh-options-modal option").count()
            rec(sh2 >= 2, f"VT-SUG-65 详情模态「责任人」候选 {sh2} 项")
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
