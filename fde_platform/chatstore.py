"""平台 Agent 对话历史存储（SQLite · config/chat_history.db）。

持久化平台级与应用级 Agent 的多轮对话（user/assistant/tool 消息，含 OpenAI
tool_calls 结构），供跨页面 / 跨「重启」原样重放续聊。

设计要点：
- `chat_session`：会话元数据。session_id 主键（Web 层统一加 “用户名:” 前缀做用户隔离），
  owner=登录用户名、scope="__platform__" 或应用名，title 首条用户消息自动截取。
- `chat_message`：消息流水（按 id 有序）。assistant 的 tool_calls 存 JSON；
  tool 结果存 tool_call_id 以便重放时与 OpenAI 协议对齐。
- **不存 system 提示词**：续聊时由 AgentSession 按当前身份/授权动态组装
  （授权变更即时生效，历史不夹带过期权限视图）。
- 载入时自动修剪「悬挂的 tool_calls」（上轮工具调用中途服务中断的残尾），
  避免重放给 LLM 时协议报错。
"""
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.environ.get("CHAT_DB", str(Path("config") / "chat_history.db")))


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_session (
            session_id TEXT PRIMARY KEY,
            owner      TEXT NOT NULL,
            scope      TEXT NOT NULL,
            title      TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_chat_sess_owner
        ON chat_session(owner, scope, updated_at)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_message (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT NOT NULL,
            role            TEXT NOT NULL,
            content         TEXT NOT NULL DEFAULT '',
            tool_calls_json TEXT NOT NULL DEFAULT '',
            tool_call_id    TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_chat_msg_sess
        ON chat_message(session_id, id)
    """)
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_schema():
    """幂等建库建表（web 导入时调用一次）。"""
    _conn().close()


# ── 会话 ────────────────────────────────────────────────

def create_session(session_id: str, owner: str, scope: str, title: str = "") -> dict:
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO chat_session "
            "(session_id, owner, scope, title, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (session_id, owner, scope, title, _now(), _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return get_session(session_id)


def get_session(session_id: str):
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM chat_session WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_sessions(owner: str, scope: str) -> list:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM chat_session WHERE owner = ? AND scope = ? "
            "ORDER BY updated_at DESC, created_at DESC, session_id",
            (owner, scope),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def set_title(session_id: str, title: str):
    conn = _conn()
    try:
        conn.execute("UPDATE chat_session SET title = ? WHERE session_id = ?",
                     (title, session_id))
        conn.commit()
    finally:
        conn.close()


def delete_session(session_id: str):
    """删除会话及其全部消息。"""
    conn = _conn()
    try:
        conn.execute("DELETE FROM chat_message WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM chat_session WHERE session_id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()


def clear_messages(session_id: str):
    """清空会话消息（保留会话本身；用于 reset）。"""
    conn = _conn()
    try:
        conn.execute("DELETE FROM chat_message WHERE session_id = ?", (session_id,))
        conn.execute("UPDATE chat_session SET title = '', updated_at = ? WHERE session_id = ?",
                     (_now(), session_id))
        conn.commit()
    finally:
        conn.close()


# ── 消息 ────────────────────────────────────────────────

def append_message(session_id: str, role: str, content: str = "",
                   tool_calls: list = None, tool_call_id: str = ""):
    """追加一条消息并刷新会话 updated_at。"""
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO chat_message (session_id, role, content, tool_calls_json, "
            "tool_call_id, created_at) VALUES (?,?,?,?,?,?)",
            (session_id, role, content or "",
             json.dumps(tool_calls, ensure_ascii=False) if tool_calls else "",
             tool_call_id or "", _now()),
        )
        conn.execute("UPDATE chat_session SET updated_at = ? WHERE session_id = ?",
                     (_now(), session_id))
        conn.commit()
    finally:
        conn.close()


def load_messages(session_id: str) -> list:
    """按序读出会话消息（OpenAI 对话格式），并修剪悬挂的 tool_calls 残尾。"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT role, content, tool_calls_json, tool_call_id FROM chat_message "
            "WHERE session_id = ? ORDER BY id", (session_id,),
        ).fetchall()
    finally:
        conn.close()
    msgs = []
    for r in rows:
        m = {"role": r["role"], "content": r["content"]}
        if r["role"] == "assistant" and r["tool_calls_json"]:
            m["tool_calls"] = json.loads(r["tool_calls_json"])
        if r["role"] == "tool" and r["tool_call_id"]:
            m["tool_call_id"] = r["tool_call_id"]
        msgs.append(m)
    # 修剪残尾：末条是「带 tool_calls 的 assistant」却没有后续 tool 响应
    # （上轮调用中途服务中断所致）→ 重放给 LLM 会协议报错，直接丢弃该残轮
    while msgs and msgs[-1]["role"] == "assistant" and msgs[-1].get("tool_calls"):
        msgs.pop()
    return msgs
