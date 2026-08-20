"""e2e 前端验收（对照各应用前端详设；playwright，可直接运行）。
断言：逐路由渲染（非看板页 .kpi==0 防粘滞）→ 造数后列表有数据 → 模态全字段 → 表单落库
→ 受限用户菜单收敛/直访回落 → 全程 0 console error / 0 pageerror / 0 HTTP≥400。
运行：python design-plus/前端验收样板/verify_view_e2e.py
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

from fde_platform.dbguard import isolate_dbs  # noqa: E402

_iso = isolate_dbs()
_iso.__enter__()
atexit.register(_iso.__exit__, None, None, None)

# 受限用户（菜单收敛/直访回落测试用）：必须在平台子进程启动前经 users 模块建好，
# 切勿在浏览器里调 HTTP API 建用户（平台无此端点）。照 verify_view_crm.py 的写法。
from fde_platform import users  # noqa: E402
users.init_schema()
users.seed_admin()
_ok, _msg = users.create_role("limited_role", "受限测试角色")
assert _ok, _msg
_ok, _msg = users.set_role_page_grants("limited_role", ["e2e:dashboard", "e2e:member", "_platform:agent"])
assert _ok, _msg
_ok, _msg = users.create_user("limited_e2e", "Limited@123", "limited_role", [], "U400", "D001")
assert _ok, _msg
LIMITED_USER, LIMITED_PWD = "limited_e2e", "Limited@123"

# 预标记「已改密」跳过首次强制改密（否则 password_changed=0 挡登录与 /api 调用，
# 见 fde_platform/auth.py 闸门），与 psc 验收脚本同模式
_auth_db = pathlib.Path(__file__).resolve().parent
while not (_auth_db / "fde_platform").is_dir():
    _auth_db = _auth_db.parent
_auth_db = _auth_db / "config" / "auth.db"
if _auth_db.exists():
    _conn = sqlite3.connect(str(_auth_db))
    _conn.execute("UPDATE users SET password_changed = 1 WHERE username IN ('admin', 'limited_e2e')")
    _conn.commit()
    _conn.close()


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


SEED_JS = r"""async () => {
  const call = async (app, svc, params) => {
    if (!app.includes("/")) app = "e2e/" + app;   // 组限定路径（应用在 app/e2e/ 下）
    const r = await fetch(`/api/apps/${app}/call/${svc}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(params || {})
    });
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) {}
    if (!r.ok) throw new Error(`${app}.${svc} HTTP ${r.status} ${text.slice(0, 160)}`);
    if (data && (data.ok === false || data.error)) {
      throw new Error(`${app}.${svc} biz ${JSON.stringify(data).slice(0, 160)}`);
    }
    return data;
  };

  const unwrap = (x) => {
    if (!x) return x;
    if (x.data !== undefined) return x.data;
    if (x.result !== undefined) return x.result;
    return x;
  };

  const taskNo = (x) => {
    x = unwrap(x);
    return (x && (x.task_no || x.no || x.id)) || null;
  };

  await call("member", "create", {
    member_no: "M001",
    name: "张三",
    email: "zhangsan@example.com",
    role: "member"
  });
  await call("member", "create", {
    member_no: "M002",
    name: "李四",
    email: "li@e2e.dev",
    role: "admin"
  });

  const t1 = await call("task", "create", {
    title: "E2E seed pending low M001",
    description: "seed pending",
    assignee_member_no: "M001",
    priority: "low"
  });
  const t2 = await call("task", "create", {
    title: "E2E seed running low M001",
    description: "seed running",
    assignee_member_no: "M001",
    priority: "low"
  });
  const t3 = await call("task", "create", {
    title: "E2E seed done high M002",
    description: "seed done",
    assignee_member_no: "M002",
    priority: "high"
  });

  const n1 = taskNo(t1);
  const n2 = taskNo(t2);
  const n3 = taskNo(t3);

  if (n2) await call("task", "start", {task_no: n2});
  if (n3) {
    await call("task", "start", {task_no: n3});
    await call("task", "complete", {task_no: n3});
  }

  return {
    seeded: true,
    members: ["M001", "M002"],
    tasks: {pending: n1, running: n2, done: n3}
  };
}"""


PROVISION_JS = r"""async () => {
  const call = async (app, svc, params) => {
    const paths = [
      `/api/apps/${app}/call/${svc}`,
      `/api/apps/platform/call/${app}.${svc}`,
      `/api/apps/platform/call/${svc}`,
      `/api/platform/call/${app}.${svc}`,
      `/api/platform/call/${svc}`
    ];
    let last = "";
    for (const path of paths) {
      const r = await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(params || {})
      });
      const text = await r.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch (e) {}
      if (r.ok) {
        if (data && (data.ok === false || data.error)) {
          last = `${path} biz ${JSON.stringify(data).slice(0, 160)}`;
          continue;
        }
        return data;
      }
      last = `${path} HTTP ${r.status} ${text.slice(0, 120)}`;
    }
    throw new Error(last || "call failed");
  };

  const username = "limited_e2e";
  const password = "Limited@123";
  let userOk = false;
  let grantOk = false;
  let last = "";

  try {
    const userAttempts = [
      ["user", "create", {username, password}],
      ["user", "create", {username, password, display_name: "受限用户"}],
      ["user", "create", {username, password, name: "受限用户"}],
      ["user", "create", {username, password, role: "user"}],
      ["account", "create", {username, password}],
      ["auth", "create_user", {username, password}]
    ];
    for (const [app, svc, params] of userAttempts) {
      try {
        await call(app, svc, params);
        userOk = true;
        break;
      } catch (e) {
        last = String(e);
      }
    }

    if (!userOk) {
      const passAttempts = [
        ["user", "set_password", {username, password}],
        ["user", "reset_password", {username, password}],
        ["auth", "set_password", {username, password}]
      ];
      for (const [app, svc, params] of passAttempts) {
        try {
          await call(app, svc, params);
          userOk = true;
          break;
        } catch (e) {
          last = String(e);
        }
      }
    }

    const page_id = "e2e:member";
    const grantAttempts = [
      ["user", "grant_page", {username, page_id}],
      ["user", "grant_page", {username, page: page_id}],
      ["user", "grant", {username, page_id}],
      ["user", "set_pages", {username, page_ids: [page_id]}],
      ["user", "grant_pages", {username, page_ids: [page_id]}],
      ["grant", "create", {username, page_id}],
      ["grant", "create", {user: username, page_id}],
      ["grant", "create", {username, page: page_id}],
      ["grant", "page", {username, page_id}],
      ["grant", "page", {user: username, page: page_id}],
      ["grant", "set", {username, page_ids: [page_id]}],
      ["acl", "grant", {username, page_id}],
      ["role", "grant_page", {username, page_id}]
    ];

    for (const [app, svc, params] of grantAttempts) {
      try {
        await call(app, svc, params);
        grantOk = true;
        break;
      } catch (e) {
        last = String(e);
        if (/exist|duplicate|already/i.test(last)) {
          grantOk = true;
          break;
        }
      }
    }
  } catch (e) {
    last = "FATAL " + String(e);
  }

  return {username, password, userOk, grantOk, last};
}"""


def fill_labeled(scope, label, value, tags=("input", "textarea")):
    for tag in tags:
        loc = scope.locator(
            f'xpath=.//label[contains(normalize-space(.), "{label}")]/following::{tag}[1]'
        )
        if loc.count():
            loc.first.fill(value)
            return

    for tag in tags:
        loc = scope.locator(
            f'xpath=.//*[contains(normalize-space(.), "{label}")]/ancestor::*'
            f'[contains(@class,"field") or contains(@class,"frow") or contains(@class,"form-row") '
            f'or contains(@class,"fv") or contains(@class,"filter") or contains(@class,"grid")][1]//{tag}'
        )
        if loc.count():
            loc.first.fill(value)
            return

    loc = scope.locator(f'input[placeholder*="{label}"], textarea[placeholder*="{label}"]')
    if loc.count():
        loc.first.fill(value)
        return

    raise AssertionError(f"未找到输入字段：{label}")


def choose_option(scope, label, value=None, text=None):
    # 稳健策略：label 后的 select 优先；否则遍历模态内全部 select，选「含目标选项」的那个，
    # 规避「label 后第一个 select」在复杂表单里命中相邻下拉的脆弱性。
    cands = []
    lb = scope.locator(f'xpath=.//label[contains(normalize-space(.), "{label}")]/following::select[1]')
    if lb.count():
        cands.append(lb.first)
    cands += [scope.locator("select").nth(i) for i in range(scope.locator("select").count())]

    if not cands:
        raise AssertionError(f"未找到下拉：{label}")

    for sel in cands:
        try:
            opts = sel.evaluate("(el) => Array.from(el.options||[]).map(o=>o.value)")
        except Exception:
            continue
        has_val = value in opts
        if value and has_val:
            try:
                sel.select_option(value=value); return
            except Exception:
                pass
        if text:
            try:
                sel.select_option(label=text); return
            except Exception:
                pass
        if has_val:
            ok = sel.evaluate(
                """(el, opt) => {
                  const hit = Array.from(el.options||[]).find(o => o.value === opt.value);
                  if (!hit) return false;
                  el.value = hit.value;
                  el.dispatchEvent(new Event('change', {bubbles: true}));
                  el.dispatchEvent(new Event('input', {bubbles: true}));
                  return true;
                }""", {"value": value})
            if ok:
                return

    dbg = [s.evaluate("(el)=>Array.from(el.options||[]).map(o=>o.value)") for s in cands[:4]]
    raise AssertionError(f"下拉选择失败：{label} value={value} text={text} 各下拉选项={dbg}")


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
    # 页面可能同时挂多个 .modal（详情 + 创建），.last 会取到隐藏的那个；
    # 改为等「可见」的模态，再取可见者中的 last。
    page.locator(".modal:visible, [role='dialog']:visible").first.wait_for(state="visible", timeout=10000)
    return page.locator(".modal:visible, [role='dialog']:visible").last


def wait_modal(page, timeout=10000):
    """轮询可见模态的 .loadbox 消失（详情经异步 get 回填，须等加载完再读内容）。"""
    end = time.time() + timeout
    while time.time() < end:
        if page.locator(".modal-mask:visible .loadbox").count() == 0:
            return True
        page.wait_for_timeout(200)
    return True


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


def main():
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        env={**os.environ, "PLATFORM_PORT": str(port), "PORT": str(port)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    state = {"limited": False, "suppress": False}
    errors = []
    ignored = []

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
                if state["suppress"]:
                    ignored.append(f"HTTP {resp.status} {url}")
                    return
                if state["limited"] and resp.status == 403:
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

            seed = page.evaluate(SEED_JS)
            assert seed and seed.get("seeded"), f"造数失败：{seed}"

            # 逐路由渲染：member / task；非看板页必须无 .kpi
            for key in ["member", "task"]:
                page.evaluate(f"location.hash = '#/{key}'")
                try:
                    page.wait_for_selector("main .card, main .tbl, main table", timeout=10000)
                except Exception:
                    pass
                page.wait_for_timeout(700)

                assert page.locator("main").inner_text().strip(), f"页面 {key} 无内容"
                assert page.locator("main .card, main .tbl, main table").count() > 0, f"页面 {key} 未渲染"
                assert page.locator(".kpi").count() == 0, f"页面 {key} 挂载未重建（残留看板）"

            # ===================== member =====================
            page.evaluate("location.hash = '#/member'")
            page.wait_for_selector('table tbody tr:has-text("M001")', timeout=15000)
            page.wait_for_timeout(500)

            assert page.locator("table tbody tr").count() >= 2, "member 造数后列表无数据"

            # 创建表单：UI 新建 M003
            click_button(page, ["+ 新建成员", "新建成员", "创建成员", "新建"])
            modal = open_modal(page)

            fill_labeled(modal, "成员编号", "M003")
            fill_labeled(modal, "姓名", "王五")

            email_input = modal.locator('input[type="email"]')
            if email_input.count():
                email_input.first.fill("wangwu@example.com")
            else:
                fill_labeled(modal, "邮箱", "wangwu@example.com")

            role_sel = modal.locator("select").first
            if role_sel.count():
                vals = role_sel.evaluate("el => Array.from(el.options).map(o => o.value)")
                assert "admin" in vals and "member" in vals, f"member 角色选项不完整：{vals}"
                try:
                    role_sel.select_option(value="member")
                except Exception:
                    role_sel.select_option(label="成员")

            click_button(modal, ["创建", "保存", "提交"])
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            # 搜索回显恰好 1 条
            kw = page.locator('input[placeholder*="编号"], input[placeholder*="姓名"], input[placeholder*="邮箱"]')
            if kw.count():
                kw.first.fill("M003")
                kw.first.press("Enter")
            else:
                fill_labeled(page, "关键字", "M003")

            try:
                click_button(page, ["查询", "搜索"])
            except Exception:
                pass

            page.wait_for_selector('table tbody tr:has-text("M003")', timeout=10000)
            page.wait_for_timeout(500)

            rows = page.locator('table tbody tr:has-text("M003")')  # 只数含 M003 的数据行（排除表头行/空态行）
            assert rows.count() == 1, f"member 搜索 M003 应恰好 1 条，实际 {rows.count()}"
            assert "M003" in rows.first.inner_text(), "member 搜索结果未回显 M003"

            # 详情模态全字段
            page.locator('.b-link:has-text("M003"), a:has-text("M003")').first.click()
            modal = open_modal(page)
            txt = modal.inner_text()
            for expected in ["M003", "王五", "wangwu@example.com", "成员", "创建时间"]:
                assert expected in txt, f"member 详情模态缺字段：{expected}"
            close_modal(page, modal)

            # ===================== task =====================
            page.evaluate("location.hash = '#/task'")
            page.wait_for_selector('table tbody tr:has-text("E2E seed pending low M001")', timeout=15000)
            page.wait_for_timeout(600)

            assert page.locator("table tbody tr").count() >= 3, "task 造数后列表无数据"

            # 详情模态全字段：待办任务
            row = page.locator('table tbody tr:has-text("E2E seed pending low M001")').first
            task_no = row.locator(".b-link").first.inner_text().strip()
            assert task_no, "task 列表未渲染 task_no 链接"

            row.locator(".b-link").first.click()
            modal = open_modal(page)
            wait_modal(page)
            try:
                modal.locator(".kv, .modal-bd .v").first.wait_for(state="visible", timeout=8000)
            except Exception:
                pass
            txt = modal.inner_text()

            for expected in [
                task_no,
                "E2E seed pending low M001",
                "待办",
                "seed pending",
                "优先级",
                "创建时间",
                "更新时间",
            ]:
                assert expected in txt, f"task 详情模态缺字段：{expected}"
            assert ("M001" in txt) or ("张三" in txt), "task 详情模态缺负责人回显"
            close_modal(page, modal)

            # 已完成任务模态：终态无状态机按钮
            row_done = page.locator('table tbody tr:has-text("E2E seed done high M002")').first
            row_done.locator(".b-link").first.click()
            modal = open_modal(page)
            wait_modal(page)
            try:
                modal.locator(".kv, .modal-bd .v").first.wait_for(state="visible", timeout=8000)
            except Exception:
                pass
            txt = modal.inner_text()
            assert "已完成" in txt, "task 已完成详情未渲染状态"

            btn_texts = modal.locator("button:visible").all_inner_texts()  # 只看可见按钮（终态隐藏的状态按钮 x-show=false 不算）
            for forbidden in ["启动", "完成", "退回"]:
                assert not any(forbidden in t for t in btn_texts), f"已完成任务不应出现 {forbidden} 按钮"
            close_modal(page, modal)

            # 创建表单：UI 新建任务并过滤回显恰好 1 条
            click_button(page, ["+ 新建任务", "新建任务", "创建任务", "新建"])
            modal = open_modal(page)

            fill_labeled(modal, "标题", "E2E ui created high M002")
            choose_option(modal, "负责人", value="M002", text="李四")
            choose_option(modal, "优先级", value="high", text="high")

            more = modal.locator(
                'button:has-text("更多字段"), summary:has-text("更多字段"), .more:has-text("更多字段")'
            )
            if more.count():
                more.first.click()
                page.wait_for_timeout(250)

            fill_labeled(modal, "描述", "ui created description", tags=("textarea",))

            click_button(modal, ["创建", "保存", "提交"])
            try:
                modal.wait_for(state="hidden", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(700)

            # 过滤：status=待办 + priority=high + assignee=M002，回显恰好 1 条
            status_chip = page.locator(
                '.chip:has-text("待办"), button:has-text("待办"), a:has-text("待办"), label:has-text("待办")'
            ).first
            if status_chip.count():
                status_chip.click()
                page.wait_for_timeout(300)

            choose_option(page, "优先级", value="high", text="high")
            choose_option(page, "负责人", value="M002", text="李四")

            try:
                click_button(page, ["查询", "搜索"])
            except Exception:
                pass

            page.wait_for_selector('table tbody tr:has-text("E2E ui created high M002")', timeout=10000)
            page.wait_for_timeout(500)

            rows = page.locator('table tbody tr:has-text("E2E ui created high M002")')  # 只数含新建任务的行（排除表头行/空态行）
            assert rows.count() == 1, f"task 过滤新建任务应恰好 1 条，实际 {rows.count()}"
            row_txt = rows.first.inner_text()
            assert "E2E ui created high M002" in row_txt, "task 新建任务未回显"
            assert "待办" in row_txt, "task 新建任务初始状态应为待办"

            # ===================== 受限用户（已在模块级经 users 模块建好）=====================
            limited_ctx = browser.new_context()
            limited_page = limited_ctx.new_page()
            attach(limited_page)

            state["limited"] = True

            limited_page.goto(f"{base}/login")
            limited_page.fill('input[name="username"]', LIMITED_USER)
            limited_page.fill('input[name="password"]', LIMITED_PWD)
            limited_page.click('button[type="submit"]')
            limited_page.wait_for_url("**/", timeout=15000)

            limited_page.goto(f"{base}/view/e2e/")
            limited_page.wait_for_selector(".rail, .menu, nav", timeout=15000)
            limited_page.wait_for_timeout(800)

            menu_txt = limited_page.locator(".rail, .menu, nav").first.inner_text()

            # 菜单收敛：授权页 看板 + member 可见，未授权 task 不可见
            assert ("成员管理" in menu_txt) or ("成员" in menu_txt), f"受限菜单未见授权页 member：{menu_txt[:120]}"
            assert "任务管理" not in menu_txt, f"受限菜单泄漏未授权页 task：{menu_txt[:120]}"

            # 直访无授权路由 → 渲染回落首个授权页（看板 order 最低为 menu[0]，对标 crm）。
            # shell 的 syncRoute 渲染回落页但未必回写 location.hash，故断言渲染内容而非 hash。
            limited_page.evaluate("location.hash = '#/task'")
            limited_page.wait_for_timeout(1200)
            header_txt = limited_page.locator("header.top h1").first.inner_text()
            assert "首页看板" in header_txt, f"受限用户直访 task 应回落看板：{header_txt[:120]}"

            assert not errors, f"前端报错：{errors[:5]}"
            print("verify_view_e2e PASS —— 路由/造数/模态/表单/受限用户/0报错")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()