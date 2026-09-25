"""e2e 前端验收 - nasa_pms:risk（风险台账 · 独立创建）。

断言：新建入口存在 → 列表 4 行 → **F-1** 风险等级恒为推导只读值（表单/模态里都没有等级控件）→
**F-2** 关闭必须选处置结论（未选则确认按钮禁用）→ **F-3** 等级为高/严重时「接受」不可选 →
**F-4** 风险编号只读 → **F-5** 类别/可能性/后果为下拉字典 → **F-6** 终态行不再显示动作按钮 →
**F-7** 「受影响需求」下拉来自跨应用 requirement.list → **F-8** 筛选收敛 →
全程 0 console error / 0 pageerror / 0 HTTP≥400。

用例来源：app/nasa_pms/risk/前端测试用例.md（§0 造数 + §1..§7）。
运行：python app/nasa_pms/tests/verify_view_nasa_pms_risk.py
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


# §0 自足造数：2 条需求（供跨应用下拉）+ 4 条风险，覆盖四个状态与三个等级
#     ⚠ 造数走 REST 而非 UI：避免用例依赖"新建功能本身是否正确"（那是 §2 的覆盖对象）
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
    statement: "8vCPU/32GB 下 P95 ≤ 2s", req_type: "technical", verify_method: "test"});
  await call("nasa_pms/requirement", "create", {title: "接口应符合 ICD-001",
    statement: "接口数据项与 ICD-001 一致", req_type: "interface", verify_method: "inspection"});
  // RSK-001 技术风险 4×4=16 严重 → 缓解 → 以「转移」关闭（终态）
  await call("nasa_pms/risk", "create", {title: "ICD 未按期冻结",
    statement: "接口文档未在 PDR 前冻结将导致集成返工", category: "technical",
    likelihood: 4, consequence: 4, req_no: "REQ-001", owner: "张三"});
  await call("nasa_pms/risk", "mitigate", {risk_no: "RSK-001", mitigation: "提前开展接口冻结评审"});
  await call("nasa_pms/risk", "close", {risk_no: "RSK-001", disposition: "transferred", note: "转移给承包商"});
  // RSK-002 进度风险 未评估 → 识别
  await call("nasa_pms/risk", "create", {title: "长周期器件交期不确定",
    statement: "FPGA 采购周期若超 26 周将使总装节点后移", category: "schedule"});
  // RSK-003 成本风险 3×4=12 高 → 评估 → 缓解（未终态）
  await call("nasa_pms/risk", "create", {title: "性能优化工作量低估",
    statement: "性能优化若超预算将挤占验证经费", category: "cost"});
  await call("nasa_pms/risk", "assess", {risk_no: "RSK-003", likelihood: 3, consequence: 4});
  await call("nasa_pms/risk", "mitigate", {risk_no: "RSK-003", mitigation: "把性能优化拆成两批，先保 P95"});
  // RSK-004 安全风险 2×2=4 低 → 评估
  await call("nasa_pms/risk", "create", {title: "地面供电中断",
    statement: "测试期间地面供电中断将损坏样机", category: "safety"});
  await call("nasa_pms/risk", "assess", {risk_no: "RSK-004", likelihood: 2, consequence: 2});
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

            step("§0 造数（2 条需求 + 4 条风险，覆盖 识别/分析中/缓解中/已关闭）")
            seed = page.evaluate(SEED_JS)
            rec(bool(seed and seed.get("seeded")), "造数完成")

            # ── §1 渲染与入口 ────────────────────────────────
            step("§1 渲染与入口（VT-ROUTE-01..VT-ROUTE-05）")

            page.evaluate("location.hash = '#/risk'")
            page.wait_for_selector('button:has-text("新建风险")', timeout=10000)
            page.wait_for_timeout(900)
            body = page.locator("main").inner_text()
            rec("风险台账" in body, "VT-ROUTE-01 标题「风险台账」可见")
            rows = page.locator("table.tbl tr.data")
            rec(rows.count() == 4, f"VT-ROUTE-01 列表 {rows.count()} 行（期望 4）")
            # VT-ROUTE-05b 未评估的风险：状态「识别」、风险值与等级显示「—」
            row_ns = page.locator("table.tbl tr.data").filter(has_text="RSK-002").first
            txt_ns = row_ns.inner_text()
            rec("识别" in txt_ns, f"VT-ROUTE-05b 未评估行状态=识别：{txt_ns[:40]!r}")
            rec("—" in txt_ns, "VT-ROUTE-05b 未评估行：风险值/等级显示「—」")
            heads = page.locator("table.tbl tr").first.inner_text()
            rec(all(h in heads for h in ("风险编号", "标题", "风险类别", "风险值", "风险等级", "状态", "责任人")),
                # VT-ROUTE-02 表头
                "VT-ROUTE-02 表头完整")
            # VT-ROUTE-03 **保留新建入口**
            rec(page.locator('button:has-text("新建风险")').count() > 0, "VT-ROUTE-03 保留新建入口")
            first = rows.first.inner_text()
            rec("技术风险" in first and "严重" in first and "已关闭" in first and "16" in first,
                # VT-ROUTE-04 首行内容
                "VT-ROUTE-04 首行显示 技术风险/严重/已关闭/风险值 16")
            # F-6：终态行不再有任何动作按钮（x-if 移出 DOM，不只是隐藏）
            row1 = page.locator("table.tbl tr.data").filter(has_text="RSK-001").first
            rec(row1.locator('button:has-text("编辑")').count() == 0
                and row1.locator('button:has-text("评估")').count() == 0
                and row1.locator('button:has-text("关闭")').count() == 0,
                "VT-ROUTE-05 已关闭行不显示 编辑/评估/关闭")
            # 未评估的风险：风险值与等级为「—」
            row2 = page.locator("table.tbl tr.data").filter(has_text="RSK-002").first
            t2 = row2.inner_text()
            rec("识别" in t2 and "—" in t2, "VT-ROUTE-05 未评估的风险：风险值/等级显示「—」")
            # VT-ROUTE-05c 动作入口与服务端**同口径**（2026-09-25 补 `close` 状态闸后同步）：
            #   · 未评估（RSK-002）→ 有「评估」、**没有**「缓解」（服务端要求已评估）、**没有**「关闭」
            #   · 缓解中（RSK-003）→ **有**「关闭」
            #   两处都用 x-if 移出 DOM（不是 x-show），所以 count() 能直接判在不在。
            rec(row2.locator('button:has-text("评估")').count() == 1
                and row2.locator('button:has-text("缓解")').count() == 0
                and row2.locator('button:has-text("关闭")').count() == 0,
                "VT-ROUTE-05c 未评估行：有「评估」、无「缓解」无「关闭」")
            row3 = page.locator("table.tbl tr.data").filter(has_text="RSK-003").first
            rec(row3.locator('button:has-text("关闭")').count() == 1,
                "VT-ROUTE-05c 缓解中行：有「关闭」（只有这一态可关闭）")

            # ── §2 新建表单（F-1 / F-5 / F-7）─────────────────
            step("§2 新建表单（VT-FORM-11..VT-FORM-19）")
            page.click('button:has-text("新建风险")')
            page.wait_for_timeout(400)
            form = page.locator(".modal-mask:visible").last
            rec(form.locator("textarea").count() > 0, "VT-FORM-11 新建模态出现")
            rec(form.locator("label").filter(has_text="风险等级").count() == 0,
                # VT-FORM-12 **F-1 等级无控件**
                "VT-FORM-12 F-1 表单里没有「风险等级」控件（等级只能推导）")
            submit = form.locator('button:has-text("提交")')
            # VT-FORM-13 未填标题/情景
            rec(submit.is_disabled(), "VT-FORM-13 未填标题/情景 → 提交 disabled")
            form.locator("input").first.fill("软件基线冻结延期")
            page.wait_for_timeout(200)
            # VT-FORM-14 只填标题
            rec(submit.is_disabled(), "VT-FORM-14 只填标题 → 仍 disabled")
            form.locator("textarea").first.fill("基线冻结若延期将导致验证项无法按时开展")
            page.wait_for_timeout(300)
            # VT-FORM-15 标题+情景齐备
            rec(not submit.is_disabled(), "VT-FORM-15 标题+情景齐备 → 可提交")
            # F-5 字典下拉
            form.locator("select").nth(0).select_option("programmatic")   # 风险类别
            form.locator("select").nth(1).select_option("5")              # 可能性
            form.locator("select").nth(2).select_option("5")              # 后果
            # F-7 受影响需求下拉来自跨应用 requirement.list
            req_opts = form.locator("select").nth(3).locator("option").all_inner_texts()
            rec(any("REQ-001" in t for t in req_opts) and any("REQ-002" in t for t in req_opts),
                # VT-FORM-16 **F-7 跨应用下拉**
                f"VT-FORM-16 F-7 受影响需求下拉含 REQ-001/REQ-002（跨应用）")
            form.locator("select").nth(3).select_option("REQ-002")
            form.locator("input").nth(1).fill("王五")                    # 责任人
            page.wait_for_timeout(200)
            submit.click()
            page.wait_for_timeout(1200)
            # VT-FORM-17 提交（类别=程序性风险、5×5、关联 REQ-002）
            rec(page.locator("table.tbl tr.data").count() == 5, "VT-FORM-17 新建成功，列表变 5 行")
            newrow = page.locator("table.tbl tr.data").filter(has_text="RSK-005").first.inner_text()
            # VT-FORM-18 **F-1 新建即推导**
            rec("严重" in newrow and "25" in newrow, "VT-FORM-18 F-1 新建即推导等级：5×5 → 严重(25)")
            page.click('button:has-text("新建风险")')
            page.wait_for_timeout(400)
            form2 = page.locator(".modal-mask:visible").last
            rec(form2.locator("input").first.input_value() == "", "VT-FORM-19 表单已重置")
            form2.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)

            # ── §3 详情 / 编辑（F-1 / F-4）────────────────────
            step("§3 详情与编辑（VT-MODAL-21..VT-MODAL-25）")
            row4 = page.locator("table.tbl tr.data").filter(has_text="RSK-004").first
            row4.locator('button:has-text("详情")').click()
            page.wait_for_timeout(900)
            m = page.locator(".modal-mask:visible").last
            head = m.locator('[data-role="risk-head"]').inner_text()
            rec("RSK-004" in head and "低" in head and "4" in head and "分析中" in head,
                f"VT-MODAL-21 只读信息条：编号/等级 低/风险值 4/状态 分析中 —— 「{head}」")
            # VT-MODAL-22 **F-1 等级为徽标文本**
            rec(m.locator("span.st").filter(has_text="低").count() >= 1, "VT-MODAL-22 F-1 等级为徽标文本，非输入框")
            rec(m.locator("input").nth(0).is_disabled() and m.locator("select").nth(2).is_disabled(),
                # VT-MODAL-23 **F-4 只读视图**
                "VT-MODAL-23 F-4 只读视图：标题与可能性均 disabled")
            m.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(300)
            row4.locator('button:has-text("编辑")').click()
            page.wait_for_timeout(900)
            m2 = page.locator(".modal-mask:visible").last
            # VT-MODAL-24 点「编辑」
            rec(not m2.locator("input").nth(0).is_disabled(), "VT-MODAL-24 编辑态标题可输入")
            m2.locator("input").nth(0).fill("地面供电中断（已复核）")
            m2.locator('button:has-text("保存")').first.click()
            page.wait_for_timeout(1200)
            t4 = page.locator("table.tbl tr.data").filter(has_text="RSK-004").first.inner_text()
            rec("已复核" in t4, "VT-MODAL-25 编辑保存后列表回显新标题")

            # ── §4 评估（F-1 的落点：等级只能经评估改变）──────
            step("§4 评估（VT-ACT-31..VT-ACT-32）")
            row2 = page.locator("table.tbl tr.data").filter(has_text="RSK-002").first
            row2.locator('button:has-text("评估")').click()
            page.wait_for_timeout(900)
            m = page.locator(".modal-mask:visible").last
            rec(not m.locator("select").nth(2).is_disabled(), "VT-ACT-31 评估态：可能性下拉可用")
            m.locator("select").nth(2).select_option("5")
            m.locator("select").nth(3).select_option("5")
            page.wait_for_timeout(300)
            m.locator('button:has-text("重评等级")').first.click()
            page.wait_for_timeout(1200)
            t2 = page.locator("table.tbl tr.data").filter(has_text="RSK-002").first.inner_text()
            rec("严重" in t2 and "25" in t2 and "分析中" in t2,
                "VT-ACT-32 评估后 等级=严重 / 风险值=25 / 状态=分析中")

            # ── §5 关闭（F-2 / F-3 / F-6）────────────────────
            step("§5 关闭（VT-ACT-41..VT-ACT-46）")
            row3 = page.locator("table.tbl tr.data").filter(has_text="RSK-003").first
            row3.locator('button:has-text("关闭")').click()
            page.wait_for_timeout(900)
            m = page.locator(".modal-mask:visible").last
            conf = m.locator('button:has-text("确认关闭")').first
            rec(conf.is_disabled(), "VT-ACT-41 F-2 未选处置结论 → 确认关闭 disabled")
            dispo = m.locator("select").last
            opt_acc = dispo.locator('option[value="accepted"]')
            opt_mit = dispo.locator('option[value="mitigated"]')
            rec(opt_acc.evaluate("el => el.disabled") is True,
                # VT-ACT-42 展开处置结论下拉
                "VT-ACT-42 F-3 等级=高 → 「接受」选项 disabled（BR-03）")
            rec(opt_mit.evaluate("el => el.disabled") is False,
                # VT-ACT-43 同上
                "VT-ACT-43 已登记缓解措施 → 「缓解完成」可选（BR-02）")
            dispo.select_option("mitigated")
            page.wait_for_timeout(300)
            # VT-ACT-44 选「缓解完成」
            rec(not conf.is_disabled(), "VT-ACT-44 选了处置结论 → 确认关闭可点")
            conf.click()
            page.wait_for_timeout(1200)
            row3 = page.locator("table.tbl tr.data").filter(has_text="RSK-003").first
            t3 = row3.inner_text()
            # VT-ACT-45 点「确认关闭」
            rec("已关闭" in t3, "VT-ACT-45 状态变「已关闭」")
            rec(row3.locator('button:has-text("编辑")').count() == 0
                and row3.locator('button:has-text("关闭")').count() == 0,
                "VT-ACT-45 F-6 终态行动作按钮消失")

            step("§5b 处置结论回显（BR-02 落库）")
            row3 = page.locator("table.tbl tr.data").filter(has_text="RSK-003").first
            row3.locator('button:has-text("详情")').click()
            page.wait_for_timeout(900)
            m3 = page.locator(".modal-mask:visible").last
            head3 = m3.locator('[data-role="risk-head"]').inner_text()
            rec("已关闭" in head3 and "缓解完成" in head3,
                # VT-ACT-46 再开该行详情
                f"VT-ACT-46 处置结论已落库并回显 —— 「{head3}」")
            m3.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(300)

            # ── §6 筛选（F-8）──────────────────────────────
            step("§6 筛选（VT-FILTER-51..VT-FILTER-53）")
            page.locator("select").nth(0).select_option("technical")   # 风险类别
            page.wait_for_timeout(900)
            n = page.locator("table.tbl tr.data").count()
            rec(n == 1 and "RSK-001" in page.locator("table.tbl tr.data").first.inner_text(),
                f"VT-FILTER-51 类别=技术风险 → {n} 行（RSK-001）")
            page.locator("select").nth(0).select_option("")            # 清类别
            page.locator("select").nth(1).select_option("closed")      # 状态
            page.wait_for_timeout(900)
            nos = page.locator("table.tbl tr.data").count()
            # VT-FILTER-52 清类别、状态筛「已关闭」
            rec(nos == 2, f"VT-FILTER-52 状态=已关闭 → {nos} 行")
            page.locator("select").nth(1).select_option("")
            page.wait_for_timeout(700)
            rec(page.locator("table.tbl tr.data").count() == 5, "VT-FILTER-53 清筛选 → 恢复 5 行")

            # ── §6b 终态行不给「编辑」入口（与服务端 `_check_mutable`（BR-06）同口径）──
            # ⚠ 这是**正例**断言：负例挡不住这类缺陷（服务端会拒、UI 却给按钮 → 用户撞永远存不下的保存）
            step("§6b 终态禁编辑入口（VT-SUG-55..VT-SUG-57）")
            page.locator("select").nth(1).select_option("closed")
            page.wait_for_timeout(900)
            rows = page.locator("table.tbl tr.data")
            n_rows = rows.count()
            vis = rows.first.locator('button:has-text("编辑"):visible').count()
            rec(n_rows >= 1 and vis == 0,
                f"已关闭 {n_rows} 行 · 可见的「编辑」按钮 {vis} 个（应为 0）")
            # 对照组：筛到**非终态**状态，编辑入口应当可见
            # ⚠ 别用"清筛选后的首行"当对照 —— 列表默认序下首行可能就是终态行，
            #   那时不显示「编辑」是**正确行为**（实测踩过：第一版断言这么写，假红）
            page.locator("select").nth(1).select_option("identified")
            page.wait_for_timeout(900)
            r2 = page.locator("table.tbl tr.data")
            n2 = r2.count()
            vis2 = r2.first.locator('button:has-text("编辑"):visible').count() if n2 else 0
            rec(n2 >= 1 and vis2 == 1,
                f"识别态 {n2} 行 · 可见的「编辑」按钮 {vis2} 个（应为 1）")
            page.locator("select").nth(1).select_option("")

            # ── §6b 责任人候选（datalist ← stakeholder.list）────────
            step("§6b 责任人候选（VT-SUG-55..VT-SUG-57）")
            page.click('button:has-text("新建风险")')
            page.wait_for_timeout(500)
            f3 = page.locator(".modal-mask:visible").last
            vals = f3.locator("datalist#sh-options-form option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            rec(len(vals) >= 2, f"VT-SUG-55 新建表单「责任人」候选 {len(vals)} 项（≥2，来自 stakeholder.list）")
            rec(any(v.startswith("候选人甲|") for v in vals), f"VT-SUG-55 候选值=姓名、标签含编号：{vals[:2]}")
            rec(f3.locator('input[list="sh-options-form"]').count() == 1,
                # VT-SUG-56 该控件类型
                "VT-SUG-56 责任人仍是**文本输入**（不是 select）")
            f3.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)
            page.locator("table.tbl tr.data button.b-link").first.click()
            page.wait_for_timeout(900)
            m2 = page.locator(".modal-mask:visible").last
            vals2 = m2.locator("datalist#sh-options-modal option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            rec(len(vals2) >= 2, f"VT-SUG-57 详情模态「责任人」候选 {len(vals2)} 项")
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
