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


# ── 权限视图：这个人的数字员工实际能调什么 ──────────────────────
#
# 工具面是按调用者授权**收窄**的（见 agent_surface / agent_service._group_plan），
# 但收窄这件事在界面上看不见——不像加了个按钮那样有视觉证据。这个页把口径
# 静态地摊开：每个应用组留了几项、每一项的授权是哪来的、以及跑某条流程会不会被拦下。
#
# 两个口径都**复用真实实现**（agent_surface.app_surface / flow._preflight），
# 这里不复刻任何一份：两份对不上正是这套东西最初出问题的形态。

def _flow_preview(user) -> list[dict]:
    """逐个 flow 预演：每个节点能拿到几个工具；跑不动则给出原因。

    直接用 `flow._preflight`（开跑前那道同一份判定），所以页面上看到"能跑"，
    真去跑就一定不会被拦——展示与执行不会各说各话。
    """
    from fde_platform import agentscope_bridge as bridge
    from fde_platform import flow as flowmod

    # 全量工具面与页面派生集**各算一次**：逐节点重建会退化成几十秒
    # （每个节点要重扫 20 个应用，且逐服务判会重扫页面注册表）
    defs = bridge.tool_schemas(platform, user)
    page_derived = (None if (user is None or user.get("is_admin"))
                    else users.page_derived_services(user["id"]))

    out = []
    for name, decl in flowmod._load_flows().items():
        nodes = flowmod._normalize_nodes(decl)
        node_rows = []
        for n in nodes:
            if n.get("type", "agent") != "agent":
                node_rows.append({"id": n.get("id", ""), "role": n.get("role", ""),
                                  "count": None, "note": "确定性节点（直调服务）"})
                continue
            try:
                got = flowmod._node_tools(platform, user, n.get("role", ""),
                                          n.get("id", ""), defs, page_derived)
                node_rows.append({"id": n.get("id", ""), "role": n.get("role", ""),
                                  "count": len(got), "note": ""})
            except Exception as e:  # FlowAbort 等：拦住的原因就是它
                node_rows.append({"id": n.get("id", ""), "role": n.get("role", ""),
                                  "count": 0, "note": str(e)})
        problems = flowmod._preflight(nodes, platform, user, defs, page_derived)
        out.append({"name": name, "ok": not problems,
                    "detail": "；".join(problems), "nodes": node_rows})
    return out


def permission_view(user_name: str = "") -> dict:
    """组装权限视图页的数据。

    `user_name` 为空 = 平台默认身份（无鉴权模式的口径，全通）。
    """
    from fde_platform import agent_surface, agentscope_bridge as bridge

    if user_name:
        target = users.get_user_by_name(user_name)
        if target is None:
            user_name = ""            # 名字失效就回落到平台默认身份
    target = users.get_user_by_name(user_name) if user_name else None

    defs = bridge.tool_schemas(platform, target)
    keep = [t for t in defs if t["_meta"]["app"] != "__platform__"]

    rows, marked = [], 0
    for row in agent_surface.app_surface(keep, target):
        usable = row["usable"]
        if not usable:
            marked += 1
            status = "none"
        elif len(usable) < len(row["all"]):
            status = "partial"
        else:
            status = "full"
        rows.append({
            "app": row["app"],
            "status": status,
            "usable": [{"name": s,
                        "source": agent_surface.grant_source(target, row["app"], s)}
                       for s in usable],
            "total": len(row["all"]),
            "hidden": [s for s in row["all"] if s not in set(usable)],
        })

    all_users = users.list_users() if hasattr(users, "list_users") else []
    return {
        "users": all_users,
        "current": user_name,
        "target": target,
        "rows": rows,
        "summary": {"groups": len(rows), "marked": marked,
                    "tools": sum(len(r["usable"]) for r in rows)},
        "flows": _flow_preview(target),
    }


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


@bp.route("/agent-admin/permission")
def permission_page():
    """权限视图：选一个用户，看他的数字员工实际能调什么（只读，admin 可见）。"""
    if not _is_admin(_current_user()):
        return redirect("/")
    return render_template(
        "agent_perm.html",
        active=resolved_backend(),
        **permission_view((request.args.get("user") or "").strip()),
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
