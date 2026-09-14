"""FDE v2 MCP 服务 —— 把全部应用的公共服务封装为 MCP tools（需求 1.3）。

**协议逻辑与传输层分离**：本模块只管 JSON-RPC 分发（MCP 语义），两种传输共用它——
- **stdio**（本文件的 `main()`）：客户端把服务当子进程拉起，身份启动时用 `--user` 绑定
- **Streamable HTTP**（`fde_platform/mcp_http.py`）：单端点 `/mcp` + Bearer 令牌，
  身份**按请求**注入（`handle_as`），供远端客户端接入

最小实现（JSON-RPC 2.0，逐行 JSON），**零新增依赖**——只用标准库，
即可被任意 MCP 客户端（Claude Desktop / Cursor / WorkBuddy / 其他）接入。

支持的方法：
- `initialize`               握手（返回协议版本、能力、服务信息）
- `notifications/initialized` 通知（不回应）
- `ping`                     心跳
- `tools/list`               列出全部公共服务（工具名 `<应用名>__<服务名>`）
- `tools/call`               调用某工具 → 路由到 platform.call（携带调用者身份）

身份：**两种来源，一套判据**——
- stdio：`--user <用户名>`（或环境变量 `FDE_MCP_USER`）指定，启动即校验存在（fail-closed）
- HTTP：`handle_as(msg, user)` 按请求传入（令牌解析出的用户）

非 admin 受应用授权约束（tools/list 仅暴露授权应用、越权调用被拒）；
缺省则用平台默认身份（并在 stderr 告警）。

启动：`python -m fde_platform.mcp_server [--user <用户名>]`
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fde import FdeError  # noqa: E402
from fde_platform import builtin_tools, platform_mcp_tools, users  # noqa: E402
from fde_platform.runtime import FdePlatform  # noqa: E402

# MCP 用日期串做版本号：2024-11-05 → 2025-03-26（引入 Streamable HTTP）→
# 2025-06-18 → 2025-11-25 → …，每次修订都是向后兼容的增补。
KNOWN_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
# 兜底值：客户端没报版本 / 报了个不合形的串时用它（我们传输层实现所依据的那版）。
PROTOCOL_VERSION = "2025-03-26"
SERVER_INFO = {"name": "fde-v2-platform", "version": "0.1.0"}
_VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def negotiate_version(asked):
    """版本协商：**客户端报什么版本就回什么版本**（合形即可）。

    MCP 规范要求「服务端支持该版本就必须回同一个」，否则回一个自己支持的版本，
    而**客户端拿到不认识的版本会直接断开**。新修订都是增补式的，而我们只实现 tools
    能力（capabilities 里也只声明它，不声明 resources/prompts/sampling/tasks），
    这部分跨版本稳定——所以「回老版本号」只会把新客户端顶掉，没有任何好处。
    （2025-03-26 引入的 Streamable HTTP 是我们真正依赖的那条底线，仍兜底。）
    """
    return asked if isinstance(asked, str) and _VERSION_RE.match(asked) else PROTOCOL_VERSION

# 「未指定」哨兵：区分「沿用实例默认身份」与「明确要求无身份（匿名）」——
# HTTP 请求解析出的用户若为空，不能悄悄回落到启动参数里的身份。
_UNSET = object()


def _log(msg: str):
    print(msg, file=sys.stderr, flush=True)


class McpServer:
    def __init__(self, username: str = None, platform=None):
        # platform 可注入：HTTP 传输复用主进程已加载好的实例（见 mcp_http.py），
        # 避免再建第二个 FdePlatform + 重复 load_all；stdio 则自建。
        if platform is not None:
            self.platform = platform
        else:
            self.platform = FdePlatform()
            self.platform.load_all()
        users.migrate_grant_app_names(self.platform)  # 历史授权短名 → qualname（幂等）
        self._tools = self.platform.all_mcp_tools() + platform_mcp_tools.tools()
        self._by_name = {t["name"]: t for t in self._tools}

        # 身份：--user / FDE_MCP_USER 指定则绑定该用户（fail-closed）；否则平台默认身份
        self.user = None  # 用户行（含 id/role，供授权检查）
        self.ctx = None   # 注入 platform.call 的 ctx；None → 平台默认身份
        if username:
            u = users.get_user_by_name(username)
            if not u:
                _log(f"[MCP] 身份不存在：{username}（拒绝启动）")
                sys.exit(1)
            self.user = u
            self.ctx = users.ctx_for_user(u)
            _log(
                f"[MCP] 以身份 {u['username']}（{u.get('role_label') or u['role']}）运行"
            )
        else:
            _log("[MCP] 未指定身份：以平台默认身份运行（无授权约束）。可用 --user <用户名> 指定。")

    # ── 身份 ────────────────────────────────────────────────
    def handle_as(self, msg: dict, user):
        """以**指定用户**身份处理一条消息（HTTP 传输用），返回响应 dict / None。

        **不改实例状态**——身份沿调用链显式传递（见 `handle` 的 user/ctx 参数）：
        HTTP 服务是多线程的（waitress threads=N），把身份写到 self 上会被并发请求互相覆盖。
        user 为 None → 以平台默认身份处理（HTTP 下不会走到：令牌校验不过直接 401）。
        """
        ctx = users.ctx_for_user(user) if user else None
        return self.handle(msg, user=user, ctx=ctx)

    # ── JSON-RPC 分发 ───────────────────────────────────────
    def handle(self, msg: dict, user=_UNSET, ctx=_UNSET):
        """处理一条 JSON-RPC 消息；通知（无 id）返回 None。

        user/ctx 缺省（`_UNSET`）→ 用实例默认身份（stdio 启动参数绑定）；
        显式传入 → 用传入的（含显式 None ＝ 匿名）。
        """
        if user is _UNSET:
            user = self.user
        if ctx is _UNSET:
            ctx = self.ctx
        method = msg.get("method")
        msg_id = msg.get("id")

        if method == "initialize":
            asked = (msg.get("params") or {}).get("protocolVersion")
            return self._result(
                msg_id,
                {
                    "protocolVersion": negotiate_version(asked),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                },
            )
        if method == "notifications/initialized":
            return None  # 通知，不回应
        if method == "ping":
            return self._result(msg_id, {})
        if method == "tools/list":
            tools = self._tools
            # 非管理员角色按**有效授权**过滤（与 Web 闸门 / agent / bridge.execute 同口径，
            # 见 users.is_effectively_granted）：聚合服务须被授权；内置文件工具须有应用可见性
            if user and not user.get("is_admin"):
                def _allowed(t):
                    app, svc = t["_meta"]["app"], t["_meta"]["service"]
                    if builtin_tools.is_builtin_service(svc):
                        return users.has_app_access(user["id"], app)
                    return users.is_effectively_granted(user, app, svc)

                tools = [t for t in tools if _allowed(t)]
            public = [{k: v for k, v in t.items() if k != "_meta"} for t in tools]
            return self._result(msg_id, {"tools": public})
        if method == "tools/call":
            return self._call(msg_id, msg.get("params") or {}, user, ctx)
        if msg_id is not None:
            return self._error(msg_id, -32601, f"Method not found: {method}")
        return None

    # ── tools/call ──────────────────────────────────────────
    def _call(self, msg_id, params: dict, user, ctx):
        name = params.get("name")
        args = params.get("arguments") or {}
        args.pop("context", None)  # 身份只由平台注入，拒绝客户端伪造（§4.1）

        tool = self._by_name.get(name)
        if tool is None:
            return self._result(
                msg_id,
                {"content": [{"type": "text", "text": f"未知工具：{name}"}], "isError": True},
            )

        app = tool["_meta"]["app"]
        service = tool["_meta"]["service"]

        # 平台管理工具：直接路由到 handler（需 admin 身份）
        if app == "_platform":
            if user and not user.get("is_admin"):
                return self._result(
                    msg_id,
                    {"content": [{"type": "text", "text": "平台管理工具仅限管理员"}], "isError": True},
                )
            try:
                result = platform_mcp_tools.handle_tool(name, args, ctx or {}, platform=self.platform)
                text = json.dumps(result, ensure_ascii=False)
                return self._result(msg_id, {"content": [{"type": "text", "text": text}]})
            except Exception as e:
                return self._result(
                    msg_id,
                    {"content": [{"type": "text", "text": f"平台工具异常：{e}"}], "isError": True},
                )

        # 授权检查（与 Web 闸门 / agent / bridge.execute 同口径）：聚合服务按有效授权；
        # 内置文件工具须有应用可见性
        if user and not user.get("is_admin"):
            if builtin_tools.is_builtin_service(service):
                denied = not users.has_app_access(user["id"], app)
                reason = f"无权访问应用：{app}"
            else:
                denied = not users.is_effectively_granted(user, app, service)
                reason = f"无权调用服务：{app}.{service}"
            if denied:
                return self._result(
                    msg_id,
                    {"content": [{"type": "text", "text": reason}], "isError": True},
                )

        try:
            if builtin_tools.is_builtin_service(service):
                # 平台内置文件工具：操作该应用文件夹下的 resource 目录
                result = builtin_tools.call_builtin(
                    self.platform.handle(app).folder, service, args
                )
            else:
                # ctx 取本次请求的身份（stdio：启动时绑定；HTTP：令牌解析所得）；
                # None → 平台默认身份
                result = self.platform.call(app, service, ctx=ctx, **args)
            text = json.dumps(result, ensure_ascii=False)
            return self._result(msg_id, {"content": [{"type": "text", "text": text}]})
        except FdeError as e:  # 业务失败 → isError，信息可读
            return self._result(
                msg_id,
                {"content": [{"type": "text", "text": f"业务失败：{e}"}], "isError": True},
            )
        except TypeError as e:
            return self._result(
                msg_id,
                {"content": [{"type": "text", "text": f"参数错误：{e}"}], "isError": True},
            )
        except Exception as e:  # 系统异常：记全量、归一返回（§7）
            import traceback

            traceback.print_exc()
            return self._result(
                msg_id,
                {
                    "content": [
                        {"type": "text", "text": f"系统错误：{type(e).__name__}"}
                    ],
                    "isError": True,
                },
            )

    # ── JSON-RPC 组装 ───────────────────────────────────────
    @staticmethod
    def _result(msg_id, result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id, code, message):
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def main():
    parser = argparse.ArgumentParser(description="FDE v2 MCP 服务（stdio）")
    parser.add_argument(
        "--user",
        default=os.environ.get("FDE_MCP_USER") or None,
        help="以该用户身份运行（校验存在；非 admin 受应用授权约束）。"
        "也可用环境变量 FDE_MCP_USER 指定。缺省则用平台默认身份。",
    )
    args = parser.parse_args()

    try:  # Windows 控制台 UTF-8（日志走 stderr，一并设置）
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    server = McpServer(username=args.user)
    _log(f"FDE MCP 服务就绪：{len(server._tools)} 个工具（stdio）")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            continue
        resp = server.handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
