r"""PG 方言改写层的验收（平台级，自包含，**不需要 PostgreSQL、不需要起服务**）。

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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from fde_platform import db  # noqa: E402

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
if _fail:
    print(f"失败 {len(_fail)} 项：")
    for f in _fail:
        print("  ✗", f)
    sys.exit(1)
print("PG 方言改写层：全部通过")
