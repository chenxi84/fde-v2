"""数字员工的**权限面**：按调用者的有效授权，算出每个应用组留哪些服务。

单独成模块，是为了让两个消费方都能**便宜地** import：

- `agent_service`（装配真实工具面，跑在 :4100 进程）
- `agent_admin`（`/agent-admin/permission` 展示页，跑在 :4000 的 Flask 进程）

后者若直接 import `agent_service`，会把 AgentScope、第二个 `FdePlatform`、第二个
`AsyncSQLAlchemyStorage` 全拉进 Flask 进程——一个只读页面不该付这个代价。

**口径只有这一份实现**：工具面装配与展示页各写一份，对不上时两边都以为自己对，
而"两处口径对不上"正是这套东西最初出问题的形态（见 `_split_by_app` 的说明）。

判据本身在 `users.effective_service_names` / `is_effectively_granted`——
本模块只负责"按应用分组、按授权收窄"这一层。
"""
from __future__ import annotations

from fde_platform import builtin_tools, users


def split_by_app(defs: list) -> dict[str, list]:
    """把工具定义按 `_meta.app` 分组，跳过平台工具。**分组口径的唯一实现**。

    工厂、权限视图页与回归测试都调这个函数——各写一份迟早对不上，
    而「对不上」正是这次事故的形态（工厂少发工具，测试却以为一切正常）。
    """
    by_app: dict[str, list] = {}
    for t in defs:
        app = t["_meta"]["app"]
        if app == "__platform__":
            continue
        by_app.setdefault(app, []).append(t)
    return by_app


def app_surface(keep: list, user, page_derived=None) -> list[dict]:
    """逐个应用算出「全部服务」与「这个用户真能调的」。

    返回 `[{app, all, usable, fts}]`（按应用名排序），是装配与展示的共同上游。

    - `user is None` / admin → `usable == all`（豁免口径见 `users.effective_service_names`）
    - 内置文件工具走**应用级** `has_app_access`（与 `bridge.execute` 同口径），
      不参与服务级授权判定——它们的可见性已在 `tool_schemas` 里定过
    - `page_derived` 由调用方算一次传进来，避免逐个服务判时退化成 N 次查询
    """
    if page_derived is None and user is not None and not user.get("is_admin"):
        page_derived = users.page_derived_services(user["id"])

    out: list[dict] = []
    for app, fts in sorted(split_by_app(keep).items()):
        all_svcs = sorted({t["_meta"].get("service", "") for t in fts})
        business = [s for s in all_svcs if not builtin_tools.is_builtin_service(s)]
        usable = set(users.effective_service_names(user, app, business, page_derived))
        if user is None or user.get("is_admin") \
                or users.has_app_access(user["id"], app):
            usable |= {s for s in all_svcs if builtin_tools.is_builtin_service(s)}
        out.append({"app": app, "all": all_svcs, "usable": sorted(usable), "fts": fts})
    return out


def grant_source(user, app: str, service: str) -> str:
    """某条服务授权的**来源**（展示用）：admin / 授权 / 页面。

    只区分三层，正好对应口径的三项：admin 豁免、显式∪角色、页面派生。
    显式与角色在 `users.is_service_granted` 里是合并判定的，这里不再拆——
    展示页只需要回答"是勾出来的，还是页面带来的"。
    """
    if user is None or user.get("is_admin"):
        return "admin"
    if users.is_service_granted(user["id"], app, service):
        return "授权"
    return "页面"
