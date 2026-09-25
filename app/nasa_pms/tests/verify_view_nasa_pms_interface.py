"""e2e 前端验收 - nasa_pms:interface（接口台账 · 独立创建 + 聚合内通知子表 + 跨接口查询视图）。

断言：定义入口存在 → 列表 4 行（定义中 / 已发布 / 变更中 / 已冻结 四态同屏）→
**F-1** 四项必填且两端互异（相同则提交禁用）→ **F-2** 定义中可改两端与 ICD、已定版置灰并给原因 →
**F-3** 状态机按钮按状态显隐 → **F-4** 版本变更（新版本号格式/递增/原因必填）→
**F-5** 详情含「版本变更通知记录」子表（每次变更两端各一条）→ **F-6** 变更通知台账按端收敛 →
**F-7** 已冻结无写入口 + 终态文案 → **F-8** 筛选收敛 → **F-9** 关联配置项下拉跨应用取数。
全程 0 console error / 0 pageerror / 0 HTTP≥400。

用例来源：app/nasa_pms/interface/前端测试用例.md（§0 造数 + §1..§8）。
运行：python app/nasa_pms/tests/verify_view_nasa_pms_interface.py
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
# 其后用例也不再执行 —— 实测 stakeholder 的 VT-SUB-32 就这么"消失"过）。与 scripts/run_gates.py 给
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


# §0 自足造数：2 个配置项（关联配置项下拉的选项源）+ 4 条接口（**四态同屏**）。
# 走 REST，不经 UI —— 避免用例依赖"定义功能本身"（那是 §6 的覆盖对象）。
# ⚠ REST 路径必须用**组限定名** `nasa_pms/interface`（短名 404「应用不存在」）；
#    配置项也要先造出来：create 会跨应用校验 ci_no 是否存在（BR-08）。
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
  const IF = "nasa_pms/interface";
  const CI = "nasa_pms/configuration_item";
  await call(CI, "create", {name: "接口控制文档（ICD）", ci_type: "document", owner: "张三"});
  await call(CI, "create", {name: "配电单元设计文件", ci_type: "document", owner: "李四"});
  await call(IF, "create", {if_name: "飞控计算机—舵机控制器 总线接口", if_type: "icd",
    provider: "飞控计算机（FCC）", consumer: "舵机控制器（SACU）",
    icd_content: "1553B 总线，周期 20ms", ci_no: "CI-001", owner: "张三"});
  await call(IF, "create", {if_name: "星务计算机—测控应答机 数据接口", if_type: "ird",
    provider: "星务计算机（OBC）", consumer: "测控应答机（TT&C）"});
  await call(IF, "create", {if_name: "姿控计算机—地面测试设备 测试接口", if_type: "idd",
    provider: "姿态控制计算机（ADCS）", consumer: "地面测试设备（GSE）"});
  await call(IF, "create", {if_name: "电源分系统—配电单元 供电接口", if_type: "icd",
    provider: "电源分系统（EPS）", consumer: "配电单元（PDU）", ci_no: "CI-002"});
  // IF-001：发布 A → 变更 B → 落实 → 变更 C ⇒ 停在「变更中」（通知 6 条 = 3 轮 × 两端）
  await call(IF, "release", {if_no: "IF-001"});
  await call(IF, "revise", {if_no: "IF-001", new_version: "B", reason: "舵机控制器换代，周期改 10ms"});
  await call(IF, "release", {if_no: "IF-001"});
  await call(IF, "revise", {if_no: "IF-001", new_version: "C", reason: "增加余度通道"});
  // IF-003：发布 A → 冻结 ⇒ 「已冻结」（通知 2 条）
  await call(IF, "release", {if_no: "IF-003"});
  await call(IF, "freeze", {if_no: "IF-003", note: "随 CDR 定稿，纳入配置管理"});
  // IF-004：发布 A ⇒ 「已发布」（通知 2 条）
  await call(IF, "release", {if_no: "IF-004"});
  // IF-002 不处理 ⇒ 「定义中」（未定版，0 条通知）
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
            page.on("dialog", lambda d: d.accept())      # 发布 / 冻结 / 版本变更的二次确认
            page.goto(f"{base}/view/nasa_pms/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)

            step("§0 造数（2 配置项 + 4 接口：定义中 / 已发布 / 变更中 / 已冻结）")
            seed = page.evaluate(SEED_JS)
            rec(bool(seed and seed.get("seeded")),
                "IF-001 变更中 · IF-002 定义中 · IF-003 已冻结 · IF-004 已发布")

            def rows():
                return page.locator("table.tbl tr.data")

            def row(no):
                return page.locator("table.tbl tr.data").filter(has_text=no).first

            def open_detail(no, mode="view"):
                row(no).locator('button:has-text("详情")' if mode == "view"
                                else 'button:has-text("编辑")').click()
                page.wait_for_timeout(900)
                return page.locator(".modal-mask:visible").last

            def close_modal(m):
                # 详情/编辑模态的取消按钮叫「关闭」，定义模态叫「取消」——两种都收
                m.locator('button:has-text("关闭"), button:has-text("取消")').first.click()
                page.wait_for_timeout(400)

            # ── §1 渲染与入口 ────────────────────────────────
            step("§1 渲染与入口（VT-ROUTE-01..VT-ROUTE-05）")
            page.evaluate("location.hash = '#/interface'")
            page.wait_for_selector('button:has-text("定义接口")', timeout=10000)
            page.wait_for_timeout(900)
            rec(rows().count() == 4, f"VT-ROUTE-01 列表 {rows().count()} 行（期望 4）")
            heads = page.locator("table.tbl tr").first.inner_text()
            rec(all(h in heads for h in ("接口编号", "接口名称", "类型", "提供方", "使用方",
                                         "版本", "状态", "变更通知", "关联配置项", "责任人")),
                # VT-ROUTE-02 表头完整性
                "VT-ROUTE-02 表头完整")
            rec(page.locator('button:has-text("定义接口"):visible').count() == 1,
                # VT-ROUTE-03 **保留定义入口**
                "VT-ROUTE-03 保留定义入口（独立创建）")
            t1 = row("IF-001").inner_text()
            rec("ICD" in t1 and "接口控制文档（ICD）" in t1 and "飞控计算机（FCC）" in t1
                and "舵机控制器（SACU）" in t1 and "C" in t1 and "变更中" in t1 and "6 条" in t1,
                # VT-ROUTE-04 行内容
                "VT-ROUTE-04 IF-001 行：ICD / 两端 / 版本 C / 变更中 / 通知 6 条")
            t2 = row("IF-002").inner_text()
            rec("定义中" in t2 and "未定版" in t2 and "0 条" in t2,
                "VT-ROUTE-04 IF-002 行：定义中 / 未定版 / 通知 0 条")
            rec("已冻结" in row("IF-003").inner_text() and "已发布" in row("IF-004").inner_text(),
                "VT-ROUTE-04 IF-003 已冻结 · IF-004 已发布（四态同屏）")
            # ⚠ 动作按钮用 x-show 隐藏（display:none 但仍在 DOM）→ 断言必须带 `:visible`
            r1 = row("IF-001")
            rec(r1.locator('button:has-text("完成变更"):visible').count() == 1
                and r1.locator('button:has-text("发布"):visible').count() == 0
                and r1.locator('button:has-text("版本变更"):visible').count() == 0
                and r1.locator('button:has-text("冻结"):visible').count() == 0,
                "VT-ROUTE-05 变更中行：只有「完成变更」")
            r2 = row("IF-002")
            rec(r2.locator('button:has-text("发布"):visible').count() == 1
                and r2.locator('button:has-text("编辑"):visible').count() == 1
                and r2.locator('button:has-text("版本变更"):visible').count() == 0,
                "VT-ROUTE-05 定义中行：有「发布」「编辑」，无「版本变更」")
            r4 = row("IF-004")
            rec(r4.locator('button:has-text("版本变更"):visible').count() == 1
                and r4.locator('button:has-text("冻结"):visible').count() == 1
                and r4.locator('button:has-text("发布"):visible').count() == 0,
                "VT-ROUTE-05 已发行：有「版本变更」「冻结」，无「发布」")
            r3 = row("IF-003")
            rec(r3.locator('button:has-text("编辑"):visible').count() == 0
                and r3.locator('button:has-text("版本变更"):visible').count() == 0
                and r3.locator('button:has-text("冻结"):visible').count() == 0
                and r3.locator('button:has-text("详情"):visible').count() == 1,
                "VT-ROUTE-05 已冻结行：写入口全消失，只剩「详情」")

            # ── §2 详情 / 编辑（F-2 / F-5 / F-9）────────────
            step("§2 详情与编辑（VT-MODAL-11..VT-MODAL-18）")
            m = open_detail("IF-002", "view")
            # ⚠ 只读信息条用 data-role 定位后单独取文本：整块 inner_text 会把 select 的
            #    全部 option 文本也吃进来，断言会假过（本用例集实测踩过）
            head = m.locator('[data-role="if-head"]').inner_text()
            rec("IF-002" in head and "定义中" in head and "未定版" in head
                and "变更通知 0 条" in head,
                "VT-MODAL-11 只读信息条：IF-002 / 定义中 / 未定版 / 通知 0 条")
            # VT-MODAL-12 只读视图
            rec(m.locator("input").first.is_disabled(), "VT-MODAL-12 只读视图 → 接口名称 disabled")
            rec(m.locator('button:has-text("保存"):visible').count() == 0,
                "VT-MODAL-12 只读视图无「保存」")
            rec("版本变更通知记录（0）" in m.locator('[data-role="change-title"]').inner_text(),
                "VT-MODAL-12 通知子表为空")
            close_modal(m)

            m = open_detail("IF-002", "edit")
            # VT-MODAL-13 点「编辑」
            rec(m.locator("input").first.is_enabled(), "VT-MODAL-13 编辑态 → 接口名称可写")
            rec(m.locator('input[placeholder*="接口的一端"]').first.is_enabled()
                and m.locator('input[placeholder*="接口的另一端"]').first.is_enabled(),
                "VT-MODAL-13 定义中 → 两端可写（BR-05：只有定义中可改端）")
            rec(m.locator('[data-role="ends-lock-hint"]:visible').count() == 0,
                "VT-MODAL-13 定义中 → 无「已定版」锁提示")
            m.locator("input").first.fill("星务计算机—测控应答机 数据接口（修订）")
            page.wait_for_timeout(200)
            m.locator('button:has-text("保存")').click()
            page.wait_for_timeout(1300)
            # VT-MODAL-14 改名称 → 保存
            rec(page.locator(".modal-mask:visible").count() == 0, "VT-MODAL-14 保存后模态关闭")
            rec("（修订）" in row("IF-002").inner_text(), "VT-MODAL-14 列表回显改后的名称")

            m = open_detail("IF-001", "view")
            head = m.locator('[data-role="if-head"]').inner_text()
            rec("变更中" in head and "C" in head and "变更通知 6 条" in head,
                # VT-MODAL-15 `IF-001` 详情（F-5）
                "VT-MODAL-15 IF-001 信息条：变更中 / 版本 C / 通知 6 条")
            crows = m.locator('[data-role="change-row"]')
            rec(crows.count() == 6, f"VT-MODAL-15 通知子表 {crows.count()} 行（3 轮 × 两端）")
            parties = [crows.nth(i).locator('[data-role="chg-party"]').inner_text()
                       for i in range(crows.count())]
            rec(parties.count("提供方") == 3 and parties.count("使用方") == 3,
                f"VT-MODAL-15 每次变更两端各一条（{parties}）")
            rec(crows.first.locator('[data-role="chg-action"]').inner_text() == "首次发布"
                and crows.first.locator('[data-role="chg-version"]').inner_text() == "定版 A"
                and crows.first.locator('[data-role="chg-party-name"]').inner_text()
                == "飞控计算机（FCC）",
                "VT-MODAL-15 首条通知：首次发布 / 定版 A / 通知对象=提供方名称快照")
            close_modal(m)

            m = open_detail("IF-001", "edit")
            rec(m.locator('input[placeholder*="接口的一端"]').first.is_disabled(),
                # VT-MODAL-16 `IF-001` 编辑态
                "VT-MODAL-16 已定版 → 提供方 disabled")
            lock = m.locator('[data-role="ends-lock-hint"]:visible')
            rec(lock.count() == 1 and "两端与约定内容不可直接改" in lock.inner_text(),
                "VT-MODAL-16 给出原因「请用版本变更」（BR-05）")
            close_modal(m)

            m = open_detail("IF-004", "edit")
            # F-9：关联配置项是「文本输入 + datalist 建议」，建议项来自**跨应用** configuration_item.list。
            # ⚠ 这条断言是**回填**（本轮实测踩到过：<select> + x-for 选项时回填静默停在第一项，
            #   详见 前端测试用例.md §9 坑 1 —— 换成文本输入后值就是文本，回填天然正确）
            rec(m.locator('input[placeholder*="CI-"]').input_value() == "CI-002",
                # VT-MODAL-17 `IF-004` 编辑态（F-9）
                "VT-MODAL-17 关联配置项跨应用取数并正确回填 CI-002")
            # ⚠ 必须**按 id 限定**：裸 `datalist option` 在本页模态里会数到**所有** datalist
            #   （2026-09-25 加「责任人」候选后当场变红 —— 2 项变 4 项）。
            #   通用规则见 pitfalls #44：datalist 选择器一律带 id。
            rec(m.locator('datalist#ci-options-modal option').count() == 2,
                "VT-MODAL-17 datalist 建议项来自配置项台账（2 个）")
            # **F-2 的正向对照**：已定版接口改「描述性字段」必须能存下来 ——
            # 这条同时守住"只读字段不进写载荷"：若 saveEdit 把置灰的 provider/consumer/icd_content
            # 也发出去，后端会正确地按 BR-05 拒掉整次保存（本轮实测踩到并修掉）
            rec(m.locator('input[placeholder*="接口的一端"]').first.is_disabled(),
                # VT-MODAL-18 **F-2 的正向对照**：已发布的 `IF-004` 改「责任人」→ 保存
                "VT-MODAL-18 已发布 → 提供方 disabled（BR-05）")
            m.locator("input").nth(4).fill("赵六")          # 责任人（第 5 个 input）
            page.wait_for_timeout(200)
            m.locator('button:has-text("保存")').click()
            page.wait_for_timeout(1300)
            rec(page.locator(".modal-mask:visible").count() == 0
                and "赵六" in row("IF-004").inner_text()
                and "已发布" in row("IF-004").inner_text(),
                "VT-MODAL-18 已发布也能改责任人并保存（描述性字段不锁，BR-05）")

            # ── §3 版本变更（F-4）────────────────────────────
            step("§3 版本变更（VT-ACT-21..VT-ACT-25）")
            row("IF-004").locator('button:has-text("版本变更"):visible').click()
            page.wait_for_timeout(600)
            rm = page.locator(".modal-mask:visible").last
            rec(rm.locator('[data-role="rm-cur"]').inner_text() == "A",
                "VT-ACT-21 版本变更模态出现，当前版本 A")
            submit = rm.locator('button:has-text("提交变更")')
            rec(submit.is_disabled(), "VT-ACT-21 新版本号为空 → 提交 disabled")
            rm.locator('input[placeholder*="单个大写字母"]').fill("a")
            page.wait_for_timeout(300)
            rec(submit.is_disabled()
                and "必须是单个大写字母" in rm.inner_text(),
                # VT-ACT-22 填 `a` / 填 `A`（＝当前）
                "VT-ACT-22 小写字母 → 拒绝（提示单个大写字母）")
            rm.locator('input[placeholder*="单个大写字母"]').fill("A")
            page.wait_for_timeout(300)
            rec(submit.is_disabled() and "必须大于当前版本 A" in rm.inner_text(),
                "VT-ACT-22 与当前版本相同 → 拒绝（版本只能递增）")
            rm.locator('button:has-text("填入下一个版本")').click()
            page.wait_for_timeout(300)
            rec(rm.locator('input[placeholder*="单个大写字母"]').input_value() == "B",
                # VT-ACT-23 点「填入下一个版本」→ 原因留空
                "VT-ACT-23 「填入下一个版本」→ B")
            rec(submit.is_disabled() and "必须说明变更原因" in rm.inner_text(),
                "VT-ACT-23 变更原因为空 → 仍 disabled（BR-04）")
            rm.locator("textarea").first.fill("配电单元增加一路备份供电")
            page.wait_for_timeout(300)
            # VT-ACT-24 版本 + 原因齐备 → 提交
            rec(not submit.is_disabled(), "VT-ACT-24 版本 + 原因齐备 → 可提交")
            submit.click()
            page.wait_for_timeout(1400)
            r4 = row("IF-004")
            rec("变更中" in r4.inner_text() and "B" in r4.inner_text() and "4 条" in r4.inner_text(),
                "VT-ACT-24 提交后：变更中 / 版本 B / 通知 4 条")
            r4.locator('button:has-text("完成变更"):visible').click()
            page.wait_for_timeout(1400)
            r4 = row("IF-004")
            rec("已发布" in r4.inner_text() and "B" in r4.inner_text() and "4 条" in r4.inner_text(),
                "VT-ACT-25 完成变更 → 回到已发布，通知不重复（仍 4 条）")

            # ── §4 变更通知台账（F-6）────────────────────────
            step("§4 变更通知台账（VT-SUB-31..VT-SUB-34）")
            nrows = page.locator('[data-role="notice-row"]')
            rec(nrows.count() == 12,
                f"VT-SUB-31 通知台账 {nrows.count()} 行（IF-001 6 + IF-003 2 + IF-004 4）")
            one = nrows.filter(has_text="IF-004").first
            rec(one.locator('[data-role="nt-party-name"]').inner_text() in
                ("电源分系统（EPS）", "配电单元（PDU）")
                and one.locator('[data-role="nt-action"]').inner_text() in ("首次发布", "版本变更"),
                "VT-SUB-32 台账行带出端名快照 / 起因 / 版本")
            page.locator('.fchip:has-text("提供方")').click()
            page.wait_for_timeout(900)
            # VT-SUB-33 切「提供方」/「使用方」
            rec(nrows.count() == 6, f"VT-SUB-33 只筛提供方 → {nrows.count()} 行")
            page.locator('.fchip:has-text("使用方")').click()
            page.wait_for_timeout(900)
            rec(nrows.count() == 6
                and all(nrows.nth(i).locator('[data-role="nt-party"]').inner_text() == "使用方"
                        for i in range(nrows.count())),
                "VT-SUB-33 只筛使用方 → 6 行（两端对称，I-2）")
            page.locator('.fchip:has-text("全部")').click()
            page.wait_for_timeout(900)
            rec(nrows.count() == 12 and "共 12 条通知" in page.locator('[data-role="sum-total"]').inner_text(),
                "VT-SUB-34 切回全部 → 12 行 + 合计文案")

            # ── §5 冻结（F-7）───────────────────────────────
            step("§5 冻结（VT-ACT-41..VT-ACT-43）")
            row("IF-004").locator('button:has-text("冻结"):visible').click()
            page.wait_for_timeout(1400)
            r4 = row("IF-004")
            rec("已冻结" in r4.inner_text()
                and r4.locator('button:has-text("冻结"):visible').count() == 0
                and r4.locator('button:has-text("版本变更"):visible').count() == 0
                and r4.locator('button:has-text("编辑"):visible').count() == 0,
                "VT-ACT-41 冻结后：状态已冻结，写入口全消失")
            m = open_detail("IF-004", "view")
            hint = m.locator('[data-role="frozen-hint"]:visible')
            rec(hint.count() == 1 and "已冻结（终态）" in hint.inner_text(),
                # VT-ACT-42 已冻结详情
                "VT-ACT-42 详情提示「已冻结（终态）—— 不能再修改、发布或变更版本」")
            rec(m.locator('button:has-text("保存"):visible').count() == 0
                and m.locator('button:has-text("冻结"):visible').count() == 0,
                "VT-ACT-42 已冻结详情无任何写入口")
            rec("变更通知 4 条" in m.locator('[data-role="if-head"]').inner_text(),
                "VT-ACT-42 冻结不影响历史通知记录")
            close_modal(m)
            m = open_detail("IF-002", "view")
            rec(m.locator('button:has-text("冻结"):visible').count() == 0,
                "VT-ACT-43 定义中的接口无「冻结」入口（BR-09：先发布）")
            close_modal(m)

            # ── §6 定义接口（F-1）───────────────────────────
            step("§6 定义接口（VT-FORM-51..VT-FORM-56）")
            page.click('button:has-text("定义接口")')
            page.wait_for_timeout(500)
            form = page.locator(".modal-mask:visible").last
            rec(form.locator("select").count() == 1, "VT-FORM-51 定义模态出现（类型下拉；关联配置项是 datalist 输入）")
            fsubmit = form.locator('button:has-text("提交")')
            # VT-FORM-52 四项皆空 → 只填名称
            rec(fsubmit.is_disabled(), "VT-FORM-52 四项必填皆空 → 提交 disabled")
            form.locator("input").first.fill("太阳翼驱动机构—电源控制器 指令接口")
            page.wait_for_timeout(200)
            rec(fsubmit.is_disabled(), "VT-FORM-52 只填名称 → 仍 disabled（类型无默认值）")
            form.locator("select").nth(0).select_option("icd")
            form.locator("input").nth(1).fill("电源控制器（PCU）")
            form.locator("input").nth(2).fill("电源控制器（PCU）")
            page.wait_for_timeout(300)
            rec(fsubmit.is_disabled() and "两端不能是同一个系统" in form.inner_text(),
                # VT-FORM-53 两端填成同一个系统
                "VT-FORM-53 两端相同 → 提交 disabled（BR-01）")
            form.locator("input").nth(2).fill("太阳翼驱动机构（SADA）")
            page.wait_for_timeout(300)
            # VT-FORM-54 两端互异 → 提交
            rec(not fsubmit.is_disabled(), "VT-FORM-54 两端互异 → 可提交")
            fsubmit.click()
            page.wait_for_timeout(1400)
            rec(rows().count() == 5, f"VT-FORM-54 定义成功，列表变 {rows().count()} 行")
            rec("定义中" in row("IF-005").inner_text() and "未定版" in row("IF-005").inner_text(),
                # VT-FORM-55 新接口落点
                "VT-FORM-55 新接口落在「定义中」且未定版")
            page.click('button:has-text("定义接口")')
            page.wait_for_timeout(500)
            form2 = page.locator(".modal-mask:visible").last
            rec(form2.locator("input").first.input_value() == "", "VT-FORM-56 表单已重置")
            close_modal(form2)

            # ── §7 筛选（F-8）────────────────────────────────
            step("§7 筛选（VT-FILTER-71..VT-FILTER-74）")
            fsel = page.locator("main .card").first.locator("select")
            fsel.nth(0).select_option("idd")
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "IF-003" in rows().first.inner_text(),
                f"VT-FILTER-71 类型=接口定义文档（IDD）→ {rows().count()} 行")
            fsel.nth(0).select_option("")
            page.wait_for_timeout(600)
            fsel.nth(1).select_option("frozen")
            page.wait_for_timeout(900)
            # VT-FILTER-72 清类型，状态筛「已冻结」/「定义中」
            rec(rows().count() == 2, f"VT-FILTER-72 状态=已冻结 → {rows().count()} 行（IF-003 / IF-004）")
            fsel.nth(1).select_option("defined")
            page.wait_for_timeout(900)
            rec(rows().count() == 2, f"VT-FILTER-72 状态=定义中 → {rows().count()} 行（IF-002 / IF-005）")
            fsel.nth(1).select_option("")
            page.wait_for_timeout(600)
            fin = page.locator("main .card").first.locator("input")
            fin.nth(0).fill("飞控计算机（FCC）")
            fin.nth(0).press("Enter")
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "IF-001" in rows().first.inner_text(),
                # VT-FILTER-73 提供方文本框填 `飞控计算机（FCC）`（回车）
                f"VT-FILTER-73 提供方=飞控计算机（FCC）→ {rows().count()} 行")
            fin.nth(0).fill("")
            fin.nth(0).press("Enter")
            page.wait_for_timeout(600)
            fin.nth(1).fill("太阳翼驱动机构（SADA）")
            fin.nth(1).press("Enter")
            page.wait_for_timeout(900)
            rec(rows().count() == 1 and "IF-005" in rows().first.inner_text(),
                f"VT-FILTER-74 使用方=太阳翼驱动机构（SADA）→ {rows().count()} 行")

            # ── §7b 责任人候选（datalist ← stakeholder.list）────────
            # 跨应用只读候选：**值仍是文本姓名**（不落 sh_no，全组 owner 一致口径），
            # 故断言两件事 —— 候选确有数据 + 控件仍是文本输入（不是 select）。
            step("§7b 责任人候选（VT-SUG-75..VT-SUG-76）")
            page.click('button:has-text("定义接口")')
            page.wait_for_timeout(500)
            f3 = page.locator(".modal-mask:visible").last
            sh = f3.locator("datalist#sh-options-form option").evaluate_all("(els) => els.map(e => (e.value || e.getAttribute('value') || '') + '|' + (e.textContent || '').trim())")
            rec(len(sh) >= 2, f"VT-SUG-75 新建表单「责任人」候选 {len(sh)} 项（≥2，来自 stakeholder.list）")
            rec(any(v.startswith("候选人甲|") for v in sh), f"VT-SUG-75 候选值=姓名、标签含编号：{sh[:2]}")
            rec(f3.locator('input[list="sh-options-form"]').count() == 1,
                "VT-SUG-76 责任人仍是**文本输入**（不是 select —— 值即文本、回填天然正确）")
            f3.locator('button:has-text("取消")').first.click()
            page.wait_for_timeout(300)
            page.locator("table.tbl tr.data button.b-link").first.click()
            page.wait_for_timeout(900)
            m2 = page.locator(".modal-mask:visible").last
            sh2 = m2.locator("datalist#sh-options-modal option").count()
            rec(sh2 >= 2, f"VT-SUG-76 详情模态「责任人」候选 {sh2} 项")
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
        print(f"    - [{s}] {note}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
