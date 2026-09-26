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

# ⑮ 缓存**只缓存 SQL 与参数计划，绝不缓存参数值**
_s1, _p1, _m1 = sqlc.compile_sql("UPDATE t SET a = ? WHERE id = ?", (1, 2), {"userno": "甲"})
_s2, _p2, _m2 = sqlc.compile_sql("UPDATE t SET a = ? WHERE id = ?", (1, 2), {"userno": "乙"})
if _p1["u_updated_by"] == "甲" and _p2["u_updated_by"] == "乙":
    print("  ✓ ⑮ 同 SQL 不同身份 → 参数各算各的（没把参数缓存进去）")
else:
    _fail.append(f"⑮ 参数被缓存污染：{_p1} / {_p2}")

print()
if _fail:
    print(f"失败 {len(_fail)} 项：")
    for f in _fail:
        print("  ✗", f)
    sys.exit(1)
print("SQL 方言改写/编译层：两条路全部通过")
