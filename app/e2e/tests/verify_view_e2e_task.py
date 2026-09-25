"""e2e 前端验收 · e2e/task「任务管理」（playwright，可直接运行）。

对照 app/e2e/task/前端测试用例.md 第⑧步用例（契约无 update/delete，单据变更仅经状态机
start / complete / reopen）。断言：§1 本页渲染（.kpi==0 防粘滞）→ §2 造数后列表有数据
（状态/优先级/负责人三路筛选抽样 + 组合空态）→ §3 详情模态全字段（待办态页脚「启动」/
已完成态终态无按钮）→ §4 表单落库回显（创建 + 必填校验）与状态机行内按钮三态收敛
（启动 / 完成 / 退回）→ §6 全程 0 console error / 0 pageerror / 0 HTTP≥400。
运行：python app/e2e/tests/verify_view_e2e_task.py
"""
import os, pathlib, socket, subprocess, sys, time, http.client, atexit, sqlite3


def _project_root() -> pathlib.Path:
    """向上找项目根（含 fde_platform/ 的目录）。不用 parents[N] 定死层级——
    本范式会被照抄进不同深度的脚本（tests/、design-plus/…），按标记定位才稳。"""
    p = pathlib.Path(__file__).resolve().parent
    while not (p / "fde_platform").is_dir():
        if p.parent == p:
            raise RuntimeError("无法定位项目根目录（未找到 fde_platform/）")
        p = p.parent
    return p


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from fde_platform.shadowdb import shadow_dbs, shadow_clear, shadow_clear_prefs, auth_db_path  # noqa: E402
from fde_platform.view_watchdog import install_watchdog  # noqa: E402

# 影子库：业务库与平台库**都**复制到副本 → 真库零字节接触，**不用停 dev server**。
# config=True 是必需的：本脚本要播种 admin（写 config/auth.db），不影子化就会污染真库。
_shadow = shadow_dbs(env=True, inprocess=False, config=True)
_shadow.__enter__()
# ⚠ **必须在副本上清表**（2026-09-18 加）：影子库是**真库的拷贝** —— 真演示数据
# （e2e 的 M001/M002、PSC 的各主数据）会被一起复制进来，而本脚本自带的造数会撞主键。
# 此前不写这句也没事，只是因为当时副本落盘在另一个目录、平台读到的其实是**新建空库**；
# 布局修正后"副本是空的"这个隐含假设当场暴露 ⇒ 显式清表，语义与《验证门禁.md》
# §四之二的「view e2e 起点 = 空表」一致。
shadow_clear("e2e")
# **个人 UI 偏好也要清**：它是操作者本机状态（如"手动隐藏过某列"），
# 不清就会让用例结果取决于谁在哪台机器上跑（实测：真库里藏了 sales_forecast 的两列）。
shadow_clear_prefs()
atexit.register(_shadow.__exit__, None, None, None)

# admin 账号（登录用）：隔离后空库播种，并预标记「已改密」跳过首次强制改密
# （否则 password_changed=0 会挡登录与 /api 调用，见 fde_platform/auth.py gate ②.5）。
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
try:
    _auth_db = auth_db_path()
    if _auth_db.exists():
        _conn = sqlite3.connect(str(_auth_db))
        _conn.execute("UPDATE users SET password_changed = 1 WHERE username = 'admin'")
        _conn.commit()
        _conn.close()
except Exception:
    pass


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_up(port, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("GET", "/api/groups")
            resp = conn.getresponse()
            resp.read()
            return True
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("platform 未在限定时间内启动")


# §0 造数（真实 REST · 带会话 Cookie）。**member 必须先于 task**：
# task.create 内部经 member.get 校验负责人存在性（BR-6），成员不存在则创建失败。
SEED_JS = r"""async () => {
  const call = async (app, svc, params) => {
    const r = await fetch(`/api/apps/e2e/${app}/call/${svc}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(params || {})
    });
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) {}
    if (!r.ok) throw new Error(`${app}.${svc} HTTP ${r.status} ${text.slice(0, 160)}`);
    // 平台统一信封 {status:"ok"|"error"}：**业务失败也是 HTTP 200**，必须显式判 status，
    // 否则 FdeError 会被静默当成成功（造数假成功、断言才炸，定位成本高）。
    if (data && data.status === "error") {
      throw new Error(`${app}.${svc} ${data.message || JSON.stringify(data).slice(0, 160)}`);
    }
    return data ? data.data : null;
  };

  // §0 字典：M001 张管理（列表姓名回显） / M002 李成员（筛选抽样 + 表单指派）
  await call("member", "create", {
    member_no: "M001", name: "张管理", email: "m001@example.com", role: "admin"
  });
  await call("member", "create", {
    member_no: "M002", name: "李成员", email: "m002@example.com", role: "member"
  });

  // D1/D2 待办（low/high）；P1 进行中（create → start）；F1 已完成（create → start → complete）
  const d1 = await call("task", "create", {
    title: "待办任务D1", description: "D1 描述文本",
    assignee_member_no: "M001", priority: "low"
  });
  const d2 = await call("task", "create", {
    title: "待办任务D2", assignee_member_no: "M002", priority: "high"
  });
  const p1 = await call("task", "create", {
    title: "进行中任务P1", assignee_member_no: "M001", priority: "low"
  });
  const p1s = await call("task", "start", { task_no: p1.task_no });
  const f1 = await call("task", "create", {
    title: "已完成任务F1", assignee_member_no: "M002", priority: "high"
  });
  await call("task", "start", { task_no: f1.task_no });
  const f1s = await call("task", "complete", { task_no: f1.task_no });

  return {
    d1: d1.task_no, d2: d2.task_no, p1: p1.task_no, f1: f1.task_no,
    d1_status: d1.status, d2_status: d2.status,
    p1_status: p1s.status, f1_status: f1s.status
  };
}"""


def fill_in(scope, selector, value, what):
    """按**模态内**选择器填值，并断言输入框恰有 1 个。

    ⚠ 不用「label + `following::input[1]`」那套（psc 样板里的 `fill_labeled`）：
    XPath 的 `following::` 轴**只受起点约束、不受 scope 约束** —— 它会顺着文档序走出模态，
    抓到模态之外的全局输入框（实测本平台抓到壳里 Agent 栏的 `#agent-rail-file`，
    于是「填任务描述」卡在 `element is not visible` 30 秒超时）。
    """
    loc = scope.locator(selector)
    assert loc.count() == 1, f"{what} 输入框应恰有 1 个（实际 {loc.count()} 个）"
    loc.fill(value)


def click_button(scope, texts):
    for t in texts:
        loc = scope.locator(
            f'button:has-text("{t}"), a:has-text("{t}"), .btn:has-text("{t}")'
        )
        if loc.count():
            loc.first.click()
            return True
    raise AssertionError(f"未找到按钮：{texts}")


def open_modal(page):
    # 页面挂两个 .modal-mask（详情 + 创建表单），隐藏者也在 DOM；等「可见」的模态再取 last。
    page.locator(".modal:visible, [role='dialog']:visible").first.wait_for(state="visible", timeout=10000)
    return page.locator(".modal:visible, [role='dialog']:visible").last


def wait_modal(page, timeout=10000):
    """轮询 .modal-mask:visible .loadbox 消失（pitfalls #16）。"""
    end = time.time() + timeout
    while time.time() < end:
        if page.locator(".modal-mask:visible .loadbox").count() == 0:
            return True
        page.wait_for_timeout(200)
    raise AssertionError("模态载入超时：.loadbox 未消失")


def close_modal(page, modal):
    btn = modal.locator('button:has-text("关闭"), button:has-text("取消")')
    if btn.count():
        btn.first.click()
    else:
        page.keyboard.press("Escape")
    try:
        modal.wait_for(state="hidden", timeout=3000)
    except Exception:
        page.keyboard.press("Escape")
    page.wait_for_timeout(250)


def row_of(page, no):
    """按**精确单号**定位列表行（列表按 created_at DESC 排序，不假设顺序，pitfalls #17）。"""
    return page.locator(f'main table tbody tr.data:has-text("{no}")').first


def row_status(page, no):
    """行**状态单元格**（第 3 列）——不读整行文本：D1 标题「待办任务D1」含「待办」、
    P1 标题含「进行中」，用整行 `has_text` 判状态会**恒真**（假过）。"""
    return row_of(page, no).locator("td").nth(2).inner_text().strip()


def wait_row_status(page, no, expect, timeout=8000):
    """轮询状态单元格收敛到 expect —— 状态机动作后页面 list.load(当前页) 是异步重载，
    直接读会读到旧行（这不是"等得久一点"，而是"断言点在重载之前的假过"）。"""
    end = time.time() + timeout
    last = ""
    while time.time() < end:
        if row_of(page, no).count():
            last = row_status(page, no)
            if last == expect:
                return
        page.wait_for_timeout(150)
    raise AssertionError(f"行 {no} 状态未收敛到 {expect!r}（实际 {last!r}）")


def wait_total(page, total, timeout=8000):
    """轮询分页条收敛到「共 N 条」（过滤控件连点会并发重载，等收敛而不是 sleep 猜）。"""
    end = time.time() + timeout
    last = ""
    while time.time() < end:
        last = page.locator("main").inner_text()
        if f"共 {total} 条" in last:
            return
        page.wait_for_timeout(150)
    raise AssertionError(f"列表未收敛到「共 {total} 条」（实际 {last[:200]!r}）")


def filter_selects(page):
    """过滤条两个下拉（顺序 = [负责人, 优先级]；创建表单里的 select 藏在未打开的模态内）。"""
    sel = page.locator("main .tagline:visible select")
    assert sel.count() == 2, f"过滤条应有 2 个下拉（负责人 / 优先级），实际 {sel.count()} 个"
    return sel


def act_buttons(row):
    """行内**可见**动作按钮文案集（x-show 隐藏者仍在 DOM → 一律 :visible，pitfalls #14）。"""
    labels = []
    for t in ("启动", "完成", "退回"):
        if row.locator(f'button:visible:has-text("{t}")').count():
            labels.append(t)
    return labels


def wait_buttons(page, no, expect, timeout=8000):
    """轮询行内动作按钮收敛到 expect（顺序无关），返回收敛到的实际值。

    ⚠ **为什么必须等按钮本身**（2026-09-18 踩到）：状态机动作后，行内**状态文本**与
    **动作按钮**是 Alpine 的两处独立绑定，重渲染不在同一拍上。此前写的是
    `wait_row_status(...)` 之后**直接断按钮** —— 负载高时状态文本已变、按钮还是上一拍的，
    于是**单跑必过、全量套件并发跑必红**（实际报错信息还会自相矛盾：
    「应变回【启动】，实际 ['启动']」—— 因为断言时的值与拼错误信息时的值是两次读取）。
    教训与 `demand` 那次同源：**等待条件必须是你要断言的那个东西**；
    错误信息也不要重新求值，用等到的那个快照。
    """
    end = time.time() + timeout
    last = None
    while time.time() < end:
        if row_of(page, no).count():
            last = sorted(act_buttons(row_of(page, no)))
            if last == sorted(expect):
                return last
        page.wait_for_timeout(150)
    raise AssertionError(f"行 {no} 动作按钮未收敛到 {sorted(expect)}（实际 {last}）")


def reset_filters(page):
    """复位过滤（负责人 → 优先级 → 状态 chips 逐个设，避免并发重载互相覆盖）。"""
    sels = filter_selects(page)
    sels.nth(0).select_option(label="全部负责人")
    page.wait_for_timeout(250)
    sels.nth(1).select_option(label="全部优先级")
    page.wait_for_timeout(250)
    page.locator("main .fchip:visible").filter(has_text="全部").first.click()
    page.wait_for_timeout(250)


STEP = ""


def main():
    global STEP
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        env={**os.environ, "PLATFORM_PORT": str(port), "PORT": str(port)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    errors = []
    ignored = []
    # 卡住诊断（2026-09-18）：页面冻死/渲染进程崩溃时 playwright 调用不返回 ——
    # 由这个守护线程把「最后完成的步骤 + 已收集的错误」打出来；否则超时被强杀时现场全丢。
    install_watchdog(errors, step_getter=lambda: STEP)

    def attach(page):
        def on_console(msg):
            if msg.type == "error":
                errors.append(msg.text[:140])

        def on_pageerror(err):
            errors.append(str(err)[:140])

        def on_response(resp):
            if resp.status >= 400:
                url = resp.url
                if "/favicon.ico" in url or url.endswith(".map"):
                    ignored.append(f"HTTP {resp.status} {url}")
                    return
                errors.append(f"HTTP {resp.status} {url}")

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("response", on_response)

    try:
        wait_up(port)
        from playwright.sync_api import sync_playwright

        base = f"http://127.0.0.1:{port}"

        with sync_playwright() as p:
            browser = p.chromium.launch()

            # admin 会话：登录页 + 登录后 new_page
            ctx = browser.new_context()
            login_page = ctx.new_page()
            attach(login_page)

            login_page.goto(f"{base}/login")
            login_page.fill('input[name="username"]', "admin")
            login_page.fill('input[name="password"]', "admin")
            login_page.click('button[type="submit"]')
            login_page.wait_for_url("**/", timeout=15000)

            page = ctx.new_page()
            attach(page)

            page.goto(f"{base}/view/e2e/")
            page.wait_for_selector(".rail, .menu, nav", timeout=15000)

            # ===================== §0 造数（真实 REST，带会话 Cookie）=====================
            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("d1"), f"造数失败：{seed}"
            d1, d2, p1, f1 = seed["d1"], seed["d2"], seed["p1"], seed["f1"]
            for _no in (d1, d2, p1, f1):
                assert str(_no).startswith("T"), f"task_no 应由后端生成（T+uuid，BR-7）：{_no!r}"
            assert seed["d1_status"] == "待办" and seed["d2_status"] == "待办", seed
            assert seed["p1_status"] == "进行中", seed          # 造数链 start 真的生效（BR-10）
            assert seed["f1_status"] == "已完成", seed          # 造数链 complete 真的生效（BR-11）

            # ===================== §1 本页渲染（防粘滞）=====================
            # VT-ROUTE-01 路由渲染（含挂载防粘滞 .kpi==0）
            STEP = "§1 路由渲染"
            page.evaluate("location.hash = '#/task'")
            page.wait_for_selector("main table.tbl", timeout=10000)
            page.wait_for_timeout(700)

            main_txt = page.locator("main").inner_text()
            assert main_txt.strip(), "task 页面无内容"
            assert page.locator("main .card").count() > 0, "task 未渲染 card"
            assert page.locator(".kpi").count() == 0, "task 挂载未重建（残留看板 KPI）"
            assert "任务台账" in main_txt, "过滤条缺「任务台账」"
            assert "状态机 · 待办 → 进行中 → 已完成" in main_txt, "过滤条缺状态机副题"
            th = page.locator("main table.tbl").first.inner_text()
            for col in ["任务编号", "标题", "状态", "负责人", "优先级", "描述", "创建时间", "更新时间", "操作"]:
                assert col in th, f"表头缺列：{col}"
            assert "共" in main_txt and "条" in main_txt, "分页条缺「共 … 条」"

            # ===================== §2 列表有数据 + 三路筛选抽样 =====================
            # VT-LIST-01 列表含所造单号（D1 行逐字段回显）
            STEP = "§2 列表有数据"
            wait_total(page, 4)
            d1_row = row_of(page, d1)
            assert d1_row.count() == 1, f"列表应含所造 D1（{d1}）"
            row_txt = d1_row.inner_text()
            for v in [d1, "待办任务D1", "待办", "M001", "张管理", "low", "D1 描述文本"]:
                assert v in row_txt, f"D1 行缺值：{v}（实际 {row_txt!r}）"
            assert row_status(page, d1) == "待办", "D1 状态单元格应为「待办」"
            assert row_status(page, p1) == "进行中", "P1 状态单元格应为「进行中」（造数链 start）"
            assert row_status(page, f1) == "已完成", "F1 状态单元格应为「已完成」（造数链 complete）"

            # VT-LIST-02 状态 chips 抽样（= task.list 的 status 参数）
            STEP = "§2 状态筛选 chips"
            page.locator("main .fchip:visible").filter(has_text="待办").first.click()
            wait_total(page, 2)
            assert row_of(page, d1).count() == 1 and row_of(page, d2).count() == 1, "「待办」应含 D1 + D2"
            assert row_of(page, p1).count() == 0 and row_of(page, f1).count() == 0, "「待办」不应含 P1 / F1"
            page.locator("main .fchip:visible").filter(has_text="进行中").first.click()
            wait_total(page, 1)
            assert row_of(page, p1).count() == 1, "「进行中」应恰含 P1"
            assert row_of(page, d1).count() == 0, "「进行中」不应含 D1"
            page.locator("main .fchip:visible").filter(has_text="全部").first.click()
            wait_total(page, 4)

            # VT-LIST-03 优先级抽样（= task.list 的 priority 参数，选项值为原值 low/high）
            STEP = "§2 优先级筛选"
            filter_selects(page).nth(1).select_option("high")
            wait_total(page, 2)
            assert row_of(page, d2).count() == 1 and row_of(page, f1).count() == 1, "high 应含 D2 + F1"
            assert row_of(page, d1).count() == 0 and row_of(page, p1).count() == 0, "high 不应含 low 的 D1 / P1"

            # VT-LIST-04 负责人抽样（= task.list 的 assignee_member_no 参数，value=member_no）
            STEP = "§2 负责人筛选"
            filter_selects(page).nth(1).select_option(label="全部优先级")
            page.wait_for_timeout(300)
            filter_selects(page).nth(0).select_option("M001")
            wait_total(page, 2)
            assert row_of(page, d1).count() == 1 and row_of(page, p1).count() == 1, "M001 应含 D1 + P1"
            assert row_of(page, d2).count() == 0 and row_of(page, f1).count() == 0, "M001 不应含 M002 的 D2 / F1"
            assert "张管理" in row_of(page, p1).inner_text(), "M001 行负责人列应回显成员姓名（memberMap 命中）"

            # VT-LIST-05 组合筛选无匹配 → 空态（不抛错、0 HTTP≥400）
            STEP = "§2 组合筛选空态"
            page.locator("main .fchip:visible").filter(has_text="进行中").first.click()
            page.wait_for_timeout(300)
            filter_selects(page).nth(0).select_option("M002")
            wait_total(page, 0)
            empty = page.locator("main table td.empty")
            assert empty.count() == 1, "空态行未渲染（进行中 ∩ M002 应为空集）"
            assert "无匹配数据" in empty.first.inner_text(), "空态文案不符"
            assert page.locator("main table tbody tr.data").count() == 0, "空态下不应有数据行"
            reset_filters(page)
            wait_total(page, 4)

            # ===================== §3 详情模态全字段 =====================
            # VT-MODAL-01 详情模态（待办态 · 全字段 + 页脚「启动」）
            STEP = "§3 详情模态（待办）"
            row_of(page, d1).locator(".b-link").first.click()
            modal = open_modal(page)
            wait_modal(page)
            # 详情内容（.kv）仅在 !loading && d 时渲染，等它出现确保载入完成
            modal.locator(".modal-bd .kv").first.wait_for(state="visible", timeout=10000)

            docno = modal.locator(".docno").first.inner_text()
            assert docno.strip() == d1, f"详情头带 docno 应为 task_no（本页写法，非「任务详情 · X」）：{docno!r}"
            assert "任务详情 · TASK DETAIL" in modal.locator(".sub").first.inner_text(), "详情头带副题不符"

            # ⚠ 断言 scope **排除 `details.raw`**（那坨 JSON 含全部字段值）：
            # 若 KV 渲染坏了而 raw 还在，读整块 .modal-bd 会**假过**。
            bd = modal.locator(".modal-bd").first
            sec_txt = "\n".join(bd.locator(".sec").all_inner_texts())
            for label in ["基本信息", "指派信息", "任务描述", "时间信息"]:
                assert label in sec_txt, f"详情模态缺分组标题：{label}"
            kv_txt = "\n".join(bd.locator(".kv").all_inner_texts())
            for label in ["任务编号", "状态", "标题", "优先级", "负责人编号", "负责人姓名", "创建时间", "更新时间"]:
                assert label in kv_txt, f"详情模态缺字段标签：{label}"
            for v in [d1, "待办任务D1", "待办", "low", "M001", "张管理"]:
                assert v in kv_txt, f"详情模态 KV 缺字段值：{v}"
            desc = bd.locator(
                'xpath=.//div[@class="sec"][normalize-space(.)="任务描述"]/following-sibling::div[1]')
            assert desc.first.inner_text().strip() == "D1 描述文本", "详情「任务描述」内容不符"
            assert modal.locator("details.raw").count() == 1, "详情缺「原始数据」折叠块"
            assert modal.locator("details.raw[open]").count() == 0, "「原始数据」应默认收起"

            ft = modal.locator(".modal-ft").first
            assert ft.locator('button:visible:has-text("启动")').count() == 1, "待办态页脚应可见【启动】"
            assert ft.locator('button:visible:has-text("完成")').count() == 0, "待办态页脚不应有【完成】"
            assert ft.locator('button:visible:has-text("退回")').count() == 0, "待办态页脚不应有【退回】"
            close_modal(page, modal)

            # VT-MODAL-02 详情模态（已完成 · 终态无动作按钮）
            STEP = "§3 详情模态（已完成）"
            row_of(page, f1).locator(".b-link").first.click()
            modal = open_modal(page)
            wait_modal(page)
            modal.locator(".modal-bd .kv").first.wait_for(state="visible", timeout=10000)
            assert modal.locator(".modal-hd .st").first.inner_text().strip() == "已完成", \
                "已完成态头带状态徽章不符"
            ft = modal.locator(".modal-ft").first
            assert ft.locator('button:visible:has-text("启动")').count() == 0, "终态不应有【启动】"
            assert ft.locator('button:visible:has-text("完成")').count() == 0, "终态不应有【完成】"
            assert ft.locator('button:visible:has-text("退回")').count() == 0, "终态不应有【退回】"
            assert "已完成 · 终态，无可用操作" in ft.inner_text(), "终态页脚缺说明文案（BR-13）"
            close_modal(page, modal)

            # ===================== §4 表单落库回显 + 状态机动作 =====================
            # VT-FORM-01 创建（模态表单 → 落库 → 列表 + 详情双回显）
            STEP = "§4 创建表单"
            click_button(page, ["＋ 新建任务", "新建任务", "新建"])
            modal = open_modal(page)
            assert "新建任务" in modal.locator(".docno").first.inner_text(), "创建模态标题不符"

            fill_in(modal, 'input[placeholder="必填 · 最多 200 字"]', "新任务N1", "任务标题")
            # 负责人 / 优先级下拉：xpath 起点是**本模态内**的 label（`following::select` 在此安全：
            # label 之后最近的 select 就是同一 frow 里的那个；不做「按 label 全局找输入框」那套）
            modal.locator('xpath=.//label[contains(normalize-space(.), "负责人")]/following::select[1]') \
                .select_option("M002")
            modal.locator('xpath=.//label[contains(normalize-space(.), "优先级")]/following::select[1]') \
                .select_option("high")
            # description 收在「更多字段 ▾」折叠区：先展再填（详设 §2.3）
            modal.locator('xpath=.//*[contains(text(), "更多字段")]').first.click()
            page.wait_for_timeout(300)
            assert modal.locator(".collapse.open").count() == 1, "「更多字段」未展开"
            fill_in(modal, 'textarea[placeholder="可选 · 最多 2000 字"]', "N1 表单创建描述", "任务描述")

            click_button(modal, ["创建任务"])
            page.wait_for_selector('.toast:has-text("已创建任务")', timeout=5000)
            toast_txt = page.locator('.toast:has-text("已创建任务")').first.inner_text()
            assert "已创建任务 · T" in toast_txt, f"创建 toast 应带出新 task_no：{toast_txt!r}"
            n1 = toast_txt.rsplit("·", 1)[-1].strip()          # 单号从 toast 捕获，不硬编（BR-7）
            assert n1.startswith("T") and len(n1) > 8, f"toast 里的 task_no 不合法：{n1!r}"
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(500)

            wait_total(page, 5)
            n1_txt = row_of(page, n1).inner_text()
            for v in [n1, "新任务N1", "待办", "M002", "李成员", "high", "N1 表单创建描述"]:
                assert v in n1_txt, f"N1 行缺值：{v}（实际 {n1_txt!r}）"
            assert row_status(page, n1) == "待办", "新任务初始状态应恒为「待办」（BR-8）"

            row_of(page, n1).locator(".b-link").first.click()   # 详情二次回显
            modal = open_modal(page)
            wait_modal(page)
            modal.locator(".modal-bd .kv").first.wait_for(state="visible", timeout=10000)
            bd_txt = modal.locator(".modal-bd").first.inner_text()
            for v in [n1, "新任务N1", "待办", "high", "M002", "李成员", "N1 表单创建描述"]:
                assert v in bd_txt, f"N1 详情回显缺：{v}"
            close_modal(page, modal)

            # VT-FORM-02 创建必填校验（前端拦 · 不发请求）
            STEP = "§4 必填校验"
            click_button(page, ["＋ 新建任务", "新建任务", "新建"])
            modal = open_modal(page)
            create_reqs = []

            def on_request(req):
                if req.method == "POST" and "/call/create" in req.url and "/e2e/task/" in req.url:
                    create_reqs.append(req.url)
            page.on("request", on_request)

            click_button(modal, ["创建任务"])
            page.wait_for_timeout(400)
            page.remove_listener("request", on_request)

            assert not create_reqs, f"必填校验不应发出 create 请求：{create_reqs}"
            page.wait_for_selector('.toast:has-text("请填写任务标题")', timeout=5000)
            assert modal.is_visible(), "必填校验后模态应保持打开"
            close_modal(page, modal)

            # VT-STATE-01 行内动作按钮随状态收敛（三态矩阵：待办 / 进行中 / 已完成）
            STEP = "§4 状态机按钮收敛"
            reset_filters(page)
            wait_total(page, 5)
            wait_row_status(page, d1, "待办")
            assert wait_buttons(page, d1, ["启动"]) == ["启动"], "待办行应仅有【启动】"
            wait_row_status(page, p1, "进行中")
            assert wait_buttons(page, p1, ["完成", "退回"]) == ["完成", "退回"], \
                "进行中行应恰有【完成】【退回】"
            wait_row_status(page, f1, "已完成")
            assert wait_buttons(page, f1, [], timeout=2000) == [], "已完成行（终态）不应有动作按钮"

            # VT-STATE-02 启动（待办 → 进行中）
            STEP = "§4 启动"
            row_of(page, d1).locator('button:visible:has-text("启动")').first.click()
            page.wait_for_selector(f'.toast:has-text("已启动 · {d1}")', timeout=5000)
            wait_row_status(page, d1, "进行中")
            assert wait_buttons(page, d1, ["完成", "退回"]) == ["完成", "退回"], \
                "启动后行按钮应变【完成】【退回】"
            wait_total(page, 5)

            # VT-STATE-03 完成（进行中 → 已完成 · 终态）
            STEP = "§4 完成"
            row_of(page, d1).locator('button:visible:has-text("完成")').first.click()
            page.wait_for_selector(f'.toast:has-text("已完成 · {d1}")', timeout=5000)
            wait_row_status(page, d1, "已完成")
            assert wait_buttons(page, d1, [], timeout=2000) == [], "完成后（终态）行不应有动作按钮"

            # VT-STATE-04 退回（进行中 → 待办；reopen 只允许进行中→待办，BR-12）
            STEP = "§4 退回"
            row_of(page, p1).locator('button:visible:has-text("退回")').first.click()
            page.wait_for_selector(f'.toast:has-text("已退回 · {p1}")', timeout=5000)
            wait_row_status(page, p1, "待办")
            assert wait_buttons(page, p1, ["启动"]) == ["启动"], "退回后行按钮应变回【启动】"
            page.locator("main .fchip:visible").filter(has_text="待办").first.click()
            wait_total(page, 3)                                 # 待办池 = D2 + N1 + 退回的 P1
            assert row_of(page, p1).count() == 1, "退回的 P1 应回到「待办」筛选结果中"
            assert row_of(page, d1).count() == 0, "已完成的 D1 不应在「待办」筛选中"
            reset_filters(page)

            # ===================== §6 0 报错 =====================
            # VT-ERR-01 全程 0 报错 + 豁免受检
            STEP = "§6 0 报错"
            assert not errors, f"task 会话前端报错：{errors[:5]}"
            # **豁免也要受检**：`ignored` 收集了却从不校验，等于给「静默吞掉」开了口子 ——
            # 任何新形态的 4xx/console error 都能混进来而不被任何人发现。本页无受限会话，
            # 故只认 favicon / sourcemap 两种豁免理由，其余一律报出。
            for _item in ignored:
                _ok = ("/favicon.ico" in _item or ".map" in _item)
                assert _ok, f"豁免理由不成立（既不是 favicon 也不是 .map）：{_item!r}"
            if ignored:
                print(f"  · 本次豁免 {len(ignored)} 条：{ignored[:3]}")
            print("VERIFY_VIEW_e2e_task: PASS")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"FAIL @ {STEP}: {e}")
        sys.exit(1)
