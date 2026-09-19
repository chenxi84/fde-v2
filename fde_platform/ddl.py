"""FDE DDL 引擎：解析 schema.sql（SQLite 子集）→ 注入审计列 → 按方言生成建表 DDL。

替代 `db.py` 里 `_add_audit_columns` / `_translate_ddl` 的**正则 DDL 改写**。
只用于「应用加载时建表」这条一次性路径（runtime.py 加载应用时调用），
不落在每次服务调用上。DML 的审计值注入仍在 `db.py` 的 `_inject_audit`，与此无关。

依赖 `sqlglot`（正式依赖，进 requirements.txt）。import 失败即抛（不回落正则）。
"""
import sqlglot
from sqlglot import exp

# 平台统一注入的审计列（TEXT，与 db.py _inject_audit 在 DML 写入的 datetime('now')/NOW() 对应）
AUDIT_COLUMNS = ("created_at", "updated_at", "created_by", "updated_by")


def parse_schema(sql_text: str) -> list:
    """解析 schema.sql（SQLite 方言）→ sqlglot 表达式列表。"""
    return sqlglot.parse(sql_text or "", read="sqlite")


def _inject_audit_columns(expr: exp.Create) -> None:
    """给单个 CREATE TABLE 表达式注入缺失的审计列（TEXT）；CREATE INDEX 跳过。

    审计列必须插在表级约束（PRIMARY KEY (...) / UNIQUE (...) 等）**之前**，
    SQLite 不允许列定义出现在表约束之后。
    """
    if not isinstance(expr, exp.Create) or expr.kind != "TABLE":
        return
    schema = expr.this
    if not isinstance(schema, exp.Schema):
        return
    columns = [c for c in schema.expressions if isinstance(c, exp.ColumnDef)]
    constraints = [c for c in schema.expressions if not isinstance(c, exp.ColumnDef)]
    existing = {c.name.lower() for c in columns}
    for name in AUDIT_COLUMNS:
        if name not in existing:
            columns.append(exp.ColumnDef(
                this=exp.to_identifier(name),
                kind=exp.DataType.build("TEXT"),
            ))
    schema.set("expressions", columns + constraints)


def _pg_time_funcs(expr: exp.Expression) -> None:
    """把 SQLite 专有的时间函数改写成本方言可用的写法（**仅 PG 需要**）。

    为什么需要：`datetime('now', 'localtime')` 是 SQLite 专有函数，sqlglot **不认识它**
    （解析成 `Anonymous`），transpile 到 PG 时**原样带过去** ⇒
    `function datetime(unknown, unknown) does not exist`，建表直接失败、平台起不来。
    2026-09-20 在测试服务器上实测踩到：`app/psc/sales_forecast/schema.sql` 的
    `settled_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))`。

    口径：SQLite 侧保持原样（本地时区，与平台既有行为一致）；
    PG 侧换成 `CURRENT_TIMESTAMP`（平台 DML 侧的审计值本来就按方言分口径）。
    """
    for node in list(expr.find_all(exp.Anonymous)):
        if str(node.this).upper() == "DATETIME":
            node.replace(exp.CurrentTimestamp())


def build_ddl(sql_text: str, dialect: str = "sqlite") -> list:
    """把 schema.sql 编译成目标方言的建表语句列表（含审计列）。

    dialect: 'sqlite' | 'postgres'。SQLite 原样；PG 由 sqlglot transpile
    （自动处理 `INTEGER PRIMARY KEY AUTOINCREMENT` → `GENERATED ... AS IDENTITY`），
    并额外规范化 SQLite 专有时间函数（见 `_pg_time_funcs`）。
    返回语句字符串列表，逐条 `conn.execute(stmt)` 即可。
    """
    exprs = parse_schema(sql_text)
    for e in exprs:
        _inject_audit_columns(e)
        if dialect == "postgres":
            _pg_time_funcs(e)
    return [e.sql(dialect=dialect) for e in exprs]


def declared_columns(sql_text: str, dialect: str = "sqlite") -> dict:
    """schema.sql 声明的 {表名: [列定义表达式]}（含平台注入的审计列）。

    `dialect` 影响**列定义生成的 SQL**：PG 下同样要规范化 SQLite 专有时间函数，
    否则补列时 `ALTER TABLE ... ADD COLUMN ... DEFAULT (datetime('now','localtime'))`
    会在 PG 上炸（与建表是同一个坑）。
    """
    exprs = parse_schema(sql_text)
    for e in exprs:
        _inject_audit_columns(e)
        if dialect == "postgres":
            _pg_time_funcs(e)
    out = {}
    for e in exprs:
        if not (isinstance(e, exp.Create) and e.kind == "TABLE"):
            continue
        schema = e.this
        if not isinstance(schema, exp.Schema):
            continue
        table = schema.this
        name = getattr(table, "name", None) or str(table)
        out[str(name)] = [c for c in schema.expressions if isinstance(c, exp.ColumnDef)]
    return out


def _existing_columns(conn, table: str, dialect: str) -> set:
    """现有表已有哪些列（小写）。表不存在 → 空集合。"""
    if dialect == "postgres":
        cur = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            (table,),
        )
    else:
        cur = conn.execute(f'PRAGMA table_info("{table}")')
    rows = cur.fetchall() or []
    names = set()
    for r in rows:
        # sqlite 走 PRAGMA 时第 1 列是列名；PG 查询就是列名本身。
        # 行可能是 tuple 也可能是 Row/dict（平台各连接工厂不同），两种都兼容。
        v = None
        try:
            v = r[1] if dialect != "postgres" else r[0]
        except Exception:
            v = None
        if v is None:
            try:
                v = r["name"] if dialect != "postgres" else r["column_name"]
            except Exception:
                v = None
        if v is not None:
            names.add(str(v).lower())
    return names


def reconcile_columns(conn, sql_text: str, dialect: str = "sqlite") -> list:
    """**对账补列**：把已有表补齐到 schema.sql 的声明（缺哪列补哪列）。

    为什么需要它：`CREATE TABLE IF NOT EXISTS` 只在**表**不存在时生效，表已存在就整句
    跳过——所以往 schema.sql 里加一列，对**已有库**毫无作用，之后任何读写该列都会
    `no such column`。而重跑建库脚本也补不上（演示环境的重置是清空行、不删库文件）。

    只做加法（补列），**绝不删列/删表**——少一列报错是显式的，删一列丢数据是静默的。

    返回补过的列（`["表.列", ...]`），供调用方记日志。不可补的情况（如 NOT NULL 且
    无默认值/主键列）**直接报错**，不做"悄悄降级成可空"——那会让库与声明长期不一致。
    """
    added = []
    for table, cols in declared_columns(sql_text, dialect).items():
        have = _existing_columns(conn, table, dialect)
        if not have:            # 表刚建好（或根本不存在）→ 无需对账
            continue
        for col in cols:
            name = col.name
            if not name or name.lower() in have:
                continue
            stmt = f'ALTER TABLE "{table}" ADD COLUMN {col.sql(dialect=dialect)}'
            try:
                conn.execute(stmt)
            except Exception as e:
                raise RuntimeError(
                    f"[ddl] 表 {table} 缺列 {name}，但无法自动补：{type(e).__name__}: {e}。"
                    f"该列声明为 NOT NULL 却没有默认值（或它是主键/唯一约束的一部分）——"
                    f"这种列在已有表上补不了。请给它一个 DEFAULT，或手工迁移该表。"
                ) from e
            added.append(f"{table}.{name}")
    return added


def execute_schema(conn, sql_text: str, dialect: str = "sqlite", reconcile: bool = True) -> list:
    """对连接执行 schema.sql 的全部建表语句，并把已有表补到与声明一致。

    返回补过的列列表（`["表.列", ...]`）；无变化时为空。
    """
    for stmt in build_ddl(sql_text, dialect):
        conn.execute(stmt)
    if not reconcile:
        return []
    return reconcile_columns(conn, sql_text, dialect)
