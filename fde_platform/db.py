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

# DML 编译层：把"字符串手术"换成 AST 改写（2026-09-27 起是**唯一**路径），见 sqlc.py 的 docstring
from fde_platform import sqlc

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_logger = logging.getLogger(__name__)

_PG_URL = os.environ.get("DATABASE_URL", "").strip()
_PG_AVAILABLE = bool(_PG_URL and _PG_URL.startswith("postgresql"))
_PG_FAIL_REASON = None   # 失败原因（供启动横幅展示）


def using_postgresql() -> bool:
    """当前是否使用 PostgreSQL（仅当**取连接方式已成功建立**时返回 True）。"""
    return _PG_AVAILABLE and (_PG_ENGINE is not None or _PG_POOL is not None)


def db_mode() -> str:
    """返回当前数据库模式，供启动横幅展示。"""
    if _PG_AVAILABLE:
        if _PG_ENGINE is not None or _PG_POOL is not None:
            p_min, p_max, p_timeout, p_recycle = _pool_limits()
            backend = "Engine" if _PG_BACKEND == "engine" else "psycopg2 原生池"
            return (f"PostgreSQL ({_PG_URL.split('@')[-1] if '@' in _PG_URL else _PG_URL}"
                    f") · {backend} {p_min}–{p_max} 条 · 等待 {p_timeout}s · 回收 {p_recycle}s"
                    f" · DML 编译层 {sqlc.mode()}")
        return f"PostgreSQL 连接失败→回退 SQLite（{_PG_FAIL_REASON or '未知原因'}）"
    return f"SQLite · DML 编译层 {sqlc.mode()}"


def dialect_of(conn) -> str:
    """这条连接**实际**用的是哪种 SQL 方言（`"postgres"` / `"sqlite"`）。

    ⚠ **不要用 `using_postgresql()` 代替它**：连接池是**懒建**的（第一次
    `get_connection` 才建），所以建池之前调 `using_postgresql()` **恒为 False**。
    `runtime._load` 恰好就是这个顺序（先算 dialect、再建连接）⇒ PostgreSQL 部署下
    建表与对账全按 SQLite 走，`PRAGMA table_info` 在 PG 上直接语法报错、
    **平台起不来**（2026-09-20 在测试服务器上实测踩到）。

    从连接对象本身判断则没有这个问题：它是什么，就是什么。
    """
    return "postgres" if isinstance(conn, _PgConnection) else "sqlite"


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
        """编译层：AST 注入审计 + 命名占位符（`_conn` 是**原生** sqlite3 连接，
        传给它做元数据探测不会递归回本函数）。"""
        ctx = getattr(self, "_fde_ctx", None) or {}
        text, named, _meta = sqlc.compile_sql(sql, params, ctx, "sqlite", raw_conn=self._conn)
        return self._conn.execute(text, named) if named else self._conn.execute(text)

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

_PG_POOL = None        # 兜底：未装 SQLAlchemy 时用 psycopg2 原生池
_PG_ENGINE = None      # 部署路径的取连接方式：SQLAlchemy Engine（pre-ping / recycle / timeout / 溢出）
_PG_BACKEND = None     # "engine" | "pool" | None（还没定）
_PG_RETRIES = 5        # 等待 PG 就绪的重试次数
_PG_RETRY_DELAY = 3     # 每次重试间隔（秒）

# URL → Engine 的注册表。**键是 URL 字符串**：`DATABASE_URL` 变了必须拿到新 Engine，
# 否则就是"模块级常量缓存"那类陷阱的重演（见 `skills.DB_PATH` 的教训，2026-09-26）。
# 影子库换根走 `FDE_DB_ROOT` / `FDE_CONFIG_ROOT`，不动 URL，故不受影响。
_ENGINE_CACHE: dict = {}


def _pool_limits() -> tuple:
    """池参数（环境变量可配）：(基线连接数, 上限, 等待秒, 回收秒)。

    默认 2/10 + 等待 30s + 回收 1800s。⚠ **不是越大越好** —— 天花板是
    `min(池上限, PG 的 max_connections)`；多组 × 多进程一起开大会把 PG 打满。
    `FDE_PG_POOL_RECYCLE=0` 表示不回收（长连接场景自己权衡）。
    """
    def _int(name, dflt):
        try:
            return int(os.environ.get(name, str(dflt)) or dflt)
        except (TypeError, ValueError):
            return dflt

    p_min = max(1, _int("FDE_PG_POOL_MIN", 2))
    p_max = max(p_min, _int("FDE_PG_POOL_MAX", 10))
    return p_min, p_max, max(1, _int("FDE_PG_POOL_TIMEOUT", 30)), max(0, _int("FDE_PG_POOL_RECYCLE", 1800))


def sa_url(url: str) -> str:
    """把用户写的 URL 钉到**本项目实际安装的驱动**上。

    ⚠ 2026-09-26 在测试服务器上实测踩到：**SQLAlchemy 2.1 起 `postgresql://` 默认解析到
    psycopg (v3) 方言**（`sqlalchemy/dialects/postgresql/psycopg.py` → `import psycopg`），
    而本项目装的是 `psycopg2-binary` ⇒ `create_engine` 抛 `ModuleNotFoundError: No module named 'psycopg'`。
    平台承诺是"配 `DATABASE_URL=postgresql://…` 即切 PG，应用零改动"——**驱动选择是平台的事**，
    所以在这里显式补成 `postgresql+psycopg2://`，用户不用改任何东西。
    """
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


def engine_for(url: str, limits: tuple = None):
    """按 URL 取（或建）Engine。**懒连接**：`create_engine` 不发网络请求，可离线断言。

    为什么借 Engine 而不是自己维护池（2026-09-26 定，见 `design-plus/CONVENTION.md` §14.1）：
    ① 池满时**等待 + 超时报错**（psycopg2 原生池是**立即**抛 PoolError，不等待）；
    ② `pool_pre_ping` 顶掉陈旧连接（PG 重启 / 空闲被中间设备断）；
    ③ `pool_recycle` —— MySQL 的 `wait_timeout` 默认 8h，接第三种库时是必需品；
    ④ URL 解析（ssl / options 等）交给成熟实现，替掉手写 `urlparse`。
    """
    p_min, p_max, p_timeout, p_recycle = limits or _pool_limits()
    url = sa_url(url)                       # 钉驱动（见 sa_url 的注释）
    key = (url, p_min, p_max, p_timeout, p_recycle)
    eng = _ENGINE_CACHE.get(key)
    if eng is None:
        from sqlalchemy import create_engine

        eng = create_engine(
            url,
            pool_size=p_min, max_overflow=max(0, p_max - p_min),
            pool_timeout=p_timeout, pool_pre_ping=True, pool_recycle=p_recycle,
        )
        _ENGINE_CACHE[key] = eng
    return eng


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

    global _PG_ENGINE, _PG_BACKEND
    p_min, p_max, p_timeout, p_recycle = _pool_limits()

    # ① 首选 SQLAlchemy Engine（见 engine_for 的四条理由）
    try:
        from sqlalchemy import text as _sa_text
        engine = engine_for(_PG_URL)
        for attempt in range(1, _PG_RETRIES + 1):
            try:
                with engine.connect() as c:
                    c.execute(_sa_text("SELECT 1"))
                _PG_ENGINE, _PG_BACKEND, _PG_FAIL_REASON = engine, "engine", None
                _logger.info(
                    "PostgreSQL Engine 就绪（基线 %d + 溢出 %d · 等待 %ds · 回收 %ds · pre-ping）",
                    p_min, max(0, p_max - p_min), p_timeout, p_recycle)
                return _PG_BACKEND
            except Exception as e:
                _PG_FAIL_REASON = str(e)[:200]
                if attempt < _PG_RETRIES:
                    _logger.info("PostgreSQL 尚未就绪（%d/%d），%d 秒后重试…",
                                 attempt, _PG_RETRIES, _PG_RETRY_DELAY)
                    time.sleep(_PG_RETRY_DELAY)
                else:
                    _logger.error("PostgreSQL 连接失败（已重试 %d 次）：%s", _PG_RETRIES, e)
        _logger.warning("Engine 建不起来，回落 psycopg2 原生池：[%s]", _PG_FAIL_REASON or "未知")
    except ImportError as e:
        # ⚠ 别写成"未安装 SQLAlchemy"就完事 —— 实测这条消息**骗过我一次**：
        #   真实原因是 SQLAlchemy 2.1 把 `postgresql://` 指到 psycopg(v3) 而它没装（见 sa_url）。
        #   带上异常原文，下一个人一眼看得出来是缺哪个模块。
        _logger.warning(
            "SQLAlchemy 不可用（%s: %s），PostgreSQL 回落 psycopg2 原生池（无 pre-ping / recycle / 等待语义）",
            type(e).__name__, e)

    import urllib.parse
    url = urllib.parse.urlparse(_PG_URL)

    for attempt in range(1, _PG_RETRIES + 1):
        try:
            _PG_POOL = pg_pool_mod.ThreadedConnectionPool(
                p_min, p_max,
                host=url.hostname,
                port=url.port or 5432,
                user=url.username,
                password=url.password,
                dbname=url.path.lstrip("/"),
            )
            _logger.info("PostgreSQL 连接池已创建：%s:%d/%s（%d–%d 条连接，第 %d 次尝试）",
                         url.hostname, url.port or 5432, url.path.lstrip("/"),
                         p_min, p_max, attempt)
            _PG_FAIL_REASON = None
            _PG_BACKEND = "pool"
            return _PG_BACKEND
        except Exception as e:
            _PG_FAIL_REASON = str(e)[:200]
            if attempt < _PG_RETRIES:
                _logger.info("PostgreSQL 尚未就绪（%d/%d），%d 秒后重试…",
                             attempt, _PG_RETRIES, _PG_RETRY_DELAY)
                time.sleep(_PG_RETRY_DELAY)
            else:
                _logger.error("PostgreSQL 连接失败（已重试 %d 次）：%s", _PG_RETRIES, e)
    return None


def _checkout(backend: str):
    """取一条 PG 连接（Engine 或原生池）。**池满是明确报错，不是静默等待/静默失败。**"""
    p_min, p_max, p_timeout, _ = _pool_limits()
    if backend == "engine":
        try:
            return _PG_ENGINE.raw_connection()      # ⚠ 走 raw：别让 SQLAlchemy 再编译一遍
        except Exception as e:                      #    我们已编译好的 SQL（`%%` 会被二次转义）
            raise RuntimeError(
                f"PostgreSQL 连接池已满（{p_min}–{p_max} 条，等待 {p_timeout}s 超时）："
                f"并发请求超过了池容量。调大 FDE_PG_POOL_MAX，或降低并发。"
                f"原始错误：{type(e).__name__}: {e}") from e
    try:
        return _PG_POOL.getconn()
    except Exception as e:
        raise RuntimeError(
            f"PostgreSQL 连接池耗尽（{p_min}–{p_max} 条）：psycopg2 原生池**不等待**，"
            f"并发一超过池容量就立刻报这个错（装上 SQLAlchemy 可换成「等待 + 超时」语义）。"
            f"可先把 FDE_PG_POOL_MAX 调大。原始错误：{type(e).__name__}: {e}") from e


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
    """包装 psycopg2 cursor，返回 _PgDictRow 并暴露 lastrowid。

    ⚠ **`cursor.lastrowid` 在 PostgreSQL 下是坏的**：psycopg2 给的是「插入行的 OID」，
      而现代 PG 已无 OID ⇒ 实测恒为 **0**（不是 None）。应用按平台约定写
      `return self.get(cur.lastrowid)`（如 app/psc/md_breakpoint/md_breakpoint.py:29）时，
      插入其实成功了，但按 0 回查为空 ⇒ 抛业务错误「记录不存在」、并被平台回滚。
      症状是「新建失败，且报的是查不到」——把驱动能力缺口报成了业务问题。

    修法（2026-09-26 起）：编译层在编译期给"自增主键表"的 INSERT 追加 `RETURNING <pk>`，
      由本包装器把带回的那一行接住，作为 `lastrowid` 返回 —— 不依赖驱动能力，也不查系统表。
    """

    def __init__(self, cursor, pk_value=None):
        from datetime import datetime, date
        from decimal import Decimal
        self._cur = cursor
        self._pk_value = pk_value          # 编译层带 RETURNING 时直接给（最可靠的一条路）
        self._raw_lastrowid = cursor.lastrowid
        self.description = cursor.description
        self.rowcount = cursor.rowcount
        self._cols = [d[0] for d in cursor.description] if cursor.description else []
        self._types = (datetime, date, Decimal)

    @property
    def lastrowid(self):
        """刚插入行的主键：**`RETURNING` 带回的**优先，其次驱动原生值。

        ⚠ legacy 分支删除时（2026-09-27），`currval` 那条兜底也一并删了 —— 它只在
        "主键由序列支撑、但我们的内省没查出来" 时才可能被用到，而那种情形下 currval 同样取不到
        （非序列主键本来就没有"刚插入那一行的 id"可取）。全仓只有 1 处读 `lastrowid`
        （`app/psc/md_breakpoint/md_breakpoint.py:29`），其表是自增主键 ⇒ 走 `RETURNING` ✓。
        """
        return self._pk_value if self._pk_value is not None else self._raw_lastrowid

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

    def __iter__(self):
        """支持 `for r in self.db.execute(...)`（**裸迭代游标**）。

        ⚠ 2026-09-27 在测试服务器上用克隆库跑链测试时撞到：`wbs.add_child` 直接迭代游标
        ⇒ PG 下 `TypeError: '_PgCursorWrapper' object is not iterable`（SQLite 上一直正常）。
        全仓有 22 处这种写法。根因是**游标 API 面**的对齐问题（不是 SQL 方言问题）：
        `sqlite3.Cursor` 可迭代，而本 shim 只实现了 fetchone/fetchall/close。
        """
        for row in self._cur:
            yield self._make_row(row)

    def __getattr__(self, name):
        """未显式实现的成员一律透传给底层驱动游标（`fetchmany` / `arraysize` / …）。

        `__getattr__` 只在**正常查找失败**时才被调用 ⇒ 不会遮挡上面显式实现的成员。
        以 `_` 开头的一律走 AttributeError：防 `__init__` 期间 `self._cur` 还没赋值时递归。
        """
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._cur, name)

    def close(self):
        self._cur.close()


class _PgConnection:
    """包装 psycopg2 连接，对外暴露与 sqlite3 兼容的接口。"""

    def __init__(self, conn, backend: str = None):
        self._conn = conn
        self._backend = backend or _PG_BACKEND

    def execute(self, sql, params=None):
        """编译层：AST 注入审计 + 命名占位符 + （INSERT 且主键自增时）`RETURNING` 带主键。

        ⚠ `_conn` 是**原生** psycopg2 连接 —— 编译层的元数据探测（`sqlc.pk_column`）必须走它。
        """
        ctx = getattr(self, "_fde_ctx", None) or {}
        text, named, meta = sqlc.compile_sql(sql.strip(), params, ctx, "postgres",
                                             raw_conn=self._conn)
        self._cursor = self._conn.cursor()
        if named:
            self._cursor.execute(text, named)
        else:
            self._cursor.execute(text)
        pk_value = None
        if meta.get("returns_pk"):
            row = self._cursor.fetchone()          # RETURNING 带回的那一行
            pk_value = row[0] if row else None
        return _PgCursorWrapper(self._cursor, pk_value=pk_value)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        try:
            self._conn.commit()
        except Exception:
            pass
        if getattr(self, "_backend", None) == "engine":
            self._conn.close()          # Engine 的 raw_connection：close = **归还池**
        elif _PG_POOL:
            _PG_POOL.putconn(self._conn)


# ── 统一入口 ────────────────────────────────────────────────

def get_connection(app_name: str, db_path: Path = None) -> object:
    """获取数据库连接（SQLite 或 PostgreSQL）。

    app_name: 应用 qualname（如 'yadi_crm/customer'），在 PG 模式下映射为 schema。
    db_path: SQLite 模式下的 .db 文件路径。
    """
    if not _PG_AVAILABLE:
        return _open_sqlite(db_path or Path(":memory:"))

    backend = _pg_pool()
    if backend is None:
        _logger.warning("PG 连接池不可用，回退 SQLite：[%s]", _PG_FAIL_REASON or "未知")
        return _open_sqlite(db_path or Path(":memory:"))

    conn = _checkout(backend)
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

    return _PgConnection(conn, backend=backend)
