"""e2e 前端验收 - nasa_pms:decision（决策台账 · 独立创建 + 聚合内两子表）。

断言：新建入口存在 → 列表 4 行（已实施 / 已决策 / 权衡中 / 提出 四态同屏）→
**F-1** 议题必填未齐则提交禁用 → **F-2** 准则为空时「启动权衡」禁用并给出原因（BR-01）→
**F-3/F-4** 编辑态可加准则 / 加方案（聚合内子表）→ **F-5** 权衡打分（含 0 分口径）→
**F-6** 决策模态：未打分的方案**不可选**（I-1）、选中非最高分方案必须给依据（BR-04）→
**F-7** 已决策后内容冻结（无保存、无加准则/加方案入口）→ **F-8** 已实施为终态 →
**F-9** 筛选收敛 → **F-10** 动作按钮按状态显隐。
全程 0 console error / 0 pageerror / 0 HTTP>=400。

用例来源：app/nasa_pms/decision/前端测试用例.md（§0 造数 + §1..§8）。
运行：python app/nasa_pms/tests/verify_view_nasa_pms_decision.py
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


# §0 自足造数：4 个决策（**已实施 / 已决策 / 权衡中 / 提出** 四态同屏）+ 2 张子表。
# 走 REST，不经 UI —— 避免用例依赖"新建功能本身"（那是 §2 的覆盖对象）。
# ⚠ REST 路径必须用**组限定名** `nasa_pms/decision`（短名 404「应用不存在」）。
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
  const DC = "nasa_pms/decision";
  await call(DC, "create", {topic: "飞控计算机选用", measure_no: "TPM-001",
                            issue: "双余度要求下的自研 / 货架取舍", owner: "张三"});
  await call(DC, "create", {topic: "推进方案选用", eval_method: "trade_study", owner: "李四"});
  await call(DC, "create", {topic: "测控链路方案", eval_method: "cost_benefit", owner: "王五"});
  await call(DC, "create", {topic: "地面站部署方式", owner: "赵六"});
  // DC-001：准则 2 / 方案 2 / 两份都打分 / 选中最高分 / 已实施
  await call(DC, "add_criterion", {dec_no: "DC-001", criterion: "成本", weight: 3});
  await call(DC, "add_criterion", {dec_no: "DC-001", criterion: "进度", weight: 2});
  await call(DC, "add_option", {dec_no: "DC-001", name: "方案A：自研", description: "自研飞控计算机"});
  await call(DC, "add_option", {dec_no: "DC-001", name: "方案B：货架产品", description: "采购货架产品并适配"});
  await call(DC, "start", {dec_no: "DC-001"});
  await call(DC, "score_option", {dec_no: "DC-001", seq: 1, score: 70});
  await call(DC, "score_option", {dec_no: "DC-001", seq: 2, score: 88, note: "总分最高"});
  await call(DC, "conclude", {dec_no: "DC-001", chosen_seq: 2,
                              risk_note: "货架产品需做环境适应性验证"});
  await call(DC, "implement", {dec_no: "DC-001", note: "已签采购合同"});
  // DC-002：选**非**最高分方案 + 依据 ⇒ 已决策（前端 F-6 的 BR-04 对照行）
  await call(DC, "add_criterion", {dec_no: "DC-002", criterion: "成本", weight: 2});
  await call(DC, "add_criterion", {dec_no: "DC-002", criterion: "风险", weight: 3});
  await call(DC, "add_option", {dec_no: "DC-002", name: "方案甲：液氧煤油"});
  await call(DC, "add_option", {dec_no: "DC-002", name: "方案乙：固液混合"});
  await call(DC, "start", {dec_no: "DC-002"});
  await call(DC, "score_option", {dec_no: "DC-002", seq: 1, score: 90});
  await call(DC, "score_option", {dec_no: "DC-002", seq: 2, score: 75});
  await call(DC, "conclude", {dec_no: "DC-002", chosen_seq: 2,
                              rationale: "方案乙风险低，成本略高但在可承受区间内"});
  // DC-003：2 个方案只打了 1 分 ⇒ 权衡中（「未打分的方案不可选」的那一行）
  await call(DC, "add_criterion", {dec_no: "DC-003", criterion: "支持性", weight: 1});
  await call(DC, "add_criterion", {dec_no: "DC-003", criterion: "成本", weight: 2});
  await call(DC, "add_option", {dec_no: "DC-003", name: "S 频段链路"});
  await call(DC, "add_option", {dec_no: "DC-003", name: "Ka 频段链路"});
  await call(DC, "start", {dec_no: "DC-003"});
  await call(DC, "score_option", {dec_no: "DC-003", seq: 1, score: 60});
  // DC-004：0 准则 0 方案 ⇒ 提出（BR-01 的前端对照行）
  await call("nasa_pms/stakeholder", "upsert", {sh_no: "SH-EX1", name: "候选人甲", sh_type: "customer"});
  await call("nasa_pms/stakeholder", "upsert", {sh_no: "SH-EX2", name: "候选人乙", sh_type: "internal_org"});
  await call("nasa_pms/technical_measure", "create", {name: "候选度量甲", category: "tpm", direction: "higher", target_value: 100, threshold_value: 80, unit: "ms"});
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

            step("§0 造数（4 个决策：已实施 / 已决策 / 权衡中 / 提出）")
            seed = page.evaluate(SEED_JS)
            rec(bool(seed and seed.get("seeded")),
                "DC-001 已实施 · DC-002 已决策 · DC-003 权衡中 · DC-004 提出")

            def rows():
                return page.locator("table.tbl tr.data")

            def row(no):
                return page.locator("table.tbl tr.data").filter(has_text=no).first

            def modal():
                return page.locator(".modal-mask:visible").last

            def open_detail(no, mode="view"):
                row(no).locator('button:has-text("详情")' if mode == "view"
                                else 'button:has-text("编辑")').click()
                page.wait_for_timeout(900)
                return modal()

            # ── §1 渲染与入口 ────────────────────────────────
            step("§1 渲染与入口（VT-ROUTE-01..VT-ROUTE-04）")
            page.evaluate("location.hash = '#/decision'")
            page.wait_for_selector('button:has-text("新建议题")', timeout=10000)
            page.wait_for_timeout(900)
            rec(rows().count() == 4, f"VT-ROUTE-01 列表 {rows().count()} 行（期望 4）")
            heads = page.locator("table.tbl tr").first.inner_text()
            rec(all(h in heads for h in ("决策编号", "决策议题", "评价方法", "状态", "选中方案", "责任人")),
                # VT-ROUTE-02 表头完整性
                "VT-ROUTE-02 表头完整")
            rec(page.locator('button:has-text("新建议题"):visible').count() == 1,
                # VT-ROUTE-03 **保留新建议题入口**
                "VT-ROUTE-03 保留新建议入口")
            # ⚠ 派生列用 data-role 精确取文本：整行 inner_text 会把相邻列的数字一起吃进来
            t1 = row("DC-001")
            rec(t1.locator('[data-role="chosen"]').inner_text() == "方案B：货架产品"
                and t1.locator('[data-role="top"]').inner_text() == "方案2 · 88"
                and t1.locator('[data-role="scored"]').inner_text() == "2/2"
                and t1.locator('[data-role="criteria-n"]').inner_text() == "2",
                "VT-ROUTE-04 DC-001：选中方案B / 最高分 方案2 · 88 / 已打分 2/2 / 准则 2")
            rec("已实施" in t1.inner_text() and "加权决策矩阵" in t1.inner_text(),
                "VT-ROUTE-04 DC-001 行：已实施 / 加权决策矩阵")
            t2 = row("DC-002")
            rec(t2.locator('[data-role="chosen"]').inner_text() == "方案乙：固液混合"
                and "已决策" in t2.inner_text() and "权衡研究" in t2.inner_text(),
                "VT-ROUTE-04 DC-002 行：已决策 / 权衡研究 / 选中方案乙")
            t3 = row("DC-003")
            rec(t3.locator('[data-role="scored"]').inner_text() == "1/2"
                and "权衡中" in t3.inner_text() and "成本收益分析" in t3.inner_text(),
                "VT-ROUTE-04 DC-003 行：权衡中 / 成本收益分析 / 已打分 1/2")
            rec("提出" in row("DC-004").inner_text()
                and row("DC-004").locator('[data-role="criteria-n"]').inner_text() == "0",
                "VT-ROUTE-04 DC-004 行：提出 / 准则 0")

            # ── §2 新建议题（F-1）───────────────────────────
            step("§2 新建议题（VT-FORM-11..VT-FORM-14）")
            page.click('button:has-text("新建议题")')
            page.wait_for_timeout(500)
            form = modal()
            subst = form.locator('button:has-text("提交")')
            rec(subst.is_disabled(), "VT-FORM-11 议题为空 → 提交 disabled")
            form.locator("input").first.fill("地面站天线口径")
            page.wait_for_timeout(200)
            # VT-FORM-12 填议题
            rec(not subst.is_disabled(), "VT-FORM-12 议题非空 → 可提交（评价方法有默认值）")
            form.locator("select").first.select_option("utility")   # 效用分析（给 §7 筛选留靶子）
            form.locator("input").nth(1).fill("")                   # 来源度量留空
            form.locator("input").nth(2).fill("评审员")              # 责任人
            page.wait_for_timeout(200)
            subst.click()
            page.wait_for_timeout(1200)
            # VT-FORM-13 选评价方法「效用分析」+ 责任人「评审员」→ 提交
            rec(rows().count() == 5, f"VT-FORM-13 新建成功，列表变 {rows().count()} 行")
            page.click('button:has-text("新建议题")')
            page.wait_for_timeout(500)
            form2 = modal()
            # VT-FORM-14 关掉重开
            rec(form2.locator("input").first.input_value() == "", "VT-FORM-14 表单已重置")
            form2.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)

            # ── §3 详情 / 两张子表（F-2 / F-3）──────────────
            step("§3 详情与子表（VT-MODAL-21..VT-MODAL-26）")
            m = open_detail("DC-004", "view")
            head = m.locator('[data-role="decision-head"]').inner_text()
            # ⚠ 只读信息条用 data-role 定位后单独取文本：整块 inner_text 会把 select 的
            #    全部 option 文本也吃进来，断言会假过（同组 review 用例集实测踩过）
            rec("DC-004" in head and "提出" in head and "准则 0" in head
                and "备选方案 0" in head and "已打分 0/0" in head,
                "VT-MODAL-21 只读信息条：DC-004 / 提出 / 准则 0 / 方案 0 / 已打分 0/0")
            rec("评价准则（0）" in m.locator('[data-role="criterion-title"]').inner_text()
                and "备选方案（0）" in m.locator('[data-role="option-title"]').inner_text(),
                "VT-MODAL-21 两张子表都为空")
            # VT-MODAL-22 只读视图
            rec(m.locator("input").first.is_disabled(), "VT-MODAL-22 只读视图 → 议题 disabled")
            rec(m.locator('button:has-text("保存"):visible').count() == 0,
                "VT-MODAL-22 只读视图无「保存」")
            startbtn = m.locator('button:has-text("启动权衡"):visible').first
            rec(startbtn.count() == 1 and startbtn.is_disabled(),
                # VT-MODAL-23 **F-2** 准则为空
                "VT-MODAL-23 准则 0 → 「启动权衡」可见但禁用（BR-01）")
            hint = m.locator('[data-role="start-block-hint"]:visible')
            rec(hint.count() == 1 and "还没有评价准则" in hint.inner_text(),
                "VT-MODAL-23 给出原因「还没有评价准则」（BR-01）")
            m.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(400)

            m = open_detail("DC-004", "edit")
            # VT-MODAL-24 点「编辑」
            rec(m.locator("input").first.is_enabled(), "VT-MODAL-24 编辑态 → 议题可写")
            rec(m.locator('input[placeholder*="评价准则"]').count() == 1
                and m.locator('input[placeholder*="备选方案名称"]').count() == 1,
                "VT-MODAL-24 未冻结 → 「加准则」「加方案」两个入口都在")
            m.locator('input[placeholder*="评价准则"]').fill("任务成功")
            m.locator('input[placeholder*="权重"]').fill("5")
            page.wait_for_timeout(200)
            m.locator('button:has-text("加准则")').click()
            page.wait_for_timeout(1200)
            n_cri = m.locator('[data-role="criterion-row"]').count()
            rec(n_cri == 1 and "任务成功" in m.locator('[data-role="criterion-row"]').first.inner_text()
                and m.locator('[data-role="criterion-weight"]').first.inner_text() == "5",
                # VT-MODAL-25 填准则「任务成功」+ 权重 `5` → 点「加准则」
                f"VT-MODAL-25 准则子表 {n_cri} 行（任务成功 / 权重 5）")
            m.locator('input[placeholder*="备选方案名称"]').fill("方案1：自建地面站")
            page.wait_for_timeout(200)
            m.locator('button:has-text("加方案")').click()
            page.wait_for_timeout(1200)
            m.locator('input[placeholder*="备选方案名称"]').fill("方案2：租用商业站")
            page.wait_for_timeout(200)
            m.locator('button:has-text("加方案")').click()
            page.wait_for_timeout(1200)
            n_opt = m.locator('[data-role="option-row"]').count()
            rec(n_opt == 2, f"VT-MODAL-26 方案子表 {n_opt} 行")
            first_opt = m.locator('[data-role="option-row"]').first.inner_text()
            rec("方案1：自建地面站" in first_opt and "未打分" in first_opt,
                "VT-MODAL-26 未打分的方案显示「未打分」")
            m.locator('button:has-text("保存")').click()
            page.wait_for_timeout(1200)
            rec(page.locator(".modal-mask:visible").count() == 0, "VT-MODAL-26 保存后模态关闭")
            rec(row("DC-004").locator('[data-role="criteria-n"]').inner_text() == "1"
                and "提出" in row("DC-004").inner_text(),
                "VT-MODAL-26 列表同步：DC-004 准则 1 / 仍是提出态")

            # ── §4 启动权衡 + 权衡打分（F-2 / F-5）──────────
            step("§4 启动权衡与打分（VT-ACT-31..VT-ACT-36）")
            r4 = row("DC-004")
            rec(r4.locator('button:has-text("启动权衡"):visible').count() == 1
                and not r4.locator('button:has-text("启动权衡"):visible').first.is_disabled(),
                "VT-ACT-31 有准则后「启动权衡」变可点（BR-01）")
            rec(r4.locator('button:has-text("权衡打分"):visible').count() == 0
                and r4.locator('button:has-text("决策"):visible').count() == 0,
                "VT-ACT-31 提出态：无「权衡打分」「决策」")
            r4.locator('button:has-text("启动权衡"):visible').click()
            page.wait_for_timeout(1200)
            r4 = row("DC-004")
            rec("权衡中" in r4.inner_text()
                and r4.locator('button:has-text("权衡打分"):visible').count() == 1
                and r4.locator('button:has-text("决策"):visible').count() == 1,
                "VT-ACT-32 启动后：状态「权衡中」+ 出现「权衡打分」「决策」")
            rec(r4.locator('button:has-text("决策"):visible').first.is_disabled(),
                "VT-ACT-32 一个方案都没打分 → 「决策」禁用（BR-03 前端镜像）")

            r4.locator('button:has-text("权衡打分"):visible').click()
            page.wait_for_timeout(900)
            wm = modal()
            rec(wm.locator('[data-role="weigh-row"]').count() == 2
                and wm.locator('[data-role="weigh-criterion-row"]').count() == 1,
                # VT-ACT-33 点「权衡打分」
                "VT-ACT-33 权衡模态：2 个方案 + 1 条准则（打分的依据）")
            rec("任务成功" in wm.locator('[data-role="weigh-criterion-row"]').first.inner_text()
                and "0~100" in wm.inner_text(),
                "VT-ACT-33 带出准则与得分口径（0~100，0 分也有效）")
            wsave = wm.locator('[data-role="weigh-save"]')
            # VT-ACT-34 得分留空
            rec(wsave.first.is_disabled(), "VT-ACT-34 得分空 → 「保存」禁用")
            wm.locator('[data-role="weigh-score"]').first.fill("80")
            page.wait_for_timeout(300)
            rec(not wsave.first.is_disabled(), "VT-ACT-34 填了得分 → 可保存")
            wsave.first.click()
            page.wait_for_timeout(1400)
            # ⚠ 断言只读 `input_value()`：打分框是 `<input>`，它的值**不进** `inner_text()`
            #    （整行 inner_text 只有序号与方案名 —— 拿它断言得分会永远假红）
            rec(wm.locator('[data-role="weigh-score"]').first.input_value() == "80",
                # VT-ACT-35 点「保存」
                "VT-ACT-35 保存后得分框回显 80")
            rec(wm.locator('[data-role="weigh-row"]').first.locator(
                '[data-role="weigh-name"]').inner_text() == "方案1：自建地面站",
                "VT-ACT-35 行内方案名不变（重取的是同一行）")
            wm.locator('[data-role="weigh-score"]').nth(1).fill("90")
            page.wait_for_timeout(300)
            wsave.nth(1).click()
            page.wait_for_timeout(1400)
            rec(wm.locator('[data-role="weigh-score"]').nth(1).input_value() == "90",
                "VT-ACT-35 第二个方案打 90（两行独立保存）")
            wm.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(400)
            rec(row("DC-004").locator('[data-role="scored"]').inner_text() == "2/2"
                and row("DC-004").locator('[data-role="top"]').inner_text() == "方案2 · 90",
                "VT-ACT-36 列表同步：已打分 2/2、最高分 方案2 · 90")
            # 分数真的落进了**聚合内子表**（不是只停在输入框里）：详情里两行都在
            m = open_detail("DC-004", "view")
            score_cells = m.locator('[data-role="option-score"]')
            rec(score_cells.count() == 2 and score_cells.nth(0).inner_text() == "80"
                and score_cells.nth(1).inner_text() == "90",
                "VT-ACT-36 详情方案子表：80 / 90（子表按聚合一次带回）")
            m.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(400)

            # ── §5 决策模态（F-6：I-1 不可选 + BR-04 依据）──
            step("§5 决策模态（VT-MODAL-41..VT-MODAL-46）")
            # 先用 DC-003（方案 2 未打分）验「未打分的方案不可选」
            r3 = row("DC-003")
            r3.locator('button:has-text("决策"):visible').click()
            page.wait_for_timeout(900)
            cm3 = modal()
            radios3 = cm3.locator('[data-role="cm-option"] input')
            rec(radios3.count() == 2 and not radios3.nth(0).is_disabled()
                and radios3.nth(1).is_disabled(),
                "VT-MODAL-41 已打分的方案可点、未打分的方案禁用（BR-03）")
            rec("未打分（不可选）" in cm3.locator('[data-role="cm-option-score"]').nth(1).inner_text(),
                "VT-MODAL-41 未打分行标注「未打分（不可选）」")
            rec(cm3.locator('button:has-text("提交决策")').is_disabled()
                and "请选择一个已打分的备选方案" in cm3.locator('[data-role="cm-hint"]').inner_text(),
                "VT-MODAL-41 未选方案 → 提交禁用并给出原因")
            cm3.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(400)

            r4 = row("DC-004")
            r4.locator('button:has-text("决策"):visible').click()
            page.wait_for_timeout(900)
            cm = modal()
            rec(cm.locator('[data-role="cm-option"]').count() == 2,
                # VT-MODAL-42 对 `DC-004` 点「决策」
                "VT-MODAL-42 决策模态列出 2 个备选方案（含得分）")
            rec("80 分" in cm.locator('[data-role="cm-option-score"]').nth(0).inner_text()
                and "90 分" in cm.locator('[data-role="cm-option-score"]').nth(1).inner_text(),
                "VT-MODAL-42 两个方案的得分都带出")
            radios = cm.locator('[data-role="cm-option"] input')
            radios.nth(0).click()                      # 方案1 = 80 分，**不是**最高分（方案2 是 90）
            page.wait_for_timeout(400)
            csub = cm.locator('button:has-text("提交决策")')
            # VT-MODAL-43 选中 `80 分`的方案（**非**最高分）
            rec(csub.is_disabled(), "VT-MODAL-43 选中非最高分方案 → 提交禁用（BR-04）")
            blk = cm.locator('[data-role="cm-block"]:visible')
            rec(blk.count() == 1 and "必须给出依据" in blk.inner_text(),
                "VT-MODAL-43 给出原因「选中的不是最高分方案 —— 必须给出依据（BR-04）」")
            cm.locator("textarea").first.fill("方案1 自主可控，得分差距在可接受范围内")
            page.wait_for_timeout(300)
            # VT-MODAL-44 填决策依据
            rec(not csub.is_disabled(), "VT-MODAL-44 填了依据 → 可提交")
            csub.click()
            page.wait_for_timeout(1400)
            r4 = row("DC-004")
            rec("已决策" in r4.inner_text()
                and r4.locator('[data-role="chosen"]').inner_text() == "方案1：自建地面站",
                # VT-MODAL-45 提交决策
                "VT-MODAL-45 提交后：状态「已决策」+ 选中方案方案1")
            rec(r4.locator('button:has-text("编辑"):visible').count() == 0
                and r4.locator('button:has-text("权衡打分"):visible').count() == 0,
                "VT-MODAL-46 已决策 → 行内「编辑」「权衡打分」入口消失（BR-06 冻结）")

            m = open_detail("DC-004", "view")
            hint = m.locator('[data-role="frozen-hint"]')
            rec(hint.count() == 1 and "已作出决策（结论是快照）" in hint.inner_text(),
                "VT-MODAL-46 详情提示「已作出决策（结论是快照）—— 内容、准则与备选方案已冻结」")
            rec(m.locator('button:has-text("保存"):visible').count() == 0
                and m.locator('input[placeholder*="评价准则"]:visible').count() == 0
                and m.locator('input[placeholder*="备选方案名称"]:visible').count() == 0,
                "VT-MODAL-46 详情无「保存」「加准则」「加方案」入口")
            rec("方案1 自主可控" in m.locator('[data-role="modal-rationale"]').inner_text(),
                "VT-MODAL-46 详情只读回显决策依据")
            m.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(400)

            # ── §6 实施（F-7 / F-8）─────────────────────────
            step("§6 实施与终态（VT-ACT-51..VT-ACT-53）")
            page.on("dialog", lambda d: d.accept())      # 实施二次确认
            rec(row("DC-001").locator('button:has-text("实施"):visible').count() == 0
                and row("DC-001").locator('button:has-text("编辑"):visible').count() == 0,
                "VT-ACT-51 已实施的 DC-001 无「实施」「编辑」（终态）")
            row("DC-004").locator('button:has-text("实施"):visible').click()
            page.wait_for_timeout(1400)
            r4 = row("DC-004")
            rec("已实施" in r4.inner_text()
                and r4.locator('button:has-text("实施"):visible').count() == 0
                and r4.locator('button:has-text("编辑"):visible').count() == 0,
                # VT-ACT-52 对「已决策」的 `DC-004` 点「实施」（二次确认）
                "VT-ACT-52 实施后：状态「已实施」+ 终态无动作按钮")
            m = open_detail("DC-004", "view")
            hint2 = m.locator('[data-role="frozen-hint"]')
            rec(hint2.count() == 1 and "已实施（终态）" in hint2.inner_text(),
                "VT-ACT-53 已实施详情提示「已实施（终态）—— 不能再修改」")
            m.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(400)

            # ── §7 筛选（F-9）───────────────────────────────
            step("§7 筛选（VT-FILTER-71..VT-FILTER-74）")
            # ⚠ 期望值按**实际动作序列**重算：DC-001 已实施 / DC-002 已决策 /
            #   DC-003 权衡中 / DC-004 已实施（§6 刚实施）/ DC-005 提出
            page.locator("select").first.select_option("utility")     # 评价方法 = 效用分析
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "DC-005" in rows().first.inner_text(),
                f"VT-FILTER-71 评价方法=效用分析 → {rows().count()} 行（DC-005）")
            page.locator("select").first.select_option("")
            page.wait_for_timeout(600)
            page.locator("select").nth(1).select_option("implemented")   # 状态 = 已实施
            page.wait_for_timeout(900)
            rec(rows().count() == 2
                and sorted(x.inner_text()[:6] for x in rows().all()) == ["DC-001", "DC-004"],
                # VT-FILTER-72 清方法，状态筛「已实施」
                f"VT-FILTER-72 状态=已实施 → {rows().count()} 行（DC-001 / DC-004）")
            page.locator("select").nth(1).select_option("weighing")
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "DC-003" in rows().first.inner_text(),
                # VT-FILTER-73 状态筛「权衡中」
                f"VT-FILTER-73 状态=权衡中 → {rows().count()} 行（DC-003）")
            page.locator("select").nth(1).select_option("")
            page.wait_for_timeout(600)
            page.locator('input[placeholder="责任人"]').fill("评审员")
            page.keyboard.press("Enter")
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "DC-005" in rows().first.inner_text(),
                f"VT-FILTER-74 责任人=评审员 → {rows().count()} 行（DC-005）")
            page.locator('input[placeholder="责任人"]').fill("")
            page.keyboard.press("Enter")
            page.wait_for_timeout(900)
            rec(rows().count() == 5, f"VT-FILTER-74 清空条件 → {rows().count()} 行（全部 5 条）")

            # ── §8b 来源度量 / 责任人候选（datalist ← technical_measure.list / stakeholder.list）──
            step("§8b 来源度量与责任人候选（VT-SUG-75..VT-SUG-77）")
            page.click('button:has-text("新建议题")')
            page.wait_for_timeout(500)
            f3 = page.locator(".modal-mask:visible").last
            tm = f3.locator("datalist#tm-options-form option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            sh = f3.locator("datalist#sh-options-form option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            rec(len(tm) >= 1, f"VT-SUG-75 新建表单「来源度量」候选 {len(tm)} 项（来自 technical_measure.list）")
            rec(any(v.startswith("TPM-") for v in tm), f"VT-SUG-75 候选值=度量编号、标签含名称：{tm[:2]}")
            # VT-SUG-76 新建表单：读 `datalist#sh-options-form`
            rec(len(sh) >= 2, f"VT-SUG-76 新建表单「责任人」候选 {len(sh)} 项（来自 stakeholder.list）")
            rec(f3.locator('input[list="tm-options-form"]').count() == 1
                and f3.locator('input[list="sh-options-form"]').count() == 1,
                "VT-SUG-77 两处仍是**文本输入**（不是 select）")
            f3.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)
            page.locator("table.tbl tr.data button.b-link").first.click()
            page.wait_for_timeout(900)
            m2 = page.locator(".modal-mask:visible").last
            tm2 = m2.locator("datalist#tm-options-modal option").count()
            sh2 = m2.locator("datalist#sh-options-modal option").count()
            rec(tm2 >= 1 and sh2 >= 2, f"VT-SUG-77 详情模态候选：度量 {tm2} 项 / 责任人 {sh2} 项")
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
    rec(not errors, f"0 console error / 0 pageerror / 0 HTTP>=400（实际 {len(errors)}）")
    for e in errors[:8]:
        print("      [X]", e)

    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    for s, ok, note in bad:
        print(f"    [X] {s} | {note}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
