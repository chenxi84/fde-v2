"""远端 MCP 端点（Streamable HTTP）端到端验收。

前置：**dev server 已在跑**（`python main.py`，默认 http://127.0.0.1:4000）。
用 `FDE_BASE=http://host:port python scripts/verify_mcp_http.py` 指向别处。

验的是「传输 + 鉴权 + 授权」三件事，不是 MCP 协议语义本身（那部分与 stdio 共用，
`scripts/verify_agent_tools.py` 已覆盖）：

  ① 无令牌 / 错令牌 / 已吊销令牌 → 401 + WWW-Authenticate（fail-closed）
  ② Accept 头不合规 → 406（规范硬性要求）
  ③ 握手 → 200 + serverInfo + Mcp-Session-Id，协议版本回客户端请求的那个
  ④ 通知（无 id）→ 202 无 body；GET /mcp → 405 + Allow（不能 404）
  ⑤ 会话不能跨令牌接管
  ⑥ **授权真生效**：admin 令牌 = 全量；planner01 令牌 = 其**有效授权**集合，
     且与 `/agent-admin/permission?user=planner01` 页（同一个 permission_view）
     的可调集合**逐条一致**；越权 tools/call → isError 的「无权调用」
  ⑦ 工具真调得动（只读服务返回真实数据）
  ⑧ 吊销后同一令牌立刻 401

自建自毁：令牌用完即吊销，不留残留。退出码 0 全绿 / 1 有失败。
"""
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests  # noqa: E402

# 输出编码：控制台代码页在本机默认是 GBK，而本脚本的结论里有 ✓/✗/⚠/⇒ 这类**非 GBK 码位** ——
# 不钉住的话 print 自己会抛 UnicodeEncodeError（**崩在打印结论那一步**），
# 而外层门禁把它显示成「该检查 FAIL」——像判据报了缺陷，其实判据根本没跑完。
# 由 scripts/verify_test_script_encoding.py 守住别忘这一行（它的扫描范围已含 scripts/）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.environ.get("FDE_BASE", "http://127.0.0.1:4000").rstrip("/")
MCP = f"{BASE}/mcp"
JSON_H = {"Content-Type": "application/json"}
ACCEPT_OK = {"Accept": "application/json, text/event-stream"}

_passed, _failed = 0, 0


def check(label, ok, detail=""):
    global _passed, _failed
    if ok:
        _passed += 1
        print(f"  ✓ {label}" + (f"  [{detail}]" if detail else ""))
    else:
        _failed += 1
        print(f"  ✗ {label}  → {detail}")


def rpc(token, method, params=None, msg_id=1, accept=True, session=None, extra=None):
    """发一条 JSON-RPC 请求，返回 (status, json_or_None, response)。"""
    h = dict(JSON_H)
    if accept:
        h.update(ACCEPT_OK)
    if token:
        h["Authorization"] = f"Bearer {token}"
    if session:
        h["Mcp-Session-Id"] = session
    if extra:
        h.update(extra)
    body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    r = requests.post(MCP, headers=h, data=json.dumps(body), timeout=180)
    try:
        return r.status_code, r.json(), r
    except ValueError:
        return r.status_code, None, r


def tool_names(token, session=None):
    st, js, _ = rpc(token, "tools/list", session=session)
    assert st == 200, f"tools/list HTTP {st}"
    return {t["name"] for t in js["result"]["tools"]}


def main():
    from fde_platform import users
    from fde_platform.agent_admin import permission_view
    from fde_platform.mcp_server import McpServer

    # 工具名是 `组__应用__服务`（runtime.all_mcp_tools），应用名和组名都可能带下划线
    # （psc__demand_pool__list），**拆名字不可靠**——取权威映射：_meta 里的 qualname。
    name2key = {t["name"]: (t["_meta"]["app"], t["_meta"]["service"])
                for t in McpServer()._tools}

    admin = users.get_user_by_name("admin")
    planner = users.get_user_by_name("planner01")
    if not planner:
        print("！缺少测试用户 planner01，无法验证「授权收窄」")
        return 2

    admin_tok, _ = users.create_mcp_token(admin["id"], "verify_mcp_http:admin")
    plan_tok, _ = users.create_mcp_token(planner["id"], "verify_mcp_http:planner01")
    try:
        print("\n① 鉴权 fail-closed")
        st, _, r = rpc(None, "initialize", {"protocolVersion": "2025-03-26"})
        check("无令牌 → 401 + WWW-Authenticate: Bearer",
              st == 401 and "Bearer" in (r.headers.get("WWW-Authenticate") or ""),
              f"HTTP {st}, {r.headers.get('WWW-Authenticate')}")
        st, _, _ = rpc("fde_mcp_" + "0" * 64, "initialize", {})
        check("错令牌 → 401", st == 401, f"HTTP {st}")

        print("\n② Accept 头（规范硬性要求）")
        st, _, _ = rpc(admin_tok, "initialize", {"protocolVersion": "2025-03-26"}, accept=False)
        check("缺 text/event-stream → 406", st == 406, f"HTTP {st}")

        print("\n③ 握手")
        st, js, r = rpc(admin_tok, "initialize", {"protocolVersion": "2025-03-26"})
        sid = r.headers.get("Mcp-Session-Id")
        check("200 + serverInfo", st == 200 and js["result"]["serverInfo"]["name"] == "fde-v2-platform",
              f"HTTP {st}")
        check("回 Mcp-Session-Id", bool(sid), sid)
        check("协议版本回客户端请求的那个",
              js["result"]["protocolVersion"] == "2025-03-26",
              js["result"]["protocolVersion"])
        st, js, _ = rpc(admin_tok, "initialize", {"protocolVersion": "2024-11-05"})
        check("老客户端请求 2024-11-05 也照回",
              js["result"]["protocolVersion"] == "2024-11-05", js["result"]["protocolVersion"])
        # 关键：新客户端报的版本我们**照回**，不能顶回老版本号（客户端会直接断开）
        for v in ("2025-06-18", "2025-11-25"):
            st, js, _ = rpc(admin_tok, "initialize", {"protocolVersion": v})
            check(f"新版本 {v} 照回（不顶回老版本）",
                  js["result"]["protocolVersion"] == v, js["result"]["protocolVersion"])

        print("\n④ 通知 / 不支持的方法")
        r = requests.post(MCP, headers={**JSON_H, **ACCEPT_OK,
                                        "Authorization": f"Bearer {admin_tok}"},
                          data=json.dumps({"jsonrpc": "2.0",
                                           "method": "notifications/initialized"}),
                          timeout=60)
        check("通知（无 id）→ 202 无 body", r.status_code == 202 and not r.content,
              f"HTTP {r.status_code}, body={r.content[:40]!r}")
        r = requests.get(MCP, headers={"Authorization": f"Bearer {admin_tok}"}, timeout=60)
        check("GET /mcp → 405 + Allow（不是 404）",
              r.status_code == 405 and "POST" in (r.headers.get("Allow") or ""),
              f"HTTP {r.status_code}, Allow={r.headers.get('Allow')}")

        print("\n⑤ 会话隔离")
        st, _, _ = rpc(plan_tok, "tools/list", session=sid)
        check("planner 令牌拿 admin 的 session → 401", st == 401, f"HTTP {st}")

        print("\n⑥ 授权真生效")
        admin_tools = tool_names(admin_tok)
        plan_tools = tool_names(plan_tok)
        biz = lambda ns: {n for n in ns if not n.startswith("_platform__")}  # noqa: E731
        check("admin 令牌拿到全量工具", len(biz(admin_tools)) > 0, f"{len(biz(admin_tools))} 个业务工具")
        check("planner01 令牌 < 全量（确实被收窄）",
              len(biz(plan_tools)) < len(biz(admin_tools)),
              f"planner {len(biz(plan_tools))} vs admin {len(biz(admin_tools))}")

        # 与权限视图页同源比对（permission_view 就是 /agent-admin/permission 渲染用的那份数据）
        pv = permission_view("planner01")
        page_apps = {r["app"] for r in pv["rows"]}
        page_set = {(r["app"], s["name"]) for r in pv["rows"] for s in r["usable"]}
        mcp_set = {name2key[n] for n in biz(plan_tools) if n in name2key}
        check("MCP 工具面 == /agent-admin/permission 页可调集合",
              mcp_set == page_set,
              f"仅 MCP 有 {sorted(mcp_set - page_set)[:3]}；仅页面有 {sorted(page_set - mcp_set)[:3]}")
        check("（附带）页面覆盖的组数与可用服务数",
              len(page_apps) > 0 and len(page_set) > 0,
              f"{len(page_apps)} 组 / {len(page_set)} 服务")

        # 越权调用：挑一个 planner01 没有的业务工具
        forbidden = sorted(biz(admin_tools) - biz(plan_tools))
        if forbidden:
            st, js, _ = rpc(plan_tok, "tools/call", {"name": forbidden[0], "arguments": {}})
            txt = json.dumps(js, ensure_ascii=False)
            check(f"planner01 越权调 {forbidden[0]} → isError「无权」",
                  js["result"].get("isError") and "无权" in txt, txt[:120])
        else:
            check("planner01 越权调用（无可选越权工具——权限面全同，跳过）", True)

        print("\n⑦ 工具真调得动")
        read_only = next((n for n in sorted(biz(admin_tools)) if n.endswith("__list")), None)
        if read_only:
            st, js, _ = rpc(admin_tok, "tools/call", {"name": read_only, "arguments": {}})
            ok = not js["result"].get("isError")
            check(f"admin 调 {read_only} 返回数据", ok, json.dumps(js, ensure_ascii=False)[:120])
        else:
            check("只读服务 tools/call（未找到 __list 工具，跳过）", True)

        print("\n⑧ 吊销即失效")
        toks = users.list_mcp_tokens(planner["id"])
        mine = next(t for t in toks if t["name"] == "verify_mcp_http:planner01")
        users.revoke_mcp_token(planner["id"], mine["id"])
        st, _, _ = rpc(plan_tok, "tools/list")
        check("吊销后同一令牌 → 401", st == 401, f"HTTP {st}")

    finally:
        for u, nm in ((admin, "verify_mcp_http:admin"), (planner, "verify_mcp_http:planner01")):
            for t in users.list_mcp_tokens(u["id"]):
                if t["name"] == nm:
                    users.revoke_mcp_token(u["id"], t["id"])
        left = users.list_mcp_tokens(admin["id"]) + users.list_mcp_tokens(planner["id"])
        print(f"\n清理：残留测试令牌 {len(left)} 枚（应为 0）")

    print(f"\n{'=' * 46}\n通过 {_passed} 项，失败 {_failed} 项\n{'=' * 46}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
