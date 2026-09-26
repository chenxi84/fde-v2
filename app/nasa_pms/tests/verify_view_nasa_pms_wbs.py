"""e2e 前端验收 - nasa_pms:wbs（工作分解结构台账 · 自引用层级树 + 元素级配置控制）。

断言：列表与入口 → 新建顶层 / 加子元素（子号自动分配）→ **BR-04** 非产品词被拒 →
**BR-01** 编号必填 → **BR-05** 发起变更只认已批准（模态候选 + 后端校验）→ 落实变更后**版次 +1、
记修订授权** → **BR-03** 无范围出处不得基线 → **BR-06** 未收口不得关闭 / 草稿没有关闭入口 →
详情模态的字典字段（范围出处 / 关联需求 / 修订授权）→ 已基线无「编辑」入口（给的是「发起变更」）
→ 树视图缩进索引 → 全程 0 console error / 0 pageerror / 0 HTTP≥400。

用例来源：app/nasa_pms/wbs/前端测试用例.md（§0 造数 + §1..§6）。
运行：python app/nasa_pms/tests/verify_view_nasa_pms_wbs.py
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
shadow_clear_prefs()
atexit.register(_shadow.__exit__, None, None, None)

from fde_platform import users  # noqa: E402

# 输出编码：控制台代码页在本机默认是 GBK，而断言文案里有 ⇒ / ✓ / ✗ / ⚠ / − 这类**非 GBK 码位** ——
# 不钉住编码的话，print 自己会抛 UnicodeEncodeError（**崩在打印结果那一步**：断言算完了却报不出来）。
# 由 scripts/verify_test_script_encoding.py 守住这一行别被删。
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
#   两条需求（供 `coverage` 与「关联需求」字段）
#   一个**已批准**的变更请求 CR-001（供「发起变更」；后端 BR-05 会再校验一次）
#   一棵树：123456（已基线）/ 123456.01 星务分系统（已基线）/ 123456.01.01 星务计算机（草稿、无范围出处）
#          / 123456.02 载荷分系统（草稿、有范围出处）
# ⚠ REST 路径必须用**组限定名** `nasa_pms/wbs`（短名 404「应用不存在」）。
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
    return data && data.data !== undefined ? data.data : data;
  };
  const REQ = "nasa_pms/requirement", WBS = "nasa_pms/wbs";
  const CI = "nasa_pms/configuration_item", CR = "nasa_pms/change_request";
  const ACT = "nasa_pms/activity";

  await call(REQ, "create", {title: "星上存储器容量不小于 2 Tbit",
    statement: "在轨 5 年内不出现容量不足", req_type: "technical", verify_method: "test"});
  await call(REQ, "create", {title: "单圈观测时长不低于 12 分钟",
    statement: "单圈观测时长 ≥ 12 min", req_type: "system", verify_method: "analysis"});

  const ci = await call(CI, "create", {name: "星务软件", ci_type: "software"});
  const cr = await call(CR, "create", {title: "星务软件时序微调", requester: "星务分系统",
    ci_nos: ci.ci_no, description: "时序微调，需重新集成"});
  await call(CR, "analyze", {cr_no: cr.cr_no, impact_analysis: "影响星务软件时序，需复测"});
  await call(CR, "submit_review", {cr_no: cr.cr_no});
  await call(CR, "approve", {cr_no: cr.cr_no, comment: "同意", approver: "项目经理"});

  await call(WBS, "create", {wbs_no: "123456", title: "遥感卫星系统", scope_ref: "SOW §3.1",
    owner: "总体设计部", description: "EO-3 遥感卫星，含星务、载荷、测控三个分系统"});
  await call(WBS, "add_child", {parent_no: "123456", title: "星务分系统", owner: "星务分系统"});
  await call(WBS, "add_child", {parent_no: "123456", title: "载荷分系统", owner: "载荷分系统"});
  await call(WBS, "update", {wbs_no: "123456.01", scope_ref: "SOW §3.2", req_nos: "REQ-001"});
  await call(WBS, "update", {wbs_no: "123456.02", scope_ref: "SOW §3.3", req_nos: "REQ-002"});
  await call(WBS, "add_child", {parent_no: "123456.01", title: "星务计算机"});
  // 「元素 ↔ 活动」那一节要两个状态都验到：123456.01.01 有 1 条活动 → 显示「1 条」；
  // 其余叶子（123456.02 / 654321 / 123456.03）没有 → 显示琥珀色「加活动」
  const act = await call(ACT, "create", {name: "星务计算机热试验", wbs_no: "123456.01.01",
    duration_days: 5});
  await call(WBS, "baseline", {wbs_no: "123456"});
  await call(WBS, "baseline", {wbs_no: "123456.01"});
  return {seeded: true, cr_no: cr.cr_no, act_no: act.act_no};
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
    """轮询等待 loc 的文本收敛到含 want，**返回等到的那个快照**（等完再重新求值会自相矛盾）。"""
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


def wait_toast(page, want="", timeout=6000):
    """等 toast 出现（可选：等它含某段文案）。Toast 4.2 秒后自动消失，必须**动作后立刻读**。"""
    end = time.time() + timeout / 1000.0
    last = ""
    while time.time() < end:
        try:
            last = page.locator(".toasts").inner_text()
        except Exception:
            last = ""
        if last.strip() and (not want or want in last):
            return last
        time.sleep(0.15)
    return last


def row_of(page, wbs_no):
    return page.locator("table.tbl tr.data").filter(has_text=wbs_no).first


def drain_toasts(page, timeout=7000):
    """等当前吐司全部消散（4.2 秒自动消失）。

    ⚠ 不排空就断言"吐司含某某"会**假过**：`.toasts` 是所有吐司的拼接，
    上一条的文案还在时，新断言可能被陈旧文本喂饱（同理也可能把新吐司读成旧的）。
    """
    end = time.time() + timeout / 1000.0
    while time.time() < end:
        try:
            if not page.locator(".toasts").inner_text().strip():
                return True
        except Exception:
            return True
        time.sleep(0.2)
    return False

def close_modal(page, timeout=8000):
    """关掉当前可见模态（表单用「取消」，详情用「关闭」）。

    ⚠ **负例之后必须显式关**：提交被拒时模态**故意保持打开**（让人改完再交），
    而 `x-show` 只隐藏元素、遮罩仍在 DOM 里 —— 不关就会挡住后续所有点击
    （实测报「subtree intercepts pointer events」并一路重试到超时）。
    """
    end = time.time() + timeout / 1000.0
    while time.time() < end:
        vis = page.locator(".modal-mask:visible")
        if vis.count() == 0:
            return True
        box = vis.last
        for label in ("取消", "关闭"):
            btn = box.locator(f'button:has-text("{label}")')
            if btn.count():
                try:
                    btn.first.click(timeout=1500)
                    break
                except Exception:
                    pass
        time.sleep(0.2)
    return page.locator(".modal-mask:visible").count() == 0


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

            step("§0 造数（两条需求 + 已批准的 CR-001 + 四个元素：两基线两草稿）")
            seed = page.evaluate(SEED_JS)
            # VT-ROUTE-01 标题「工作分解结构台账」可见
            rec(bool(seed and seed.get("seeded")),
                "REQ-001/002 就绪；CR-001 已批准；123456 与 123456.01 已基线，"
                "123456.02 与 123456.01.01 草稿")

            # ── §1 渲染与入口 ────────────────────────────────
            step("§1 渲染与入口（VT-ROUTE-01..05）")
            page.evaluate("location.hash = '#/wbs'")
            page.wait_for_selector('button:has-text("新建顶层元素")', timeout=10000)
            page.wait_for_timeout(900)
            body = page.locator("main").inner_text()
            # VT-ROUTE-01 列表
            rec("工作分解结构台账" in body, "VT-ROUTE-01 标题「工作分解结构台账」可见")
            rows = page.locator("table.tbl tr.data")
            rec(rows.count() == 4, "VT-ROUTE-01 列表 " + str(rows.count()) + " 行（期望 4）")
            heads = page.locator("table.tbl tr").first.inner_text()
            # VT-ROUTE-02 表头完整
            rec(all(h in heads for h in ("元素编号", "元素名称", "类型", "层级", "父元素", "状态",
                                         "版次", "责任方", "范围定义出处", "关联需求")),
                "VT-ROUTE-02 表头完整")
            # VT-ROUTE-03 保留新建入口
            rec(page.locator('button:has-text("新建顶层元素")').count() > 0,
                "VT-ROUTE-03 保留新建入口（顶层元素）")
            first = row_of(page, "123456").inner_text()
            # VT-ROUTE-04 首行 123456
            # VT-ROUTE-05 123456.02 状态「草稿」
            rec("遥感卫星系统" in first and "产品" in first and "已基线" in first
                and "（顶层）" in first and "v0" in first,
                "VT-ROUTE-04 首行 123456：遥感卫星系统 / 产品 / 已基线 / （顶层）/ v0")
            r2 = row_of(page, "123456.02").inner_text()
            # VT-FORM-11 新建模态出现
            rec("载荷分系统" in r2 and "草稿" in r2, "VT-ROUTE-05 123456.02 状态「草稿」")

            # ── §2 新建与加子元素 ────────────────────────────
            step("§2 新建顶层 / 加子元素（VT-FORM-11..16）")
            page.click('button:has-text("新建顶层元素")')
            page.wait_for_selector('.modal-mask:visible [data-role="form-no"]', timeout=8000)
            rec(True, "VT-FORM-11 新建模态出现（含编号输入框）")
            page.fill('[data-role="form-no"]', "")
            page.fill('[data-role="form-title"]', "没编号的元素")
            drain_toasts(page)
            page.click('[data-role="form-submit"]')
            t = wait_toast(page, "顶层元素必须给出编号")
            # VT-FORM-12 顶层缺编号被拒且行数不变
            rec("顶层元素必须给出编号" in t and rows.count() == 4,
                "VT-FORM-12 顶层缺编号被拒且行数不变：" + str(t[:40]))
            close_modal(page)                       # 提交被拒时模态**故意不关**，测试要自己收
            page.locator('button:has-text("新建顶层元素")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="form-no"]', timeout=8000)
            page.fill('[data-role="form-no"]', "654321")
            page.fill('[data-role="form-title"]', "地面支持系统")
            page.click('[data-role="form-submit"]')
            n = wait_rows(page, 5)
            # VT-FORM-13 新建顶层成功
            # VT-FORM-14 子元素模态标题点名父元素
            rec(n == 5 and "654321" in page.locator("table.tbl").inner_text(),
                "VT-FORM-13 新建顶层成功，列表 " + str(n) + " 行")

            page.locator('button:has-text("新建顶层元素")').wait_for(state="visible")
            row_of(page, "123456").locator('button:has-text("加子元素")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="form-title"]', timeout=8000)
            hd = page.locator(".modal-mask:visible").last.inner_text()
            rec("123456" in hd and "新增子元素" in hd, "VT-FORM-14 子元素模态标题点名父元素")
            page.fill('[data-role="form-title"]', "测控分系统")
            page.click('[data-role="form-submit"]')
            n = wait_rows(page, 6)
            # VT-FORM-14 子号自动分配 → 123456.03
            rec(n == 6 and "123456.03" in page.locator("table.tbl").inner_text(),
                "VT-FORM-14 子号自动分配 → 123456.03，列表 " + str(n) + " 行")
            page.click('button:has-text("新建顶层元素")')
            page.wait_for_selector('.modal-mask:visible [data-role="form-title"]', timeout=8000)
            # VT-FORM-15 重开表单已重置
            rec(page.input_value('[data-role="form-title"]') == "",
                "VT-FORM-15 重开表单已重置（不残留上次输入）")
            close_modal(page)
            # ⚠ 非产品词要用**子元素**表单测：顶层表单缺编号会先被 BR-01 拦下，轮不到 BR-04
            row_of(page, "123456").locator('button:has-text("加子元素")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="form-title"]', timeout=8000)
            page.fill('[data-role="form-title"]', "工程部")
            drain_toasts(page)
            page.click('[data-role="form-submit"]')
            t = wait_toast(page, "非产品词")
            # VT-FORM-16 BR-04 非产品词被拒且行数不变
            rec("非产品词" in t and rows.count() == 6,
                "VT-FORM-16 BR-04 非产品词被拒且行数不变：" + str(t[:44]))
            close_modal(page)

            # ── §3 三个状态动作 ─────────────────────────────
            step("§3 状态动作（VT-ACT-21..26）")
            # VT-ACT-21 已基线行有「发起变更」
            rec(row_of(page, "123456").locator('button:has-text("发起变更")').count() > 0,
                "VT-ACT-21 已基线行有「发起变更」")
            # ⚠ `x-show` 只改 CSS，按钮**仍在 DOM** —— 断言"没有这个按钮"必须按**可见性**判
            #   （`count()` 会把隐藏的也算上；本组 decision 页的注释早写过这条，照样踩了）
            # VT-ACT-21 草稿行**看不到**「发起变更」
            rec(row_of(page, "123456.02").locator('button:has-text("发起变更")').is_visible() is False,
                "VT-ACT-21 草稿行**看不到**「发起变更」（不在配置控制之下）")
            # VT-ACT-21 草稿行**看不到**「关闭」
            rec(row_of(page, "123456.02").locator('button:has-text("关闭")').is_visible() is False,
                "VT-ACT-21 草稿行**看不到**「关闭」（先纳入基线才谈收口）")
            # VT-ACT-21 草稿行**看得到**「纳入基线」
            # VT-ACT-22 变更号候选只列已批准的
            rec(row_of(page, "123456.02").locator('button:has-text("纳入基线")').is_visible(),
                "VT-ACT-21 草稿行**看得到**「纳入基线」")

            row_of(page, "123456").locator('button:has-text("发起变更")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="change-cr"]', timeout=8000)
            opts = page.locator("#wbs-cr-options option").all_inner_texts()
            # VT-ACT-23 发起变更后该行状态 → 变更中
            rec(any("CR-001" in o for o in opts), "VT-ACT-22 变更号候选只列已批准的：" + str(opts[:2]))
            page.fill('[data-role="change-cr"]', "CR-001")
            drain_toasts(page)
            page.click('[data-role="change-submit"]')
            t = wait_toast(page, "变更中")
            r = wait_text(row_of(page, "123456"), "变更中", timeout=6000)
            rec("变更中" in r, "VT-ACT-23 发起变更后该行状态 → 变更中（" + str(t[:30]) + "）")
            # VT-ACT-23 按钮变为「落实变更」
            # VT-ACT-24 落实变更后回到已基线、版次 v1
            rec(row_of(page, "123456").locator('button:has-text("落实变更")').count() > 0,
                "VT-ACT-23 按钮变为「落实变更」")

            row_of(page, "123456").locator('button:has-text("落实变更")').click()
            r = wait_text(row_of(page, "123456"), "已基线", timeout=6000)
            # VT-ACT-24 修订授权列记下 CR-001
            rec("已基线" in r and "v1" in r, "VT-ACT-24 落实变更后回到已基线、版次 v1")
            # VT-ACT-24 落实变更把批准号写进「修订授权」
            #   ⚠ 「修订授权」已列入 `col_default_hidden`（版式需要，见 §7）—— 平台列隐藏走
            #     `display:none`，而 `inner_text()` **不含未渲染内容**：藏着断言会**静默读空**。
            #     所以取证改走**详情模态**（同组 technical_measure 页面对同一陷阱的处理）。
            row_of(page, "123456").locator('button:has-text("详情")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="modal-rev-auth"]', timeout=8000)
            auth = page.locator('[data-role="modal-rev-auth"]').inner_text()
            rec("CR-001" in auth, "VT-ACT-24 修订授权记下 CR-001（详情模态：" + auth.strip()[:16] + "）")
            close_modal(page)

            btn = row_of(page, "123456.01.01").locator('button:has-text("纳入基线")')
            # VT-ACT-25 BR-03 无范围出处 → 「纳入基线」**禁用
            rec(btn.count() > 0 and btn.is_disabled(),
                "VT-ACT-25 BR-03 无范围出处 → 「纳入基线」**禁用**（前端镜像）")
            # ⚠ 前端禁用只是**提示**，判据在后端 —— 绕过界面直接打服务，确认硬闸也拒
            msg = page.evaluate("""async () => {
              const r = await fetch('/api/apps/nasa_pms/wbs/call/baseline', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({wbs_no: '123456.01.01'})});
              const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch (e) {}
              return (j && (j.message || j.data || j.error)) || t.slice(0, 160);
            }""")
            rec("范围定义出处" in str(msg), "VT-ACT-25 后端硬闸也拒（BR-03）：" + str(str(msg)[:52]))
            # VT-ACT-25 状态仍是草稿
            rec("草稿" in row_of(page, "123456.01.01").inner_text(),
                "VT-ACT-25 状态仍是草稿（被拒不留痕）")

            row_of(page, "123456.01").locator('button:has-text("关闭")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="close-submit"]', timeout=8000)
            drain_toasts(page)
            page.click('[data-role="close-submit"]')
            t = wait_toast(page, "未关闭的子元素")
            # VT-ACT-26 BR-06 未收口不得关闭
            rec("未关闭的子元素" in t and "已基线" in row_of(page, "123456.01").inner_text(),
                "VT-ACT-26 BR-06 未收口不得关闭：" + str(t[:44]))
            close_modal(page)

            # ── §4 详情模态（字典字段）──────────────────────
            step("§4 详情模态（VT-MODAL-31..35）")
            row_of(page, "123456.01").locator('button:has-text("详情")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="wbs-head"]', timeout=8000)
            form = page.locator(".modal-mask:visible").last
            head = form.locator('[data-role="wbs-head"]').inner_text()
            # VT-MODAL-31 头部
            rec("层级 2" in head and "123456" in head and "v0" in head,
                "VT-MODAL-31 头部：" + str(head[:60]))
            # VT-MODAL-32 范围定义出处 = SOW §3.2
            rec(form.locator('[data-role="modal-scope"]').input_value() == "SOW §3.2",
                "VT-MODAL-32 范围定义出处 = SOW §3.2")
            # VT-MODAL-32 关联需求 = REQ-001
            rec(form.locator('[data-role="modal-reqnos"]').input_value() == "REQ-001",
                "VT-MODAL-32 关联需求 = REQ-001（交叉引用矩阵的 X）")
            # VT-MODAL-33 已基线元素**看不到**「编辑」入口
            rec(form.locator('button:has-text("编辑")').is_visible() is False,
                "VT-MODAL-33 已基线元素**看不到**「编辑」入口（给的是「发起变更」）")
            rec("发起变更" in form.inner_text(), "VT-MODAL-33 提示「已基线：改动需先发起变更」")
            close_modal(page)

            row_of(page, "123456.02").locator('button:has-text("详情")').click()
            page.wait_for_selector('.modal-mask:visible [data-role="wbs-head"]', timeout=8000)
            form = page.locator(".modal-mask:visible").last
            # VT-MODAL-34 草稿元素看得到「编辑」入口
            rec(form.locator('button:has-text("编辑")').is_visible(),
                "VT-MODAL-34 草稿元素看得到「编辑」入口")
            form.locator('button:has-text("编辑")').click()
            page.wait_for_timeout(300)
            # VT-MODAL-34 编辑态字段可写
            # VT-MODAL-35 修改字典字段落库并回显到列表
            rec(not form.locator('[data-role="modal-title"]').is_disabled(),
                "VT-MODAL-34 编辑态字段可写")
            form.locator('[data-role="modal-title"]').fill("载荷分系统（含相机）")
            form.locator('button:has-text("保存")').click()
            r = wait_text(row_of(page, "123456.02"), "载荷分系统（含相机）", timeout=6000)
            rec("载荷分系统（含相机）" in r, "VT-MODAL-35 修改字典字段落库并回显到列表")
            close_modal(page)          # 保存后模态仍在（回只读态），不关会挡住 §5 的点击

            # ── §5 树视图 ───────────────────────────────────
            step("§5 树视图（VT-TREE-41..43）")
            page.click('button:has-text("树视图")')
            page.wait_for_selector('[data-role="tree"]:visible', timeout=8000)
            tree = page.locator('[data-role="tree"]:visible')
            t = tree.inner_text()
            # VT-TREE-41 缩进索引覆盖各层元素
            # VT-TREE-42 树视图标注「WBS 索引」
            rec(all(x in t for x in ("123456", "123456.01", "123456.01.01", "654321")),
                "VT-TREE-41 缩进索引覆盖各层元素（含 3 层深的 123456.01.01）")
            # VT-TREE-43 缩进层级可见
            rec("WBS 索引" in t, "VT-TREE-42 树视图标注「WBS 索引」（材料 §3.4.4 图 3-12）")
            indents = page.evaluate(
                "() => Array.from(document.querySelectorAll('[data-role=\"tree\"] .sline'))"
                ".map(e => e.style.paddingLeft)")
            # VT-TREE-43 切回列表视图正常
            rec(len(set(indents)) >= 2, "VT-TREE-43 缩进层级可见：" + str(sorted(set(indents))[:4]))
            page.click('button:has-text("列表视图")')
            page.wait_for_selector("table.tbl", timeout=8000)
            rec(page.locator("table.tbl tr.data").count() == 6, "VT-TREE-43 切回列表视图正常")

            # ── §6 元素 ↔ 活动（VT-REL-01..03，2026-09-26 增补）──────────────────
            # 材料依据：WBS 手册 §4 "The lowest level of each WBS element should have at least
            #   one task or activity" —— 台账上要看得见"这个叶子有没有活动"，并能一步跳过去建。
            # ⚠ 本页对 `activity` **只读**（跳转过去；写活动仍是活动页自己的事）：全仓的视图层
            #   跨应用调用**一律只读**，第一条写边不从这里开（见 architecture.md 的方向表）。
            step("§6 元素 ↔ 活动（VT-REL-01..03）")

            def act_cell(no):
                c = row_of(page, no).locator('[data-role="act-cell"]')
                b = c.locator('button[data-role="act-entry"]')
                return b.inner_text().strip() if (b.count() and b.is_visible()) else c.inner_text().strip()

            # VT-REL-01 叶子显示读数/入口，非叶子显示「—」
            rec(act_cell("123456.01.01") == "1 条",
                "VT-REL-01 有活动的叶子显示「1 条」")
            rec(all(act_cell(x) == "加活动" for x in ("123456.02", "123456.03")),
                "VT-REL-01 没有活动的叶子显示「加活动」（材料 §4 那条的可见证据）")
            rec(all(act_cell(x) == "—" for x in ("123456", "123456.01")),
                "VT-REL-01 非叶子显示「—」（活动只能挂最底层元素）")

            # VT-REL-02 点「1 条」→ 跳到进度活动台账并**按该元素筛选**
            row_of(page, "123456.01.01").locator('[data-role="act-entry"]').click()
            page.wait_for_selector('[data-role="f-wbs"]', timeout=10000)
            page.wait_for_timeout(1000)
            rec(page.input_value('[data-role="f-wbs"]') == "123456.01.01",
                "VT-REL-02 跳过去带着「挂靠元素」筛选：" + page.input_value('[data-role="f-wbs"]'))
            n = page.locator(".scroll-x table.tbl tr.data").count()
            rec(n == 1, f"VT-REL-02 活动台账只剩该元素下的 1 条（实际 {n} 行）")

            # VT-REL-03 点「加活动」→ 跳到活动台账、**新建模态已开且元素已预选**
            page.evaluate("location.hash = '#/wbs'")
            page.wait_for_selector("table.tbl tr.data", timeout=10000)
            page.wait_for_timeout(800)
            row_of(page, "123456.02").locator('[data-role="act-entry"]').click()
            page.wait_for_selector('.modal-mask:visible [data-role="form-wbs"]', timeout=10000)
            rec(page.input_value('[data-role="form-wbs"]') == "123456.02",
                "VT-REL-03 「加活动」跳过去：新建模态已开、挂靠元素已预选 123456.02")
            close_modal(page)
            page.evaluate("location.hash = '#/wbs'")          # §7 版式要在**本页**量
            page.wait_for_selector("table.tbl tr.data", timeout=10000)
            page.wait_for_timeout(800)

            # ── §7 版式（VT-LAYOUT-01..03，2026-09-26 增补）──────────────────
            # 判据来源：本页 15 列**同时铺开**时表格最小内容宽 1380px > 卡片 1238px（1500 宽 ·
            #   右栏收起实测），浏览器只能把最后一列「操作」压到 48px → 四个按钮竖排 →
            #   行高从 39px 涨到 223px，整页看着散架。下面是修完后的固化判据。
            # ⚠ 量版式必须**说清画布**：默认 context 是 1280×720 且 Agent 右栏默认展开 ——
            #   那是"更窄的另一种版式"，所以本段显式两档量（默认档 + 1920 档），且量完还原。
            step("§7 版式（VT-LAYOUT-01..03）")

            def _layout(pg):
                return pg.evaluate("""() => {
                  const bx = document.querySelector('.scroll-x');
                  const tb = bx && bx.querySelector('table.tbl');
                  if (!tb) return null;
                  const tr = tb.querySelector('tr.data');
                  const vis = tr ? Array.from(tr.querySelectorAll('td:last-child button'))
                                   .filter(b => b.offsetParent !== null) : [];
                  const tops = new Set(vis.map(b => Math.round(b.getBoundingClientRect().top)));
                  return {over: tb.scrollWidth - bx.clientWidth, btns: vis.length, lines: tops.size,
                          rowH: tr ? Math.round(tr.getBoundingClientRect().height) : 0,
                          hidden: Array.from(document.querySelectorAll('table.tbl th'))
                                    .filter(t => t.offsetParent === null)
                                    .map(t => t.textContent.replace(/[⇅▲▼?]/g, '').trim())};
                }""")

            lay = _layout(page)
            # VT-LAYOUT-01 操作列按钮不换行（窄画布下也一样 —— "宁可横滚，不可变形"）
            rec(lay and lay["lines"] <= 1,
                f"VT-LAYOUT-01 操作按钮不换行（{lay and lay['btns']} 个按钮占 "
                f"{lay and lay['lines']} 行 · 行高 {lay and lay['rowH']}px）")
            # VT-LAYOUT-02 四个字典列默认隐藏（表格最小宽 1380 → 938）
            rec(lay and sorted(lay["hidden"]) == sorted(["内容描述", "规范号", "预算与报告号", "修订授权"]),
                f"VT-LAYOUT-02 默认隐藏的正是四个字典列：{lay and lay['hidden']}")
            # VT-LAYOUT-03 正常桌面宽度（1920 · 右栏展开）下列表不横向溢出
            page.set_viewport_size({"width": 1920, "height": 1080})
            page.wait_for_timeout(700)
            lay2 = _layout(page)
            rec(lay2 and lay2["over"] <= 2,
                f"VT-LAYOUT-03 1920 宽（右栏展开）不横向溢出（超出 {lay2 and lay2['over']}px）")
            page.set_viewport_size({"width": 1280, "height": 720})
            page.wait_for_timeout(400)

            # 豁免清单受检（V5）：收集了却从不校验 = 给静默吞掉开口子
            for _ig in ignored:
                rec(("/favicon.ico" in _ig or ".map" in _ig), f"豁免理由成立：{_ig[:90]}")

            step("§8 硬件指标（VT-HW-90）")
            rec(not errors, f"0 console error / 0 pageerror / 0 HTTP≥400（实际 {len(errors)}）")
            for e in errors[:6]:
                print("      ✗", e)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{'='*60}")
    print(f"  用例 {len(RESULTS)} 项 · 通过 {len(RESULTS)-len(bad)} · 失败 {len(bad)}")
    print(f"  {'VERIFY_RESULT: PASS' if not bad else 'VERIFY_RESULT: FAIL'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
