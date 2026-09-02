"""FDE v2 平台 Web 服务（Flask）。

提供浏览器端（CONVENTION 需求 1）：
- `/`            首页：应用组（系统）清单，按 app/ 下的一级目录展示
- `/group/<组>`  组详情：该组下的全部应用（`/group/-` 为未分组桶）
- `/app/<名>`    应用详情：服务清单 + 手工调用表单 + Agent 窗口 + MCP 信息
平台 API：
- `GET  /api/groups`                     应用组清单（组名 + 组内应用）
- `GET  /api/apps`                       应用清单（含所属组与服务数）
- `GET  /api/apps/<名>/services`         某应用的服务清单（含入参契约）
- `POST /api/apps/<名>/call/<服务>`      手工调用服务（body = 参数对象）
- `GET  /api/mcp/tools`                  全部公共服务的 MCP tool 定义
- Agent：`POST /api/apps/<名>/agent/chat` / `.../agent/reset`（应用级）
- 平台级 Agent（跨应用）：`POST /api/agent/chat` / `/api/agent/reset`
- 对话历史（两套前缀同构，`<base>` = `/api/agent` 或 `/api/apps/<名>/agent`）：
  `GET <base>/sessions` 列表 · `POST <base>/sessions` 新建 ·
  `GET <base>/sessions/<sid>/messages` 历史 · `DELETE <base>/sessions/<sid>` 删除
  （持久化于 config/chat_history.db，切页面/重启不丢；按登录用户隔离）

按安全约束，本地 DEMO 只绑回环地址 127.0.0.1（由 main.py 指定 host）。
"""
import json
import os
import time
import traceback
from pathlib import Path

import httpx

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    render_template_string,
    request,
    send_file,
    send_from_directory,
)

from fde import FdeError
from fde_platform import builtin_tools, integration, listsort, scanner, users, view_registry
from fde_platform.logging_config import init_logging
from fde_platform.runtime import FdePlatform

init_logging()

_PKG_DIR = Path(__file__).parent
VERSION = "v2.2.0-beta"
HOST = os.environ.get("PLATFORM_HOST", "127.0.0.1")
PORT = int(os.environ.get("PLATFORM_PORT", 4000))

# ── 平台实例（加载一次并缓存）──────────────────────────────
platform = FdePlatform()
platform.load_all()
users.migrate_grant_app_names(platform)  # 历史授权短名 → 组限定名 qualname（幂等）

app = Flask(__name__, template_folder=str(_PKG_DIR / "templates"))

# 会话签名密钥 —— 优先 env SECRET_KEY；否则从文件恢复；再否自动生成并持久化（防开源回退值泄露）
_SECRET_PATH = _PKG_DIR.parent / "config" / ".secret_key"
_secret = os.environ.get("SECRET_KEY", "").strip()
if _secret:
    app.secret_key = _secret
elif _SECRET_PATH.is_file():
    app.secret_key = _SECRET_PATH.read_text(encoding="utf-8").strip()
else:
    import secrets
    app.secret_key = secrets.token_hex(32)
    _SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SECRET_PATH.write_text(app.secret_key, encoding="utf-8")

# Agent 会话缓存 {键: AgentSession}（延迟创建；"__platform__" 为平台级跨应用 Agent）
_agent_sessions: dict = {}

# 未分组应用在 URL 里的占位键（直接放在 app/ 下、不属于任何组目录的应用）
UNGROUPED_KEY = "-"
UNGROUPED_LABEL = "未分组"


def _get_agent(app_name):
    key = app_name or "__platform__"
    if key not in _agent_sessions:
        _agent_sessions[key] = _build_agent(app_name)
    return _agent_sessions[key]


def _build_agent(app_name):
    """Agent 后端（Phase 3 起唯一：AgentScope 编排）。

    AgentScope import 失败时，``AgentScopeSession.chat`` 自带降级提示（不抛错、不阻断），
    故这里直接返回；不再保留旧 ReAct 后端。
    """
    from fde_platform.agent_agentscope import AgentScopeSession

    return AgentScopeSession(platform, app_name)


def _coerce(params: dict, schema: list[dict]) -> dict:
    """按服务入参契约把表单字符串值转为声明类型（int/float/bool…）。

    未知的键忽略；可选参数留空则省略（用默认值）。
    """
    pmap = {p["name"]: p for p in schema}
    out = {}
    for key, value in params.items():
        p = pmap.get(key)
        if p is None:
            continue
        if value is None or value == "":
            if not p["required"]:
                continue  # 省略 → 走默认值
            value = ""
        jt = p["json_type"]
        try:
            if jt == "integer":
                value = int(value)
            elif jt == "number":
                value = float(value)
            elif jt == "boolean":
                if isinstance(value, str):
                    value = value.strip().lower() in ("1", "true", "yes", "on")
                else:
                    value = bool(value)
            elif jt == "string":
                # JSON body 原生 dict/list 透传不 str()——无类型注解参数归一 string，
                # 强转 str() 会腐蚀 list/dict 报文（如 product.sync payload）；表单字符串客户端仍走转换
                if not isinstance(value, (dict, list)):
                    value = str(value)
            # array / object：按 JSON 原样透传
        except (ValueError, TypeError):
            pass  # 转不动就原样传，交给服务自身校验报错
        out[key] = value
    return out


def build_app_summary() -> list[dict]:
    """应用清单（名称、所属组、聚合根类、可见服务数与服务名）。

    按当前会话用户的**服务级授权**自过滤：admin / 未登录见全部；
    普通用户只见有授权的应用，且每个应用只列被授权的服务。
    """
    summaries = []
    for name in users.visible_app_names(platform.app_names()):
        handle = platform.handle(name)
        all_svcs = platform.services(name)
        visible = set(users.visible_service_names(name, [s["name"] for s in all_svcs]))
        svc_names = [s["name"] for s in all_svcs if s["name"] in visible]
        summaries.append(
            {
                "name": name,
                "group": handle.group,
                "class": handle.cls.__name__,
                "service_count": len(svc_names),
                "services": svc_names,
            }
        )
    return summaries


def build_group_summary() -> list[dict]:
    """应用组清单（按 app/ 一级目录；组不是新实体，纯目录呈现）。

    每组含当前用户可见的应用名列表；无任何可见应用的组不呈现。
    未分组应用（直接放 app/ 下）汇入 key="-" 的「未分组」桶，列在最后。
    """
    visible = set(users.visible_app_names(platform.app_names()))
    cards = []
    for g in platform.groups():
        apps = [n for n in platform.apps_in_group(g) if n in visible]
        if apps:
            cards.append({"key": g, "name": g, "apps": apps,
                          "app_count": len(apps), "ungrouped": False})
    ungrouped = [n for n in platform.apps_in_group(None) if n in visible]
    if ungrouped:
        cards.append({"key": UNGROUPED_KEY, "name": UNGROUPED_LABEL, "apps": ungrouped,
                      "app_count": len(ungrouped), "ungrouped": True})
    return cards


def _render_markdown(text: str) -> str:
    """把 README 渲染为 HTML；未安装 markdown 库时返回空串（模板退回等宽 <pre>）。"""
    if not text or not text.strip():
        return ""
    try:
        import markdown as _md

        return _md.markdown(text, extensions=["tables", "fenced_code"])
    except ImportError:
        return ""


# ══════════════════════════════════════════════════════════
# 前端页面
# ══════════════════════════════════════════════════════════


_SCAN_CACHE = {"t": 0.0, "v": None}


def _get_scan(refresh=False):
    """跨应用调用扫描结果缓存（首页 KPI/扫描明细常驻需要；60s TTL，/api/scan 强制刷新）。"""
    now = time.monotonic()
    if refresh or _SCAN_CACHE["v"] is None or now - _SCAN_CACHE["t"] > 60:
        _SCAN_CACHE["v"] = scanner.scan_report(platform)
        _SCAN_CACHE["t"] = now
    return _SCAN_CACHE["v"]


def _app_display_names() -> dict:
    """{应用短名: 显示名}——取自视图注册表菜单名，供首页可达清单芯片显示。"""
    reg = view_registry.registry()
    return {p["key"]: p["name"] for m in reg["modules"] for p in m["pages"]}


@app.route("/")
def index():
    groups = build_group_summary()
    scan = _get_scan()
    return render_template(
        "index.html",
        groups=groups,
        total_apps=sum(g["app_count"] for g in groups),
        port=PORT,
        scan=scan,
        app_names=_app_display_names(),
    )


@app.route("/group/<group_key>")
def group_detail(group_key):
    """组详情页：列出该组下当前用户可见的全部应用。"""
    if group_key == UNGROUPED_KEY:
        group, label = None, UNGROUPED_LABEL
    else:
        if group_key not in platform.groups():
            return render_template("error.html", message=f"应用组不存在：{group_key}"), 404
        group, label = group_key, group_key
    visible = set(users.visible_app_names(platform.apps_in_group(group)))
    return render_template(
        "group.html",
        group_key=group_key,
        group_name=label,
        apps=build_app_summary_for(sorted(visible)),
    )


def build_app_summary_for(names: list[str]) -> list[dict]:
    """build_app_summary 的指定子集版（组详情页用，复用同一可见性过滤逻辑）。"""
    return [s for s in build_app_summary() if s["name"] in set(names)]


@app.route("/app/<path:app_name>")
def app_detail(app_name):
    if app_name not in platform.app_names():
        return render_template("error.html", message=f"应用不存在：{app_name}"), 404
    handle = platform.handle(app_name)
    all_svcs = platform.services(app_name)
    visible = set(users.visible_service_names(app_name, [s["name"] for s in all_svcs]))
    services = [s for s in all_svcs if s["name"] in visible]
    # MCP 工具：聚合服务按授权过滤；平台内置文件工具只要有应用可见性即保留
    tools = [
        t for t in platform.all_mcp_tools()
        if t["_meta"]["app"] == app_name
        and (builtin_tools.is_builtin_service(t["_meta"]["service"]) or t["_meta"]["service"] in visible)
    ]
    readme = platform.readme(app_name)
    folder = handle.folder
    import_files = builtin_tools.list_files(folder, builtin_tools.IMPORT_DIR)["files"]
    export_files = builtin_tools.list_files(folder, builtin_tools.EXPORT_DIR)["files"]
    return render_template(
        "app_detail.html",
        app_name=app_name,
        group=handle.group,  # 所属组（None=未分组），用于面包屑返回组页
        class_name=handle.cls.__name__,
        services=services,
        tools=tools,
        readme=readme,
        readme_html=_render_markdown(readme),
        import_files=import_files,
        export_files=export_files,
        mcp_command="python -m fde_platform.mcp_server --user <用户名>",
    )


# ══════════════════════════════════════════════════════════
# 前端视图（view/ 通用同源静态托管）
#   模块 = view/ 下含 index.html 的目录（如 view/crm/），由 design-plus/
#   VIEW_CONVENTION.md（技能 fde-view-gen）按统一范式生成；view/lib/ 为跨模块公共基座
#   （api.js / shell.js / 设计系统），view/pages/ 为平台公共页（Agent / 服务台），
#   二者无 index.html、不进模块清单，但同样按需静态放行。
#   同源 → 无需 CORS、会话 Cookie 天然携带；/view/ 不在鉴权白名单，
#   未登录访问页面自动重定向 /login（fetch 则收 401 由前端自处理）。
# ══════════════════════════════════════════════════════════

_VIEW_DIR = Path(__file__).resolve().parents[1] / "view"
_APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _view_modules() -> list:
    """有视图页面的组（组 = app/ 一级目录；页面来自 app/<组>/<应用>/view.js 与
    view/<组>/<页>.js，由 view_registry 扫描合并）。"""
    return view_registry.viewable_groups()


@app.route("/view/")
def view_index():
    """视图模块清单页。"""
    return render_template_string(
        """{% extends "base.html" %}
{% block title %}前端视图 · FDE 平台{% endblock %}
{% block content %}
  <div class="section-title">前端视图模块（{{ modules|length }}）</div>
  <div class="group-grid">
  {% for m in modules %}
    <div class="card group-card reveal">
      <h3><a href="/view/{{ m }}/">/view/{{ m }}/</a></h3>
      <div class="muted">应用模块「{{ m }}」工作台</div>
    </div>
  {% else %}
    <div class="card muted">尚无任何视图模块。</div>
  {% endfor %}
  </div>
{% endblock %}""",
        modules=_view_modules(),
    )


@app.route("/view/<module>")
def view_module_root(module):
    return redirect(f"/view/{module}/")


@app.route("/view/<module>/")
@app.route("/view/<module>/<path:filename>")
def view_module(module, filename="index.html"):
    if module.startswith((".", "_")):
        return render_template("error.html", message=f"视图模块不存在：{module}"), 404
    # 组根（请求 index.html）：该组只要有视图页面（app/<组>/<应用>/view.js 或
    # view/<组>/<页>.js）就渲染平台通用壳 view_shell.html——壳经 /api/view_boot 拿清单、
    # 动态 import() 各页工厂装配菜单。组可无 view/<组>/ 目录（纯应用页组），故不查文件系统。
    if filename == "index.html":
        if view_registry.boot_manifest(module) is None:
            return render_template("error.html", message=f"视图模块不存在：{module}"), 404
        return render_template("view_shell.html", module=module)
    # 子文件：静态放行 view/<module>/<filename>（公共层 lib/ · pages/ · 组级页 dashboard.js 等）。
    # 应用页不在这里——它们经 /app/<名>/view.{js,html} 写死端点 serve（见下）。
    target = _VIEW_DIR / module
    if not target.is_dir():
        return render_template("error.html", message=f"视图模块不存在：{module}"), 404
    return send_from_directory(str(target), filename)


def _serve_app_view(app_name, fname, mime):
    """serve 应用前端文件（仅写死文件名 view.js / view.html）。

    安全要点：文件名是常量（非用户可控），目录经 platform.handle 校验应用存在后取得，
    故绝无目录穿越；同目录的 <应用>.py / .db / resource/ 永远不会被本端点 expose。"""
    if app_name not in platform.app_names():
        return render_template("error.html", message=f"应用不存在：{app_name}"), 404
    path = platform.handle(app_name).folder / fname
    if not path.is_file():
        return render_template("error.html", message=f"该应用无前端视图（缺 {fname}）"), 404
    return send_file(str(path), mimetype=mime)


@app.route("/app/<path:app_name>/view.js")
def app_view_js(app_name):
    """应用前端页面（ES Module；MIME 必须为 JS，否则动态 import 被浏览器拒）。"""
    return _serve_app_view(app_name, "view.js", "text/javascript")


@app.route("/app/<path:app_name>/view.html")
def app_view_html(app_name):
    """应用前端模板片段（页面经 import.meta.url 相对自身抓取）。"""
    return _serve_app_view(app_name, "view.html", "text/html")


def _serve_group_view(group, page, ext, mime):
    """serve 组级聚合页前端文件（app/<组>/<页>.{js,html}，松散文件，无对应后端应用）。

    安全要点：group/page 均为单段路径（路由转换器不含 /），文件名 = f"{page}.{ext}"
    常量拼接，故绝无目录穿越；同组应用子目录里的 .py/.db 不会被本端点触及。"""
    if group.startswith((".", "_")) or page.startswith((".", "_")):
        return render_template("error.html", message="页面不存在"), 404
    path = _APP_DIR / group / f"{page}.{ext}"
    if not path.is_file():
        return render_template("error.html", message=f"页面不存在：{group}/{page}.{ext}"), 404
    return send_file(str(path), mimetype=mime)


@app.route("/app/<group>/<page>.js")
def group_view_js(group, page):
    """组级聚合页 JS（ES Module；MIME 必须为 JS，否则动态 import 被浏览器拒）。"""
    return _serve_group_view(group, page, "js", "text/javascript")


@app.route("/app/<group>/<page>.html")
def group_view_html(group, page):
    """组级聚合页模板片段。"""
    return _serve_group_view(group, page, "html", "text/html")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(str(_VIEW_DIR / "lib"), "icon.svg",
                               mimetype="image/svg+xml")


# ══════════════════════════════════════════════════════════
# 平台 API
# ══════════════════════════════════════════════════════════


@app.route("/api/me")
def api_me():
    """当前登录用户（前端渲染用户条 / 判定管理员入口用）。"""
    u = users.session_user()
    if not u:
        return jsonify({"status": "error", "message": "未登录"}), 401
    return jsonify({"status": "ok", "data": {
        "username": u["username"], "role": u["role"],
        "role_label": u["role_label"], "is_admin": bool(u["is_admin"]),
        "user_no": u["user_no"], "department_no": u["department_no"],
    }})


@app.route("/api/view_registry")
def api_view_registry():
    """前端页面注册表（管理页授权 UI 的选项来源）：扫描 view/ 动态生成，
    含每页派生服务集。仅管理员。"""
    u = users.session_user()
    if not u:
        return jsonify({"status": "error", "message": "未登录"}), 401
    if not u["is_admin"]:
        return jsonify({"status": "error", "message": "视图注册表仅限管理员"}), 403
    return jsonify({"status": "ok", "data": view_registry.registry()})


@app.route("/api/view_registry/rescan", methods=["POST"])
def api_view_registry_rescan():
    """手动刷新页面注册表缓存（管理页「重新扫描」按钮）。仅管理员。"""
    u = users.session_user()
    if not u:
        return jsonify({"status": "error", "message": "未登录"}), 401
    if not u["is_admin"]:
        return jsonify({"status": "error", "message": "视图注册表仅限管理员"}), 403
    view_registry.invalidate()
    return jsonify({"status": "ok", "data": view_registry.registry()})


@app.route("/api/my_pages")
def api_my_pages():
    """当前用户的前端页面授权集（shell 菜单渲染源）。
    admin → is_admin=true（shell 全通，含仅 admin 可见的服务台）；否则为角色页面授权。"""
    u = users.session_user()
    if not u:
        return jsonify({"status": "error", "message": "未登录"}), 401
    if u["is_admin"]:
        return jsonify({"status": "ok", "data": {"is_admin": True, "pages": []}})
    return jsonify({"status": "ok", "data": {
        "is_admin": False, "pages": users.get_user_page_grants(u["id"])}})


@app.route("/api/prefs/<path:key>", methods=["GET"])
def api_pref_get(key):
    """读当前登录用户的偏好（JSON），如列表自定义显示列。不存在返回 null。"""
    u = users.session_user()
    if not u:
        return jsonify({"status": "error", "message": "未登录"}), 401
    return jsonify({"status": "ok", "data": users.get_pref(u["id"], key)})


@app.route("/api/prefs/<path:key>", methods=["POST", "PUT"])
def api_pref_set(key):
    """写当前登录用户的偏好（body.value 任意 JSON）。per-user 持久化，跟账号走。"""
    u = users.session_user()
    if not u:
        return jsonify({"status": "error", "message": "未登录"}), 401
    body = request.get_json(silent=True) or {}
    users.set_pref(u["id"], key, body.get("value"))
    return jsonify({"status": "ok"})


@app.route("/api/view_boot")
def api_view_boot():
    """某业务模块的壳启动清单（通用壳 bootShell 的装配源）：
    {brand(约定推导), pages(按 PAGE_META.order 升序，含动态 import 的 url)}。
    任意登录用户可取（菜单的授权过滤在 shell 端按 /api/my_pages 另行收口）。"""
    module = request.args.get("module", "")
    man = view_registry.boot_manifest(module)
    if man is None:
        return jsonify({"status": "error", "message": f"未知视图模块：{module}"}), 404
    return jsonify({"status": "ok", "data": man})


@app.route("/api/groups")
def api_groups():
    """应用组清单（组名 + 组内可见应用；未分组桶 key 为 "-"）。"""
    return jsonify({"status": "ok", "data": build_group_summary()})


@app.route("/api/apps")
def api_apps():
    return jsonify({"status": "ok", "data": build_app_summary()})


@app.route("/api/apps/<path:app_name>/services")
def api_services(app_name):
    if app_name not in platform.app_names():
        return jsonify({"status": "error", "message": f"应用不存在：{app_name}"}), 404
    all_svcs = platform.services(app_name)
    visible = set(users.visible_service_names(app_name, [s["name"] for s in all_svcs]))
    return jsonify({"status": "ok", "data": [s for s in all_svcs if s["name"] in visible]})


@app.route("/api/apps/<path:app_name>/call/<service>", methods=["POST"])
def api_call(app_name, service):
    """手工调用服务。请求体即参数对象（JSON）。"""
    if app_name not in platform.app_names():
        return jsonify({"status": "error", "message": f"应用不存在：{app_name}"}), 404

    svc = next((s for s in platform.services(app_name) if s["name"] == service), None)
    if svc is None:
        return jsonify({"status": "error", "message": f"应用 {app_name} 无此服务：{service}"}), 404

    raw = request.get_json(silent=True) or {}
    raw.pop("context", None)  # 丢弃客户端伪造的身份（§4.1 防伪造）

    # 平台级 list 排序（fde_platform/listsort.py）：sort_by/sort_dir 为平台保留参数，
    # 先行弹出、不透传应用；拦截后剥分页取全量 → 平台排序 → 按请求分页切片。
    list_sort = None
    if service == "list" and listsort.wants_sort(raw):
        sort_by, sort_dir = listsort.pop_sort(raw)
        req_page, req_size = listsort.pop_paging(raw)
        list_sort = (sort_by, sort_dir, req_page, req_size)

    params = _coerce(raw, svc["parameters"])

    try:
        # 身份来自登录态（无会话则 None → 平台默认身份）；客户端无法伪造（§4.1）
        result = platform.call(app_name, service, ctx=users.current_caller_ctx(), **params)
        if list_sort is not None:
            result = listsort.apply(result, *list_sort)
        return jsonify({"status": "ok", "data": result})
    except FdeError as e:
        return jsonify({"status": "error", "kind": "business", "message": str(e)})
    except TypeError as e:
        return jsonify(
            {"status": "error", "kind": "params", "message": f"参数错误：{e}"}
        )
    except Exception as e:
        traceback.print_exc()  # 系统异常：记全量日志，对调用方归一（§7）
        return jsonify(
            {"status": "error", "kind": "system", "message": f"系统错误：{type(e).__name__}"}
        )


@app.route("/api/mcp/tools")
def api_mcp_tools():
    """全部公共服务的 MCP tool 定义（对外 schema 去掉内部 _meta）。"""
    tools = []
    for t in platform.all_mcp_tools():
        tools.append({k: v for k, v in t.items() if k != "_meta"})
    return jsonify({"status": "ok", "data": tools})


@app.route("/api/scan")
def api_scan():
    """静态调用扫描报告（校验 self.fde.call 目标，CONVENTION §10.8）。同步刷新首页缓存。"""
    return jsonify({"status": "ok", "data": _get_scan(refresh=True)})


# ══════════════════════════════════════════════════════════
# 平台 API — 资源文件（import-file 上传区 / export-file 产出区）
# ══════════════════════════════════════════════════════════


@app.route("/api/apps/<path:app_name>/files")
def api_list_files(app_name):
    """列出应用 resource 目录下的文件。Query: directory=import-file(默认)|export-file。"""
    if app_name not in platform.app_names():
        return jsonify({"status": "error", "message": f"应用不存在：{app_name}"}), 404
    try:
        data = builtin_tools.list_files(
            platform.handle(app_name).folder,
            request.args.get("directory", builtin_tools.IMPORT_DIR),
        )
    except FdeError as e:
        return jsonify({"status": "error", "message": str(e)})
    return jsonify({"status": "ok", "data": data})


@app.route("/api/apps/<path:app_name>/files", methods=["POST"])
def api_upload_files(app_name):
    """上传文件到 import-file（人工输入区，仅接受页面上传；支持多文件）。"""
    if app_name not in platform.app_names():
        return jsonify({"status": "error", "message": f"应用不存在：{app_name}"}), 404
    uploads = request.files.getlist("files")
    if not uploads or all(not u.filename for u in uploads):
        return jsonify({"status": "error", "message": "未选择文件"})
    import_dir = platform.handle(app_name).folder / "resource" / builtin_tools.IMPORT_DIR
    import_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for fs in uploads:
        name = builtin_tools.safe_filename(fs.filename)
        if not name:
            return jsonify({"status": "error", "message": f"非法文件名：{fs.filename}"})
        fs.save(str(import_dir / name))
        saved.append(name)
    return jsonify({"status": "ok", "message": f"已上传 {len(saved)} 个文件", "data": saved})


@app.route("/api/apps/<path:app_name>/files/<directory>/<path:filename>")
def api_download_file(app_name, directory, filename):
    """下载 resource 目录下的文件。"""
    if app_name not in platform.app_names():
        return jsonify({"status": "error", "message": f"应用不存在：{app_name}"}), 404
    try:
        target = builtin_tools._resolve(platform.handle(app_name).folder, directory, filename)
    except FdeError as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    return send_file(str(target), as_attachment=True, download_name=target.name)


@app.route("/api/apps/<path:app_name>/files/<directory>/<path:filename>", methods=["DELETE"])
def api_delete_file(app_name, directory, filename):
    """删除 resource 目录下的文件。"""
    if app_name not in platform.app_names():
        return jsonify({"status": "error", "message": f"应用不存在：{app_name}"}), 404
    try:
        target = builtin_tools._resolve(platform.handle(app_name).folder, directory, filename)
    except FdeError as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    try:
        target.unlink()
    except OSError as e:
        return jsonify({"status": "error", "message": f"删除失败：{e}"})
    return jsonify({"status": "ok", "message": f"已删除：{target.name}"})


# ── 多智能体 agent_service 反代 ─────────────────────────
# AgentScope agent_service（独立 FastAPI，:4100）作为多智能体编排层，
# FDE Flask 反代其 REST/SSE 端点并桥接身份（登录态 → X-User-ID）。
# 鉴权由 auth.gate（/api/* 需登录）兜底；agent_service 内部按 X-User-ID 隔离租户。

AGENT2_BASE = os.environ.get("AGENT_SERVICE_URL", "http://127.0.0.1:4100")


@app.route("/api/agent2/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def api_agent2_proxy(path):
    """反代 agent_service 请求；注入 X-User-ID（当前登录用户名）。"""
    u = users.session_user()
    if u is None:
        return jsonify({"status": "error", "message": "未登录"}), 401
    url = f"{AGENT2_BASE}/{path}"
    headers = {"X-User-ID": u["username"]}
    params = request.args.to_dict()
    body = request.get_json(silent=True)
    method = request.method  # 提前提取：gen() 在响应流式阶段执行，request 上下文已结束

    try:
        if path.endswith("/stream"):
            # SSE 流式：原样转发字节流（长连接，不超时）
            def gen():
                with httpx.stream(
                    method, url, headers=headers, params=params,
                    json=body, timeout=None,
                ) as r:
                    for chunk in r.iter_bytes():
                        yield chunk

            return Response(gen(), mimetype="text/event-stream")

        resp = httpx.request(
            method, url, headers=headers, params=params, json=body, timeout=120,
        )
        return Response(
            resp.content, status=resp.status_code,
            content_type=resp.headers.get("content-type", "application/json"),
        )
    except httpx.ConnectError:
        return jsonify({"status": "error",
                        "message": "agent_service 未启动（python -m fde_platform.agent_service）"}), 503


# ── agent_service 适配层（多智能体，模拟现有 /api/agent/* 形状）────────
# 前端 agent_rail 只需把 URL 前缀从 /api/agent 改成 /api/agent2，协议不变。
# 后端封装 agent_service 细节：credential/agent 初始化、chat 触发+SSE 翻译、HITL 缓存。

_AGENT2_CRED = None
_AGENT2_AGENT = None
_AGENT2_MODEL = None
_AGENT2_PENDING = {}  # session_id -> {"reply_id": str, "tool_calls": [ToolCallBlock]}

_LEADER_PROMPT = (
    "你是产销协同的多智能体编排 leader。你持有团队工具（TeamCreate/AgentCreate/TeamSay），"
    "遇到需要多领域协作的复杂任务时必须组建团队：先 TeamCreate 建团队，再用 AgentCreate "
    "按 subagent_type 创建成员（可选：sales/planning/inventory/delivery/integration/scheduler），"
    "用 TeamSay 给成员派活并汇总回报。简单查询可直接调用业务工具回答。"
)


def _agent2_headers():
    u = users.session_user()
    return {"X-User-ID": u["username"] if u else "anon"}


def _ensure_agent2():
    """确保 agent_service 有 credential + leader agent（幂等，缓存全局）。"""
    global _AGENT2_CRED, _AGENT2_AGENT, _AGENT2_MODEL
    if _AGENT2_CRED and _AGENT2_AGENT:
        return True
    u = users.session_user()
    if u is None:
        return False
    from fde_platform import llm
    p = llm.load_profile("operator")
    if not p:
        return False
    headers = _agent2_headers()
    try:
        api_key = llm.decrypt_key(p["api_key_enc"])
        r = httpx.post(f"{AGENT2_BASE}/credential/", json={"data": {
            "type": "deepseek_credential", "api_key": api_key,
            "base_url": p["base_url"],
        }}, headers=headers, timeout=30)
        r.raise_for_status()
        _AGENT2_CRED = r.json()["credential_id"]
        r = httpx.post(f"{AGENT2_BASE}/agent/", json={
            "name": "leader", "system_prompt": _LEADER_PROMPT,
        }, headers=headers, timeout=30)
        r.raise_for_status()
        _AGENT2_AGENT = r.json()["agent_id"]
        _AGENT2_MODEL = p["model"]
        return True
    except Exception:
        _AGENT2_CRED = None
        _AGENT2_AGENT = None
        return False


def _agent2_new_session() -> str | None:
    """新建 agent_service session（带 chat_model_config），返回 session_id。"""
    headers = _agent2_headers()
    try:
        r = httpx.post(f"{AGENT2_BASE}/sessions/", json={
            "agent_id": _AGENT2_AGENT,
            "name": "对话",
            "chat_model_config": {
                "type": "deepseek_credential", "credential_id": _AGENT2_CRED,
                "model": _AGENT2_MODEL or "deepseek-v4-pro",
                "parameters": {},
            },
        }, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()["session_id"]
    except Exception:
        return None


@app.route("/api/agent2/chat/stream", methods=["POST"])
def api_agent2_chat_stream():
    """多智能体对话（SSE）：触发 chat + 订阅 stream，翻译成现有事件格式。"""
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    session_id = data.get("session_id", "")
    if not message:
        return jsonify({"status": "error", "message": "消息不能为空"})
    if not _ensure_agent2():
        def _err():
            yield "data: " + json.dumps(
                {"event": "error", "data": "agent_service 未配置或未启动（python -m fde_platform.agent_service）"},
                ensure_ascii=False) + "\n\n"
        return Response(_err(), mimetype="text/event-stream")

    sid = session_id if session_id else _agent2_new_session()
    if sid is None:
        def _err2():
            yield "data: " + json.dumps({"event": "error", "data": "会话创建失败"}, ensure_ascii=False) + "\n\n"
        return Response(_err2(), mimetype="text/event-stream")

    headers = _agent2_headers()
    msg = {"role": "user", "name": "user",
           "content": [{"type": "text", "text": message}]}
    full_text = {"v": ""}
    pending = {"reply_id": None, "tool_calls": []}

    def _translate(evt):
        """翻译单个事件。REPLY_END 不产出（多轮合并由 gen 层处理）。"""
        t = evt.get("type")
        if t == "TEXT_BLOCK_DELTA":
            d = evt.get("delta", "") or ""
            full_text["v"] += d
            return {"event": "delta", "data": d}
        if t == "TOOL_CALL_START":
            return {"event": "tool", "data": evt.get("tool_call_name") or ""}
        if t == "REQUIRE_USER_CONFIRM":
            pending["reply_id"] = evt.get("reply_id")
            pending["tool_calls"] = evt.get("tool_calls") or []
            _AGENT2_PENDING[sid] = pending
            return {"event": "confirm_required", "data": [
                {"id": tc.get("id"), "name": tc.get("name"), "input": tc.get("input")}
                for tc in pending["tool_calls"]
            ]}
        return None

    def gen():
        try:
            # 触发 chat（异步返回 started）
            r = httpx.post(f"{AGENT2_BASE}/chat/", json={
                "agent_id": _AGENT2_AGENT, "session_id": sid, "input": msg,
            }, headers=headers, timeout=60)
            if r.status_code >= 400:
                yield "data: " + json.dumps({"event": "error", "data": f"HTTP {r.status_code}"}, ensure_ascii=False) + "\n\n"
                return
            # 订阅 stream 并翻译；read timeout 10s = 静默超时（leader 收敛后无新事件）。
            # 多智能体 leader 收到 worker 回报会开启新一轮 reply，故 REPLY_END 不 break，
            # 持续读直到静默超时，把多轮文本合并成最终 done。
            with httpx.stream("GET", f"{AGENT2_BASE}/sessions/{sid}/stream",
                              params={"agent_id": _AGENT2_AGENT}, headers=headers,
                              timeout=(None, 10, None, None)) as up:
                for line in up.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        evt = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    translated = _translate(evt)
                    if translated:
                        yield "data: " + json.dumps(translated, ensure_ascii=False) + "\n\n"
                    if evt.get("type") == "REQUIRE_USER_CONFIRM":
                        return  # HITL 停车，等 confirm 续跑
        except httpx.ReadTimeout:
            pass  # 静默超时：leader 已收敛
        except Exception:
            yield "data: " + json.dumps({"event": "error", "data": "agent_service 调用失败"}, ensure_ascii=False) + "\n\n"
        finally:
            yield "data: " + json.dumps({"event": "done", "data": full_text["v"]}, ensure_ascii=False) + "\n\n"

    return Response(gen(), mimetype="text/event-stream")


@app.route("/api/agent2/sessions", methods=["GET"])
def api_agent2_sessions():
    """列会话（翻译成现有 [{session_id, title}] 形状）。"""
    _ensure_agent2()
    headers = _agent2_headers()
    try:
        r = httpx.get(f"{AGENT2_BASE}/sessions/", params={"agent_id": _AGENT2_AGENT},
                      headers=headers, timeout=30)
        r.raise_for_status()
        sessions = r.json().get("sessions") or []
        out = []
        for s in sessions:
            sess = s.get("session") or {}
            item = {
                "session_id": sess.get("id"),
                "title": sess.get("name") or "对话",
            }
            # 提取 team 成员（worker session_id + agent_id + name），供前端订阅 worker 进度
            team = s.get("team")
            if isinstance(team, dict):
                members = []
                for m in (team.get("members") or []):
                    agent = m.get("agent") or {}
                    members.append({
                        "name": (agent.get("data") or {}).get("name") or "worker",
                        "agent_id": agent.get("id"),
                        "session_id": m.get("session_id"),
                    })
                if members:
                    item["team"] = {"members": members}
            out.append(item)
        return jsonify({"status": "ok", "data": out})
    except Exception:
        return jsonify({"status": "error", "message": "agent_service 不可用"})


@app.route("/api/agent2/sessions", methods=["POST"])
def api_agent2_session_create():
    """新建会话。"""
    if not _ensure_agent2():
        return jsonify({"status": "error", "message": "agent_service 不可用"})
    sid = _agent2_new_session()
    if sid is None:
        return jsonify({"status": "error", "message": "会话创建失败"})
    return jsonify({"status": "ok", "data": {"session_id": sid}})


@app.route("/api/agent2/sessions/<sid>", methods=["DELETE"])
def api_agent2_session_delete(sid):
    """删除会话。"""
    headers = _agent2_headers()
    try:
        httpx.delete(f"{AGENT2_BASE}/sessions/{sid}",
                     params={"agent_id": _AGENT2_AGENT}, headers=headers, timeout=30)
    except Exception:
        pass
    return jsonify({"status": "ok", "message": "已删除"})


@app.route("/api/agent2/sessions/<sid>/messages", methods=["GET"])
def api_agent2_session_messages(sid):
    """历史消息（翻译成现有 OpenAI 格式）。agent_id 可由调用方指定（查 worker 历史时传 worker agent）。"""
    headers = _agent2_headers()
    agent_id = request.args.get("agent_id") or _AGENT2_AGENT
    try:
        r = httpx.get(f"{AGENT2_BASE}/sessions/{sid}/messages",
                      params={"agent_id": agent_id}, headers=headers, timeout=30)
        r.raise_for_status()
        raw = r.json().get("messages") or []
        return jsonify({"status": "ok", "data": _agent2_to_openai(raw)})
    except Exception:
        return jsonify({"status": "ok", "data": []})


def _agent2_to_openai(raw_msgs):
    """agent_service Msg JSON → OpenAI 格式 [{role, content, tool_calls}]。"""
    out = []
    for m in raw_msgs or []:
        role = m.get("role")
        blocks = m.get("content") or []
        text = ""
        tool_calls = []
        for b in blocks:
            bt = b.get("type")
            if bt == "text":
                text += b.get("text", "")
            elif bt == "tool_call":
                tool_calls.append({"id": b.get("id"), "type": "function",
                                   "function": {"name": b.get("name"), "arguments": b.get("input", "")}})
        if role == "user":
            out.append({"role": "user", "content": text})
        elif role == "assistant":
            out.append({"role": "assistant", "content": text,
                        "tool_calls": tool_calls if tool_calls else None})
    return out


@app.route("/api/agent2/confirm", methods=["POST"])
def api_agent2_confirm():
    """HITL 确认：decisions=[{id, confirmed}] → UserConfirmResultEvent 续跑。"""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "default")
    decisions = data.get("decisions") or []
    pending = _AGENT2_PENDING.get(session_id)
    if not pending:
        def _err():
            yield "data: " + json.dumps({"event": "error", "data": "无待确认操作"}, ensure_ascii=False) + "\n\n"
        return Response(_err(), mimetype="text/event-stream")

    headers = _agent2_headers()
    full_text = {"v": ""}

    def _translate(evt):
        t = evt.get("type")
        if t == "TEXT_BLOCK_DELTA":
            d = evt.get("delta", "") or ""
            full_text["v"] += d
            return {"event": "delta", "data": d}
        if t == "TOOL_CALL_START":
            return {"event": "tool", "data": evt.get("tool_call_name") or ""}
        if t == "REQUIRE_USER_CONFIRM":
            pending2 = {"reply_id": evt.get("reply_id"), "tool_calls": evt.get("tool_calls") or []}
            _AGENT2_PENDING[session_id] = pending2
            return {"event": "confirm_required", "data": [
                {"id": tc.get("id"), "name": tc.get("name"), "input": tc.get("input")}
                for tc in pending2["tool_calls"]
            ]}
        return None

    def gen():
        try:
            confirm_results = []
            by_id = {tc.get("id"): tc for tc in pending["tool_calls"]}
            for d in decisions:
                tc = by_id.get((d or {}).get("id"))
                if tc is not None:
                    confirm_results.append({"confirmed": bool(d.get("confirmed")), "tool_call": tc})
            input_event = {"type": "USER_CONFIRM_RESULT", "reply_id": pending["reply_id"],
                           "confirm_results": confirm_results}
            r = httpx.post(f"{AGENT2_BASE}/chat/", json={
                "agent_id": _AGENT2_AGENT, "session_id": session_id, "input": input_event,
            }, headers=headers, timeout=60)
            if r.status_code >= 400:
                yield "data: " + json.dumps({"event": "error", "data": f"HTTP {r.status_code}"}, ensure_ascii=False) + "\n\n"
                return
            with httpx.stream("GET", f"{AGENT2_BASE}/sessions/{session_id}/stream",
                              params={"agent_id": _AGENT2_AGENT}, headers=headers,
                              timeout=(None, 10, None, None)) as up:
                for line in up.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        evt = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    translated = _translate(evt)
                    if translated:
                        yield "data: " + json.dumps(translated, ensure_ascii=False) + "\n\n"
                    if evt.get("type") == "REQUIRE_USER_CONFIRM":
                        return  # 再次停车，等下一次 confirm
        except httpx.ReadTimeout:
            pass  # 静默超时：leader 已收敛
        except Exception as e:
            yield "data: " + json.dumps({"event": "error", "data": str(e)}, ensure_ascii=False) + "\n\n"
        finally:
            yield "data: " + json.dumps({"event": "done", "data": full_text["v"]}, ensure_ascii=False) + "\n\n"

    return Response(gen(), mimetype="text/event-stream")


# ── Agent ─────────────────────────────────────────────────


@app.route("/api/apps/<path:app_name>/agent/chat", methods=["POST"])
def api_agent_chat(app_name):
    if app_name not in platform.app_names():
        return jsonify({"status": "error", "message": f"应用不存在：{app_name}"}), 404
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    session_id = data.get("session_id", "default")
    if not message:
        return jsonify({"status": "error", "message": "消息不能为空"})
    result = _get_agent(app_name).chat(message, session_id)
    return jsonify({"status": "ok", "data": result})


@app.route("/api/apps/<path:app_name>/agent/reset", methods=["POST"])
def api_agent_reset(app_name):
    data = request.get_json(silent=True) or {}
    _get_agent(app_name).reset(data.get("session_id", "default"))
    return jsonify({"status": "ok", "message": "会话已重置"})


# ── 平台级 Agent（跨应用，首页入口）──────────────────────


@app.route("/api/agent/chat", methods=["POST"])
def api_platform_agent_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    session_id = data.get("session_id", "default")
    if not message:
        return jsonify({"status": "error", "message": "消息不能为空"})
    result = _get_agent(None).chat(message, session_id)
    return jsonify({"status": "ok", "data": result})


def _agent_stream_response(agent, message: str, session_id: str):
    """SSE 流式响应：AgentScope 后端走原生事件流；旧后端回落为单帧 done。"""
    if hasattr(agent, "stream_chat"):
        return Response(agent.stream_chat(message, session_id), mimetype="text/event-stream")
    result = agent.chat(message, session_id)

    def _single():
        yield "data: " + json.dumps(
            {"event": "done", "data": result.get("reply", ""),
             "tools": [t.get("tool") for t in result.get("tool_calls", [])]},
            ensure_ascii=False,
        ) + "\n\n"

    return Response(_single(), mimetype="text/event-stream")


@app.route("/api/agent/chat/stream", methods=["POST"])
def api_platform_agent_chat_stream():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    session_id = data.get("session_id", "default")
    if not message:
        return jsonify({"status": "error", "message": "消息不能为空"})
    return _agent_stream_response(_get_agent(None), message, session_id)


@app.route("/api/apps/<path:app_name>/agent/chat/stream", methods=["POST"])
def api_agent_chat_stream(app_name):
    if app_name not in platform.app_names():
        return jsonify({"status": "error", "message": f"应用不存在：{app_name}"}), 404
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    session_id = data.get("session_id", "default")
    if not message:
        return jsonify({"status": "error", "message": "消息不能为空"})
    return _agent_stream_response(_get_agent(app_name), message, session_id)


def _agent_confirm_response(agent, session_id: str, decisions: list):
    """SSE 流式确认响应（HITL：用户确认/拒绝危险操作后继续）。"""
    if hasattr(agent, "confirm"):
        return Response(agent.confirm(session_id, decisions), mimetype="text/event-stream")
    return jsonify({"status": "error", "message": "当前后端不支持交互确认"}), 400


@app.route("/api/agent/confirm", methods=["POST"])
def api_platform_agent_confirm():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "default")
    decisions = data.get("decisions") or []
    return _agent_confirm_response(_get_agent(None), session_id, decisions)


@app.route("/api/apps/<path:app_name>/agent/confirm", methods=["POST"])
def api_agent_confirm(app_name):
    if app_name not in platform.app_names():
        return jsonify({"status": "error", "message": f"应用不存在：{app_name}"}), 404
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "default")
    decisions = data.get("decisions") or []
    return _agent_confirm_response(_get_agent(app_name), session_id, decisions)


@app.route("/api/agent/reset", methods=["POST"])
def api_platform_agent_reset():
    data = request.get_json(silent=True) or {}
    _get_agent(None).reset(data.get("session_id", "default"))
    return jsonify({"status": "ok", "message": "会话已重置"})


# ── Agent 执行进度（「执行中」状态轮询，只读阶段信号）────

@app.route("/api/apps/<path:app_name>/agent/progress", methods=["GET"])
def api_agent_progress(app_name):
    """读该会话在途对话的阶段进度（当前轮次 / 正在调用的工具）；data=null 表示无在途对话。"""
    from fde_platform.agent_common import get_progress
    sid = request.args.get("session_id", "default")
    return jsonify({"status": "ok", "data": get_progress(app_name, sid)})


@app.route("/api/agent/progress", methods=["GET"])
def api_platform_agent_progress():
    from fde_platform.agent_common import get_progress
    sid = request.args.get("session_id", "default")
    return jsonify({"status": "ok", "data": get_progress(None, sid)})


# ── 对话历史（会话管理）────────────────────────────────
# 会话按登录用户隔离：session_id 统一加 “用户名:” 前缀存储；owner 列做归属校验。
# 未启用鉴权时（users.session_user() 恒 None）归为 anon（单用户 DEMO 场景）。

from fde_platform import agent_state  # noqa: E402

agent_state.init_schema()


def _chat_user():
    u = users.session_user()
    return (u["username"] if u else "anon"), bool(u and u.get("is_admin"))


def _full_sid(username: str, sid: str) -> str:
    return f"{username}:{sid}"


def _strip_sid(username: str, full_sid: str) -> str:
    prefix = f"{username}:"
    return full_sid[len(prefix):] if full_sid.startswith(prefix) else full_sid


def _sessions_list(scope: str):
    username, _ = _chat_user()
    rows = agent_state.list_sessions(owner=username, scope=scope)
    return jsonify({"status": "ok", "data": [
        {"session_id": _strip_sid(username, r["session_id"]),
         "title": r["title"] or "新对话",
         "created_at": r["created_at"], "updated_at": r["updated_at"]}
        for r in rows
    ]})


def _session_create(scope: str):
    import uuid
    username, _ = _chat_user()
    raw = uuid.uuid4().hex[:12]
    agent_state.create_session(_full_sid(username, raw), username, scope)
    return jsonify({"status": "ok",
                    "data": {"session_id": raw, "title": "新对话"}})


def _session_owned(scope: str, sid: str):
    """取当前用户拥有的会话（校验归属与 scope）；不满足返回 None。"""
    username, is_admin = _chat_user()
    sess = agent_state.get_session(_full_sid(username, sid))
    if sess is None or sess["scope"] != scope:
        return None
    if sess["owner"] != username and not is_admin:
        return None
    return sess


def _session_messages(scope: str, sid: str):
    username, _ = _chat_user()
    if _session_owned(scope, sid) is None:
        return jsonify({"status": "error", "message": "会话不存在"}), 404
    from fde_platform.agent_agentscope import load_session_messages
    return jsonify({"status": "ok",
                    "data": load_session_messages(_full_sid(username, sid))})


def _session_delete(scope: str, sid: str):
    username, _ = _chat_user()
    if _session_owned(scope, sid) is None:
        return jsonify({"status": "error", "message": "会话不存在"}), 404
    agent_state.delete_session(_full_sid(username, sid))
    return jsonify({"status": "ok", "message": "会话已删除"})


@app.route("/api/agent/sessions", methods=["GET"])
def api_platform_sessions():
    return _sessions_list("__platform__")


@app.route("/api/agent/sessions", methods=["POST"])
def api_platform_session_create():
    return _session_create("__platform__")


@app.route("/api/agent/sessions/<sid>/messages", methods=["GET"])
def api_platform_session_messages(sid):
    return _session_messages("__platform__", sid)


@app.route("/api/agent/sessions/<sid>", methods=["DELETE"])
def api_platform_session_delete(sid):
    return _session_delete("__platform__", sid)


@app.route("/api/apps/<path:app_name>/agent/sessions", methods=["GET"])
def api_agent_sessions(app_name):
    if app_name not in platform.app_names():
        return jsonify({"status": "error", "message": f"应用不存在：{app_name}"}), 404
    return _sessions_list(app_name)


@app.route("/api/apps/<path:app_name>/agent/sessions", methods=["POST"])
def api_agent_session_create(app_name):
    if app_name not in platform.app_names():
        return jsonify({"status": "error", "message": f"应用不存在：{app_name}"}), 404
    return _session_create(app_name)


@app.route("/api/apps/<path:app_name>/agent/sessions/<sid>/messages", methods=["GET"])
def api_agent_session_messages(app_name, sid):
    if app_name not in platform.app_names():
        return jsonify({"status": "error", "message": f"应用不存在：{app_name}"}), 404
    return _session_messages(app_name, sid)


@app.route("/api/apps/<path:app_name>/agent/sessions/<sid>", methods=["DELETE"])
def api_agent_session_delete(app_name, sid):
    if app_name not in platform.app_names():
        return jsonify({"status": "error", "message": f"应用不存在：{app_name}"}), 404
    return _session_delete(app_name, sid)


# ── 错误页 ────────────────────────────────────────────────


@app.errorhandler(404)
def page_not_found(e):
    return render_template("error.html", message="页面不存在"), 404


# ── 集成接口管理 ──────────────────────────────────────────

@app.route("/integration")
def integration_page():
    ep_list = integration.list_endpoints()
    stats = integration.stats_by_target()
    return render_template("integration.html",
                           endpoints=ep_list, stats=stats,
                           apps=platform.app_names())


@app.route("/api/integration/endpoints")
def api_integration_list():
    return jsonify({"status": "ok", "data": integration.list_endpoints()})


@app.route("/api/integration/discover")
def api_integration_discover():
    report = scanner.scan_report(platform)
    external = integration.discover(platform)
    cross = integration.cross_group_calls(report)
    return jsonify({"status": "ok", "data": {"external": external, "cross_group": cross}})


@app.route("/api/integration/endpoints/<int:eid>")
def api_integration_get(eid):
    all_eps = integration.list_endpoints()
    ep = [e for e in all_eps if e["id"] == eid]
    if not ep:
        return jsonify({"status": "error", "message": "端点不存在"}), 404
    return jsonify({"status": "ok", "data": ep[0]})


@app.route("/api/integration/endpoints", methods=["POST"])
def api_integration_save():
    d = request.get_json(silent=True) or {}
    eid = integration.save_endpoint(
        app_name=d.get("app_name", ""),
        method_name=d.get("method_name", ""),
        target=d.get("target", ""),
        kind=d.get("kind", "external"),
        url=d.get("url") or None,
        http_method=d.get("http_method", "POST"),
        content_type=d.get("content_type", "application/json"),
        auth_type=d.get("auth_type", "none"),
        auth_param_name=d.get("auth_param_name") or None,
        auth_credential=d.get("auth_credential") or None,
        extra_headers=d.get("extra_headers") or None,
        timeout_s=int(d.get("timeout_s", 30)),
        retries=int(d.get("retries", 1)),
        mock_enabled=bool(d.get("mock_enabled")),
        mock_data=d.get("mock_data") or None,
    )
    return jsonify({"status": "ok", "id": eid})


@app.route("/api/integration/endpoints/<int:eid>", methods=["DELETE"])
def api_integration_delete(eid):
    integration.delete_endpoint(eid)
    return jsonify({"status": "ok"})


@app.route("/api/integration/test/<int:eid>", methods=["POST"])
def api_integration_test(eid):
    """连通测试（复用 integration.test_endpoint，含自动 GET 方法探测）。"""
    result = integration.test_endpoint(eid)
    code = 200 if result.get("status") == "ok" else 400
    return jsonify(result), code


@app.route("/api/integration/logs")
def api_integration_logs():
    target = request.args.get("target")
    limit = int(request.args.get("limit", 50))
    return jsonify({"status": "ok", "data": integration.recent_logs(target, limit)})


@app.route("/api/integration/stats")
def api_integration_stats():
    return jsonify({"status": "ok", "data": integration.stats_by_target()})
