"""FDE v2 平台 — 大模型配置页与 API（可插拔 Blueprint）。

Agent 对话的模型配置管理面：密钥加密落库、掩码不回显、保存即生效。
配置逻辑与 provider 实现在 ``fde_platform/llm.py``；本模块只是其 Web 界面。
可插拔：删除本模块 + main.py 的 register 调用即无此页，agent 仍按库内配置 / 环境变量工作。
仅 admin 可访问（无鉴权模式全通，与 scheduler 同口径）。
"""
from flask import Blueprint, jsonify, redirect, render_template, request

from fde_platform import llm, users

bp = Blueprint("llm", __name__)


def _is_admin(user) -> bool:
    """与 scheduler 同口径：角色带 is_admin 标志；无鉴权模式（user=None）全通。"""
    return user is None or bool(user.get("is_admin"))


def _current_user():
    try:
        return users.session_user()
    except Exception:  # 无请求上下文 / 无鉴权
        return None


@bp.route("/llm")
def page():
    if not _is_admin(_current_user()):
        return redirect("/")
    providers = [(k, llm.PROVIDER_LABELS[k]) for k in llm.PROVIDERS]
    return render_template("llm_settings.html",
                           profiles=llm.list_profiles(),
                           providers=providers,
                           roles=llm.ROLES)


@bp.route("/llm/save", methods=["POST"])
def save():
    user = _current_user()
    if not _is_admin(user):
        return jsonify({"status": "error", "message": "无权限"}), 403
    d = request.get_json(silent=True) or {}
    role = d.get("role")
    if role not in llm.ROLES:
        return jsonify({"status": "error", "message": f"未知 role：{role}"}), 400
    provider = d.get("provider") or "openai_compat"
    if provider not in llm.PROVIDERS:
        return jsonify({"status": "error", "message": f"未知 provider：{provider}"}), 400
    if not (d.get("model") or "").strip():
        return jsonify({"status": "error", "message": "模型名不能为空"}), 400
    # 密钥：clear_key=清空(None)；否则非空=更新、空串=保持不变
    if d.get("clear_key"):
        api_key = None
    else:
        api_key = d.get("api_key") or ""
    try:
        llm.save_profile(
            role, provider=provider, base_url=d.get("base_url") or "", model=d.get("model") or "",
            api_key=api_key, temperature=d.get("temperature"), max_tokens=d.get("max_tokens"),
            timeout_s=d.get("timeout_s"), enabled=bool(d.get("enabled", True)),
            updated_by=(user or {}).get("username"))
    except Exception as e:
        return jsonify({"status": "error", "message": f"保存失败：{e}"}), 500
    return jsonify({"status": "ok"})


@bp.route("/llm/test", methods=["POST"])
def test():
    if not _is_admin(_current_user()):
        return jsonify({"ok": False, "error": "无权限"}), 403
    d = request.get_json(silent=True) or {}
    role = d.get("role") if d.get("role") in llm.ROLES else None
    result = llm.test_connection(
        provider=d.get("provider") or "openai_compat", base_url=d.get("base_url") or "",
        model=d.get("model") or "", api_key=d.get("api_key") or "",
        temperature=d.get("temperature") if d.get("temperature") is not None else 0.1,
        max_tokens=d.get("max_tokens"), timeout_s=d.get("timeout_s") or 20, role=role)
    return jsonify(result)


@bp.route("/llm/api")
def api():
    """只读视图（绝不含密钥），供前端刷新状态。"""
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    return jsonify({"status": "ok", "data": llm.list_profiles()})


def register(app) -> None:
    app.register_blueprint(bp)
