"""Agent 主动上报告警（平台级通用告警池，与 /api/alerts 聚合打通）。

区别于 /api/alerts 里「平台主动聚合」的来源（库存预警 / 定时任务失败 / 集成失败），
这里存的是「Agent 巡检后主动上报」的告警（经 platform_raise_alert 工具写入）。
统一结构 {source, level, title, detail, time}，与 /api/alerts 完全一致。

存储：config/agent_alerts.db（SQLite 单表，零外部依赖，与 auth.db/skills.db 同级）。
"""
import sqlite3
from datetime import datetime
from pathlib import Path

# 路径**调用时解析**（认 `FDE_CONFIG_ROOT`，见 `config_paths.py`）；原先是模块级常量。
from fde_platform.config_paths import config_path  # noqa: E402

_LEVELS = ("red", "amber")


def _conn():
    conn = sqlite3.connect(str(config_path("agent_alerts.db")))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agent_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'Agent 上报',
            level TEXT NOT NULL DEFAULT 'amber',
            title TEXT NOT NULL,
            detail TEXT DEFAULT '',
            time TEXT DEFAULT '',
            module TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    # 加列式迁移（老库补列）。⚠ 刻意**不带 DEFAULT** —— 那样存量行会被填成 ''，
    # "没归属"与"显式平台级"就分不开了（同 skills.py 的注释）。
    cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_alerts)").fetchall()}
    if "module" not in cols:
        conn.execute("ALTER TABLE agent_alerts ADD COLUMN module TEXT")
    return conn


def raise_alert(source: str, level: str, title: str, detail: str = "",
                time: str = "", module: str = None) -> dict:
    """写入一条 agent 上报的告警。level 非法时归一为 amber。

    `module` = 上报该告警的 agent 所属**应用组**（空/None = 平台级）。
    告警按组隔离的键就是它 —— 组视角只看「本组 ∪ 平台级」。
    """
    if not title:
        return {"error": "告警标题不能为空"}
    if level not in _LEVELS:
        level = "amber"
    time = time or datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO agent_alerts (source, level, title, detail, time, module) "
            "VALUES (?,?,?,?,?,?)",
            (source or "Agent 上报", level, title, detail or "", time, module or ""),
        )
        conn.commit()
        return {"id": cur.lastrowid, "message": "告警已上报"}
    finally:
        conn.close()


def list_agent_alerts(limit: int = 100, module: str = None) -> list[dict]:
    """读最近 N 条 agent 上报的告警（统一结构；`module` 一并带出，供页面打「平台级」标记）。

    `module` 给定时按「本组 ∪ 平台级」过滤（不给 = 全量，平台管理视角）。
    """
    conn = _conn()
    try:
        sql = ("SELECT source, level, title, detail, time, "
               "COALESCE(module,'') AS module FROM agent_alerts")
        args = []
        if module:
            sql += " WHERE COALESCE(module,'') IN ('', ?)"
            args.append(module)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = conn.execute(sql, tuple(args)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
