"""FDE 数据库抽象层：SQLite ↔ PostgreSQL 双模。

本地开发不配 DATABASE_URL → 默认 SQLite（行为不变）。
Docker 部署配 DATABASE_URL=postgresql://... → 自动切 PostgreSQL。

应用代码零改动：``self.db.execute() / fetchone() / fetchall()`` 接口保持一致。
"""
import logging
import os
import sqlite3
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_logger = logging.getLogger(__name__)

_PG_URL = os.environ.get("DATABASE_URL", "").strip()
_PG_AVAILABLE = bool(_PG_URL and _PG_URL.startswith("postgresql"))
_PG_FAIL_REASON = None   # 失败原因（供启动横幅展示）


def using_postgresql() -> bool:
    """当前是否使用 PostgreSQL（仅当连接池已成功建立时返回 True）。"""
    return _PG_AVAILABLE and _PG_POOL is not None


def db_mode() -> str:
    """返回当前数据库模式，供启动横幅展示。"""
    if _PG_AVAILABLE:
        if _PG_POOL is not None:
            return f"PostgreSQL ({_PG_URL.split('@')[-1] if '@' in _PG_URL else _PG_URL})"
        return f"PostgreSQL 连接失败→回退 SQLite（{_PG_FAIL_REASON or '未知原因'}）"
    return "SQLite"


# ── DDL 翻译 ─────────────────────────────────────────────

def _translate_ddl(sql: str) -> str:
    """SQLite DDL → PostgreSQL DDL（仅必要转换）。"""
    import re
    sql = re.sub(r'\bAUTOINCREMENT\b', '', sql, flags=re.IGNORECASE)
    sql = re.sub(
        r"INTEGER PRIMARY KEY\b(?!\s*GENERATED)",
        "INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY",
        sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bdatetime\('now'\)\b", "NOW()", sql)
    sql = re.sub(r"\bdatetime\('now','localtime'\)\b", "NOW()", sql)
    return sql


# ── SQLite 适配器（原有行为）────────────────────────────────

def _open_sqlite(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── PostgreSQL 适配器 ────────────────────────────────────────

_PG_POOL = None
_PG_RETRIES = 5        # 等待 PG 就绪的重试次数
_PG_RETRY_DELAY = 3     # 每次重试间隔（秒）


def _pg_pool():
    """惰性创建 PostgreSQL 连接池（带重试，应对容器启动时序）。"""
    global _PG_POOL, _PG_FAIL_REASON
    if _PG_POOL is not None:
        return _PG_POOL
    try:
        from psycopg2 import pool as pg_pool_mod
    except ImportError:
        _PG_FAIL_REASON = "psycopg2 未安装"
        _logger.warning(_PG_FAIL_REASON)
        return None

    import urllib.parse
    url = urllib.parse.urlparse(_PG_URL)

    for attempt in range(1, _PG_RETRIES + 1):
        try:
            _PG_POOL = pg_pool_mod.ThreadedConnectionPool(
                2, 10,
                host=url.hostname,
                port=url.port or 5432,
                user=url.username,
                password=url.password,
                dbname=url.path.lstrip("/"),
            )
            _logger.info("PostgreSQL 连接池已创建：%s:%d/%s（第 %d 次尝试）",
                         url.hostname, url.port or 5432, url.path.lstrip("/"), attempt)
            _PG_FAIL_REASON = None
            return _PG_POOL
        except Exception as e:
            _PG_FAIL_REASON = str(e)[:200]
            if attempt < _PG_RETRIES:
                _logger.info("PostgreSQL 尚未就绪（%d/%d），%d 秒后重试…",
                             attempt, _PG_RETRIES, _PG_RETRY_DELAY)
                time.sleep(_PG_RETRY_DELAY)
            else:
                _logger.error("PostgreSQL 连接失败（已重试 %d 次）：%s", _PG_RETRIES, e)
    return None


class _PgConnection:
    """包装 psycopg2 连接，对外暴露与 sqlite3 兼容的接口。"""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        sql = _translate_ddl(sql)
        self._cursor = self._conn.cursor()
        if params:
            sql = sql.replace("?", "%s")
            self._cursor.execute(sql, params)
        else:
            self._cursor.execute(sql)
        if self._cursor.description:
            cols = [d[0] for d in self._cursor.description]

            def _dict_row(values):
                return {cols[i]: values[i] for i in range(len(values))}

            orig_fetchone = self._cursor.fetchone
            self._cursor.fetchone = lambda: (
                _dict_row(row) if (row := orig_fetchone()) else None)

            orig_fetchall = self._cursor.fetchall
            self._cursor.fetchall = lambda: [_dict_row(r) for r in orig_fetchall()]

        return self._cursor

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        try:
            self._conn.commit()
        except Exception:
            pass
        if _PG_POOL:
            _PG_POOL.putconn(self._conn)


# ── 统一入口 ────────────────────────────────────────────────

def get_connection(app_name: str, db_path: Path = None) -> object:
    """获取数据库连接（SQLite 或 PostgreSQL）。

    app_name: 应用 qualname（如 'yadi_crm/customer'），在 PG 模式下映射为 schema。
    db_path: SQLite 模式下的 .db 文件路径。
    """
    if not _PG_AVAILABLE:
        return _open_sqlite(db_path or Path(":memory:"))

    pool = _pg_pool()
    if pool is None:
        _logger.warning("PG 连接池不可用，回退 SQLite：[%s]", _PG_FAIL_REASON or "未知")
        return _open_sqlite(db_path or Path(":memory:"))

    conn = pool.getconn()
    schema = app_name.replace("/", "_").replace("-", "_")

    try:
        curs = conn.cursor()
        curs.execute(
            "SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = %s",
            (schema,))
        if not curs.fetchone():
            curs.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn.commit()
        curs.execute(f"SET search_path TO {schema}")
        conn.commit()
    except Exception as e:
        _logger.warning("Schema 初始化失败 [%s]：%s", schema, e)

    return _PgConnection(conn)
