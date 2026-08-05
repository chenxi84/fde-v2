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
import os
import time
import traceback
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    render_template_string,
    request,
    send_file,
    send_from_directory,
)

from fde import FdeError
from fde_platform import builtin_tools, integration, scanner, users, view_registry
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
        from fde_platform.agent import AgentSession

        _agent_sessions[key] = AgentSession(platform, app_name)
    return _agent_sessions[key]


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
#   模块 = view/ 下含 index.html 的目录（如 view/crm/），由 design/
#   VIEW_CONVENTION.md（技能 fde-view-gen）按统一范式生成；view/lib/ 为跨模块公共基座
#   （api.js / shell.js / 设计系统），view/pages/ 为平台公共页（Agent / 服务台），
#   二者无 index.html、不进模块清单，但同样按需静态放行。
#   同源 → 无需 CORS、会话 Cookie 天然携带；/view/ 不在鉴权白名单，
#   未登录访问页面自动重定向 /login（fetch 则收 401 由前端自处理）。
# ══════════════════════════════════════════════════════════

_VIEW_DIR = Path(__file__).resolve().parents[1] / "view"


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
    params = _coerce(raw, svc["parameters"])

    try:
        # 身份来自登录态（无会话则 None → 平台默认身份）；客户端无法伪造（§4.1）
        result = platform.call(app_name, service, ctx=users.current_caller_ctx(), **params)
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


@app.route("/api/agent/reset", methods=["POST"])
def api_platform_agent_reset():
    data = request.get_json(silent=True) or {}
    _get_agent(None).reset(data.get("session_id", "default"))
    return jsonify({"status": "ok", "message": "会话已重置"})


# ── Agent 执行进度（「执行中」状态轮询，只读阶段信号）────

@app.route("/api/apps/<path:app_name>/agent/progress", methods=["GET"])
def api_agent_progress(app_name):
    """读该会话在途对话的阶段进度（当前轮次 / 正在调用的工具）；data=null 表示无在途对话。"""
    from fde_platform.agent import get_progress
    sid = request.args.get("session_id", "default")
    return jsonify({"status": "ok", "data": get_progress(app_name, sid)})


@app.route("/api/agent/progress", methods=["GET"])
def api_platform_agent_progress():
    from fde_platform.agent import get_progress
    sid = request.args.get("session_id", "default")
    return jsonify({"status": "ok", "data": get_progress(None, sid)})


# ── 对话历史（会话管理）────────────────────────────────
# 会话按登录用户隔离：session_id 统一加 “用户名:” 前缀存储；owner 列做归属校验。
# 未启用鉴权时（users.session_user() 恒 None）归为 anon（单用户 DEMO 场景）。

from fde_platform import chatstore  # noqa: E402

chatstore.init_schema()


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
    rows = chatstore.list_sessions(owner=username, scope=scope)
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
    chatstore.create_session(_full_sid(username, raw), username, scope)
    return jsonify({"status": "ok",
                    "data": {"session_id": raw, "title": "新对话"}})


def _session_owned(scope: str, sid: str):
    """取当前用户拥有的会话（校验归属与 scope）；不满足返回 None。"""
    username, is_admin = _chat_user()
    sess = chatstore.get_session(_full_sid(username, sid))
    if sess is None or sess["scope"] != scope:
        return None
    if sess["owner"] != username and not is_admin:
        return None
    return sess


def _session_messages(scope: str, sid: str):
    username, _ = _chat_user()
    if _session_owned(scope, sid) is None:
        return jsonify({"status": "error", "message": "会话不存在"}), 404
    return jsonify({"status": "ok",
                    "data": chatstore.load_messages(_full_sid(username, sid))})


def _session_delete(scope: str, sid: str):
    username, _ = _chat_user()
    if _session_owned(scope, sid) is None:
        return jsonify({"status": "error", "message": "会话不存在"}), 404
    chatstore.delete_session(_full_sid(username, sid))
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
    # 用 get_endpoint 获取含已解密凭证的完整配置
    eps = integration.list_endpoints()
    ep_list = [e for e in eps if e["id"] == eid]
    if not ep_list:
        return jsonify({"status": "error", "message": "端点不存在"}), 404
    summary = ep_list[0]
    full = integration.get_endpoint(summary["app_name"], summary["method_name"])
    if not full:
        return jsonify({"status": "error", "message": "端点不存在"}), 404

    t0 = time.time()
    try:
        if full["mock_enabled"]:
            integration.log_call(full["app_name"], full["method_name"], full["target"],
                                 "Mock 测试", "mock", 0, response_summary=full.get("mock_data") or "{}")
            return jsonify({"status": "ok", "result": "mock"})

        if not full.get("url"):
            return jsonify({"status": "error", "message": "未配置 URL 且未开启 Mock"}), 400

        import urllib.request
        import base64

        body_data = request.get_json(silent=True) or {}
        req = urllib.request.Request(full["url"], method=full.get("http_method", "POST"))
        req.add_header("Content-Type", full.get("content_type", "application/json"))

        # 额外自定义 header
        for k, v in (full.get("extra_headers") or {}).items():
            req.add_header(k, v)

        # 鉴权
        auth_type = full.get("auth_type", "none")
        cred = full.get("auth_credential") or ""
        param_name = full.get("auth_param_name") or ""
        if auth_type == "basic" and cred:
            encoded = base64.b64encode(cred.encode()).decode()
            req.add_header("Authorization", f"Basic {encoded}")
        elif auth_type == "bearer" and cred:
            req.add_header("Authorization", f"Bearer {cred}")
        elif auth_type == "apikey_header" and param_name and cred:
            req.add_header(param_name, cred)
        elif auth_type == "apikey_query":
            sep = "&" if "?" in full["url"] else "?"
            req.full_url = full["url"] + f"{sep}{param_name}={cred}"

        if body_data and full.get("http_method", "POST") in ("POST", "PUT", "PATCH"):
            data_bytes = json.dumps(body_data).encode() if isinstance(body_data, dict) else str(body_data).encode()
            resp = urllib.request.urlopen(req, data=data_bytes, timeout=full.get("timeout_s", 30))
        else:
            resp = urllib.request.urlopen(req, timeout=full.get("timeout_s", 30))

        resp_body = resp.read().decode(errors="replace")[:2000]
        dur = int((time.time() - t0) * 1000)
        integration.log_call(full["app_name"], full["method_name"], full["target"],
                             f"{full.get('http_method','POST')} {full['url']}", "success", dur,
                             response_summary=resp_body[:500])
        return jsonify({"status": "ok", "code": resp.status, "duration_ms": dur,
                        "body_preview": resp_body[:500]})

    except Exception as e:
        dur = int((time.time() - t0) * 1000)
        integration.log_call(full["app_name"], full["method_name"], full["target"],
                             f"{full.get('http_method','POST')} {full['url']}", "error", dur,
                             error_msg=str(e)[:500])
        return jsonify({"status": "error", "message": str(e)[:500], "duration_ms": dur})


@app.route("/api/integration/logs")
def api_integration_logs():
    target = request.args.get("target")
    limit = int(request.args.get("limit", 50))
    return jsonify({"status": "ok", "data": integration.recent_logs(target, limit)})


@app.route("/api/integration/stats")
def api_integration_stats():
    return jsonify({"status": "ok", "data": integration.stats_by_target()})
