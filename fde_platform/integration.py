"""FDE 集成接口管理 —— 发现、配置、Mock、跟踪外部系统与本平台跨组调用。

扫描两类接口：
  1. 外部系统适配器：应用中以 `_` 前缀的方法（CONVENTION §7.3），如 `_sap_sync_order`
  2. 跨组调用：`self.fde.call("组/应用", "服务", ...)`（组名不同时记录）

配置落 `config/integration.db`；执行日志独立记录。
"""
import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "config" / "integration.db"
_logger = logging.getLogger(__name__)


# ── 数据库 ────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS endpoints (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name    TEXT NOT NULL,           -- 所属应用 qualname
            method_name TEXT NOT NULL,           -- 方法名（_sap_xxx 或跨组服务名）
            target      TEXT NOT NULL,           -- 目标系统/应用组标识
            kind        TEXT NOT NULL DEFAULT 'external',  -- external / cross_group
            url         TEXT,                    -- 外部系统 URL
            timeout_s   INTEGER DEFAULT 30,
            retries     INTEGER DEFAULT 1,
            mock_enabled INTEGER DEFAULT 0,      -- 0=真实调用 1=Mock
            mock_data   TEXT,                    -- Mock 返回的 JSON
            enabled     INTEGER DEFAULT 1,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS call_logs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint_id  INTEGER REFERENCES endpoints(id),
            app_name     TEXT,
            method_name  TEXT,
            target       TEXT,
            request_summary TEXT,     -- 请求参数摘要
            response_summary TEXT,    -- 响应摘要
            status       TEXT,        -- success / error / mock
            duration_ms  INTEGER,
            error_msg    TEXT,
            created_at   TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_call_logs_target ON call_logs(target);
        CREATE INDEX IF NOT EXISTS idx_call_logs_created ON call_logs(created_at);
    """)
    conn.commit()
    return conn


# ── 发现 ──────────────────────────────────────────────────

# 已知外部系统前缀（大写，供 _is_external_adapter 白名单匹配）
_KNOWN_SYSTEM_PREFIXES = {
    "sap", "mom", "wms", "mdm", "erp", "crm", "scm",
    "api", "http", "rest", "rpc", "soap", "grpc",
    "sms", "mail", "push", "msg", "mqs", "kfk", "mq",
    "oauth", "sso", "ldap", "ftp", "sftp", "s3",
}


def _is_external_adapter(method_name: str) -> bool:
    """判定 `_` 前缀方法是否为外部系统适配器。

    规则：
    1. 排除 Python 魔术方法（__xxx__）和平台约定方法（_init_db）
    2. 方法名须为 `_<系统>_<操作>` 格式，且 <系统> 必须在已知外部系统白名单中
    3. 方法名不能匹配常见内部辅助方法前缀（二次确认）
    """
    if method_name.startswith("__") or method_name in ("_init_db",):
        return False
    parts = method_name[1:].split("_", 1)
    if len(parts) < 2:
        return False
    system = parts[0].lower()
    return system in _KNOWN_SYSTEM_PREFIXES


def _is_gateway_app(cls, app_name: str) -> tuple:
    """判定是否为网关应用（封装外部系统调用）。返回 (是否网关, 目标系统名)。"""
    # 1. 应用名含 gateway
    if "gateway" in app_name.lower():
        parts = app_name.split("/")[-1].replace("_gateway", "")
        return True, parts.upper()
    # 2. 类内有 _http_call 辅助方法
    if hasattr(cls, "_http_call") and callable(getattr(cls, "_http_call", None)):
        return True, app_name.split("/")[-1].upper()
    return False, ""


def discover(platform) -> list[dict]:
    """扫描全部应用，发现外部适配器与跨组调用。
    识别两类：1) `_` 前缀外部适配器方法  2) 网关应用的全部公共服务。
    """
    results = []
    for qn in platform.app_names():
        h = platform.handle(qn)
        is_gw, gw_target = _is_gateway_app(h.cls, qn)

        for name in dir(h.cls):
            if not callable(getattr(h.cls, name, None)):
                continue

            # 类别 1：`_` 前缀外部适配器
            if name.startswith("_") and _is_external_adapter(name):
                parts = name[1:].split("_", 1)
                target = parts[0].upper() if parts else "UNKNOWN"
                results.append({
                    "app_name": qn, "method_name": name, "target": target,
                    "kind": "external", "url": None, "timeout_s": 30,
                    "retries": 1, "mock_enabled": False,
                    "configured": _is_configured(qn, name),
                })

            # 类别 2：网关应用的公共服务
            elif is_gw and not name.startswith("_"):
                results.append({
                    "app_name": qn, "method_name": name, "target": gw_target,
                    "kind": "external", "url": None, "timeout_s": 30,
                    "retries": 1, "mock_enabled": False,
                    "configured": _is_configured(qn, name),
                })
    return results


def cross_group_calls(scanner_report: dict) -> list[dict]:
    """从 scanner 报告提取跨应用组调用。"""
    results = []
    for site in scanner_report.get("sites", []):
        # 检查是否跨组：比较调用方组与目标方组
        caller = site.get("app", "")
        target = f"{site.get('target_app', '')}.{site.get('target_service', '')}"
        caller_group = caller.split("/")[0] if "/" in caller else ""
        target_group = site.get("target_app", "").split("/")[0] if "/" in site.get("target_app", "") else ""
        if caller_group and target_group and caller_group != target_group:
            results.append({
                "app_name": caller,
                "method_name": site.get("target_service", ""),
                "target": target,
                "kind": "cross_group",
                "status": site.get("status", "ok"),
            })
    return results


# ── 配置 CRUD ─────────────────────────────────────────────

def _is_configured(app_name: str, method_name: str) -> bool:
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM endpoints WHERE app_name=? AND method_name=?", (app_name, method_name)
    ).fetchone()
    conn.close()
    return row is not None


def list_endpoints() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM endpoints ORDER BY kind, target, app_name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_endpoint(app_name: str, method_name: str, target: str, kind: str = "external",
                  url: str = None, timeout_s: int = 30, retries: int = 1,
                  mock_enabled: bool = False, mock_data: str = None) -> int:
    conn = _get_conn()
    existing = conn.execute(
        "SELECT id FROM endpoints WHERE app_name=? AND method_name=?",
        (app_name, method_name)
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE endpoints SET target=?, kind=?, url=?, timeout_s=?, retries=?,
               mock_enabled=?, mock_data=?, updated_at=datetime('now','localtime')
               WHERE id=?""",
            (target, kind, url, timeout_s, retries, 1 if mock_enabled else 0, mock_data, existing["id"])
        )
        eid = existing["id"]
    else:
        cur = conn.execute(
            """INSERT INTO endpoints (app_name, method_name, target, kind, url, timeout_s,
               retries, mock_enabled, mock_data) VALUES (?,?,?,?,?,?,?,?,?)""",
            (app_name, method_name, target, kind, url, timeout_s, retries, 1 if mock_enabled else 0, mock_data)
        )
        eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def delete_endpoint(endpoint_id: int):
    conn = _get_conn()
    conn.execute("DELETE FROM endpoints WHERE id=?", (endpoint_id,))
    conn.commit()
    conn.close()


def get_endpoint(app_name: str, method_name: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM endpoints WHERE app_name=? AND method_name=?",
        (app_name, method_name)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── 执行日志 ──────────────────────────────────────────────

def log_call(app_name: str, method_name: str, target: str, request_summary: str,
             status: str, duration_ms: int, response_summary: str = "", error_msg: str = ""):
    conn = _get_conn()
    endpoint = get_endpoint(app_name, method_name)
    eid = endpoint["id"] if endpoint else None
    conn.execute(
        """INSERT INTO call_logs (endpoint_id, app_name, method_name, target,
           request_summary, response_summary, status, duration_ms, error_msg)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (eid, app_name, method_name, target, request_summary[:500], response_summary[:500],
         status, duration_ms, error_msg[:500])
    )
    conn.commit()
    conn.close()


def recent_logs(target: str = None, limit: int = 50) -> list[dict]:
    conn = _get_conn()
    if target:
        rows = conn.execute(
            "SELECT * FROM call_logs WHERE target=? ORDER BY created_at DESC LIMIT ?",
            (target, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM call_logs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def stats_by_target() -> list[dict]:
    """按目标系统统计调用情况。"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT target,
               COUNT(*) AS total,
               SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success_count,
               SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS error_count,
               SUM(CASE WHEN status='mock' THEN 1 ELSE 0 END) AS mock_count,
               AVG(duration_ms) AS avg_duration_ms,
               MAX(duration_ms) AS max_duration_ms,
               COUNT(DISTINCT app_name) AS app_count
        FROM call_logs
        GROUP BY target
        ORDER BY total DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_logs(before_days: int = 30):
    """清理 N 天前的日志。"""
    conn = _get_conn()
    conn.execute(
        "DELETE FROM call_logs WHERE created_at < datetime('now','localtime',?)",
        (f"-{before_days} days",)
    )
    conn.commit()
    conn.close()
