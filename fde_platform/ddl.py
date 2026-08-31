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


def build_ddl(sql_text: str, dialect: str = "sqlite") -> list:
    """把 schema.sql 编译成目标方言的建表语句列表（含审计列）。

    dialect: 'sqlite' | 'postgres'。SQLite 原样；PG 由 sqlglot transpile
    （自动处理 `INTEGER PRIMARY KEY AUTOINCREMENT` → `GENERATED ... AS IDENTITY`）。
    返回语句字符串列表，逐条 `conn.execute(stmt)` 即可。
    """
    exprs = parse_schema(sql_text)
    for e in exprs:
        _inject_audit_columns(e)
    return [e.sql(dialect=dialect) for e in exprs]


def execute_schema(conn, sql_text: str, dialect: str = "sqlite") -> None:
    """对连接执行 schema.sql 的全部建表语句。"""
    for stmt in build_ddl(sql_text, dialect):
        conn.execute(stmt)
