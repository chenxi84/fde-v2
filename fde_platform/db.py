"""FDE 数据库抽象层：SQLite ↔ PostgreSQL 双模。

本地开发不配 DATABASE_URL → 默认 SQLite（行为不变）。
Docker 部署配 DATABASE_URL=postgresql://... → 自动切 PostgreSQL。

应用代码零改动：``self.db.execute() / fetchone() / fetchall()`` 接口保持一致。
"""
import logging
import os
import re
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
    """SQLite DDL → PostgreSQL DDL + 自动追审审计列。"""
    sql = re.sub(r'\bAUTOINCREMENT\b', '', sql, flags=re.IGNORECASE)
    sql = re.sub(
        r"INTEGER PRIMARY KEY\b(?!\s*GENERATED)",
        "INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY",
        sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bdatetime\('now'\)\b", "NOW()", sql)
    sql = re.sub(r"\bdatetime\('now','localtime'\)\b", "NOW()", sql)
    sql = re.sub(r'\bDATETIME\b', 'TIMESTAMP', sql, flags=re.IGNORECASE)
    # 在 CREATE TABLE 语句逐列追加缺失的审计列
    if re.search(r'CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS', sql, re.IGNORECASE):
        missing = []
        if 'created_at' not in sql.lower():
            missing.append('created_at TEXT')
        if 'updated_at' not in sql.lower():
            missing.append('updated_at TEXT')
        if 'created_by' not in sql.lower():
            missing.append('created_by TEXT')
        if 'updated_by' not in sql.lower():
            missing.append('updated_by TEXT')
        if missing:
            sql = re.sub(r'\)\s*$', ', ' + ', '.join(missing) + ')', sql, flags=re.IGNORECASE)
    return sql


# ── 审计值注入 ──────────────────────────────────────────

def _inject_audit(sql: str, params, ctx: dict) -> tuple:
    sql = sql.strip()  # 去首尾空白保证索引对齐
    """在 INSERT/UPDATE 语句中自动注入审计字段值（跳过应用已手写的列）。

    INSERT → 追加 created_at / updated_at / created_by / updated_by
    UPDATE → 追加 updated_at / updated_by
    ctx 来自 self.ctx，由 runtime 层注入到连接上。"""
    user = (ctx or {}).get("userno", "") or ""
    now_sqlite = "datetime('now','localtime')"
    sql_upper = sql.strip().upper()

    if sql_upper.startswith("INSERT INTO"):
        # 跳过应用已手写的列（用 sql_upper 做大小写无关匹配）
        extra_cols, extra_vals, extra_params = [], [], []
        if 'CREATED_AT' not in sql_upper:
            extra_cols.append("created_at"); extra_vals.append(now_sqlite)
        if 'UPDATED_AT' not in sql_upper:
            extra_cols.append("updated_at"); extra_vals.append(now_sqlite)
        if 'CREATED_BY' not in sql_upper:
            extra_cols.append("created_by"); extra_vals.append("?")
            extra_params.append(user)
        if 'UPDATED_BY' not in sql_upper:
            extra_cols.append("updated_by"); extra_vals.append("?")
            extra_params.append(user)
        if extra_cols:
            sql = re.sub(r'\)\s*VALUES\s*\(',
                         ', ' + ', '.join(extra_cols) + ') VALUES (',
                         sql, count=1, flags=re.IGNORECASE)
            sql = re.sub(r'\)\s*$',
                         ', ' + ', '.join(extra_vals) + ')', sql, count=1)
            new_params = list(params or ()) + extra_params
            return sql, tuple(new_params) if params else tuple(extra_params)
        return sql, params

    if sql_upper.startswith("UPDATE"):
        # 只追加应用未手写的审计列
        set_parts = []
        set_params = []
        set_part_sql = sql_upper
        if " WHERE " in sql_upper:
            set_part_sql = sql_upper[:sql_upper.index(" WHERE ")]
        if 'UPDATED_AT' not in set_part_sql:
            set_parts.append(f"updated_at = {now_sqlite}")
        if 'UPDATED_BY' not in set_part_sql:
            set_parts.append("updated_by = ?")
            set_params.append(user)
        if not set_parts:
            return sql, params

        audit_set = ", " + ", ".join(set_parts)
        if " WHERE " in sql_upper:
            idx = sql_upper.index(" WHERE ")
            set_q_count = sql_upper[:idx].count("?")
            sql = sql[:idx] + audit_set + " " + sql[idx:]
            plist = list(params or ())
            new_params = plist[:set_q_count] + set_params + plist[set_q_count:]
        else:
            sql = sql.rstrip() + audit_set
            new_params = list(params or ()) + set_params
        return sql, tuple(new_params) if params else tuple(set_params)

    return sql, params


# ── SQLite 适配器（原有行为）────────────────────────────────

class _SqliteAuditWrapper:
    """包装 sqlite3 连接，在 execute() 时自动注入审计字段。"""

    def __init__(self, conn):
        self._conn = conn
        self._fde_ctx = {}       # runtime.py 在注入 inst.db 前设置

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, val):
        self._conn.row_factory = val

    def execute(self, sql, params=None):
        ctx = getattr(self, "_fde_ctx", None) or {}
        sql, params = _inject_audit(sql, params, ctx)
        return self._conn.execute(sql, params or ())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _open_sqlite(db_path: Path) -> _SqliteAuditWrapper:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return _SqliteAuditWrapper(conn)


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


class _PgDictRow(dict):
    """兼容 sqlite3.Row 的字典行：支持 row['name'] 和 row[0] 两种访问。"""

    def __init__(self, cols, values):
        super().__init__({cols[i]: values[i] for i in range(len(cols))})
        self._keys = list(cols)
        self._values = list(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

    def keys(self):
        return self._keys

    def __iter__(self):
        return iter(self._keys)


class _PgCursorWrapper:
    """包装 psycopg2 cursor，返回 _PgDictRow 并暴露 lastrowid。"""

    def __init__(self, cursor):
        from datetime import datetime, date
        from decimal import Decimal
        self._cur = cursor
        self.lastrowid = cursor.lastrowid
        self.description = cursor.description
        self.rowcount = cursor.rowcount
        self._cols = [d[0] for d in cursor.description] if cursor.description else []
        self._types = (datetime, date, Decimal)

    def _to_jsonable(self, value):
        if value is None:
            return None
        if isinstance(value, self._types):
            return str(value)
        return value

    def _make_row(self, values):
        return _PgDictRow(self._cols, [self._to_jsonable(v) for v in values])

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        return self._make_row(row)

    def fetchall(self):
        return [self._make_row(r) for r in self._cur.fetchall()]

    def close(self):
        self._cur.close()


class _PgConnection:
    """包装 psycopg2 连接，对外暴露与 sqlite3 兼容的接口。"""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        sql = _translate_ddl(sql)
        sql = sql.strip()  # 去首尾空白，保证和 sql_upper 索引对齐
        ctx = getattr(self, "_fde_ctx", None) or {}
        user = (ctx or {}).get("userno", "") or ""
        sql_upper = sql.upper()

        if sql_upper.startswith("INSERT INTO"):
            extra_cols, extra_vals, extra_params = [], [], []
            if 'created_at' not in sql_upper:
                extra_cols.append("created_at"); extra_vals.append("NOW()")
            if 'updated_at' not in sql_upper:
                extra_cols.append("updated_at"); extra_vals.append("NOW()")
            if 'created_by' not in sql_upper:
                extra_cols.append("created_by"); extra_vals.append("%s")
                extra_params.append(user)
            if 'updated_by' not in sql_upper:
                extra_cols.append("updated_by"); extra_vals.append("%s")
                extra_params.append(user)
            if extra_cols:
                sql = re.sub(r'\)\s*VALUES\s*\(',
                             ', ' + ', '.join(extra_cols) + ') VALUES (',
                             sql, count=1, flags=re.IGNORECASE)
                sql = re.sub(r'\)\s*$',
                             ', ' + ', '.join(extra_vals) + ')', sql, count=1)
                params = list(params or ()) + extra_params

        elif sql_upper.startswith("UPDATE"):
            set_part = sql_upper
            if " WHERE " in sql_upper:
                set_part = sql_upper[:sql_upper.index(" WHERE ")]
            set_parts, set_params = [], []
            if 'UPDATED_AT' not in set_part:
                set_parts.append("updated_at = NOW()")
            if 'UPDATED_BY' not in set_part:
                set_parts.append("updated_by = %s")
                set_params.append(user)
            if set_parts:
                audit_set = ", " + ", ".join(set_parts)
                if " WHERE " in sql_upper:
                    idx = sql_upper.index(" WHERE ")
                    set_q = sql_upper[:idx].count("?")
                    sql = sql[:idx] + audit_set + " " + sql[idx:]
                    plist = list(params or ())
                    params = plist[:set_q] + set_params + plist[set_q:]
                else:
                    sql = sql.rstrip() + audit_set
                    params = list(params or ()) + set_params

        self._cursor = self._conn.cursor()
        if params:
            sql = sql.replace("?", "%s")
            try:
                self._cursor.execute(sql, tuple(params))
            except Exception:
                print(f"[AUDIT-DEBUG] SQL: {sql[:400]}", flush=True)
                print(f"[AUDIT-DEBUG] Params: {tuple(params)}", flush=True)
                raise
        else:
            self._cursor.execute(sql)
        return _PgCursorWrapper(self._cursor)

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
