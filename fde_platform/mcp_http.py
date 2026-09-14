"""FDE v2 平台 — 远端 MCP 传输层（Streamable HTTP，可插拔）。

把 `mcp_server.McpServer` 的协议逻辑挂到主进程 Flask 上的 **单端点 `/mcp`**，
让远端 AI 客户端（Claude Desktop / Cursor / WorkBuddy / mcp-remote 等，一视同仁）
经 HTTPS 接入平台全部应用服务。

    客户端 ──HTTPS──► nginx ──► Flask :4000  POST /mcp
                                    │  Authorization: Bearer fde_mcp_xxx
                                    │        ↓ users.verify_mcp_token
                                    ▼  handle_as(msg, user)   ← 与 stdio 共用分发
                               web.platform（主进程已加载，不再建第二个实例）

**为什么放 Flask 进程而不另起服务**：那进程已经加载好 platform 并持有内存缓存，
再起一个就多一份全平台实例 + 一份内存。

**为什么身份按请求注入而不是进程绑定**：HTTP 服务多线程（waitress threads=N），
一个进程要同时服务多个用户；身份沿调用链显式传递（见 mcp_server.handle_as）。

协议要点（Streamable HTTP，MCP 2025-03-26）：
- 只接受 `POST /mcp`；`Accept` 须同时含 `application/json` 与 `text/event-stream`，否则 406
- `initialize` 响应带 `Mcp-Session-Id`；同会话后续请求可带上（我们记录但不强制）
- 无 `id` 的 JSON-RPC 通知 → `202 Accepted` 无 body
- 缺/错令牌 → `401` + `WWW-Authenticate: Bearer`
- `GET /mcp`（服务端主动推送）我们不做 → **405**（规范要求如此声明，不能 404）
- `DELETE /mcp` → 结束会话，204
- 工具是同步返回完整结果 → 回 `application/json`，不必开 SSE 流

**不做**旧的 HTTP+SSE 传输（`GET /sse` + `POST /messages` 那套有状态模型）：
streamable-http 是当前标准、单端点、更简单。真有客户端只认旧传输时再补。

可插拔：删除本文件 + auth.py 的 `/mcp` 放行 + main.py 的注册块即回落无远端 MCP
（stdio 的 `python -m fde_platform.mcp_server` 不受影响）。
"""
import json
import logging
import secrets
import threading
import time

from flask import Blueprint, Response, jsonify, request

_logger = logging.getLogger(__name__)

# Streamable HTTP 要求客户端声明同时能收 JSON 与 SSE（我们只回 JSON，但仍按规范校验）
REQUIRED_ACCEPT = ("application/json", "text/event-stream")
SESSION_HEADER = "Mcp-Session-Id"
# 会话记录上限（内存里只留最近若干条，防长时间运行无限增长）
_MAX_SESSIONS = 4096

_sessions = {}           # session_id -> {"user_id": int, "username": str, "ts": float}
_lock = threading.Lock()

bp = Blueprint("mcp_http", __name__)


# ── 响应helpers ─────────────────────────────────────────


def _unauthorized(reason: str = "缺少或无效的访问令牌") -> Response:
    """401 + WWW-Authenticate（规范要求客户本能据此发起认证）。"""
    resp = jsonify({
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32001, "message": reason},
    })
    resp.status_code = 401
    resp.headers["WWW-Authenticate"] = 'Bearer realm="fde-v2"'
    return resp


def _json_ok(payload, session_id: str = None, status: int = 200) -> Response:
    resp = jsonify(payload)
    resp.status_code = status
    if session_id:
        resp.headers[SESSION_HEADER] = session_id
    return resp


def _new_session(user: dict) -> str:
    sid = secrets.token_urlsafe(24)
    now = time.time()
    with _lock:
        if len(_sessions) >= _MAX_SESSIONS:  # 淘汰最老的（内存有界）
            for k in sorted(_sessions, key=lambda k: _sessions[k]["ts"])[: _MAX_SESSIONS // 4]:
                _sessions.pop(k, None)
        _sessions[sid] = {"user_id": user["id"], "username": user["username"], "ts": now}
    return sid


def _session_owner(sid: str):
    with _lock:
        s = _sessions.get(sid)
        if s:
            s["ts"] = time.time()      # 活跃即续期
        return s


# ── 端点 ────────────────────────────────────────────────


@bp.route("/mcp", methods=["POST"], strict_slashes=False)
def mcp_post():
    """MCP 请求入口。身份 = Bearer 令牌，其余全交给 McpServer.handle_as。"""
    from fde_platform import users

    # ① 令牌（缺/错一律 401 + WWW-Authenticate）
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return _unauthorized("缺少 Authorization: Bearer <令牌>")
    user = users.verify_mcp_token(auth[7:].strip())
    if not user:
        return _unauthorized("令牌无效或已被吊销")

    # ② Accept 头（规范硬性要求；不满足 406 而不是静默降级）
    accept = request.headers.get("Accept", "")
    if not all(m in accept for m in REQUIRED_ACCEPT):
        return _json_ok(
            {"jsonrpc": "2.0", "id": None,
             "error": {"code": -32600,
                       "message": "Accept 头须同时包含 application/json 与 text/event-stream"}},
            status=406,
        )

    # ③ 会话（客户端带了就校验归属：同一 session 不能被别的令牌接管）
    sid_in = request.headers.get(SESSION_HEADER)
    if sid_in:
        owner = _session_owner(sid_in)
        if owner and owner["user_id"] != user["id"]:
            return _unauthorized("会话不属于当前令牌")

    # ④ 解析 JSON（支持单条与批量数组）
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        return _json_ok(
            {"jsonrpc": "2.0", "id": None,
             "error": {"code": -32700, "message": "Parse error"}},
            status=400,
        )

    server = _get_server()
    batch = isinstance(body, list)
    msgs = body if batch else [body]

    out, saw_initialize = [], False
    for m in msgs:
        if not isinstance(m, dict):
            out.append({"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        if m.get("method") == "initialize":
            saw_initialize = True
        try:
            resp = server.handle_as(m, user)
        except Exception as e:      # 单条炸掉不能带走整批
            _logger.exception("[mcp] 处理请求失败 method=%s", m.get("method"))
            resp = {"jsonrpc": "2.0", "id": m.get("id"),
                    "error": {"code": -32603, "message": f"Internal error: {type(e).__name__}"}}
        if resp is not None:
            out.append(resp)

    # 全是通知 → 202 无 body（规范要求）
    if not out:
        return Response(status=202)

    # initialize 成功 → 建会话并回 Mcp-Session-Id
    sid = None
    if saw_initialize and not sid_in:
        sid = _new_session(user)

    payload = out if batch else out[0]
    return _json_ok(payload, session_id=sid)


@bp.route("/mcp", methods=["GET"], strict_slashes=False)
def mcp_get():
    """服务端主动推送（SSE）我们不做——但必须 405 + Allow（规范要求，不能 404）。"""
    resp = jsonify({"error": "本服务不支持服务端推送（SSE）；请用 POST /mcp"})
    resp.status_code = 405
    resp.headers["Allow"] = "POST, DELETE"
    return resp


@bp.route("/mcp", methods=["DELETE"], strict_slashes=False)
def mcp_delete():
    """结束会话（可选；客户端通常直接关闭）。"""
    sid = request.headers.get(SESSION_HEADER)
    if sid:
        with _lock:
            _sessions.pop(sid, None)
    return Response(status=204)


# ── 装配 ────────────────────────────────────────────────

_server = None
_server_lock = threading.Lock()


def _get_server():
    """惰性建**唯一**一个 McpServer，复用主进程已加载的 platform（首次调用时构建）。

    惰性而非 register() 时构建：register 发生在 main.py 里、web.platform 刚就绪，
    但若有人只 import 不请求，就不必付 tool 清单构建的代价。
    """
    global _server
    if _server is None:
        with _server_lock:
            if _server is None:
                from fde_platform.mcp_server import McpServer
                from fde_platform.web import platform

                _server = McpServer(platform=platform)
                _logger.info("[mcp] HTTP 传输就绪：%d 个工具，端点 POST /mcp", len(_server._tools))
    return _server


def register(app):
    """挂载 /mcp（main.py 以 try-import 方式启用）。"""
    app.register_blueprint(bp)
    # 预热：启动即把工具清单算好，避免第一个客户端握手时等一次全量构建
    try:
        _get_server()
    except Exception:
        _logger.exception("[mcp] 预热失败（首个请求时会重试）")
    return bp
