"""AgentScope × FDE 桥接层（FDE 侧，AgentScope 无关）。

把 FDE 的「应用服务 + 内置文件工具」序列化成 OpenAI function-calling 工具定义
（按当前用户的服务授权过滤），并支持把「工具名 + 参数」路由回 `platform.call` 执行
（身份由平台注入、fail-closed）。AgentScope 侧只消费这两个接口，不感知 FDE 内部的
按名路由 / 授权 / ctx 细节。

用法（AgentScope 接入时）：
    tools = tool_schemas(platform, user)          # 喂进 AgentScope Toolkit
    result = execute(platform, user, name, args)  # AgentScope 调工具时回调
"""
import json

from fde import FdeError
from fde_platform import builtin_tools, introspect, users
from fde_platform.runtime import tool_prefix


def tool_schemas(platform, user=None) -> list[dict]:
    """FDE 服务 → OpenAI function-calling 工具定义（含内置文件工具），按 user 服务授权过滤。

    user=None 表示平台默认身份（无授权约束，admin / CLI / 未登录）。返回项：
        {"type":"function","function":{name,description,parameters},"_meta":{app,service}}
    _meta 仅平台内部路由用，喂给 AgentScope 前应剥掉。
    """
    defs = []
    for name in sorted(platform.app_names()):
        handle = platform.handle(name)
        prefix = tool_prefix(name)
        all_svcs = platform.services(name)
        visible = set(users.visible_service_names(name, [s["name"] for s in all_svcs]))
        for s in all_svcs:
            if s["name"] not in visible:
                continue
            t = introspect.to_mcp_tool(prefix, s, qualname=name,
                                       group=handle.group, app_name=handle.name)
            defs.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["inputSchema"],
                },
                "_meta": t["_meta"],
            })
        if user is None or user.get("is_admin") or users.has_app_access(user["id"], name):
            for t in builtin_tools.builtin_tool_defs(prefix, qualname=name,
                                                     group=handle.group, app_name=handle.name):
                defs.append({
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["inputSchema"],
                    },
                    "_meta": t["_meta"],
                })
    defs.extend(_platform_tool_defs(user))
    return defs


def _platform_tool_defs(user=None) -> list:
    """平台级工具（非应用作用域）：skill 沉淀（全员）+ 集成/定时任务配置（admin）。

    _meta.app 用哨兵 __platform__；_meta.dangerous=True 的走 HITL 确认。
    """
    defs = [
        {
            "type": "function",
            "function": {
                "name": "platform_propose_skill",
                "description": (
                    "任务完成后，把本次形成的、可复用的操作流程沉淀为一个 skill 草稿（提交人工审批）。"
                    "仅当流程通用可复用（下次同类任务可直接照做）时才调用；一次性/特异操作不要提议。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string",
                                 "description": "技能名（简洁动词短语，如「导入客户预测」）"},
                        "description": {"type": "string", "description": "技能用途说明"},
                        "trigger": {"type": "string",
                                    "description": "触发条件（自然语言，何时该用此技能）"},
                        "steps": {
                            "type": "array",
                            "description": "有序步骤；每步 tool=工具名、args=参数模板（占位符如 {{version_no}}）、note=说明",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "tool": {"type": "string"},
                                    "args": {"type": "object"},
                                    "note": {"type": "string"},
                                },
                                "required": ["tool"],
                            },
                        },
                    },
                    "required": ["name", "description", "trigger", "steps"],
                },
            },
            "_meta": {"app": "__platform__", "service": "propose_skill", "dangerous": False},
        },
        {
            "type": "function",
            "function": {
                "name": "platform_raise_alert",
                "description": (
                    "巡检/分析发现问题时，主动上报一条告警到平台通用告警池（前台「告警」页可见）。"
                    "level 取值 red(严重)/amber(警告)；title 一句话说清问题；detail 补充说明；"
                    "source 可自定义来源（默认「Agent 上报」）。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "string", "enum": ["red", "amber"],
                                 "description": "告警级别：red=严重，amber=警告"},
                        "title": {"type": "string", "description": "告警标题（一句话）"},
                        "detail": {"type": "string", "description": "告警详情（补充说明，可选）"},
                        "source": {"type": "string",
                                  "description": "告警来源标识（可选，默认「Agent 上报」）"},
                    },
                    "required": ["level", "title"],
                },
            },
            "_meta": {"app": "__platform__", "service": "raise_alert", "dangerous": False},
        },
        {
            "type": "function",
            "function": {
                "name": "platform_list_flows",
                "description": "列出全部已声明的工作流（flow，见 app/<组>/_flow_*.yaml）。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            "_meta": {"app": "__platform__", "service": "list_flows", "dangerous": False},
        },
        {
            "type": "function",
            "function": {
                "name": "platform_run_flow",
                "description": (
                    "执行一个已声明的工作流（flow）：按顺序运行多个角色节点，前一个节点的结果"
                    "作为后一个节点的输入（结果经状态键传递）。先 platform_list_flows 查看可用 flow。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "flow 名（如「产销协同链」）"},
                    },
                    "required": ["name"],
                },
            },
            "_meta": {"app": "__platform__", "service": "run_flow", "dangerous": False},
        },
        {
            "type": "function",
            "function": {
                "name": "platform_flow_progress",
                "description": "查询最近一次工作流（flow）执行的进度（跑到第几步 / 哪个角色 / 结果摘要）。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            "_meta": {"app": "__platform__", "service": "flow_progress", "dangerous": False},
        },
    ]
    if user is None or user.get("is_admin"):
        defs.extend(_admin_platform_tool_defs())
    return defs


def _admin_platform_tool_defs() -> list:
    """管理员平台工具：集成接口 + 定时任务配置。dangerous=True 走 HITL。"""
    def _t(name, desc, params, service, dangerous):
        return {
            "type": "function",
            "function": {"name": name, "description": desc, "parameters": params},
            "_meta": {"app": "__platform__", "service": service, "dangerous": dangerous},
        }

    obj = {"type": "object"}
    return [
        # ── 集成 ──
        _t("platform_list_integrations", "列出全部集成接口配置（app/service/目标/类型/状态）",
           {"type": "object", "properties": {}, "required": []}, "list_integrations", False),
        _t("platform_discover_integrations", "扫描全部应用，发现可配置的外部系统适配器（如 _http_xxx、_erp_xxx）与网关",
           {"type": "object", "properties": {}, "required": []}, "discover_integrations", False),
        _t("platform_save_integration",
           "创建/更新某应用某服务的集成接口配置（可含认证凭证，凭证加密落库）",
           {"type": "object", "properties": {
               "app_name": {"type": "string", "description": "应用 qualname（如 psc/sales_forecast）"},
               "method_name": {"type": "string", "description": "服务名（如 import_orig_qty）"},
               "target": {"type": "string", "description": "目标应用/网关（外部适配器名或网关应用）"},
               "kind": {"type": "string", "description": "external=外部适配器 / gateway=网关应用", "default": "external"},
               "url": {"type": "string", "description": "外部 HTTP 地址（kind=external 时）"},
               "auth_type": {"type": "string", "description": "none/bearer/api_key/basic"},
               "auth_credential": {"type": "string", "description": "认证凭证（加密保存）"},
               "mock_enabled": {"type": "boolean", "description": "是否启用 mock"},
           }, "required": ["app_name", "method_name", "target"]}, "save_integration", True),
        _t("platform_delete_integration", "删除某条集成接口配置",
           {"type": "object", "properties": {"endpoint_id": {"type": "integer", "description": "接口配置 id"}},
            "required": ["endpoint_id"]}, "delete_integration", True),
        _t("platform_integration_logs", "查看集成调用日志",
           {"type": "object", "properties": {
               "target": {"type": "string", "description": "按目标过滤（可选）"},
               "limit": {"type": "integer", "description": "条数", "default": 50},
           }, "required": []}, "integration_logs", False),
        _t("platform_test_integration", "对某条已配置的集成端点做连通测试（发真实请求，返回响应预览）",
           {"type": "object", "properties": {"endpoint_id": {"type": "integer", "description": "端点 id"}},
            "required": ["endpoint_id"]}, "test_integration", True),
        # ── 定时任务 ──
        _t("platform_list_jobs", "列出全部定时任务（含启用状态/上次运行结果）",
           {"type": "object", "properties": {}, "required": []}, "list_jobs", False),
        _t("platform_create_job",
           "创建定时任务：按 cron 表达式定时调用某应用某服务",
           {"type": "object", "properties": {
               "app_name": {"type": "string", "description": "应用 qualname"},
               "service": {"type": "string", "description": "服务名（必须是对外公共服务、非 _ 前缀；外部适配器如 _http_fetch_sales_history 请改用其对外包装服务，如 sync_external_history）"},
               "cron_expr": {"type": "string", "description": "cron 表达式（分 时 日 月 周）"},
               "params": {"type": "object", "description": "服务入参 JSON"},
               "run_as_user": {"type": "string", "description": "运行身份用户名（可选，默认平台身份）"},
               "description": {"type": "string"},
           }, "required": ["app_name", "service", "cron_expr"]}, "create_job", True),
        _t("platform_update_job", "更新定时任务（cron/入参/描述/启停）",
           {"type": "object", "properties": {
               "job_id": {"type": "integer"},
               "cron_expr": {"type": "string"},
               "params": {"type": "object"},
               "description": {"type": "string"},
               "enabled": {"type": "boolean"},
           }, "required": ["job_id"]}, "update_job", True),
        _t("platform_delete_job", "删除定时任务",
           {"type": "object", "properties": {"job_id": {"type": "integer"}},
            "required": ["job_id"]}, "delete_job", True),
        _t("platform_set_job_enabled", "启用/停用定时任务",
           {"type": "object", "properties": {
               "job_id": {"type": "integer"}, "enabled": {"type": "boolean"}},
            "required": ["job_id", "enabled"]}, "set_job_enabled", True),
        _t("platform_run_job_now", "立即执行一次定时任务（不等 cron）",
           {"type": "object", "properties": {"job_id": {"type": "integer"}},
            "required": ["job_id"]}, "run_job_now", True),
        # ── 用户与权限 ──
        _t("platform_list_users", "列出全部用户（含角色 / 个人与角色授权 / 有效授权数）",
           {"type": "object", "properties": {}, "required": []}, "list_users", False),
        _t("platform_create_user",
           "创建用户（指定角色 + 个人服务授权）",
           {"type": "object", "properties": {
               "username": {"type": "string", "description": "登录名"},
               "password": {"type": "string", "description": "密码（≥4 位）"},
               "role": {"type": "string", "description": "角色名（admin/user/自建角色）", "default": "user"},
               "user_no": {"type": "string", "description": "用户编号（可选）"},
               "department_no": {"type": "string", "description": "部门编号（可选）"},
               "grants": {"type": "array", "items": {"type": "string"},
                          "description": "个人服务授权，形如 'app.service'（如 psc/sales_forecast.list）"},
           }, "required": ["username", "password"]}, "create_user", True),
        _t("platform_delete_user", "删除用户",
           {"type": "object", "properties": {"username": {"type": "string"}},
            "required": ["username"]}, "delete_user", True),
        _t("platform_reset_password", "重置用户密码",
           {"type": "object", "properties": {
               "username": {"type": "string"}, "new_password": {"type": "string"}},
            "required": ["username", "new_password"]}, "reset_password", True),
        _t("platform_set_user_role", "更换用户角色",
           {"type": "object", "properties": {
               "username": {"type": "string"}, "role": {"type": "string"}},
            "required": ["username", "role"]}, "set_user_role", True),
        _t("platform_set_user_grants", "整体替换用户个人服务授权",
           {"type": "object", "properties": {
               "username": {"type": "string"},
               "grants": {"type": "array", "items": {"type": "string"},
                          "description": "服务授权列表，形如 'app.service'"}},
            "required": ["username", "grants"]}, "set_user_grants", True),
        _t("platform_list_roles", "列出全部角色（含授权数 / 绑定用户数）",
           {"type": "object", "properties": {}, "required": []}, "list_roles", False),
        _t("platform_create_role", "创建角色（可带服务授权 + 是否管理员）",
           {"type": "object", "properties": {
               "name": {"type": "string", "description": "角色名（小写蛇形）"},
               "label": {"type": "string", "description": "显示名"},
               "is_admin": {"type": "boolean", "description": "管理员角色（绕过授权检查）", "default": False},
               "grants": {"type": "array", "items": {"type": "string"},
                          "description": "角色服务授权，形如 'app.service'"},
           }, "required": ["name"]}, "create_role", True),
        _t("platform_delete_role", "删除角色（须无用户绑定）",
           {"type": "object", "properties": {"name": {"type": "string"}},
            "required": ["name"]}, "delete_role", True),
        _t("platform_set_role_grants", "整体替换角色服务授权",
           {"type": "object", "properties": {
               "name": {"type": "string"},
               "grants": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "grants"]}, "set_role_grants", True),
    ]


_INDEX_CACHE: dict = {}


def _index(platform) -> dict:
    """工具名 → (qualname app, service) 反查表（platform 加载后静态，按实例缓存）。"""
    key = id(platform)
    idx = _INDEX_CACHE.get(key)
    if idx is None:
        idx = {
            t["function"]["name"]: (t["_meta"]["app"], t["_meta"]["service"])
            for t in tool_schemas(platform, None)
        }
        _INDEX_CACHE[key] = idx
    return idx


def _call_platform_tool(platform, user, service: str, args: dict):
    """平台级工具执行分发（非应用作用域）。"""
    if service == "propose_skill":
        from fde_platform import skills

        return skills.propose(
            args.get("name", ""), args.get("description", ""), args.get("trigger", ""),
            args.get("steps", []), created_by="agent",
        )
    if service == "raise_alert":
        from fde_platform import alerts as alerts_mod

        return alerts_mod.raise_alert(
            args.get("source", "Agent 上报"), args.get("level", "amber"),
            args.get("title", ""), args.get("detail", ""),
        )
    if service == "list_flows":
        from fde_platform import flow

        return {"flows": flow.list_flows()}
    if service == "run_flow":
        from fde_platform import flow

        return flow.run_flow(args.get("name", ""), platform, user)
    if service == "flow_progress":
        from fde_platform import flow

        return flow.get_progress() or {}
    # 集成 / 定时任务配置：仅管理员（user=None 视为无鉴权全通，与平台 _is_admin_user 一致）
    if user is not None and not user.get("is_admin"):
        raise FdeError("无权调用平台配置工具（仅管理员）")
    from fde_platform import integration, scheduler

    if service == "list_integrations":
        return integration.list_endpoints()
    if service == "discover_integrations":
        return {"external": integration.discover(platform)}
    if service == "save_integration":
        return {"endpoint_id": integration.save_endpoint(
            args.get("app_name", ""), args.get("method_name", ""), args.get("target", ""),
            kind=args.get("kind", "external"), url=args.get("url"),
            auth_type=args.get("auth_type", "none"), auth_credential=args.get("auth_credential"),
            mock_enabled=bool(args.get("mock_enabled", False)),
        )}
    if service == "delete_integration":
        integration.delete_endpoint(args.get("endpoint_id"))
        return {"deleted": args.get("endpoint_id")}
    if service == "integration_logs":
        return integration.recent_logs(args.get("target"), int(args.get("limit") or 50))
    if service == "test_integration":
        return integration.test_endpoint(int(args.get("endpoint_id")))
    if service == "list_jobs":
        return scheduler.list_jobs()
    if service == "create_job":
        username = (user or {}).get("username") or "agent"
        ok, msg, job_id = scheduler.create_job(
            args.get("app_name", ""), args.get("service", ""), args.get("cron_expr", ""),
            params=args.get("params"), run_as_user=args.get("run_as_user", ""),
            description=args.get("description", ""), created_by=username,
        )
        if not ok:
            raise FdeError(msg)
        return {"job_id": job_id, "message": msg}
    if service == "update_job":
        ok, msg = scheduler.update_job(
            args.get("job_id"), args.get("cron_expr", ""), args.get("params"),
            args.get("run_as_user", ""), args.get("description", ""),
            bool(args.get("enabled", True)),
        )
        if not ok:
            raise FdeError(msg)
        return {"job_id": args.get("job_id"), "message": msg}
    if service == "delete_job":
        ok, msg = scheduler.delete_job(args.get("job_id"))
        if not ok:
            raise FdeError(msg)
        return {"job_id": args.get("job_id"), "message": msg}
    if service == "set_job_enabled":
        ok, msg = scheduler.set_enabled(args.get("job_id"), bool(args.get("enabled", True)))
        if not ok:
            raise FdeError(msg)
        return {"job_id": args.get("job_id"), "message": msg}
    if service == "run_job_now":
        return scheduler.run_job_now(args.get("job_id"))
    # 用户与权限（users 模块顶层已 import）
    if service == "list_users":
        return users.list_users()
    if service == "create_user":
        ok, msg = users.create_user(
            args.get("username", ""), args.get("password", ""), args.get("role", "user"),
            args.get("grants", []), args.get("user_no", ""), args.get("department_no", ""))
        if not ok:
            raise FdeError(msg)
        return {"username": args.get("username"), "message": msg}
    if service == "delete_user":
        ok, msg = users.delete_user(args.get("username", ""))
        if not ok:
            raise FdeError(msg)
        return {"message": msg}
    if service == "reset_password":
        ok, msg = users.reset_password(args.get("username", ""), args.get("new_password", ""))
        if not ok:
            raise FdeError(msg)
        return {"message": msg}
    if service == "set_user_role":
        ok, msg = users.set_role(args.get("username", ""), args.get("role", ""))
        if not ok:
            raise FdeError(msg)
        return {"message": msg}
    if service == "set_user_grants":
        ok, msg = users.set_service_grants(args.get("username", ""), args.get("grants", []))
        if not ok:
            raise FdeError(msg)
        return {"message": msg}
    if service == "list_roles":
        return users.list_roles()
    if service == "create_role":
        ok, msg = users.create_role(
            args.get("name", ""), args.get("label", ""),
            bool(args.get("is_admin", False)), args.get("grants"))
        if not ok:
            raise FdeError(msg)
        return {"name": args.get("name"), "message": msg}
    if service == "delete_role":
        ok, msg = users.delete_role(args.get("name", ""))
        if not ok:
            raise FdeError(msg)
        return {"message": msg}
    if service == "set_role_grants":
        ok, msg = users.set_role_grants(args.get("name", ""), args.get("grants", []))
        if not ok:
            raise FdeError(msg)
        return {"message": msg}
    raise FdeError(f"未知平台工具：{service}")


def execute(platform, user, tool_name: str, args: dict) -> str:
    """执行一次工具调用（按 user 服务授权 fail-closed），返回 JSON 文本。"""
    args = dict(args or {})
    args.pop("context", None)  # 身份只由平台注入，拒绝客户端伪造

    resolved = _index(platform).get(tool_name)
    if resolved is None:
        return json.dumps({"error": f"未知工具：{tool_name}"}, ensure_ascii=False)
    app, service = resolved

    # 平台工具（非应用作用域，如 skill 沉淀 / 集成 / 定时任务配置）
    if app == "__platform__":
        try:
            result = _call_platform_tool(platform, user, service, args)
        except FdeError as e:
            return json.dumps({"error": f"业务失败：{e}"}, ensure_ascii=False)
        except TypeError as e:
            return json.dumps({"error": f"参数错误：{e}"}, ensure_ascii=False)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return json.dumps({"error": f"系统错误：{type(e).__name__}"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    # 服务级授权校验（与 Web 闸门 / 旧 agent 一致）
    if user is not None and not user.get("is_admin"):
        if builtin_tools.is_builtin_service(service):
            if not users.has_app_access(user["id"], app):
                return json.dumps({"error": f"无权访问应用：{app}"}, ensure_ascii=False)
        elif not users.is_service_granted(user["id"], app, service):
            return json.dumps({"error": f"无权调用服务：{app}.{service}"}, ensure_ascii=False)

    try:
        if builtin_tools.is_builtin_service(service):
            result = builtin_tools.call_builtin(platform.handle(app).folder, service, args)
        else:
            ctx = users.ctx_for_user(user) if user else None
            result = platform.call(app, service, ctx=ctx, **args)
        return json.dumps(result, ensure_ascii=False)
    except FdeError as e:
        return json.dumps({"error": f"业务失败：{e}"}, ensure_ascii=False)
    except TypeError as e:
        return json.dumps({"error": f"参数错误：{e}"}, ensure_ascii=False)
    except Exception as e:  # 系统异常：记全量、对调用方归一
        import traceback
        traceback.print_exc()
        return json.dumps({"error": f"系统错误：{type(e).__name__}"}, ensure_ascii=False)
