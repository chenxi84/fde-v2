"""Agent 会话状态持久化（AgentScope 原生 state，取代 chatstore 的 message 存储）。

会话元数据（owner/scope/title）+ AgentScope 的 ``AgentState``（含 context 对话记忆）
各一张表，按 session_id 跨进程恢复。前端历史展示从 ``AgentState.context`` 派生
（见 agent_agentscope.context_to_messages）。

设计要点：
- **不 import AgentScope**：本模块只存/取 ``state_dict``（``AgentState.model_dump()``
  的原始 dict），``model_validate`` 重建由 agent_agentscope 负责——保持本模块可独立运行。
- 与 chatstore 的会话元数据 API 同形状（create/get/list/set_title/delete），web.py 与
  agent_common 可近乎无缝切换。
- 会话隔离沿用 web 层的 ``用户名:session_id`` 前缀（owner 列归属校验不变）。

可插拔：删除本模块即回落「无会话持久化」，Agent 照常工作（仅丢失跨重启记忆）。
"""
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.environ.get("AGENT_STATE_DB", str(Path("config") / "agent_state.db")))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_session (
    session_id TEXT PRIMARY KEY,
    owner      TEXT NOT NULL,
    scope      TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_sess_owner
    ON agent_session(owner, scope, updated_at);
CREATE TABLE IF NOT EXISTS agent_state (
    session_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA)
    return conn


def init_schema() -> None:
    _conn().close()


# ── 会话元数据（与 chatstore 同 API 形状）─────────────────

def create_session(session_id: str, owner: str, scope: str, title: str = "") -> dict:
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO agent_session "
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
            "SELECT * FROM agent_session WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_sessions(owner: str, scope: str) -> list:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM agent_session WHERE owner = ? AND scope = ? "
            "ORDER BY updated_at DESC, created_at DESC, session_id",
            (owner, scope),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def set_title(session_id: str, title: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            "UPDATE agent_session SET title = ?, updated_at = ? WHERE session_id = ?",
            (title, _now(), session_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_session(session_id: str) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM agent_state WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM agent_session WHERE session_id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()


def clear_state(session_id: str) -> None:
    """清空会话的对话记忆（保留会话本身；用于 reset）。"""
    conn = _conn()
    try:
        conn.execute("DELETE FROM agent_state WHERE session_id = ?", (session_id,))
        conn.execute("UPDATE agent_session SET title = '', updated_at = ? WHERE session_id = ?",
                     (_now(), session_id))
        conn.commit()
    finally:
        conn.close()


# ── AgentState 持久化（存原始 dict，不 import AgentScope）───

def save_state(session_id: str, state_dict: dict) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO agent_state (session_id, state_json, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET state_json=excluded.state_json, "
            "updated_at=excluded.updated_at",
            (session_id, json.dumps(state_dict, ensure_ascii=False), _now()),
        )
        conn.execute("UPDATE agent_session SET updated_at = ? WHERE session_id = ?",
                     (_now(), session_id))
        conn.commit()
    finally:
        conn.close()


def load_state(session_id: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT state_json FROM agent_state WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["state_json"])
        except (ValueError, TypeError):
            return None
    finally:
        conn.close()
