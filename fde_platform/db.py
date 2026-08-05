"""FDE 数据库抽象层：SQLite ↔ PostgreSQL 双模。

本地开发不配 DATABASE_URL → 默认 SQLite（行为不变）。
Docker 部署配 DATABASE_URL=postgresql://... → 自动切 PostgreSQL。

应用代码零改动：`self.db.execute() / fetchone() / fetchall()` 接口保持一致。
"""
import logging
import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_logger = logging.getLogger(__name__)

_PG_URL = os.environ.get("DATABASE_URL", "").strip()
_PG_AVAILABLE = bool(_PG_URL and _PG_URL.startswith("postgresql"))


def using_postgresql() -> bool:
    """当前是否使用 PostgreSQL。"""
    return _PG_AVAILABLE


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
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── PostgreSQL 适配器 ────────────────────────────────────────

_PG_POOL = None


def _pg_pool():
    """惰性创建 PostgreSQL 连接池（线程安全，最小 2 最大 10）。"""
    global _PG_POOL
    if _PG_POOL is not None:
        return _PG_POOL
    try:
        from psycopg2 import pool as pg_pool_mod
        from psycopg2 import extras as pg_extras
        import urllib.parse

        url = urllib.parse.urlparse(_PG_URL)
        _PG_POOL = pg_pool_mod.ThreadedConnectionPool(
            2, 10,
            host=url.hostname,
            port=url.port or 5432,
            user=url.username,
            password=url.password,
            dbname=url.path.lstrip("/"),
        )
        _logger.info("PostgreSQL 连接池已创建：%s:%d/%s",
                     url.hostname, url.port or 5432, url.path.lstrip("/"))
        return _PG_POOL
    except ImportError:
        _logger.warning("psycopg2 未安装，回退 SQLite")
        return None
    except Exception as e:
        _logger.error("PostgreSQL 连接失败：%s，回退 SQLite", e)
        return None


class _PgConnection:
    """包装 psycopg2 连接，对外暴露与 sqlite3 兼容的接口。

    - execute(sql, params) → cursor（有 fetchone/fetchall/lastrowid）
    - row_factory → 自动 DictRow
    - commit / rollback / close
    """

    def __init__(self, conn):
        self._conn = conn
        self._cursor = None

    def execute(self, sql, params=None):
        from psycopg2 import extras as pg_extras
        sql = _translate_ddl(sql)
        self._cursor = self._conn.cursor()
        if params:
            # psycopg2 用 %s 而非 ?——把 ? 替换为 %s
            sql = sql.replace("?", "%s")
            self._cursor.execute(sql, params)
        else:
            self._cursor.execute(sql)
        # 包装 fetchone/fetchall 返回 DictRow
        if self._cursor.description:
            cols = [d[0] for d in self._cursor.description]

            def _dict_row(values):
                return {cols[i]: values[i] for i in range(len(values))}

            orig_fetchone = self._cursor.fetchone
            self._cursor.fetchone = lambda: (
                _dict_row(row) if (row := orig_fetchone()) else None)

            orig_fetchall = self._cursor.fetchall
            self._cursor.fetchall = lambda: [_dict_row(r) for r in orig_fetchall()]

        self._cursor.lastrowid = self._cursor.lastrowid
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
        if db_path and db_path.is_file() is not None:
            return _open_sqlite(db_path or Path(":memory:"))
        return _open_sqlite(db_path or Path(":memory:"))

    pool = _pg_pool()
    if pool is None:
        return _open_sqlite(db_path or Path(":memory:"))

    conn = pool.getconn()
    schema = app_name.replace("/", "_").replace("-", "_")

    try:
        # 确保 schema 存在
        curs = conn.cursor()
        curs.execute(
            "SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = %s",
            (schema,))
        if not curs.fetchone():
            curs.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn.commit()
        # 限定 search_path 到该 schema
        curs.execute(f"SET search_path TO {schema}")
        conn.commit()
    except Exception as e:
        _logger.warning("Schema 初始化失败：%s", e)

    return _PgConnection(conn)
