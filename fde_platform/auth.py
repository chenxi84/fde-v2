"""FDE v2 平台 — 鉴权（执行面，可插拔）。

仿 v1，负责：
- 登录 / 登出（Flask 签名 cookie 会话；角色每次请求实时查库，改权即时生效）
- before_request 单闸：
    白名单 → 登录检查 → /auth/ 仅管理员 → 应用级授权（view_args）
    → 普通用户的首页/清单过滤短路 → Agent 会话按用户隔离
- after_request：向 HTML 响应 </body> 前注入用户状态条（不改 base.html）
- register(app)：唯一扩展点（main.py 以 try-import 方式启用，删本模块即还原无认证）

依赖方向单向：auth.py → users.py → 数据库；web/agent 只依赖 users（取 ctx），不感知本模块。
"""
import sys
from pathlib import Path

from flask import (
    Blueprint,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from markupsafe import escape

from fde_platform import users

# ── 常量 ────────────────────────────────────────────────

OPEN_PATHS = {"/login", "/logout", "/favicon.ico", "/change-password"}
WHITELIST_PREFIXES = ("/static/",)

# 这些端点的请求体会被改写 session_id（见 gate 末段，做 Agent 会话按用户隔离）
AGENT_ENDPOINTS = {
    "api_agent_chat", "api_agent_reset",
    "api_platform_agent_chat", "api_platform_agent_reset",
    # SSE 流式 + HITL 确认（同样按用户隔离 session_id）
    "api_agent_chat_stream", "api_agent_confirm",
    "api_platform_agent_chat_stream", "api_platform_agent_confirm",
}

# 应用前端静态资源端点（/app/<名>/view.{js,html}）：是前端代码而非数据，
# 跳过 ④ 的应用可见性校验（任何登录用户可加载，与旧 view/ 静态托管同安全 posture）。
# 授权仍在两处收口：菜单按页面授权渲染（shell）、数据调用按服务闸门（本 gate ④ 的 service 分支）。
# 端点只 serve 写死文件名，.py/.db 等永不暴露（见 web._serve_app_view）。
APP_VIEW_ASSET_ENDPOINTS = {"app_view_js", "app_view_html"}


# ── 会话 / 当前用户 ─────────────────────────────────────


def current_user():
    """取当前登录用户（按请求缓存于 g；每次请求查库，授权变更即时生效）。"""
    if "auth_user" in g:
        return g.auth_user
    username = session.get("username")
    user = users.get_user_by_name(username) if username else None
    g.auth_user = user
    return user


def _safe_next(value: str) -> str:
    """防开放重定向：next 必须是站内相对路径。"""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


def _deny(message: str):
    """403：API 路径返 JSON，页面复用 error.html。"""
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "message": message}), 403
    return render_template("error.html", message=message), 403


def _implicit_page_grant(user, app_name: str, service: str) -> bool:
    """页面授权隐式放行：请求经 `X-Fde-Page` 头声明来源页（lib/api.js 自动注入），
    且 ① 该用户角色获授此页、② 页面源码派生的服务边含 (app, service) → 放行。

    防伪：声明的页仍要过角色授权校验——声明未授权页 → 拒；声明已授权页 → 放行的
    服务必在该页派生集内（授权的自然延伸）。无头请求（MCP/Agent/CLI/裸 curl）不享受
    隐式放行，仍按显式授权判定。派生表由 view_registry 扫描生成（svc() 字面量）。"""
    page_id = (request.headers.get("X-Fde-Page") or "").strip()
    if not page_id:
        return False
    if not users.is_page_granted(user["id"], page_id):
        return False
    from fde_platform import view_registry  # 惰性导入，避免顶层耦合

    # 页面派生边按短名记录（页内 svc() 用短名、属页面所在组）；请求 app_name 为 qualname，取短名比对
    short = app_name.rsplit("/", 1)[-1]
    return (short, service) in view_registry.page_services(page_id)


# ── 单一闸门 ────────────────────────────────────────────


def gate():
    """before_request 钩子：全部认证/授权逻辑收口于此。

    路由匹配先于钩子，request.view_args 已就绪——所有带 <app_name> 的路由
    （页面/API）在此统一拦截，无需逐路由加装饰器；返回非 None 即短路视图。
    """
    path = request.path

    # ① 白名单
    if path in OPEN_PATHS or path.startswith(WHITELIST_PREFIXES):
        return None

    # ② 登录检查
    user = current_user()
    if user is None:
        if path.startswith("/api/"):
            return jsonify({"status": "error", "message": "未登录"}), 401
        return redirect(url_for("auth.login", next=path))

    # ②.5 首次登录强制改密（password_changed=0）
    if not user.get("password_changed") and path != "/change-password":
        if path.startswith("/api/"):
            return jsonify({"status": "error", "message": "请先修改默认密码"}), 403
        return redirect(url_for("auth.change_password", next=path))

    # ③ 管理区仅管理员角色（is_admin 标志，见 users._is_admin_user 口径）
    if path.startswith("/auth/") and not user.get("is_admin"):
        return _deny("用户管理仅限管理员")

    # ④ 授权（view_args 由路由匹配填充）：带 service → 服务级；否则 → 应用可见性
    #    （首页/清单的按服务过滤交由 web 用 users.visible_* 自渲染，不在此短路）
    view_args = request.view_args or {}
    app_name = view_args.get("app_name")
    service = view_args.get("service")
    if app_name and not user.get("is_admin") \
            and request.endpoint not in APP_VIEW_ASSET_ENDPOINTS:
        if service is not None:
            if not (users.is_service_granted(user["id"], app_name, service)
                    or _implicit_page_grant(user, app_name, service)):
                return _deny(f"无权调用服务：{app_name}.{service}")
        elif not users.has_app_access(user["id"], app_name):
            return _deny(f"无权访问应用：{app_name}")

    # ⑤ Agent 会话按用户隔离：就地把请求体 session_id 改写为 "用户名:原值"
    #    （Flask get_json() 结果有缓存，视图读到同一份 dict，故改写对视图可见）
    if request.endpoint in AGENT_ENDPOINTS:
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            data["session_id"] = f"{user['username']}:{data.get('session_id', 'default')}"

    return None


# ── 用户状态条注入（不改 base.html）─────────────────────

_USERBAR = """
<div id="auth-userbar">
  <span>👤 {username}（{role_label}）</span>
  {admin_link}
  <a href="/logout">退出</a>
</div>
<style>
#auth-userbar {{
  position: fixed; right: 16px; bottom: 16px; z-index: 9999;
  display: flex; align-items: center; gap: 14px;
  background: #0e1b2a; color: #e2e8f0; padding: 8px 16px;
  border-radius: 20px; font-size: 13px;
  box-shadow: 0 4px 18px rgba(10,22,34,.4);
  font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
}}
#auth-userbar a {{ color: #f5b04c; text-decoration: none; transition: color .15s; }}
#auth-userbar a:hover {{ color: #fff; }}
</style>
"""


def inject_userbar(resp):
    """after_request：向已登录用户的 HTML 响应注入悬浮用户条。"""
    try:
        user = g.get("auth_user") if "auth_user" in g else None
        content_type = resp.content_type or ""
        if (
            user
            and "text/html" in content_type
            and resp.status_code < 300
            and not resp.is_streamed
        ):
            html = resp.get_data(as_text=True)
            if "</body>" in html:
                admin_link = (
                    '<a href="/auth/users">用户管理</a>'
                    if user.get("is_admin")
                    else ""
                )
                bar = _USERBAR.format(
                    username=escape(user["username"]),
                    role_label=escape(user.get("role_label") or user["role"]),
                    admin_link=admin_link,
                )
                resp.set_data(html.replace("</body>", bar + "\n</body>", 1))
    except Exception:
        pass  # 注入失败绝不影响正常响应
    return resp


# ── 登录 / 登出 ─────────────────────────────────────────

auth_bp = Blueprint("auth", __name__)


def _platform_stats():
    """登录页品牌墙的实时系统状态（应用 / 应用组 / 开放服务计数 + 端口）。"""
    try:
        from fde_platform.web import PORT, build_group_summary, platform

        return {
            "apps": len(platform.app_names()),
            "groups": len(build_group_summary()),
            "services": sum(len(platform.services(n)) for n in platform.app_names()),
            "port": PORT,
        }
    except Exception:
        return None


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if current_user():
            return redirect("/")
        return render_template(
            "login.html", error=None, next=_safe_next(request.args.get("next", "/")),
            stats=_platform_stats(),
        )

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    nxt = _safe_next(request.form.get("next", "/"))

    user = users.get_user_by_name(username)
    if user and users.verify_password(user, password):
        session.clear()
        session["username"] = user["username"]
        return redirect(nxt)
    return render_template("login.html", error="用户名或密码错误", next=nxt)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/change-password", methods=["GET", "POST"])
def change_password():
    user = current_user()
    if user is None:
        return redirect(url_for("auth.login"))
    error = None
    if request.method == "POST":
        old_pw = request.form.get("old_password") or ""
        new_pw = request.form.get("new_password") or ""
        new_pw2 = request.form.get("new_password2") or ""
        if not users.verify_password(user, old_pw):
            error = "当前密码错误"
        elif len(new_pw) < 6:
            error = "新密码至少 6 位"
        elif new_pw != new_pw2:
            error = "两次输入的新密码不一致"
        elif old_pw == new_pw:
            error = "新密码不能与当前密码相同"
        else:
            users.reset_password(user["username"], new_pw)
            # 标记已改密
            conn = users.get_conn()
            conn.execute("UPDATE users SET password_changed = 1 WHERE id = ?", (user["id"],))
            conn.commit()
            conn.close()
            nxt = _safe_next(request.form.get("next", "/"))
            return redirect(nxt)
    return render_template("change_password.html", error=error,
                           next=_safe_next(request.args.get("next", "/")),
                           username=user["username"])


# ── 插件入口 ────────────────────────────────────────────


def register(app):
    """把鉴权系统接入传入的 Flask app（唯一扩展点）。"""
    import logging
    logger = logging.getLogger(__name__)
    users.init_schema()
    if users.seed_admin():
        logger.warning("首次启动：已播种默认管理员 admin/admin，请尽快改密")

    app.register_blueprint(users.bp)
    app.register_blueprint(auth_bp)
    app.before_request(gate)

    @app.context_processor
    def _inject_auth_user():
        """向所有模板注入当前登录用户（gate 已置 g.auth_user；登录页/未登录为 None）。"""
        user = g.get("auth_user") if "auth_user" in g else None
        return {"auth_user": user}

    # 右下角悬浮用户条（登录用户/用户管理/退出）按需求移除，不再注入；
    # 用户管理入口已移至 base.html 顶部导航（仅 admin 可见），用户名/退出仍在 .uchip。
    # app.after_request(inject_userbar)

    logger.info("鉴权已启用 · 用户库 %s", users.DB_PATH)
    return app


if __name__ == "__main__":
    # 独立入口：python -m fde_platform.auth（带认证启动）
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fde_platform.web import HOST, PORT, app

    register(app)
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
