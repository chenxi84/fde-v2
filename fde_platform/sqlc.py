# -*- coding: utf-8 -*-
"""DML 编译层：把**应用写的 SQLite 方言 SQL** 编译到目标方言（含审计列注入）。

## 为什么要有它（2026-09-26 加，决策与边界见 `design-plus/CONVENTION.md` §14）

应用侧承诺不变：**裸 SQL + `?` 占位符 + SQLite 方言 + `schema.sql` 是唯一真相源**。
但"一套 SQL 两边（将来多边）跑"必须有人在**语义层**做方言翻译，而旧做法是三处**字符串手术**：

| 旧做法（已在 2026-09-27 删除，此处留作对照） | 它的问题 |
|---|---|
| `re.sub(r'\\)\\s*VALUES\\s*\\(', …)` 找 INSERT 的列清单 | 多行 `VALUES (…),(…)` 只补到**最后一行**；`INSERT…SELECT` 直接不匹配 |
| `re.sub(r'\\)\\s*$', …)` 补审计值 | 同上；`WITH … INSERT` 形态失效 |
| `sql.replace("%","%%").replace("?","%s")` 全局替换 | 字面量里的 `?` 也被换（`WHERE note='why?'` 当场炸）；`%` 与 LIKE 通配叠加；mysql 的**反斜杠字面量语义**（sqlite 里是普通字符、mysql 里是转义符）永远处理不了 |

本模块把这三件事搬到 **AST 层**（sqlglot，DDL 早就在用它）：

1. 解析（`read="sqlite"`）——**这才是"应用 SQL 不能改"与"多方言"两者能同时成立的唯一载体**：
   语义翻译（`||` → `CONCAT('…', …)`）、字面量按目标方言**重新转义**（`'a\\b'` 在 mysql 要写成
   `'a\\\\b'`）、时间函数改写（复用 `ddl._time_funcs`），这些都是字符串替换做不到的；
2. 注入审计列（INSERT 的**每一行**、INSERT…SELECT 的投影、UPDATE 的 SET）——AST 层做，
   于是"多行 VALUES / INSERT…SELECT / CTE"这些形态的边界**结构性消失**（不是被照顾到）；
3. 占位符**改名**：应用的 `?` → `p0 p1 …`（按文档顺序），审计值 → `u_created_by` / `u_updated_by`。
   命名之后**参数顺序不再需要数**（旧做法要靠数 `?` 把审计参数插进 params 中间，那是最脆的一段）；
   顺带**参数个数不匹配当场报错**（旧做法会静默错位绑定）。
4. 按**驱动**出占位符风格：sqlite3 认 `:name`、psycopg2/pymysql 认 `%(name)s`
   （⚠ 与"方言"无关而与"驱动"有关：sqlglot 给 mysql 生成的是 `:name`，那是 mysql-connector
   prepared 的风格，pymysql 不认 ⇒ 这一行改写必须按驱动做）。
5. 字面量 `%` 转义**只对 %-插值驱动**做（psycopg2 / pymysql）；sqlite3 不做插值，
   转义反而是错的。

## 开关

**本层是唯一路径**（2026-09-27 起）：原先有个 `FDE_SQL_COMPILER=legacy` 的退回开关（走 `db.py` 内联的
字符串手术），灰度验证通过后已删除 —— 回退手段改为 git（`CONVENTION.md` §14.3）。

## 边界：能编译的与不能编译的

能：SELECT / INSERT（单行、多行、INSERT…SELECT）/ UPDATE / DELETE / WITH / 子查询。
不能（**明确报错，不静默降级**）：解析失败的 SQL、`INSERT … DEFAULT VALUES`、`INSERT … SET`、
参数个数与占位符不匹配、以及"要补审计列但找不到落脚点"的形态。
"""
import os
import re
from functools import lru_cache

import sqlglot
from sqlglot import exp
from sqlglot.tokens import TokenType

from fde import FdeError
from fde_platform.ddl import AUDIT_COLUMNS, _time_funcs

# 方言 → 该方言**默认驱动**的口径。新增数据库时这里是第一处要动的地方（连同下面的 pk 策略）。
DIALECTS = {
    "sqlite": {
        "driver": "sqlite3",
        "paramstyle": "colon",          # :name（原生）
        "now": "datetime('now','localtime')",   # 保持平台既有口径（本地时区）
        "pk": "lastrowid",              # 驱动原生 lastrowid 就是对的
    },
    "postgres": {
        "driver": "psycopg2",
        "paramstyle": "pyformat",       # %(name)s（原生）
        "now": "CURRENT_TIMESTAMP",     # SQL 标准，各方言都认（与 ddl._time_funcs 同口径）
        "pk": "returning",              # ⚠ PG 的 cursor.lastrowid 恒为 0 ⇒ 必须走 RETURNING
    },
    "mysql": {
        "driver": "pymysql",
        "paramstyle": "pyformat",       # %(name)s；sqlglot 生成 :name，需按驱动改写
        "now": "CURRENT_TIMESTAMP",
        "pk": "lastrowid",              # mysql 驱动的 lastrowid 本来就对
    },
}

# **只有一条路**（2026-09-27 删掉 legacy 之后）：应用照旧写 SQLite 方言裸 SQL，平台总在编译层翻译。
# 保留 `mode()` 只为让启动横幅能显示当前口径（部署后据此核对）。
MODE = "sqlglot"


def mode() -> str:
    """当前编译口径（横幅/日志显示用）。"""
    return MODE


def dialect_of_driver(conn, dialect: str) -> str:
    """按连接实际类型定方言（与 `db.dialect_of` 同口径；这里只做名字归一）。"""
    return dialect if dialect in DIALECTS else "sqlite"


# ── AST 改写 ────────────────────────────────────────────────

def _now_node(dialect: str) -> exp.Expression:
    return sqlglot.parse_one(DIALECTS[dialect]["now"], read=dialect)


def _visible_columns(node) -> set:
    """该节点里出现的列名（小写）——用来判断"审计列是不是应用自己已经写了"。"""
    return {c.name.lower() for c in node.find_all(exp.Column) if c.name}


def _inject_audit(e, dialect: str) -> bool:
    """在 AST 上补审计列/值；返回是否补了（INSERT 的每一行都补）。

    ⚠ INSERT 的列清单是**裸标识符**，不是 `ddl` 建表用的 `ColumnDef` —— 两处不能共用构造
    （原型里混用会生成 `created_at TEXT` 塞进 INSERT 列清单的非法 SQL）。
    """
    if isinstance(e, exp.Insert):
        schema, values = e.this, e.expression
        if not isinstance(schema, exp.Schema):
            raise FdeError("编译层不支持：INSERT 没有列清单（如 INSERT … DEFAULT VALUES）")
        have = {c.name.lower() for c in schema.expressions if c.name}
        add = [n for n in AUDIT_COLUMNS if n not in have]
        if not add:
            return False
        for n in add:
            schema.append("expressions", exp.to_identifier(n))
        if isinstance(values, exp.Values):
            for tup in values.expressions:               # ⚠ **每一行**都要补（旧正则只补到最后一行）
                for n in add:
                    tup.append("expressions", _now_node(dialect) if n.endswith("_at")
                               else exp.Placeholder(this="u_" + n))
        elif isinstance(values, exp.Select):             # INSERT … SELECT
            for n in add:
                values.select(_now_node(dialect) if n.endswith("_at")
                              else exp.Placeholder(this="u_" + n), copy=False)
        else:
            raise FdeError(f"编译层不支持：INSERT 的值不是 VALUES/SELECT（{type(values).__name__}）")
        return True

    if isinstance(e, exp.Update):
        have = _visible_columns(e)                        # 应用自己写了 updated_* 就别重复补
        add = [n for n in ("updated_at", "updated_by") if n not in have]
        if not add:
            return False
        for n in add:
            e.args["expressions"].append(exp.EQ(
                this=exp.to_column(n),
                expression=_now_node(dialect) if n == "updated_at"
                else exp.Placeholder(this="u_" + n)))
        return True

    return False


def _rename_placeholders_in_text(sql: str) -> tuple:
    """按**词法顺序**把应用的 `?` 改成 `:p0 :p1 …`；返回 (改名后的 SQL, 占位符个数)。

    ⚠⚠ **绝不能用 AST 遍历顺序当"第几个"**：`find_all()` 的次序**不是文本次序**
    （AND 链在 AST 里是嵌套的二元节点，遍历会先到右子树）。实测：
    `WHERE plan_type = ? AND phase = ? AND status='approved' AND plan_no <> ?`
    被编成 `plan_type = :p1 AND phase = :p2 AND plan_no <> :p0` —— **参数错位是静默的**
    （不报错、往库里写错值），2026-09-26 被 tech_plan 的链测试当场抓住。

    走词法位置还有两个白拿的好处：① tokenizer 知道引号边界，`WHERE note = 'why?'` 里的
    `?` **不会**被当成占位符（旧的正则替换会在此处炸）；② 审计注入的命名占位符此刻
    也已经是命名的，与位置无关。

    ⚠ sqlglot 的 token `start`/`end` 是**闭区间**（`end` 指向最后一个字符），切片要 `end+1`。
    """
    toks = sqlglot.Dialect.get_or_raise("sqlite").tokenizer_class().tokenize(sql)
    ph = [t for t in toks if t.token_type == TokenType.PLACEHOLDER]
    out = sql
    for i, t in reversed(list(enumerate(ph))):        # 从后往前替换，前面的位置才不失效
        out = out[:t.start] + f":p{i}" + out[t.end + 1:]
    return out, len(ph)


# 我方**无法忠实翻译**的 SQLite 函数（2026-09-27 实测：这些在 PG 上要么静默错值、要么语义不等价）
_UNMAPPABLE = ("STRFTIME", "JULIANDAY", "PRINTF", "DATE", "TIME")


def _check_unmappable(e, dialect: str, sql_text: str) -> None:
    """拦下"翻不成目标方言"的 SQLite 函数 —— **宁可不支持，也不静默错值**。

    为什么必须有（2026-09-27 实测，都是"新应用可能用到"的形态）：
      · `strftime('%Y-%m', d)` → `TO_CHAR(d, '%YYYY-%MM')` —— **PG 的模板不带 `%`** ⇒ 静默给出带 `%` 的错值；
      · `datetime(d, '-7 days')` → **`CURRENT_TIMESTAMP`** —— "某时间减 7 天"被翻成"当前时间"，**最坏的一类**；
        （根因：我复用了 DDL 的 `ddl._time_funcs`，而它只认 `datetime('now',…)` 那一种，其余一律替换 —— DDL 里
         只有"默认值"这一种用法，DML 里却有"带列/带修饰符"的用法。）
      · `julianday` / `printf` / `date(…, '+1 day')` → 原样带过去，PG 上**跑起来才报错**（响亮，但消息难懂）。

    口径：**只放行 `datetime('now'[, 'localtime'])`**（审计列那种用法，翻成 `CURRENT_TIMESTAMP`），
    其余一律在这里明确拒绝，并告诉调用方两条出路（改用目标方言写法 / 把日期处理挪到应用侧 Python）。
    """
    if dialect == "sqlite":
        return
    for node in e.find_all(exp.Anonymous):
        name = str(node.this).upper()
        if name not in _UNMAPPABLE and name != "DATETIME":
            continue
        args = [a.sql(dialect="sqlite").strip().strip("'\"").lower() for a in node.expressions]
        if name == "DATETIME" and args and args[0] == "now":
            continue                      # 放行：等价于 CURRENT_TIMESTAMP
        raise FdeError(
            f"编译层不支持把 {name}(…) 翻到 {dialect}（会静默给错值或语义不等价）—— "
            f"请改用目标方言的写法，或把这段日期处理放到应用侧（Python）。语句：{sql_text[:100]}")

    # ⚠ `strftime` 曾被误判为"不可翻译"（我看到 `TO_CHAR(d,'%YYYY-%MM')` 就以为 sqlglot 不支持）——
    #   实际是**我自己的转义跑在渲染之前**造成的（见 `_escape_percent_text` 的注释）：把顺序修正后，
    #   sqlglot 对 strftime 的翻译是**忠实**的（实测各格式串 → PG `'YYYY-MM-DD HH24:MI'`（无 `%`）、
    #   MySQL `'%Y-%m-%d %H:%i'`、TSQL `'yyyy-MM-dd HH:mm'`、Oracle 同 PG）⇒ **不再拦它**。


def _normalize_conflict_keys(e) -> None:
    """去掉冲突目标上的**排序修饰符**（`ON CONFLICT(a NULLS FIRST)` 这类）。

    为什么需要（2026-09-27 在真 PG 上实测）：sqlglot 的 **sqlite 解析器**把 `ON CONFLICT(a)`
    解析成 `Ordered(this=Column(a), nulls_first=True)`（SQLite 语法里"带可选排序的索引列"的产物），
    而 **postgres 生成器**会忠实渲染那个修饰符 ⇒ 编译出 `ON CONFLICT(a NULLS FIRST)`，
    **PG 直接语法错**（实测：`syntax error at or near "NULLS"`）。SQLite 侧渲染恰好忽略它，所以本地看不出来
    —— 又一个"只在 PG 上现形"的形态。

    语义上该去掉：冲突目标（conflict target）在任何方言里都**不接受** `NULLS FIRST/LAST` 或 `DESC`
    （它是"匹配哪个唯一索引"，不是排序）。去掉包装、留内层列即可。

    ⚠ 顺带说明：`app/psc/sales_forecast/sales_forecast.py:458` 的注释写着"先删后插，避免依赖
    ON CONFLICT 的方言差异" —— 前人正是绕开了这个坑；本函数把它补上，让这种写法重新可用。
    """
    for oc in e.find_all(exp.OnConflict):
        keys = oc.args.get("conflict_keys") or []
        if any(isinstance(k, exp.Ordered) for k in keys):
            oc.set("conflict_keys", [k.this if isinstance(k, exp.Ordered) else k for k in keys])


_PLACEHOLDER = re.compile(r"%\([A-Za-z_]\w*\)s")


def _escape_percent_text(sql: str) -> str:
    """把渲染后的 SQL 里**除驱动占位符以外**的 `%` 转义成 `%%`（只给 %-插值驱动用）。

    ⚠ **必须在渲染之后做**（2026-09-27 实测的排序 bug）：原先我在 AST 阶段就把字面量里的 `%`
    转义了，于是 sqlglot 拿到的是 `'%%Y-%%m'`，它按目标方言翻译**日期格式串**时认歪
    ⇒ 编出 `TO_CHAR(d, '%YYYY-%MM')`（PG 的模板不带 `%`）**静默错值**。
    正确的顺序是：**先让 sqlglot 渲染**（它会忠实地把 `%Y-%m` 翻成 `YYYY-MM`），
    **再**给驱动补转义 —— 此时格式串里的 `%` 已经没有了，只有占位符与真正的取模/字面量 `%`。

    ⚠ 占位符 `%(name)s` 是**我们自己生成的**，必须原样跳过；其余 `%`（字面量里的、以及 `a % 2`
    这类取模）一律转义 —— 给 pyformat 驱动看的。
    """
    out, i, n = [], 0, len(sql)
    while i < n:
        m = _PLACEHOLDER.match(sql, i)
        if m:                                   # 驱动占位符：原样
            out.append(m.group(0)); i = m.end(); continue
        ch = sql[i]
        out.append("%%" if ch == "%" else ch)
        i += 1
    return "".join(out)


def _to_driver_placeholders(sql: str, paramstyle: str) -> str:
    """sqlglot 按方言给出的占位符 → 目标**驱动**认的写法。

    sqlglot 的 mysql 生成器给 `:name`（mysql-connector prepared 风格），pymysql 只认
    `%(name)s` ⇒ 按驱动补一次改写。碰的都是我们自己生成的命名占位符，安全。
    """
    if paramstyle != "pyformat":
        return sql
    if "%(" in sql:
        return sql
    return re.sub(r":([A-Za-z_]\w*)", r"%(\1)s", sql)


def _insert_table(e) -> str:
    if isinstance(e, exp.Insert):
        t = e.this
        if isinstance(t, exp.Schema):
            t = t.this
        if isinstance(t, exp.Table):
            return t.name
    return ""


# ── 主键策略（决定 PG 要不要追加 RETURNING）────────────────────

_PK_MISS = object()
_pk_cache: dict = {}


def pk_column(raw_conn, table: str, dialect: str):
    """该表**由序列/自增支撑**的主键列名；没有（或查不到）→ None。

    为什么只认"序列/自增支撑"：业务自编码主键（如 `REQ-001`）不需要 lastrowid；
    只有自增主键才需要"刚插入那一行的 id"。

    ⚠ `raw_conn` 必须是**驱动的原生连接**，不能用平台包装过的连接 ——
    否则这里的元数据查询会再次走进 `execute` → 又一次编译（递归）。
    """
    key = (dialect, table)
    hit = _pk_cache.get(key, _PK_MISS)
    if hit is not _PK_MISS:
        return hit
    col = None
    try:
        cur = raw_conn.cursor()
        if dialect == "postgres":
            cur.execute(
                "SELECT column_name FROM information_schema.columns c "
                "WHERE c.table_name = %s AND c.table_schema = current_schema() "
                "AND (c.column_default LIKE 'nextval%%' OR c.is_identity = 'YES')",
                (table,))
        elif dialect == "mysql":
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s AND table_schema = database() "
                "AND extra LIKE '%%auto_increment%%'", (table,))
        else:
            cur.execute(f'PRAGMA table_info("{table}")')
        row = cur.fetchone()
        cur.close()
        if row is None:
            col = None
        elif dialect == "sqlite":
            col = str(row[1]) if len(row) > 1 else None       # PRAGMA: (cid, name, type, …, pk)
        else:
            col = str(row[0])
    except Exception:                                          # noqa: BLE001
        col = None                                             # 查不到 = 不追加（不比现状更糟）
    _pk_cache[key] = col
    return col


def _append_returning(e, pk_col: str) -> None:
    e.set("returning", exp.Returning(expressions=[exp.to_column(pk_col)]))


# ── 编译（带缓存；**只缓存 SQL 文本与参数计划，绝不缓存参数值**）──

@lru_cache(maxsize=512)
def _compile_cached(sql_text: str, dialect: str, pk_col, audit: bool):
    """返回 (编译后的 SQL, 应用占位符个数, 是否带 RETURNING)。

    参数值**不进缓存** —— 用户/时间都是每次调用现算的（缓存住就等于把 A 用户的身份
    写进了 B 用户的语句里）。
    """
    spec = DIALECTS[dialect]
    renamed, n_app = _rename_placeholders_in_text(sql_text)     # 词法顺序改名（见该函数注释）
    try:
        e = sqlglot.parse_one(renamed, read="sqlite")
    except Exception as ex:                                    # noqa: BLE001
        raise FdeError(
            f"SQL 无法解析（编译层）：{ex}。语句：{sql_text[:120]}"
            f"。这是**编译层无法解析**的语句：请改成标准写法，或把这段逻辑挪到应用侧。") from ex
    if e is None:
        raise FdeError(f"SQL 为空（编译层）：{sql_text[:120]}")

    injected = _inject_audit(e, dialect) if audit else False
    _check_unmappable(e, dialect, sql_text)    # 翻不成的 SQLite 函数：**明确拒绝**，不静默错值
    _time_funcs(e, dialect)                    # 只对放行过的 `datetime('now',…)` 生效（与 DDL 同口径）
    _normalize_conflict_keys(e)                # 冲突目标不许带排序修饰符（PG 上会语法错）
    uses_returning = False
    if (dialect == "postgres" and pk_col and isinstance(e, exp.Insert)
            and not e.args.get("returning")):
        _append_returning(e, pk_col)
        uses_returning = True

    out = e.sql(dialect=dialect)
    out = _to_driver_placeholders(out, spec["paramstyle"])
    # ⚠ 转义要看**驱动会不会插值**：psycopg2 / pymysql 只在**传了参数**时才做 %-插值，
    #   不传参数时 `%` 就是普通字符 —— 无脑转义会把 `'%'` 变成 `'%%'`（LIKE 模式当场变错，
    #   而且这种错**只在不带参数的查询上出现**，最难发现）。且**必须在渲染之后**（见函数注释）。
    if spec["paramstyle"] == "pyformat" and (n_app > 0 or injected):
        out = _escape_percent_text(out)
    return out, n_app, uses_returning, injected


_SQL_KIND = re.compile(r"^\s*(INSERT|UPDATE)", re.I)


def compile_sql(sql_text: str, params, ctx: dict = None, dialect: str = "sqlite",
                raw_conn=None) -> tuple:
    """编译一条应用 SQL。

    返回 `(sql, params_dict, meta)`：`params_dict` 是**命名参数字典**（可直接交给驱动），
    `meta` 含 `returns_pk`（PG 下本条会带回主键，调用方应读一次 fetchone）。
    """
    spec = DIALECTS.get(dialect)
    if spec is None:
        raise FdeError(f"编译层不认识的方言：{dialect}")
    params = tuple(params or ())
    audit = bool(_SQL_KIND.match(sql_text))

    pk_col = None
    if audit and dialect == "postgres" and raw_conn is not None:
        pk_col = pk_column(raw_conn, _insert_table(sqlglot.parse_one(sql_text, read="sqlite")),
                           dialect) if sql_text.strip().upper().startswith("INSERT") else None

    sql, n_app, uses_returning, injected = _compile_cached(sql_text, dialect, pk_col, audit)

    if n_app != len(params):
        raise FdeError(
            f"SQL 参数个数与占位符不匹配（编译层）：语句里有 {n_app} 个 `?`，"
            f"传了 {len(params)} 个参数。语句：{sql_text[:120]}")

    p = {f"p{i}": v for i, v in enumerate(params)}
    if injected:
        user = (ctx or {}).get("userno", "") or ""
        p["u_created_by"] = user
        p["u_updated_by"] = user
    return sql, p, {"returns_pk": uses_returning, "injected": injected, "n_app": n_app}
