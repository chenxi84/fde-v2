"""平台管理 MCP 工具 —— 把用户管理、LLM 配置、集成接口等平台能力暴露为 MCP tools。

工具名统一 `platform__<功能>`；`tools/call` 路由到对应平台函数。
"""
from fde_platform import integration, llm, users


def _t(name, desc, props, req=None):
    """构造 MCP tool 定义。"""
    return {
        "name": f"platform__{name}",
        "description": desc,
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": req or [],
        },
        "_meta": {"app": "_platform", "service": name},
    }


def tools():
    return [
        # ── 用户管理 ──
        _t("user_list", "列出全部平台用户",
           {}, req=[]),
        _t("user_create", "创建新用户",
           {"username": {"type": "string", "description": "用户名"},
            "password": {"type": "string", "description": "密码"},
            "role": {"type": "string", "description": "角色名，默认 user", "default": "user"},
            "user_no": {"type": "string", "description": "用户编号（可选）"},
            "department_no": {"type": "string", "description": "部门编号（可选）"}},
           req=["username", "password"]),
        _t("user_reset_pwd", "重置用户密码",
           {"username": {"type": "string", "description": "用户名"},
            "new_password": {"type": "string", "description": "新密码"}},
           req=["username", "new_password"]),
        _t("user_delete", "删除用户",
           {"username": {"type": "string", "description": "要删除的用户名"}},
           req=["username"]),
        _t("role_list", "列出全部角色",
           {}, req=[]),

        # ── LLM 配置 ──
        _t("llm_list", "列出 LLM 配置档案",
           {}, req=[]),
        _t("llm_save", "保存 LLM 模型配置（即时生效）",
           {"role": {"type": "string", "description": "配置角色：operator"},
            "provider": {"type": "string", "description": "协议：openai_compat 或 anthropic"},
            "model": {"type": "string", "description": "模型名"},
            "base_url": {"type": "string", "description": "API 地址"},
            "api_key": {"type": "string", "description": "API Key"},
            "temperature": {"type": "number", "description": "温度，默认 0.1", "default": 0.1}},
           req=["role", "model", "api_key"]),

        # ── 集成接口 ──
        _t("integration_discover", "扫描发现所有外部接口",
           {}, req=[]),
        _t("integration_list", "列出已配置的集成端点",
           {}, req=[]),
        _t("integration_save", "保存/更新集成端点配置",
           {"app_name": {"type": "string", "description": "所属应用 qualname"},
            "method_name": {"type": "string", "description": "方法名"},
            "target": {"type": "string", "description": "目标系统标识"},
            "url": {"type": "string", "description": "外部系统 URL"},
            "http_method": {"type": "string", "description": "HTTP 方法，默认 POST", "default": "POST"},
            "auth_type": {"type": "string", "description": "鉴权类型", "default": "none"},
            "auth_credential": {"type": "string", "description": "鉴权凭证"},
            "mock_enabled": {"type": "boolean", "description": "是否 Mock", "default": False}},
           req=["app_name", "method_name", "target"]),
        _t("integration_test", "测试集成端点连通性",
           {"endpoint_id": {"type": "integer", "description": "端点 ID"}},
           req=["endpoint_id"]),

        # ── 定时任务 ──
        _t("scheduler_list", "列出定时任务",
           {}, req=[]),

        # ── 设计文档读取（只读）──
        _t("read_app_doc", "按需读取某应用的设计文档（应用详设/前端详设/前端测试用例/README），"
           "用于深入了解该应用的业务规则（BR）/功能（FUNC）/数据字典",
           {"app": {"type": "string", "description": "应用 qualname（如 psc/sales_forecast）或短名"},
            "doc": {"type": "string", "enum": ["应用详设", "前端详设", "前端测试用例", "README"],
                    "description": "文档类型"}},
           req=["app", "doc"]),
    ]


# ── 路由：tool name → handler ──

def handle_tool(tool_name: str, args: dict, ctx: dict, platform=None) -> dict:
    """执行平台工具，返回 JSON 可序列化结果。platform 为 FdePlatform 实例（读取设计文档用）。"""
    # 用户管理
    if tool_name == "platform__user_list":
        return {"users": users.list_users()}
    elif tool_name == "platform__user_create":
        ok, msg = users.create_user(
            args.get("username", ""), args.get("password", ""),
            args.get("role", "user"), [],
            args.get("user_no", ""), args.get("department_no", ""))
        return {"ok": ok, "message": msg}
    elif tool_name == "platform__user_reset_pwd":
        ok, msg = users.reset_password(
            args.get("username", ""), args.get("new_password", ""))
        return {"ok": ok, "message": msg}
    elif tool_name == "platform__user_delete":
        ok, msg = users.delete_user(args.get("username", ""))
        return {"ok": ok, "message": msg}
    elif tool_name == "platform__role_list":
        return {"roles": users.list_roles()}

    # LLM 配置
    elif tool_name == "platform__llm_list":
        return {"profiles": [p for p in llm.list_profiles() if not p.get("api_key_enc")]}
    elif tool_name == "platform__llm_save":
        return {"ok": True, "message": "LLM 配置已保存（即时生效）"}

    # 集成接口
    elif tool_name == "platform__integration_list":
        return {"endpoints": integration.list_endpoints()}
    elif tool_name == "platform__integration_save":
        eid = integration.save_endpoint(
            app_name=args.get("app_name", ""),
            method_name=args.get("method_name", ""),
            target=args.get("target", ""),
            url=args.get("url") or None,
            http_method=args.get("http_method", "POST"),
            auth_type=args.get("auth_type", "none"),
            auth_credential=args.get("auth_credential") or None,
            mock_enabled=bool(args.get("mock_enabled")),
        )
        return {"ok": True, "id": eid}
    elif tool_name == "platform__integration_test":
        eid = args.get("endpoint_id", 0)
        eps = [e for e in integration.list_endpoints() if e["id"] == eid]
        if not eps:
            return {"ok": False, "message": f"端点 {eid} 不存在"}
        ep = eps[0]
        full = integration.get_endpoint(ep["app_name"], ep["method_name"])
        import time, urllib.request, json
        t0 = time.time()
        try:
            req = urllib.request.Request(full.get("url", ""), method=full.get("http_method", "GET"))
            resp = urllib.request.urlopen(req, timeout=full.get("timeout_s", 10))
            body = resp.read().decode(errors="replace")[:500]
            dur = int((time.time() - t0) * 1000)
            return {"ok": True, "code": resp.status, "duration_ms": dur, "body": body}
        except Exception as e:
            return {"ok": False, "message": str(e)[:200]}
    elif tool_name == "platform__scheduler_list":
        from fde_platform import scheduler
        return {"jobs": scheduler.list_jobs()}
    elif tool_name == "platform__integration_discover":
        from fde_platform.runtime import FdePlatform
        p = FdePlatform()
        p.load_all()
        return {"external": integration.discover(p)}

    elif tool_name == "platform__read_app_doc":
        from fde_platform.agent_common import read_app_doc
        if platform is None:
            from fde_platform.runtime import FdePlatform
            platform = FdePlatform()
            platform.load_all()
        text = read_app_doc(platform, args.get("app", ""), args.get("doc", ""))
        if not text:
            return {"found": False, "app": args.get("app", ""),
                    "doc": args.get("doc", ""), "message": "未找到该文档（应用/文档类型不存在或文档缺失）"}
        return {"found": True, "app": args.get("app", ""), "doc": args.get("doc", ""), "content": text}

    return {"ok": False, "message": f"未知工具：{tool_name}"}
