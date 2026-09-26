r"""SQL 方言改写/编译层的验收（平台级，自包含，**不需要 PostgreSQL、不需要起服务**）。

⚠ **本脚本覆盖两条路**（2026-09-26 扩展）：
  · **A. legacy**：`db.py` 内联的字符串手术（`_inject_audit` + `%`/`?` 替换）—— 默认路径；
  · **B. 编译层**：`fde_platform/sqlc.py`（sqlglot AST 改写）—— `FDE_SQL_COMPILER=sqlglot` 时启用。
A 段先把开关**钉死成 legacy**（否则门禁结果随环境变量漂），B 段直接调 `sqlc` 的 API。
两条路都要绿：切开关那天，判据不能跟着漂。


## 为什么需要它

`_PgConnection.execute` 在把 SQL 交给 psycopg2 之前做了三件改写：① 注入审计列；
② 把**字面量 `%`** 转义成 `%%`；③ 把 `?` 换成 `%s`。这三件事互相牵制，
**本地全程 SQLite、根本不走这条路径**，所以它们错了本地一律发现不了 ——
2026-09-20 一天之内就在这里连撞四个，每一个都只能在真实 PostgreSQL 上现形：

| 症状 | 根因 |
|---|---|
| `IndexError: tuple index out of range` | 字面量 `%` 没转义（`LIKE '%' \|\| ? \|\| '%'`）⇒ 所有模糊搜索全崩 |
| `TypeError: not all arguments converted` | 审计注入自己写了 `%s`，又被那次转义改成 `%%s` ⇒ 占位符消失 |
| `PRAGMA` 语法错 | 方言在建连接之前判定（那是 `runtime.py`，不归本脚本管） |
| `function datetime(...) does not exist` | schema.sql 里的 SQLite 专有函数（归 `ddl.py`） |

## 怎么做到不起数据库还能验

psycopg2 默认走**客户端插值**，其行为与 Python 的 `%` 运算一致（`%s` 取值、`%%` 出字面量 `%`）。
所以拿一个假连接接住改写后的 `(sql, params)`，再做一次 `sql % params`：
**占位符少一个就抛 `TypeError`/`IndexError`，多一个就把 `%s` 留在了 SQL 里**——
两种错法都抓得到，而这两条正是上面四个缺陷里的前两个。

⚠ **本脚本只验「占位符账」与「字面量 `%` 是否存活」**，不验 SQL 语法是否合法（那要真 PG）：
它用 Python 的 `%` 插值代替 psycopg2 的适配器，**不会**给替换进去的值加 SQL 引号。
所以下面断言的期望值里没有引号——想看带引号的效果，看服务器上的实测日志。

用法：`python scripts/verify_pg_translate.py`（退出码 0 全过 / 1 有失败）
"""
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

os.environ["FDE_SQL_COMPILER"] = "legacy"        # A 段钉死 legacy（见文件头）

from fde_platform import db  # noqa: E402
from fde_platform import sqlc  # noqa: E402
from fde import FdeError  # noqa: E402

# 输出编码：控制台代码页在本机默认是 GBK，而本脚本的结论里有 ✓/✗/⚠/⇒ 这类**非 GBK 码位** ——
# 不钉住的话 print 自己会抛 UnicodeEncodeError（**崩在打印结论那一步**），
# 而外层门禁把它显示成「该检查 FAIL」——像判据报了缺陷，其实判据根本没跑完。
# 由 scripts/verify_test_script_encoding.py 守住别忘这一行（它的扫描范围已含 scripts/）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail = []


class _FakeCursor:
    """接住改写后的 SQL：顺便用 Python 的 `%` 插值模拟 psycopg2 的客户端插值。"""

    def __init__(self, sink):
        self._sink = sink
        self.lastrowid = 0
        self.description = None
        self.rowcount = 0

    def execute(self, sql, params=None):
        p = tuple(params or ())
        if p:
            rendered = sql % p          # ← 占位符与参数对不上就在这里炸
        else:
            rendered = sql
        self._sink.append(rendered)


class _FakeConn:
    def __init__(self, sink):
        self._sink = sink

    def cursor(self):
        return _FakeCursor(self._sink)

    def commit(self):
        pass


def run(label, sql, params, *, expect_in=(), expect_not_in=("%s", "%%")):
    """跑一次改写；返回渲染后的 SQL（失败则记一笔）。"""
    sink = []
    conn = db._PgConnection(_FakeConn(sink))
    conn._fde_ctx = {"userno": "tester", "departmentno": "", "role": "admin"}
    try:
        conn.execute(sql, params)
    except Exception as e:
        _fail.append(f"{label}：改写后无法插值 → {type(e).__name__}: {e}")
        return ""
    rendered = sink[-1]
    for frag in expect_in:
        if frag not in rendered:
            _fail.append(f"{label}：渲染结果里缺少 {frag!r}\n      实际：{rendered}")
    for frag in expect_not_in:
        if frag in rendered:
            _fail.append(f"{label}：渲染结果里残留了 {frag!r}（占位符被吃掉或没转义）\n"
                         f"      实际：{rendered}")
    return rendered


# ① 模糊搜索：**字面量 % 必须存活**，且占位符正常取值
#    这正是 md_customer / md_material / inventory_strategy 等 12 处的形态。
r = run("① LIKE 字面量 %",
        "SELECT a FROM t WHERE x LIKE '%' || ? || '%' ORDER BY a", ("CUST",),
        expect_in=("LIKE '%' || CUST || '%'",))
if r:
    print(f"  ✓ ① LIKE 字面量 %：{r}")

# ② UPDATE：审计注入的占位符**不能**被那次转义吃掉
#    这正是 outbound_plan.close_expired 的形态（曾经报 not all arguments converted）。
r = run("② UPDATE + 审计注入",
        "UPDATE t SET status = '已关闭' WHERE status = '待出库' AND d < ?", ("2026-09-20",),
        expect_in=("updated_at = NOW()", "updated_by = tester", "d < 2026-09-20"))
if r:
    print(f"  ✓ ② UPDATE + 审计注入：{r}")

# ③ INSERT：审计列注入 + 占位符计数
r = run("③ INSERT + 审计注入",
        "INSERT INTO t (a, b) VALUES (?, ?)", ("1", "2"),
        expect_in=("created_at, updated_at, created_by, updated_by", "tester"))
if r:
    print(f"  ✓ ③ INSERT + 审计注入：{r}")

# ④ 不带参数时不做插值：字面量 % 原样保留（psycopg2 不插值，% 就是普通字符）
r = run("④ 无参数 + 字面量 %",
        "SELECT a FROM t WHERE x LIKE '%流水%'", None,
        expect_in=("LIKE '%流水%'",), expect_not_in=("%%",))
if r:
    print(f"  ✓ ④ 无参数 + 字面量 %：{r}")

# ⑤ 边界：SQL 里同时有 % 与 ? 但没有 UPDATE/INSERT 关键字（纯 SELECT）
r = run("⑤ SELECT 同时含 % 与 ?",
        "SELECT a FROM t WHERE x LIKE 'a%' AND y = ?", ("v",),
        expect_in=("LIKE 'a%' AND y = v",))
if r:
    print(f"  ✓ ⑤ SELECT 同时含 % 与 ?：{r}")

print()
print("── B 段：编译层（sqlc，sqlglot AST 改写）──────────────────────────")


def cmp_sql(label, sql, params, dialect, *,
            want_in=(), want_not_in=(), raw_in=(), raw_not_in=(), ctx=None, expect_err=None):
    """编译一条 SQL 并用 `%` 渲染（与 psycopg2 的 pyformat 同口径），断言片段。"""
    try:
        text, named, meta = sqlc.compile_sql(sql, params, ctx or {"userno": "tester"}, dialect)
    except FdeError as e:
        if expect_err:
            if expect_err in str(e):
                print(f"  ✓ {label}：按预期报错")
            else:
                _fail.append(f"{label}：报错信息里没有 {expect_err!r}，实际：{e}")
            return ""
        _fail.append(f"{label}：不该报错却报了 → {e}")
        return ""
    if expect_err:
        _fail.append(f"{label}：应当报错（{expect_err}）却没报")
        return ""
    # `raw_*` 看的是**未渲染**的编译产物：`%%` 这种"给驱动看的转义"在渲染时会被还原成
    # `%`，所以只能在这一层断言（否则"转对了"与"没转"渲染后长得一模一样）。
    for frag in raw_in:
        if frag not in text:
            _fail.append(f"{label}：产物缺 {frag!r} ｜ 实际：{text}")
    for frag in raw_not_in:
        if frag in text:
            _fail.append(f"{label}：产物里不该有 {frag!r} ｜ 实际：{text}")
    try:
        rendered = text % named if named else text
    except Exception as e:                                    # noqa: BLE001
        _fail.append(f"{label}：编译产物无法插值 → {type(e).__name__}: {e} ｜ 实际：{text}")
        return ""
    for frag in want_in:
        if frag not in rendered:
            _fail.append(f"{label}：缺 {frag!r} ｜ 实际：{rendered}")
    for frag in want_not_in:
        if frag in rendered:
            _fail.append(f"{label}：残留 {frag!r} ｜ 实际：{rendered}")
    if not _fail or _fail[-1] != f"{label}：缺":
        print(f"  ✓ {label}：{rendered[:96]}")
    return rendered


# ⑥ 占位符顺序 —— **这条是 2026-09-26 实测踩到的真 bug 的固化**
#    根因：`find_all()` 的遍历次序不是文本次序（AND 链是嵌套节点，先到右子树），
#    于是 `WHERE a = ? AND b = ? AND c = ?` 被错位成 p1/p2/p0 —— **静默写错值**。
#    修法：走 tokenizer 的**词法位置**（token.start/end，闭区间）。
cmp_sql("⑥ 占位符按文本次序（AND 链）",
        "SELECT a FROM t WHERE x = ? AND y = ? AND z = ?", ("1", "2", "3"), "postgres",
        want_in=("x = 1 AND y = 2 AND z = 3",))

# ⑦ 引号里的 `?` 不是占位符（tokenizer 知道引号边界；旧的正则替换会在这里炸）
cmp_sql("⑦ 引号里的 ? 不算占位符",
        "SELECT a FROM t WHERE note = 'why?' AND x = ?", ("v",), "postgres",
        want_in=("note = 'why?' AND x = v",))

# ⑧ 审计注入：多行 VALUES **每一行**都补（旧的只补到最后一行）
cmp_sql("⑧ 多行 INSERT 每行都补审计",
        "INSERT INTO t (a, b) VALUES (?, ?), (?, ?)", (1, 2, 3, 4), "sqlite",
        want_in=("created_by", "(:p0, :p1", "(:p2, :p3"))

# ⑨ 审计注入：INSERT…SELECT 补在投影里（旧的整条不匹配）
cmp_sql("⑨ INSERT…SELECT 补投影",
        "INSERT INTO t (a) SELECT x FROM y WHERE z = ?", ("k",), "sqlite",
        want_in=("INSERT INTO t (a, created_at", "SELECT x, DATETIME"))

# ⑩ UPDATE：只补审计列，且应用自己写的 updated_* 不重复补
cmp_sql("⑩ UPDATE 补审计（不重复补）",
        "UPDATE t SET a = ?, updated_by = ? WHERE id = ?", ("v", "someone", 7), "sqlite",
        want_in=("a = :p0, updated_by = :p1", "updated_at = DATETIME", "id = :p2"),
        want_not_in=("updated_by = DATETIME",))

# ⑪ 字面量 % 的转义**只在驱动会插值时**做（无参数时不转义，否则 LIKE 模式当场变错）
cmp_sql("⑪ 无参数不转义 %",
        "SELECT a FROM t WHERE y LIKE '%流水%'", None, "postgres",
        want_in=("LIKE '%流水%'",), want_not_in=("%%",))
cmp_sql("⑪ 有参数才转义 %",
        "SELECT a FROM t WHERE y LIKE '%' || ? || '%'", ("k",), "postgres",
        raw_in=("LIKE '%%' || %(p0)s || '%%'",),
        want_in=("LIKE '%' || k || '%'",))

# ⑫ mysql 的按驱动占位符（sqlglot 给 :name，pymysql 要 %(name)s）+ 拼接换 CONCAT
cmp_sql("⑫ mysql 按驱动改写",
        "SELECT a FROM t WHERE y LIKE '%' || ? || '%'", ("k",), "mysql",
        raw_in=("CONCAT('%%', %(p0)s, '%%')",), raw_not_in=(":p0",),
        want_in=("CONCAT('%', k, '%')",))

# ⑬ PG 的 RETURNING：主键自增时编译期追加（替掉 currval hack）
_r = sqlc._compile_cached("INSERT INTO t (a) VALUES (?)", "postgres", "id", True)
if _r[2] and "RETURNING id" in _r[0]:
    print(f"  ✓ ⑬ PG 追加 RETURNING：{_r[0][-24:]}")
else:
    _fail.append(f"⑬ PG 未追加 RETURNING：{_r}")

# ⑭ 边界必须**明确报错**，不静默
cmp_sql("⑭ 参数个数不匹配", "INSERT INTO t (a, b) VALUES (?, ?)", (1,), "sqlite",
        expect_err="参数个数与占位符不匹配")
cmp_sql("⑭ INSERT 无列清单", "INSERT INTO t DEFAULT VALUES", (), "sqlite",
        expect_err="没有列清单")
cmp_sql("⑭ 语法错", "SELECT FROM WHERE", (), "sqlite", expect_err="SQL 无法解析")

# ⑳ UPSERT：冲突目标**不许带排序修饰符**（2026-09-27 在真 PG 上实测到的编译层缺陷）
#    根因：sqlglot 的 sqlite 解析器把 `ON CONFLICT(a)` 解析成 `Ordered(..., nulls_first=True)`，
#    而 postgres 生成器忠实渲染 ⇒ `ON CONFLICT(a NULLS FIRST)` ⇒ **PG 语法错**（SQLite 侧恰好忽略它，
#    所以本地看不出来）。修法：编译层归一冲突目标（`sqlc._normalize_conflict_keys`）。
#    ⚠ 应用里目前没人用 UPSERT —— `sales_forecast.py:458` 的注释写着"先删后插，避免依赖 ON CONFLICT
#      的方言差异"，前人正是绕开了这个坑。
_upsert = "INSERT INTO t (a,b) VALUES (?, ?) ON CONFLICT(a) DO UPDATE SET b = ?"
for _d in ("sqlite", "postgres"):
    cmp_sql(f"⑳ UPSERT 冲突目标无排序修饰符 [{_d}]", _upsert, ("1", "2", "3"), _d,
            want_in=("ON CONFLICT", "DO UPDATE"), raw_not_in=("NULLS FIRST", "NULLS LAST"))

# ㉑ 六类"新应用可能用到"的形态：**要么忠实、要么响亮失败**（不许静默改写成语义不同的 SQL）
#    出处：2026-09-27 为回答"legacy 还有必要留么"而主动撞编译层的那一轮（7 类里 UPSERT 命中真缺陷 ⑳）
for _label, _sql, _p, _must_in in [
    ("INSERT OR REPLACE 忠实", "INSERT OR REPLACE INTO t (a,b) VALUES (?, ?)", ("1", "2"), "OR REPLACE"),
    ("WITH … UPDATE 忠实", "WITH x AS (SELECT a FROM y) UPDATE t SET b = ? WHERE a IN (SELECT a FROM x)",
     ("v",), "WITH x AS"),
    # ⚠ strftime 一度被我误判为"翻不了"（看到 `%YYYY-%MM` 就下结论）—— 其实是**转义跑在渲染之前**
    #   造成的，顺序修正后它翻得忠实（PG：'YYYY-MM'，无 `%`）。这条现在断言的是"忠实翻译"。
    ("strftime → PG 模板不带 %", "SELECT strftime('%Y-%m', d) AS m FROM t WHERE k = ?",
     ("1",), "TO_CHAR"),

]:
    cmp_sql(f"㉑ {_label}", _sql, _p, "postgres", want_in=(_must_in,))
# 取模 `a % 2` 也要按驱动转义（`%%`）—— ⚠ 断言必须看**未渲染的产物**：
# `text % params` 会把 `%%` 还原成 `%`，渲染后与"没转义"长得一模一样。
cmp_sql("㉑ 取模 % 按驱动转义", "SELECT a % 2 FROM t WHERE k = ?", ("1",), "postgres",
        raw_in=("a %% 2",), want_in=("a % 2",))

# 另三类：**必须响亮失败**（明确 FdeError），不许静默编译成语义不同的语句
cmp_sql("㉑ DEFAULT VALUES 明确拒绝", "INSERT INTO t DEFAULT VALUES", (), "postgres",
        expect_err="没有列清单")
# `datetime(列, 修饰符)` 曾被翻成 CURRENT_TIMESTAMP（"减 7 天"→"当前时间"）—— 现在必须明确拒绝
cmp_sql("㉑ datetime(列,修饰符) 明确拒绝", "SELECT datetime(d, '-7 days') FROM t WHERE k = ?", ("1",),
        "postgres", expect_err="不支持把 DATETIME")
cmp_sql("㉑ julianday 明确拒绝", "SELECT julianday(d) FROM t WHERE k = ?", ("1",),
        "postgres", expect_err="不支持把 JULIANDAY")
cmp_sql("㉑ datetime('now') 放行", "SELECT datetime('now','localtime') AS n FROM t WHERE k = ?", ("1",),
        "postgres", want_in=("CURRENT_TIMESTAMP",))

# ⑮ 缓存**只缓存 SQL 与参数计划，绝不缓存参数值**
_s1, _p1, _m1 = sqlc.compile_sql("UPDATE t SET a = ? WHERE id = ?", (1, 2), {"userno": "甲"})
_s2, _p2, _m2 = sqlc.compile_sql("UPDATE t SET a = ? WHERE id = ?", (1, 2), {"userno": "乙"})
if _p1["u_updated_by"] == "甲" and _p2["u_updated_by"] == "乙":
    print("  ✓ ⑮ 同 SQL 不同身份 → 参数各算各的（没把参数缓存进去）")
else:
    _fail.append(f"⑮ 参数被缓存污染：{_p1} / {_p2}")

print()
print("── C 段：部署侧取连接方式（Engine 注册表，离线可断言）────────────")


def ck(ok, note):
    if ok:
        print(f"  ✓ {note}")
    else:
        _fail.append(note)


# ⑯ 池参数：默认 + 环境变量
os.environ.pop("FDE_PG_POOL_MAX", None)
ck(db._pool_limits() == (2, 10, 30, 1800), f"⑯ 池参数默认 (2,10,30,1800)：{db._pool_limits()}")
os.environ["FDE_PG_POOL_MAX"] = "25"
os.environ["FDE_PG_POOL_TIMEOUT"] = "5"
ck(db._pool_limits()[1] == 25 and db._pool_limits()[2] == 5,
   f"⑯ 环境变量生效：{db._pool_limits()}")

# ⑰ Engine 注册表：URL 与池参数都是键的一部分（换库/换池 → 必须换 Engine）
#    ⚠ 这是"模块级常量缓存"陷阱的同款：键漏了 URL，换库后还指着旧库（见 skills.DB_PATH 的教训）
os.environ.pop("FDE_PG_POOL_MAX", None)
os.environ.pop("FDE_PG_POOL_TIMEOUT", None)
_e1 = db.engine_for("postgresql://u:p@h:5432/db_a")          # 默认池参数（2/10）
ck(db.engine_for("postgresql://u:p@h:5432/db_a") is _e1, "⑰ 同 URL + 同池参数 → 复用同一 Engine")
ck(_e1.pool.size() == 2 and _e1.pool._max_overflow == 8,
   f"⑰ 池参数进了 Engine：size={_e1.pool.size()} overflow={_e1.pool._max_overflow}")
ck(db.engine_for("postgresql://u:p@h:5432/db_b") is not _e1, "⑰ 换库（URL 变）→ 新 Engine")
os.environ["FDE_PG_POOL_MAX"] = "25"                          # 换池参数，URL 不变
ck(db.engine_for("postgresql://u:p@h:5432/db_a") is not _e1,
   "⑰ 换池参数（URL 不变）→ 也是新 Engine（不沿用旧池）")
os.environ.pop("FDE_PG_POOL_MAX", None)

# ⑰b URL 钉驱动：SQLAlchemy 2.1 起 `postgresql://` 默认指 psycopg(v3)，本项目装的是 psycopg2
#     ⇒ 平台必须自己补 `+psycopg2`（用户只写 `postgresql://…`，承诺不变）
ck(db.sa_url("postgresql://u:p@h:5432/d") == "postgresql+psycopg2://u:p@h:5432/d",
   f"⑰b postgresql:// 补成 +psycopg2：{db.sa_url('postgresql://u:p@h:5432/d')}")
ck(db.sa_url("postgres://u:p@h/d") == "postgresql+psycopg2://u:p@h/d", "⑰b postgres:// 别名同样处理")
ck(db.sa_url("postgresql+psycopg2://u:p@h/d") == "postgresql+psycopg2://u:p@h/d",
   "⑰b 已带驱动的不重复补")
ck(db.sa_url("sqlite:///x.db") == "sqlite:///x.db", "⑰b 非 PG URL 原样返回")

# ⑱ 池耗尽必须**明确报错**（不是静默等待、也不是莫名的驱动错）
#    psycopg2 原生池是"立即抛"，Engine 是"等到超时" —— 两条路都要有可读的错误
class _DeadPool:
    def getconn(self):
        raise RuntimeError("connection pool exhausted")


_real_pool, _real_backend = db._PG_POOL, db._PG_BACKEND
try:
    db._PG_POOL = _DeadPool()
    try:
        db._checkout("pool")
        _fail.append("⑱ 池耗尽没有报错")
    except RuntimeError as e:
        ck("连接池耗尽" in str(e) and "FDE_PG_POOL_MAX" in str(e),
           f"⑱ 池耗尽报错可读：{str(e)[:58]}…")
finally:
    db._PG_POOL, db._PG_BACKEND = _real_pool, _real_backend

print()
print("── D 段：PG 侧游标 API 面与 sqlite3.Cursor 对齐（离线可断言）──────────")


class _FakeCur2:
    """最小假游标：只有 sqlite3.Cursor 的常用面（迭代 / fetchall / fetchmany / arraysize）。"""

    def __init__(self, rows):
        self._rows = list(rows)
        self.description = [("a",), ("b",)]
        self.rowcount = len(self._rows)
        self.lastrowid = 0
        self.arraysize = 1

    def __iter__(self):
        return iter(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def fetchmany(self, n=1):
        return self._rows[:n]

    def close(self):
        pass


_w = db._PgCursorWrapper(_FakeCur2([(1, "甲"), (2, "乙")]))
try:
    _it = list(_w)                                     # ⑲ 裸迭代（应用里 22 处这种写法）
    ck(len(_it) == 2 and _it[0]["a"] == 1 and _it[1]["b"] == "乙",
       f"⑲ 游标可迭代且行是字典行：{_it}")
except TypeError as e:
    ck(False, f"⑲ 游标不可迭代（PG 上应用会炸）：{e}")
ck(getattr(_w, "arraysize", None) == 1, "⑲ 未实现的成员透传到底层游标（__getattr__ 兜底）")
ck(len(_w.fetchmany(1)) == 1, "⑲ fetchmany 同样可用（透传）")

print()
if _fail:
    print(f"失败 {len(_fail)} 项：")
    for f in _fail:
        print("  ✗", f)
    sys.exit(1)
print("SQL 方言改写/编译层 + 部署侧取连接方式：全部通过")
