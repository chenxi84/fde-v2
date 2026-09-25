"""e2e 前端验收 - e2e:member（成员管理）
断言：路由渲染防粘滞（.kpi==0）→ 空库空态 → 造数后列表有数据（关键字/角色 chips 抽样 +
分页参数 + 平台列排序）→ 详情模态全字段（含 created_at 契约缺口取证）→
创建落库回显（创建/必填校验/后端负向/无编辑入口）→ 全程 0 console error / 0 pageerror / 0 HTTP≥400。
运行：python app/e2e/tests/verify_view_e2e_member.py
"""
import atexit
import http.client
import json
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import time


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


# 造数 / 取证统一走**真实 REST**（pitfalls #18）：页面内 fetch `/api/apps/e2e/member/call/<服务>`
# （带会话 Cookie）。平台把业务错包成 HTTP 200 + {status:"error",kind:"business"}，
# 故这里同时回传 http 码与信封，供「0 HTTP≥400」与负向路径两处断言使用。
REST_JS = r"""async ({service, params}) => {
  const r = await fetch(`/api/apps/e2e/member/call/${service}`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(params || {})
  });
  const text = await r.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch (e) {}
  return {http: r.status, body, raw: text.slice(0, 300)};
}"""


def rest(page, service, params=None):
    """调用 member 服务并返回 data；业务错/协议错一律抛（造数必须干净）。"""
    res = page.evaluate(REST_JS, {"service": service, "params": params or {}})
    if res["http"] != 200 or not res["body"] or res["body"].get("status") != "ok":
        raise AssertionError(f"member.{service} 调用失败：HTTP {res['http']} {res['raw']!r}")
    return res["body"].get("data")


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
    # 详情 + 创建两个 .modal 常驻 DOM（x-show 隐藏），故一律用「可见者」定位：
    # 隐藏的那个若被 .first/.last 命中，读文本会拿到空/旧内容（pitfalls #14/#15）。
    page.locator("main .modal:visible").first.wait_for(state="visible", timeout=10000)
    return page.locator("main .modal:visible").last


def wait_modal(page, timeout=10000):
    """轮询 .modal-mask:visible .loadbox 消失（pitfalls #16）。"""
    end = time.time() + timeout
    while time.time() < end:
        if page.locator("main .modal-mask:visible .loadbox").count() == 0:
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


def open_create(page):
    """点「+ 新建成员」并返回创建模态（正文用 placeholder 精确定位）。"""
    click_button(page, ["+ 新建成员", "新建成员"])
    modal = open_modal(page)
    modal.locator('input[placeholder="如 M001"]').first.wait_for(state="visible", timeout=5000)
    return modal


def fill_create(modal, member_no, name, email, role):
    modal.locator('input[placeholder="如 M001"]').first.fill(member_no)
    modal.locator('input[placeholder="成员姓名"]').first.fill(name)
    modal.locator('input[placeholder="name@example.com"]').first.fill(email)
    # option 的 value 是 `admin` / `member`（文案「管理员」/「成员」），按 value 选（详情 §2.3）
    modal.locator("select").first.select_option(role)


STEP = ""


def step(name):
    global STEP
    STEP = name
    print(f"  -> {name}", flush=True)


def main():
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

            # ===================== §1 本页渲染（防粘滞）=====================
            # §1 VT-ROUTE-01 路由渲染（含挂载防粘滞 .kpi==0）
            step("§1 路由渲染")
            page.evaluate("location.hash = '#/member'")
            page.wait_for_selector("main table.tbl", timeout=10000)
            page.wait_for_timeout(700)

            main_txt = page.locator("main").inner_text()
            assert main_txt.strip(), "member 页面无内容"
            assert page.locator("main .card").count() > 0, "member 未渲染 card"
            assert page.locator(".kpi").count() == 0, "member 挂载未重建（残留看板 KPI）"
            # 主区头 = PAGE_META.title（壳层按 route 取 menu 项）
            assert page.locator("header.top h1").inner_text().strip() == "成员管理", \
                "主区头标题不是「成员管理」"
            # 列表三段式：过滤条 / 表头 / 分页条
            assert "成员列表" in main_txt, "过滤条缺「成员列表」"
            assert "主数据 · 创建后只读" in main_txt, "过滤条缺副题「主数据 · 创建后只读」"
            th = page.locator("main table.tbl").first.inner_text()
            for col in ["成员编号", "姓名", "邮箱", "角色", "创建时间"]:
                assert col in th, f"表头缺列：{col}"
            assert "共" in main_txt and "条" in main_txt, "分页条缺「共 … 条」"
            for btn in ["查询", "+ 新建成员"]:
                assert page.locator(f'main button:has-text("{btn}")').count() >= 1, \
                    f"工具栏缺按钮：{btn}"

            # §1 VT-ROUTE-02 空库空态（同时充当「起点确实是空表」的分母闸）
            step("§1 空库空态")
            empty = page.locator("main table td.empty")
            assert empty.count() == 1, "空库应有 1 行空态行"
            empty_txt = empty.first.inner_text()
            assert "暂无成员" in empty_txt, f"库空态文案不符：{empty_txt!r}"
            assert "点「新建成员」创建" in empty_txt, f"库空态缺引导语：{empty_txt!r}"
            assert page.locator("main table tbody tr.data").count() == 0, "空库不应有数据行"
            assert "共 0 条" in page.locator("main").inner_text(), "空库分页条应「共 0 条」"

            # ===================== §0 造数（真实 REST，带会话 Cookie）=====================
            step("§0 造数 M001/M002")
            rest(page, "create", {"member_no": "M001", "name": "张三",
                                  "email": "zhangsan@example.com", "role": "member"})
            rest(page, "create", {"member_no": "M002", "name": "李四",
                                  "email": "lisi@e2e.dev", "role": "admin"})
            seeded = rest(page, "list", {})
            # 分母非空闸：先证明造数真的落库，再断言「列表里有什么」
            assert seeded["total"] == 2, f"造数后 list.total 应为 2，实际 {seeded.get('total')}"

            # ===================== §2 列表有数据 + 过滤抽样 =====================
            # §2 VT-LIST-01 列表含所造编号（M001 行逐字段回显）
            step("§2 列表有数据")
            click_button(page, ["查询"])
            page.wait_for_selector('main table tbody tr:has-text("M001")', timeout=10000)
            page.wait_for_timeout(400)

            assert page.locator("main table tbody tr.data").count() == 2, "造数后应恰 2 行数据"
            m001_row = page.locator('main table tbody tr:has-text("M001")').first
            row_txt = m001_row.inner_text()
            for v in ["M001", "张三", "zhangsan@example.com", "成员"]:
                assert v in row_txt, f"M001 行缺值：{v}（实际 {row_txt!r}）"
            m002_row = page.locator('main table tbody tr:has-text("M002")').first
            assert "管理员" in m002_row.inner_text(), "M002 角色徽章应为「管理员」（roleLabel 映射）"
            assert "共 2 条" in page.locator("main").inner_text(), "造数后应「共 2 条」"

            # §2 VT-LIST-04 分页条与分页参数（page 契约 integer）
            step("§2 分页条与分页参数")
            list_bodies = []

            def on_req(req):
                if req.method == "POST" and "/apps/e2e/member/call/list" in req.url:
                    try:
                        list_bodies.append(json.loads(req.post_data or "{}"))
                    except Exception:
                        list_bodies.append({})

            page.on("request", on_req)
            click_button(page, ["查询"])
            page.wait_for_timeout(600)
            page.remove_listener("request", on_req)

            assert list_bodies, "未捕获到 /call/list 请求（分页参数无从断言）"
            last_body = list_bodies[-1]
            assert isinstance(last_body.get("page"), int), \
                f"list 请求的 page 应为 JSON 数字（契约 integer）：{last_body!r}"
            assert last_body.get("page") == 1, f"重载应回第 1 页：{last_body!r}"
            pager_txt = page.locator("main").inner_text()
            assert "共 2 条" in pager_txt and "1 / 1" in pager_txt, "分页条应「共 2 条」「1 / 1」"
            assert page.locator('main button:has-text("上一页")').first.is_disabled(), \
                "单页时「上一页」应禁用"

            # §2 VT-LIST-02 关键字模糊抽样 + 无命中空态
            step("§2 关键字抽样 张 / 不存在XYZ")
            kw = page.locator('main input[placeholder="编号 / 姓名 / 邮箱"]').first
            kw.fill("张")
            kw.press("Enter")
            page.wait_for_timeout(600)
            assert page.locator('main table tbody tr:has-text("M001")').count() == 1, \
                "keyword=张 应命中 M001"
            assert page.locator('main table tbody tr:has-text("M002")').count() == 0, \
                "keyword=张 不应含 M002（姓名「李四」无「张」）"
            assert "共 1 条" in page.locator("main").inner_text(), "keyword=张 应「共 1 条」"

            kw.fill("不存在XYZ")
            kw.press("Enter")
            page.wait_for_timeout(600)
            empty = page.locator("main table td.empty")
            assert empty.count() == 1, "无命中应渲染空态行"
            hit_txt = empty.first.inner_text()
            assert "无符合条件的成员" in hit_txt, f"过滤空态文案不符：{hit_txt!r}"
            assert "暂无成员" not in hit_txt, "带过滤时应走「无符合条件」分支，而非库空态"
            assert "共 0 条" in page.locator("main").inner_text(), "无命中应「共 0 条」"

            # §2 VT-LIST-03 角色 chips 抽样 + 组合过滤
            step("§2 角色 chips + 组合过滤")
            kw.fill("")
            kw.press("Enter")
            page.wait_for_timeout(500)
            # chip 文案 = roleLabel(r) + '(' + r + ')'，用 text-is 精确匹配（「管理员(admin)」内含 admin）
            page.locator('main .fchip:text-is("管理员(admin)")').first.click()
            page.wait_for_timeout(600)
            assert page.locator('main table tbody tr:has-text("M002")').count() == 1, \
                "chip=admin 应命中 M002"
            assert page.locator('main table tbody tr:has-text("M001")').count() == 0, \
                "chip=admin 不应含 M001（role=member）"
            assert "共 1 条" in page.locator("main").inner_text(), "chip=admin 应「共 1 条」"

            kw.fill("张")
            kw.press("Enter")
            page.wait_for_timeout(600)
            assert page.locator("main table tbody tr.data").count() == 0, \
                "组合条件 admin ∩ 姓名含「张」应为空集"
            assert "无符合条件的成员" in page.locator("main table td.empty").first.inner_text(), \
                "组合过滤空集应显示「无符合条件的成员」"

            page.locator('main .fchip:text-is("全部")').first.click()
            page.wait_for_timeout(300)
            kw.fill("")
            kw.press("Enter")
            page.wait_for_timeout(600)
            assert page.locator("main table tbody tr.data").count() == 2, "复位过滤后应回到 2 行"
            assert "共 2 条" in page.locator("main").inner_text(), "复位过滤后应「共 2 条」"

            # §2 VT-LIST-05 平台列排序（member_no 升 → 降 → 默认序三击）
            step("§2 列排序")
            page.wait_for_selector('main table.tbl th[data-sort="member_no"]', timeout=10000)
            th_no = page.locator('main table.tbl th[data-sort="member_no"]').first
            th_no.click()                                       # 升序：M001 首行
            page.wait_for_timeout(700)
            first_row = page.locator("main table tbody tr.data").first.inner_text()
            assert "M001" in first_row, f"member_no 升序首行应为 M001，实际 {first_row!r}"
            th_no.click()                                       # 降序：M002 首行
            page.wait_for_timeout(700)
            first_row = page.locator("main table tbody tr.data").first.inner_text()
            assert "M002" in first_row, f"member_no 降序首行应为 M002，实际 {first_row!r}"
            th_no.click()                                       # 第三击恢复默认序（created_at, member_no）
            page.wait_for_timeout(700)
            first_row = page.locator("main table tbody tr.data").first.inner_text()
            assert "M001" in first_row, f"默认序首行应为 M001，实际 {first_row!r}"
            assert "共 2 条" in page.locator("main").inner_text(), "排序后 total 应保持「共 2 条」"

            # ===================== §3 详情模态全字段 =====================
            # §3 VT-MODAL-01 详情模态（字段全集 + 头带 docno + 原始数据默认收起 + 页脚只读）
            step("§3 详情模态全字段")
            page.locator('main table tbody tr:has-text("M001") .b-link').first.click()
            modal = open_modal(page)
            wait_modal(page)
            # 详情内容（.kv）仅在 !loading && d 时渲染，等它出现确保载入完成
            modal.locator(".modal-bd .kv").first.wait_for(state="visible", timeout=10000)
            assert page.locator("main .modal:visible").count() == 1, \
                "同时只应有 1 个可见模态（另一个 x-show 隐藏）"

            bd_txt = modal.locator(".modal-bd").first.inner_text()
            for label in ["成员编号", "姓名", "邮箱", "角色", "角色代码", "创建时间"]:
                assert label in bd_txt, f"详情模态缺字段标签：{label}"
            for v in ["M001", "张三", "zhangsan@example.com", "成员", "member"]:
                assert v in bd_txt, f"详情模态缺字段值：{v}"
            for sec in ["基本信息", "联系方式", "角色权限", "审计信息"]:
                assert sec in bd_txt, f"详情模态缺语义分段：{sec}"

            docno = modal.locator(".docno").first.inner_text()
            assert "成员详情 · M001" in docno, f"详情头带缺 docno：{docno!r}"
            assert modal.locator(".modal-hd .st").first.inner_text().strip() == "成员", \
                "头带角色徽章应为「成员」"
            assert modal.locator("details.raw").count() == 1, "详情缺「原始数据」折叠块"
            assert modal.locator("details.raw[open]").count() == 0, "「原始数据」应默认收起"

            ft_txt = modal.locator(".modal-ft").first.inner_text()
            assert "创建后只读" in ft_txt and "不开放修改" in ft_txt, \
                f"详情页脚缺只读文案：{ft_txt!r}"
            assert "关闭" in ft_txt, f"详情页脚缺【关闭】：{ft_txt!r}"

            # §3 VT-MODAL-02 审计字段取证：get 载荷无 created_at（与前端详设 §4 不一致，见本文件 §7 同名条目）
            step("§3 审计字段取证")
            payload = rest(page, "get", {"member_no": "M001"})
            assert set(payload.keys()) == {"member_no", "name", "email", "role"}, \
                f"member.get 载荷键集应与契约四字段一致（created_at 未返回）：{sorted(payload)}"
            assert "created_at" not in payload, "get 载荷意外含 created_at —— 需同步前端详设与本用例"
            # 「原始数据」默认收起 ⇒ 其内容不在渲染流里，`inner_text()` 会拿到空串；
            # 取 DOM 文本用 `text_content()`（收起态下仍在 DOM，故可断言其内容）。
            raw_txt = modal.locator("details.raw pre").first.text_content() or ""
            assert '"member_no": "M001"' in raw_txt and "created_at" not in raw_txt, \
                f"「原始数据」JSON 应只有四字段：{raw_txt[:120]!r}"
            # 列表「创建时间」列（第 5 列）与详情「创建时间」值：dash/fmtTime 兜底「—」
            assert m001_row.locator("td").nth(4).inner_text().strip() == "—", \
                "列表「创建时间」列应为 dash 兜底「—」（list 未返回 created_at）"
            assert modal.locator(".kv").last.inner_text().strip().endswith("—"), \
                "详情「创建时间」应为 fmtTime 兜底「—」（get 未返回 created_at）"

            # §4 VT-FORM-04 无编辑入口（BR-11：后端不开放 update/delete/停用）
            step("§4 无编辑入口")
            ft_btns = modal.locator(".modal-ft button").all_inner_texts()
            assert [b.strip() for b in ft_btns] == ["关闭"], \
                f"详情页脚按钮集合应恰为 [关闭]（无编辑入口）：{ft_btns}"
            assert "操作" not in page.locator("main table.tbl").first.inner_text(), \
                "表头不应有「操作」列（BR-11 无行内动作）"
            for act in ["编辑", "保存修改", "删除"]:
                assert page.locator(f'main button:has-text("{act}")').count() == 0, \
                    f"本页不应存在【{act}】按钮（BR-11 创建后只读）"
            close_modal(page, modal)

            # ===================== §4 表单落库回显 =====================
            # §4 VT-FORM-02 前端必填校验（拦在前端，不发请求）
            step("§4 必填校验（不发请求）")
            modal = open_create(page)
            create_reqs = []

            def on_create_req(req):
                if req.method == "POST" and "/call/create" in req.url and "e2e/member" in req.url:
                    create_reqs.append(req.url)

            page.on("request", on_create_req)
            click_button(modal, ["创建"])
            page.wait_for_timeout(400)
            page.remove_listener("request", on_create_req)
            assert not create_reqs, f"必填校验不应发出 create 请求：{create_reqs}"
            page.wait_for_selector('.toast:has-text("必填字段缺失")', timeout=5000)
            assert page.locator('.toast.warn:has-text("必填字段缺失")').count() == 1, \
                "必填校验应为 warn 级 toast"
            assert modal.is_visible(), "必填校验后模态应保持打开"
            close_modal(page, modal)

            # §4 VT-FORM-01 创建（M003 落库并回显）
            step("§4 创建表单落库回显")
            modal = open_create(page)
            fill_create(modal, "M003", "王五", "wangwu@example.com", "admin")
            click_button(modal, ["创建"])
            page.wait_for_selector('.toast:has-text("成员 M003 创建成功")', timeout=5000)
            assert page.locator('.toast.err').count() == 0, "创建成功不应出现 err 级 toast"
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(500)

            page.wait_for_selector('main table tbody tr:has-text("M003")', timeout=10000)
            page.wait_for_timeout(400)
            m003_row = page.locator('main table tbody tr:has-text("M003")').first
            m003_txt = m003_row.inner_text()
            for v in ["M003", "王五", "wangwu@example.com", "管理员"]:
                assert v in m003_txt, f"M003 行缺值：{v}（实际 {m003_txt!r}）"
            assert "共 3 条" in page.locator("main").inner_text(), "创建后应「共 3 条」"

            # 重开 M003 详情四字段回显
            page.locator('main table tbody tr:has-text("M003") .b-link').first.click()
            modal = open_modal(page)
            wait_modal(page)
            modal.locator(".modal-bd .kv").first.wait_for(state="visible", timeout=10000)
            m003_bd = modal.locator(".modal-bd").first.inner_text()
            for v in ["M003", "王五", "wangwu@example.com", "管理员"]:
                assert v in m003_bd, f"M003 详情回显缺：{v}"
            close_modal(page, modal)

            # §4 VT-FORM-03 后端业务校验负向路径（HTTP 仍 200）
            step("§4 后端负向：重复编号 / 非法邮箱")
            modal = open_create(page)
            fill_create(modal, "M001", "重复", "dup@example.com", "member")
            click_button(modal, ["创建"])
            page.wait_for_selector('.toast:has-text("成员编号已存在")', timeout=5000)
            assert modal.is_visible(), "重复编号后模态应保持打开便于修改"
            assert modal.locator('.modal-ft button:has-text("创建")').first.is_visible(), \
                "失败后按钮文案应回到「创建」（非「创建中…」）"

            fill_create(modal, "M004", "格式错", "bad-email", "member")
            click_button(modal, ["创建"])
            page.wait_for_selector('.toast:has-text("邮箱格式非法")', timeout=5000)
            assert modal.is_visible(), "非法邮箱后模态应保持打开便于修改"
            # 业务错由平台包成 HTTP 200 + status:error，故这两条负向路径**不产生** HTTP≥400
            assert page.locator('main table tbody tr:has-text("M004")').count() == 0, \
                "两次失败均不应落库（列表无 M004）"
            assert "共 3 条" in page.locator("main").inner_text(), "失败不应改变列表总数"
            close_modal(page, modal)

            # ===================== §6 0 报错 =====================
            # §6 VT-ERR-01 会话 0 报错 + 豁免受检
            step("§6 0 报错红线")
            assert not errors, f"member 会话前端报错：{errors[:5]}"
            # **豁免也要受检**：`ignored` 收集了却从不校验，等于给「静默吞掉」开了口子 ——
            # 任何新形态的 4xx/console error 都能混进来而不被任何人发现。
            # 本脚本无受限用户会话（归组级补充），故**只认 favicon / sourcemap** 两种豁免理由。
            for _item in ignored:
                _ok = ("/favicon.ico" in _item or ".map" in _item)
                assert _ok, f"豁免理由不成立（既不是 favicon/.map）：{_item!r}"
            if ignored:
                print(f"  · 本次豁免 {len(ignored)} 条：{ignored[:3]}")
            print("VERIFY_VIEW_e2e_member: PASS")

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
