"""FDE v2 — 移动端入口 `/m/`：登录后只显示数字员工对话。

**为什么单独一个入口而不是把 PC 端做成响应式**：PC 端是一套完整的壳（菜单 + 表格 +
图表 + Agent 右栏），把壳做成响应式的代价远大于另起一个页面；而"手机上其实只需要
和数字员工说句话"这件事，本来就该有自己的入口。两者共用同一个 `agentRail` 组件与
同一套 `/api/agent2/*` 接口，不存在第二份对话实现。

**鉴权零改动**：`/m/` 不在 `auth.OPEN_PATHS` 里，`auth.gate()` 的第②段自动拦未登录，
并带到 `/login?next=/m/`；`_safe_next` 接受任意站内路径，登录成功后原样跳回来。
`/m/` 也不带 `app_name` 这个 view_arg，所以 gate ④（应用级授权）不适用——
**不需要给 `/m/` 配任何应用授权**，能登录就能用，看到什么由智能体继承的权限决定。

可插拔：删除本模块 + `main.py` 里那段注册，即无移动入口，其余照常工作。
"""
from flask import Blueprint, render_template

from fde_platform import users

bp = Blueprint("mobile", __name__)


@bp.route("/m/")
def mobile_page():
    """移动端对话页。

    不带任何业务数据进模板：对话内容由前端经 `/api/agent2/*` 拿，
    模板只负责把 `agentRail` 组件挂起来。
    """
    return render_template("mobile.html", user=users.session_user())


def register(app) -> None:
    app.register_blueprint(bp)
