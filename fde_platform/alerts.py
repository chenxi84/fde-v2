"""Agent 主动上报告警（平台级通用告警池，与 /api/alerts 聚合打通）。

区别于 /api/alerts 里「平台主动聚合」的来源（库存预警 / 定时任务失败 / 集成失败），
这里存的是「Agent 巡检后主动上报」的告警（经 platform_raise_alert 工具写入）。
统一结构 {source, level, title, detail, time}，与 /api/alerts 完全一致。

存储：config/agent_alerts.db（SQLite 单表，零外部依赖，与 auth.db/skills.db 同级）。
"""
import sqlite3
from datetime import datetime
from pathlib import Path

_DB = Path(__file__).resolve().parents[1] / "config" / "agent_alerts.db"

_LEVELS = ("red", "amber")


def _conn():
    conn = sqlite3.connect(str(_DB))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agent_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'Agent 上报',
            level TEXT NOT NULL DEFAULT 'amber',
            title TEXT NOT NULL,
            detail TEXT DEFAULT '',
            time TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    return conn


def raise_alert(source: str, level: str, title: str, detail: str = "",
                time: str = "") -> dict:
    """写入一条 agent 上报的告警。level 非法时归一为 amber。"""
    if not title:
        return {"error": "告警标题不能为空"}
    if level not in _LEVELS:
        level = "amber"
    time = time or datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO agent_alerts (source, level, title, detail, time) "
            "VALUES (?,?,?,?,?)",
            (source or "Agent 上报", level, title, detail or "", time),
        )
        conn.commit()
        return {"id": cur.lastrowid, "message": "告警已上报"}
    finally:
        conn.close()


def list_agent_alerts(limit: int = 100) -> list[dict]:
    """读最近 N 条 agent 上报的告警（与 /api/alerts 统一结构 {source,level,title,detail,time}）。"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT source, level, title, detail, time FROM agent_alerts "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
