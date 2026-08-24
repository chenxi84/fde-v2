"""FDE v2 平台 — Agent 后端管理页（可插拔 Blueprint）。

展示 AgentScope 2.0 插件式后端的接入状态与运行观测（Phase 1 范围）：
- 当前生效的 Agent 后端（reactive 旧 ReAct / agentscope AgentScope 编排）与切换方式；
- AgentScope 是否可用（import 状态 / 版本）、FDE 暴露的工具数量；
- 对话模型配置摘要（指向 /llm 配置）。

skill 库（草稿→审批→发布/评分/版本）与 Permission 三态规则属 Phase 2，本页先留观测位。

可插拔：删除本模块 + main.py 的 register 调用即无此页，Agent 后端照常工作。
仅 admin 可访问（无鉴权模式全通，与 llm_admin / scheduler 同口径）。
"""
from flask import Blueprint, jsonify, redirect, render_template, request

from fde_platform import llm, skills, users
from fde_platform.web import platform

bp = Blueprint("agent_admin", __name__)


def _is_admin(user) -> bool:
    return user is None or bool(user.get("is_admin"))


def _current_user():
    try:
        return users.session_user()
    except Exception:
        return None


def agentscope_info() -> dict:
    """AgentScope 接入状态（import 结果 / 版本），失败不影响主流程。"""
    info = {"available": False, "version": "", "error": ""}
    try:
        import agentscope

        info["available"] = True
        info["version"] = getattr(agentscope, "__version__", "")
    except Exception as e:  # noqa: BLE001
        info["error"] = f"{type(e).__name__}: {e}"
    return info


def resolved_backend() -> str:
    """当前实际生效的后端（唯一：AgentScope）。"""
    return "agentscope" if agentscope_info()["available"] else "unavailable"


def tool_count() -> int:
    """FDE 平台暴露的对外服务数（含内置文件工具），即喂给 Agent 的工具清单量级。"""
    try:
        return len(platform.all_mcp_tools())
    except Exception:
        return sum(len(platform.services(n)) for n in platform.app_names())


@bp.route("/agent-admin")
def page():
    if not _is_admin(_current_user()):
        return redirect("/")
    return render_template(
        "agent_admin.html",
        active=resolved_backend(),
        agentscope=agentscope_info(),
        tool_count=tool_count(),
        profile=llm.public_view("operator"),
        skills=skills.list_skills(),
    )


# ── Skill 库操作（form POST → 回跳 /agent-admin）─────────────

def _admin_guard():
    if not _is_admin(_current_user()):
        return redirect("/")
    return None


@bp.route("/agent-admin/skills/<int:skill_id>/approve", methods=["POST"])
def skill_approve(skill_id):
    _admin_guard()
    try:
        skills.approve(skill_id)
    except Exception as e:
        pass
    return redirect("/agent-admin")


@bp.route("/agent-admin/skills/<int:skill_id>/reject", methods=["POST"])
def skill_reject(skill_id):
    _admin_guard()
    skills.reject(skill_id)
    return redirect("/agent-admin")


@bp.route("/agent-admin/skills/<int:skill_id>/deprecate", methods=["POST"])
def skill_deprecate(skill_id):
    _admin_guard()
    skills.deprecate(skill_id)
    return redirect("/agent-admin")


@bp.route("/agent-admin/skills/<int:skill_id>/rate", methods=["POST"])
def skill_rate(skill_id):
    _admin_guard()
    try:
        skills.rate(skill_id, request.form.get("score", ""))
    except Exception:
        pass
    return redirect("/agent-admin")


@bp.route("/agent-admin/status")
def status():
    if not _is_admin(_current_user()):
        return jsonify({"status": "error", "message": "无权限"}), 403
    return jsonify({
        "status": "ok",
        "data": {
            "active": resolved_backend(),
            "agentscope": agentscope_info(),
            "tool_count": tool_count(),
            "profile": llm.public_view("operator"),
        },
    })


def register(app) -> None:
    app.register_blueprint(bp)
