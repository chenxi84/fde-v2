"""e2e 前端验收 - nasa_pms:tech_plan（技术计划台账 · 独立创建 + 聚合内版本台账 + 覆盖矩阵查询视图）。

断言：新建入口存在 → 列表 7 行（草稿 / 审批中 / 已批准 / 已修订 四态同屏）→
**F-1** 三项必填未齐则提交禁用 → **F-2** 草稿态内容可改（本页语义差的前半）→
**F-3** 已批准 / 审批中两条锁定路径**各有解锁入口**（修订 / 撤回，互不混淆）→
**F-4** 提交审批（提交后内容锁定）→ **F-5** 撤回（回提交前状态）→ **F-6** 批准记名 + 落版本台账 →
**F-7** 批准被 I-1（同阶段同类型唯一）拦下时前端只报错不改状态 → **F-8** 修订：版本递增 + 阶段推进 →
**F-9** 版本台账是快照（推进后旧版本行不改写）→ **F-10** 覆盖矩阵（查询视图）缺口与覆盖来源 →
**F-11** 动作按钮按状态显隐 → **F-12** 筛选。
全程 0 console error / 0 pageerror / 0 HTTP>=400。

用例来源：app/nasa_pms/tech_plan/前端测试用例.md（§0 造数 + §1..§14）。
运行：python app/nasa_pms/tests/verify_view_nasa_pms_tech_plan.py
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
# 其后用例也不再执行 —— 实测 stakeholder 的 VT-ROUTE-32 就这么"消失"过）。与 scripts/run_gates.py 给
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


# §0 自足造数：7 份计划（**草稿 / 审批中 / 已批准 / 已修订** 四态同屏）+ 4 条版本台账。
# 走 REST，不经 UI —— 避免用例依赖"新建功能本身"（那是 §5 的覆盖对象）。
# ⚠ REST 路径必须用**组限定名** `nasa_pms/tech_plan`（短名 404「应用不存在」）。
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
  const TP = "nasa_pms/tech_plan";
  // PLAN-001 系统工程管理计划：V1 批准 → 修订推进到 B 阶段 → V2 批准 ⇒ **已批准 V2（台账 2 行）**
  await call(TP, "create", {name: "系统工程管理计划", plan_type: "semp", phase: "a",
                            maturity: "preliminary", owner: "张三",
                            scope: "系统工程过程与 17 项共性技术过程"});
  await call(TP, "submit", {plan_no: "PLAN-001"});
  await call(TP, "approve", {plan_no: "PLAN-001", approver: "李四", note: "SRR 前批准"});
  await call(TP, "revise", {plan_no: "PLAN-001", summary: "阶段推进到 B 阶段，过程裁剪口径更新",
                            phase: "b", maturity: "baseline"});
  await call(TP, "submit", {plan_no: "PLAN-001"});
  await call(TP, "approve", {plan_no: "PLAN-001", approver: "李四"});
  // PLAN-002 验证与确认计划：**已批准 V1**（A 阶段，覆盖矩阵里「此刻生效」的那一支）
  await call(TP, "create", {name: "验证与确认计划", plan_type: "verification", phase: "a",
                            maturity: "preliminary", owner: "李四"});
  await call(TP, "submit", {plan_no: "PLAN-002"});
  await call(TP, "approve", {plan_no: "PLAN-002", approver: "李四"});
  // PLAN-003 集成计划：**审批中**（C 阶段缺口；§6 由 UI 走 撤回 → 再提交）
  await call(TP, "create", {name: "集成计划", plan_type: "integration", phase: "c", owner: "王五"});
  await call(TP, "submit", {plan_no: "PLAN-003"});
  // PLAN-004 人因集成计划：**草稿**（B 阶段缺口）
  await call(TP, "create", {name: "人因集成计划", plan_type: "hsi", phase: "b", owner: "赵六"});
  // PLAN-005 技术开发计划：批准 V1 → 修订 ⇒ **已修订 V2（台账 1 行）**，成熟度可用「更新」
  await call(TP, "create", {name: "技术开发计划", plan_type: "technology_dev", phase: "d",
                            maturity: "preliminary", owner: "王五"});
  await call(TP, "submit", {plan_no: "PLAN-005"});
  await call(TP, "approve", {plan_no: "PLAN-005", approver: "王五"});
  await call(TP, "revise", {plan_no: "PLAN-005", summary: "D 阶段技术成熟度方案更新",
                            maturity: "update"});
  // PLAN-006 配置管理计划：**草稿**（E 阶段缺口；§3 由 UI 改内容）
  await call(TP, "create", {name: "配置管理计划", plan_type: "cm", phase: "e", owner: "孙七"});
  // PLAN-007 验证与确认计划（另起一份）：**审批中**，与 PLAN-002 同阶段同类型
  //   ⇒ §8 由 UI 点「批准」，验证前端把 I-1 的拒绝原样呈现且**状态不变**
  await call(TP, "create", {name: "验证与确认计划（另起一份）", plan_type: "verification",
                            phase: "a", maturity: "preliminary"});
  await call(TP, "submit", {plan_no: "PLAN-007"});
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
            # 提交审批 / 撤回 / 修订都要二次确认 —— 挂上自动接受（默认行为是**驳回**，动作会静默不发生）
            page.on("dialog", lambda d: d.accept())
            page.goto(f"{base}/view/nasa_pms/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)

            step("§0 造数（7 份计划：草稿 2 / 审批中 2 / 已批准 2 / 已修订 1 + 4 条版本台账）")
            seed = page.evaluate(SEED_JS)
            rec(bool(seed and seed.get("seeded")),
                "PLAN-001 已批准V2 · PLAN-002 已批准V1 · PLAN-003/007 审批中 · "
                "PLAN-004/006 草稿 · PLAN-005 已修订V2")

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
                for _ in range(5):
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

            def cov_rows():
                return page.locator('[data-role="cov-row"]')

            def cov_pick(phase_cn):
                page.locator(f'[data-role="cov-phases"] .fchip:has-text("{phase_cn}")').click()
                page.wait_for_timeout(900)

            def cov_row(type_txt):
                return cov_rows().filter(has_text=type_txt).first

            # ── §1 渲染与入口 ────────────────────────────────
            step("§1 渲染与入口（VT-ROUTE-01..VT-ROUTE-05）")
            page.evaluate("location.hash = '#/tech_plan'")
            page.wait_for_selector('button:has-text("新建计划")', timeout=10000)
            page.wait_for_timeout(1200)
            rec(rows().count() == 7, f"VT-ROUTE-01 列表 {rows().count()} 行（期望 7）")
            heads = page.locator("table.tbl tr").first.inner_text()
            rec(all(h in heads for h in ("计划编号", "名称", "计划类型", "覆盖阶段", "成熟度",
                                         "版本", "已批准版本", "批准人", "状态")),
                # VT-ROUTE-02 表头完整性
                "VT-ROUTE-02 表头完整")
            rec(page.locator('button:has-text("新建计划"):visible').count() == 1,
                # VT-ROUTE-03 **保留新建入口**
                "VT-ROUTE-03 保留新建入口（独立创建）")
            # ⚠ 不用 `select:visible` 的 nth 下标钉筛选控件 —— 平台壳的 Agent 右栏自带一个
            #    会话选择器，数量会随壳的实现变化；本页的选择器一律带 `data-role`，按语义取。
            t = page.locator('[data-role="f-type"] option').all_inner_texts()
            ph = page.locator('[data-role="f-phase"] option').all_inner_texts()
            st = page.locator('[data-role="f-status"] option').all_inner_texts()
            # VT-ROUTE-04 **筛选下拉按语义钉住**
            rec(len(t) == 9 and t[0] == "全部计划类型", "VT-ROUTE-04 计划类型筛选（8 类 + 全部）")
            rec(len(ph) == 7 and ph[0] == "全部阶段", "VT-ROUTE-04 阶段筛选（6 阶段 + 全部）")
            rec(len(st) == 5 and st[0] == "全部状态", "VT-ROUTE-04 状态筛选（4 态 + 全部）")
            t1 = row("PLAN-001").inner_text()
            rec("系统工程管理计划（SEMP）" in t1 and "B 阶段" in t1 and "基线（Baseline）" in t1
                and "V2" in t1 and "李四" in t1 and "已批准" in t1,
                "VT-ROUTE-05 PLAN-001：SEMP / B 阶段 / 基线 / V2 / 李四 / 已批准（推进后的当前版本）")
            rec("阶段推进到 B 阶段" not in t1,
                "VT-ROUTE-05 修订说明是**默认隐藏列**（BR/坑 10：藏了就不该在行文本里）")
            t3 = row("PLAN-003").inner_text()
            rec("集成计划（Integration Plan）" in t3 and "C 阶段" in t3
                and "方法（Approach）" in t3 and "审批中" in t3,
                "VT-ROUTE-05 PLAN-003：集成计划 / C 阶段 / 方法（缺省成熟度）/ 审批中")
            rec("已修订" in row("PLAN-005").inner_text()
                and "更新（Update）" in row("PLAN-005").inner_text(),
                "VT-ROUTE-05 PLAN-005：已修订 / 成熟度「更新」（BR-07：已有基线才谈得上更新）")
            rec("草稿" in row("PLAN-004").inner_text() and "草稿" in row("PLAN-006").inner_text(),
                "VT-ROUTE-05 PLAN-004 / PLAN-006：草稿")

            # ── §2 阶段覆盖矩阵（查询视图）────────────────────
            step("§2 阶段覆盖矩阵（VT-COV-11..VT-COV-15）")
            rec(cov_rows().count() == 48,
                f"VT-COV-11 缺省「全部阶段」= 6 阶段 × 8 类型 = {cov_rows().count()} 格")
            rec("已覆盖 4 / 48 格" in page.locator('[data-role="cov-total"]').inner_text(),
                "VT-COV-11 覆盖计数：4/48（此时 PLAN-008 还没建）")
            cov_pick("B 阶段（Phase B）")
            # VT-COV-12 点 `B 阶段` chip
            rec(cov_rows().count() == 8, f"VT-COV-12 选 B 阶段 → {cov_rows().count()} 格")
            b_semp = cov_row("系统工程管理计划（SEMP）").inner_text()
            rec("已覆盖" in b_semp and "此刻生效" in b_semp and "PLAN-001 V2" in b_semp,
                "VT-COV-12 B 阶段 SEMP：由**此刻生效**的 PLAN-001 V2 覆盖")
            b_hsi = cov_row("人因集成计划（HSI Plan）").inner_text()
            rec("缺口" in b_hsi and "1" in b_hsi,
                # VT-COV-13 `B 阶段` 的 HSI 行
                "VT-COV-13 B 阶段 HSI：有 1 份计划但停在草稿 -> 缺口（I-1 的「至少一份」面）")
            cov_pick("A 阶段（Phase A）")
            a_semp = cov_row("系统工程管理计划（SEMP）").inner_text()
            rec("已覆盖" in a_semp and "历史版本" in a_semp and "PLAN-001 V1" in a_semp,
                # VT-COV-14 点 `A 阶段` chip
                "VT-COV-14 A 阶段 SEMP：计划已推进到 B，靠**版本台账里的 V1** 覆盖")
            a_ver = cov_row("验证与确认计划（V&V Plan）").inner_text()
            rec("已覆盖" in a_ver and "此刻生效" in a_ver and "PLAN-002 V1" in a_ver,
                "VT-COV-14 A 阶段 V&V：PLAN-002 此刻已批准（另起一份 PLAN-007 仍在审批中）")
            cov_pick("D 阶段（Phase D）")
            rec("已覆盖" in cov_row("技术开发计划").inner_text()
                and "历史版本" in cov_row("技术开发计划").inner_text(),
                "VT-COV-15 D 阶段技术开发计划：已修订 V2 -> 由台账 V1 覆盖")
            cov_pick("C 阶段（Phase C）")
            c_int = cov_row("集成计划（Integration Plan）").inner_text()
            rec("缺口" in c_int and "已覆盖 0 / 8 格" in
                page.locator('[data-role="cov-total"]').inner_text(),
                "VT-COV-15 C 阶段全缺口（集成计划只有审批中）")
            cov_pick("全部阶段")

            # ── §3 详情与编辑（草稿态可改 —— 本页语义差的前半）────
            step("§3 草稿态详情与编辑（VT-MODAL-21..VT-MODAL-24）")
            m = open_detail("PLAN-006", "view")
            head = m.locator('[data-role="plan-head"]').inner_text()
            rec("PLAN-006" in head and "草稿" in head and "V1" in head and "已批准 0 版" in head,
                "VT-MODAL-21 只读信息条：PLAN-006 / 草稿 / V1 / 已批准 0 版")
            rec("版本台账（0 版已批准）" in m.locator('[data-role="version-title"]').inner_text(),
                "VT-MODAL-21 版本台账为空（从未获批）")
            rec(m.locator('[data-role="frozen-hint"]:visible').count() == 0,
                "VT-MODAL-21 草稿态无「内容已锁定」提示")
            rec(m.locator('button:has-text("保存"):visible').count() == 0,
                "VT-MODAL-21 只读视图无「保存」")
            rec(m.locator('button:has-text("提交审批"):visible').count() == 1,
                "VT-MODAL-21 草稿态页脚出现「提交审批」")
            m.locator('button:has-text("关闭")').first.click()
            page.wait_for_timeout(400)

            m = open_detail("PLAN-006", "edit")
            rec(m.locator('[data-role="m-name"]').is_enabled()
                and m.locator('[data-role="m-type"]').is_enabled()
                and m.locator('[data-role="m-phase"]').is_enabled()
                and m.locator('[data-role="m-maturity"]').is_enabled(),
                # VT-MODAL-22 点「编辑」
                "VT-MODAL-22 **草稿态内容全可写**（名称 / 类型 / 覆盖阶段 / 成熟度）")
            m.locator('[data-role="m-name"]').fill("配置管理计划（含数据管理）")
            m.locator('[data-role="m-owner"]').fill("孙七")
            page.wait_for_timeout(300)
            m.locator('button:has-text("保存")').click()
            page.wait_for_timeout(1300)
            # VT-MODAL-23 改名 + 责任人 → 「保存」
            rec(page.locator(".modal-mask:visible").count() == 0, "VT-MODAL-23 保存后模态关闭")
            rec("配置管理计划（含数据管理）" in row("PLAN-006").inner_text()
                and "孙七" in row("PLAN-006").inner_text(),
                "VT-MODAL-24 草稿态改名已生效（F-2 的正面）")

            # ── §4 两条锁定路径各有解锁入口（本页语义差）────────
            step("§4 已批准 vs 审批中：锁定与解锁入口（VT-ROUTE-31..VT-ROUTE-33）")
            # ⚠ 已批准 / 审批中的行**没有「编辑」入口**（F-11 按状态显隐）—— 所以这里只能
            #    开只读详情：要断的不是"输框 disabled"（只读视图本来就 disabled、断不出东西），
            #    而是**为什么锁**与**往哪解锁**（提示文案点名的那条路径）。
            r1 = row("PLAN-001")
            rec(r1.locator('button:has-text("编辑"):visible').count() == 0,
                "VT-ROUTE-31 已批准行没有「编辑」入口（内容已锁）")
            m = open_detail("PLAN-001", "view")
            hint = m.locator('[data-role="frozen-hint"]:visible')
            rec(hint.count() == 1 and "已批准（第 2 版）" in hint.inner_text()
                and "「修订」出下一版" in hint.inner_text(),
                "VT-ROUTE-31 提示：解锁入口是「修订」（版本递增，不是原地改）")
            rec(m.locator('button:has-text("修订"):visible').count() == 1
                and m.locator('button:has-text("撤回"):visible').count() == 0,
                "VT-ROUTE-31 页脚只给「修订」（已批准的解锁路径）")
            close_all_modals()

            r3 = row("PLAN-003")
            rec(r3.locator('button:has-text("编辑"):visible').count() == 0,
                "VT-ROUTE-32 审批中行也没有「编辑」入口")
            m = open_detail("PLAN-003", "view")
            hint3 = m.locator('[data-role="frozen-hint"]:visible')
            rec(hint3.count() == 1 and "审批中" in hint3.inner_text()
                and "「撤回」再改" in hint3.inner_text(),
                "VT-ROUTE-32 提示：解锁入口是「撤回」（与已批准**不同**的一条路径）")
            rec(m.locator('button:has-text("撤回"):visible').count() == 1
                and m.locator('button:has-text("修订"):visible').count() == 0,
                "VT-ROUTE-32 审批中只有「撤回」，没有「修订」（两条锁定轴不混）")
            rec("「修订」出下一版" not in hint3.inner_text(),
                "VT-ROUTE-32 两条提示文案不同 —— 照抄别的页的单一 frozen() 会把它们弄成一句")
            close_all_modals()

            m = open_detail("PLAN-005", "view")
            rec("已修订" in m.locator('[data-role="plan-head"]').inner_text()
                and m.locator('[data-role="frozen-hint"]:visible').count() == 0,
                # VT-ROUTE-33 `PLAN-005`（已修订）
                "VT-ROUTE-33 已修订（V2 待提交）**不**算锁定态（本页没有终态）")
            rec(m.locator('button:has-text("提交审批"):visible').count() == 1
                and m.locator('button:has-text("修订"):visible').count() == 0,
                "VT-ROUTE-33 已修订的下一步是「提交审批」，不是再修订（BR-06）")
            rec(row("PLAN-005").locator('button:has-text("编辑"):visible').count() == 1,
                "VT-ROUTE-33 已修订行有「编辑」入口（内容还没定下来）")
            close_all_modals()

            # ── §5 新建计划（F-1 三项必填）───────────────────
            step("§5 新建计划（VT-FORM-41..VT-FORM-44）")
            page.click('button:has-text("新建计划")')
            page.wait_for_timeout(600)
            form = page.locator(".modal-mask:visible").last
            submit = form.locator('button:has-text("提交")')
            rec(form.locator('[data-role="n-type"]').count() == 1
                and form.locator('[data-role="n-phase"]').count() == 1,
                "VT-FORM-41 新建模态出现（计划类型 + 覆盖阶段两个下拉）")
            # VT-FORM-42 三项皆空 → 只填名称 → 只选类型
            rec(submit.is_disabled(), "VT-FORM-42 名称 / 类型 / 阶段皆空 -> 提交 disabled")
            form.locator('[data-role="n-name"]').fill("系统安全性计划（另建）")
            page.wait_for_timeout(250)
            rec(submit.is_disabled(), "VT-FORM-42 只填名称 -> 仍 disabled（类型与阶段都不给默认值）")
            form.locator('[data-role="n-type"]').select_option("review")
            page.wait_for_timeout(250)
            rec(submit.is_disabled(), "VT-FORM-42 选了类型 -> 仍 disabled（阶段也要）")
            form.locator('[data-role="n-phase"]').select_option("b")
            page.wait_for_timeout(300)
            # VT-FORM-43 补上阶段
            rec(not submit.is_disabled(), "VT-FORM-43 三项齐备 -> 可提交")
            submit.click()
            page.wait_for_timeout(1400)
            rec(rows().count() == 8, f"VT-FORM-44 新建成功，列表变 {rows().count()} 行（PLAN-008）")
            rec("草稿" in row("PLAN-008").inner_text() and "V1" in row("PLAN-008").inner_text(),
                "VT-FORM-44 新计划以「草稿 / V1」落库")

            # ── §6 提交审批（锁定）→ 撤回（解锁）→ 再提交 ───────
            step("§6 提交与撤回（VT-ACT-51..VT-ACT-54）")
            row("PLAN-008").locator('button:has-text("提交审批"):visible').click()
            page.wait_for_timeout(1400)
            r8 = row("PLAN-008")
            rec("审批中" in r8.inner_text()
                and r8.locator('button:has-text("编辑"):visible').count() == 0
                and r8.locator('button:has-text("批准"):visible').count() == 1,
                "VT-ACT-51 提交后：审批中 / 「编辑」消失 / 出现「批准」（F-4）")
            m = open_detail("PLAN-008", "view")
            # VT-ACT-52 打开详情
            rec(m.locator('[data-role="m-name"]').is_disabled(), "VT-ACT-52 详情里内容已 disabled")
            m.locator('button:has-text("撤回"):visible').click()
            page.wait_for_timeout(1500)
            rec("草稿" in row("PLAN-008").inner_text(),
                # VT-ACT-53 点「撤回」
                "VT-ACT-53 撤回后回「草稿」（V1 回草稿 —— 撤回不丢信息）")
            m = page.locator(".modal-mask:visible").first
            rec(m.locator('button:has-text("撤回"):visible').count() == 0
                and m.locator('button:has-text("提交审批"):visible').count() == 1,
                "VT-ACT-53 详情页脚回到「提交审批」这一步")
            close_all_modals()
            # ⚠ 「解锁真的解开了」必须在**编辑态**断 —— 只读视图的输框本来就 disabled，
            #    在那上面断言恒真（这是个会静默假过的写法）。
            rec(row("PLAN-008").locator('button:has-text("编辑"):visible').count() == 1,
                "VT-ACT-53 撤回后「编辑」入口回来了")
            m = open_detail("PLAN-008", "edit")
            rec(m.locator('[data-role="m-name"]').is_enabled()
                and m.locator('[data-role="frozen-hint"]:visible').count() == 0,
                "VT-ACT-53 撤回后编辑态内容可写、锁定提示消失（解锁真的解开了）")
            close_all_modals()
            row("PLAN-008").locator('button:has-text("提交审批"):visible').click()
            page.wait_for_timeout(1500)
            # VT-ACT-54 再「提交审批」
            rec("审批中" in row("PLAN-008").inner_text(), "VT-ACT-54 再提交 -> 审批中（停在待批）")

            # ── §7 批准（记名 + 落版本台账）──────────────────
            step("§7 批准（VT-ACT-61..VT-ACT-64）")
            close_all_modals()
            row("PLAN-008").locator('button:has-text("批准"):visible').click()
            page.wait_for_timeout(800)
            am = page.locator(".modal-mask:visible").last
            rec(am.locator('[data-role="am-hint"]').count() == 1, "VT-ACT-61 批准模态出现")
            abtn = am.locator('button:has-text("批准并落版本台账")')
            # VT-ACT-62 批准人空 → 填「李四」
            rec(abtn.is_disabled(), "VT-ACT-62 批准人未填 -> disabled（BR-08 记名）")
            am.locator('[data-role="am-approver"]').fill("李四")
            page.wait_for_timeout(300)
            rec(not abtn.is_disabled(), "VT-ACT-62 填了批准人 -> 可点")
            abtn.click()
            page.wait_for_timeout(1600)
            r8 = row("PLAN-008")
            rec("已批准" in r8.inner_text() and "V1" in r8.inner_text()
                and "李四" in r8.inner_text(),
                # VT-ACT-63 提交
                "VT-ACT-63 批准后：已批准 / 批准版本 V1 / 批准人 李四")
            m = open_detail("PLAN-008", "view")
            vrows = m.locator('[data-role="version-row"]')
            rec(vrows.count() == 1, f"VT-ACT-64 版本台账落 1 行（{vrows.count()}）")
            vr = vrows.first
            rec(vr.locator('[data-role="ver-no"]').inner_text() == "V1"
                and vr.locator('[data-role="ver-phase"]').inner_text() == "B 阶段"
                and vr.locator('[data-role="ver-maturity"]').inner_text() == "方法（Approach）"
                and vr.locator('[data-role="ver-approver"]').inner_text() == "李四",
                "VT-ACT-64 台账行：V1 / B 阶段 / 方法（当时快照）/ 李四（同事务落库）")
            close_all_modals()

            # ── §8 批准被 I-1 拦下（同阶段同类型唯一）───────────
            step("§8 批准被 I-1 拦下（VT-ACT-71..VT-ACT-72）")
            row("PLAN-007").locator('button:has-text("批准"):visible').click()
            page.wait_for_timeout(800)
            am7 = page.locator(".modal-mask:visible").last
            am7.locator('[data-role="am-approver"]').fill("钱七")
            page.wait_for_timeout(300)
            am7.locator('button:has-text("批准并落版本台账")').click()
            page.wait_for_timeout(1600)
            rec(page.locator(".modal-mask:visible").count() >= 1,
                "VT-ACT-71 被拒时批准模态不关闭（错误经 toast 呈现，不静默吞掉）")
            rec("审批中" in row("PLAN-007").inner_text()
                and row("PLAN-007").locator('[data-role="plan-approved-ver"]').inner_text() == "—"
                and row("PLAN-007").locator('[data-role="plan-approver"]').inner_text() == "—",
                "VT-ACT-72 PLAN-007（verification@a）仍为审批中、批准版本与批准人仍为「—」—— "
                "PLAN-002 已占该格子（I-1 / BR-03）")
            close_all_modals()

            # ── §9 修订（版本递增 + 阶段推进）────────────────
            step("§9 修订（VT-ACT-81..VT-ACT-85）")
            row("PLAN-008").locator('button:has-text("修订"):visible').click()
            page.wait_for_timeout(800)
            rm = page.locator(".modal-mask:visible").last
            rec(rm.locator('[data-role="rm-hint"]').count() == 1
                and "V1" in rm.locator('[data-role="rm-hint"]').inner_text()
                and "V2" in rm.locator('[data-role="rm-hint"]').inner_text(),
                "VT-ACT-81 修订模态给出「当前 V1 -> 修订后 V2」的提示")
            rvbtn = rm.locator('button:has-text("修订出新版本")')
            # VT-ACT-82 修订说明为空 → 填写
            rec(rvbtn.is_disabled(), "VT-ACT-82 修订说明为空 -> disabled（BR-06 留痕）")
            rm.locator("textarea").fill("阶段推进到 C 阶段，评审计划口径并入")
            rm.locator('[data-role="rm-phase"]').select_option("c")
            rm.locator('[data-role="rm-maturity"]').select_option("baseline")
            page.wait_for_timeout(300)
            rec(not rvbtn.is_disabled(), "VT-ACT-82 填了修订说明 -> 可点")
            rvbtn.click()
            page.wait_for_timeout(1600)
            r8 = row("PLAN-008")
            rec("已修订" in r8.inner_text() and "V2" in r8.inner_text()
                and "C 阶段" in r8.inner_text() and "基线（Baseline）" in r8.inner_text(),
                # VT-ACT-83 选「推进到 C 阶段」+ 成熟度「基线」→ 提交
                "VT-ACT-83 修订后：已修订 / V2 / 阶段推进到 C / 成熟度「基线」（I-2）")
            m = open_detail("PLAN-008", "view")
            rec(m.locator('[data-role="version-row"]').count() == 1
                and m.locator('[data-role="ver-no"]').first.inner_text() == "V1"
                and m.locator('[data-role="ver-phase"]').first.inner_text() == "B 阶段",
                # VT-ACT-84 详情里的版本台账
                "VT-ACT-84 台账仍 1 行且**是批准那一刻的快照**（V1@B 阶段）—— 修订不改写历史")
            rec("V2" in m.locator('[data-role="m-ver"]').inner_text()
                and "阶段推进到 C 阶段" in m.locator('[data-role="m-revise-note"]').inner_text(),
                "VT-ACT-85 主档：版本 V2（流转产物）+ 修订说明落库")
            close_all_modals()

            # ── §10 版本台账快照（推进后旧版本行不改写）────────
            step("§10 版本台账是快照（VT-SUB-91..VT-SUB-92）")
            m = open_detail("PLAN-001", "view")
            vrows = m.locator('[data-role="version-row"]')
            rec(vrows.count() == 2, f"VT-SUB-91 PLAN-001 台账 2 行（{vrows.count()}）")
            rec(vrows.nth(0).locator('[data-role="ver-phase"]').inner_text() == "A 阶段"
                and vrows.nth(0).locator('[data-role="ver-maturity"]').inner_text()
                == "初步（Preliminary）"
                and vrows.nth(1).locator('[data-role="ver-phase"]').inner_text() == "B 阶段"
                and vrows.nth(1).locator('[data-role="ver-maturity"]').inner_text()
                == "基线（Baseline）",
                "VT-SUB-92 V1@A 阶段·初步 / V2@B 阶段·基线（推进的两版都在，各自是当时的快照）")
            rec("版本台账（2 版已批准）" in m.locator('[data-role="version-title"]').inner_text(),
                "VT-SUB-92 台账标题反映已获批版本数")
            close_all_modals()

            # ── §11 覆盖矩阵复看（修订后缺口被填上）────────────
            step("§11 覆盖矩阵复看（VT-COV-101..VT-COV-103）")
            cov_pick("全部阶段")
            rec("已覆盖 5 / 48 格" in page.locator('[data-role="cov-total"]').inner_text(),
                "VT-COV-101 覆盖从 4/48 变 5/48（PLAN-008 批准过 V1）")
            cov_pick("B 阶段（Phase B）")
            rec("已覆盖" in cov_row("评审计划（Review Plan）").inner_text()
                and "历史版本" in cov_row("评审计划（Review Plan）").inner_text()
                and "已覆盖 2 / 8 格" in page.locator('[data-role="cov-total"]').inner_text(),
                # VT-COV-102 `B 阶段`
                "VT-COV-102 B 阶段新增「评审计划」一格（由 PLAN-008 的台账 V1@B 覆盖）")
            cov_pick("C 阶段（Phase C）")
            c_rev = cov_row("评审计划（Review Plan）").inner_text()
            rec("缺口" in c_rev and "1" in c_rev,
                "VT-COV-103 C 阶段「评审计划」：主档已推进到 C 但新版未批 -> 缺口 / 计划数 1")
            cov_pick("全部阶段")

            # ── §12 动作按钮按状态显隐（F-11）────────────────
            step("§12 动作按钮按状态显隐（VT-ACT-111..VT-ACT-111）")
            r4 = row("PLAN-004")
            rec(r4.locator('button:has-text("编辑"):visible').count() == 1
                and r4.locator('button:has-text("提交审批"):visible').count() == 1
                and r4.locator('button:has-text("批准"):visible').count() == 0
                and r4.locator('button:has-text("修订"):visible').count() == 0,
                "VT-ACT-111 草稿行：有「编辑」「提交审批」，无「批准」「修订」")
            r1 = row("PLAN-001")
            rec(r1.locator('button:has-text("修订"):visible').count() == 1
                and r1.locator('button:has-text("编辑"):visible').count() == 0
                and r1.locator('button:has-text("提交审批"):visible').count() == 0,
                "VT-ACT-111 已批准行：只有「修订」")
            r3 = row("PLAN-003")
            rec(r3.locator('button:has-text("批准"):visible').count() == 1
                and r3.locator('button:has-text("编辑"):visible').count() == 0
                and r3.locator('button:has-text("修订"):visible').count() == 0,
                "VT-ACT-111 审批中行：只有「批准」")
            r8 = row("PLAN-008")
            rec(r8.locator('button:has-text("编辑"):visible').count() == 1
                and r8.locator('button:has-text("提交审批"):visible').count() == 1
                and r8.locator('button:has-text("修订"):visible').count() == 0,
                "VT-ACT-111 已修订行：「编辑」「提交审批」（下一步是提交，不是再修订）")

            # ── §13 筛选（F-12）─────────────────────────────
            step("§13 筛选（VT-FILTER-121..VT-FILTER-125）")
            page.locator('[data-role="f-type"]').select_option("review")
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "PLAN-008" in rows().first.inner_text(),
                f"VT-FILTER-121 类型=评审计划 -> {rows().count()} 行")
            page.locator('[data-role="f-type"]').select_option("")
            page.wait_for_timeout(500)
            page.locator('[data-role="f-status"]').select_option("approved")
            page.wait_for_timeout(900)
            # VT-FILTER-122 状态 = 已批准
            rec(rows().count() == 2, f"VT-FILTER-122 状态=已批准 -> {rows().count()} 行"
                "（PLAN-001 / PLAN-002）")
            page.locator('[data-role="f-status"]').select_option("draft")
            page.wait_for_timeout(900)
            # VT-FILTER-123 状态 = 草稿
            rec(rows().count() == 2, f"VT-FILTER-123 状态=草稿 -> {rows().count()} 行"
                "（PLAN-004 / PLAN-006）")
            page.locator('[data-role="f-status"]').select_option("")
            page.wait_for_timeout(500)
            page.locator('[data-role="f-phase"]').select_option("c")
            page.wait_for_timeout(900)
            # VT-FILTER-124 阶段 = C 阶段
            rec(rows().count() == 2, f"VT-FILTER-124 阶段=C 阶段 -> {rows().count()} 行"
                "（PLAN-003 / PLAN-008）")
            page.locator('[data-role="f-phase"]').select_option("")
            page.wait_for_timeout(500)
            page.locator('[data-role="f-owner"]').fill("王五")
            page.keyboard.press("Enter")
            page.wait_for_timeout(900)
            rec(rows().count() == 2, f"VT-FILTER-125 责任人=王五 -> {rows().count()} 行"
                "（PLAN-003 / PLAN-005）")
            page.locator('[data-role="f-owner"]').fill("")
            page.keyboard.press("Enter")
            page.wait_for_timeout(700)

            # ── §8b 责任人候选（datalist ← stakeholder.list）────────
            # 跨应用只读候选：**值仍是文本姓名**（不落 sh_no，全组 owner 一致口径），
            # 故断言两件事 —— 候选确有数据 + 控件仍是文本输入（不是 select）。
            step("§8b 责任人候选（VT-SUG-132..VT-SUG-133）")
            page.click('button:has-text("新建计划")')
            page.wait_for_timeout(500)
            f3 = page.locator(".modal-mask:visible").last
            sh = f3.locator("datalist#sh-options-form option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            rec(len(sh) >= 2, f"VT-SUG-132 新建表单「责任人」候选 {len(sh)} 项（≥2，来自 stakeholder.list）")
            rec(any(v.startswith("候选人甲|") for v in sh), f"VT-SUG-132 候选值=姓名、标签含编号：{sh[:2]}")
            rec(f3.locator('input[list="sh-options-form"]').count() == 1,
                "VT-SUG-133 责任人仍是**文本输入**（不是 select —— 值即文本、回填天然正确）")
            f3.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)
            page.locator("table.tbl tr.data button.b-link").first.click()
            page.wait_for_timeout(900)
            m2 = page.locator(".modal-mask:visible").last
            sh2 = m2.locator("datalist#sh-options-modal option").count()
            rec(sh2 >= 2, f"VT-SUG-133 详情模态「责任人」候选 {sh2} 项")
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

    # ── §14 硬件指标 ────────────────────────────────────────
    step("§14 硬件指标（VT-HW-130..VT-HW-131）")
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
