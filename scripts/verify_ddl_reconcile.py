"""DDL 对账补列的验收（平台级，自包含，不需要起服务）。

背景：`CREATE TABLE IF NOT EXISTS` 只在**表**不存在时生效，表已存在就整句跳过——
于是往 `schema.sql` 里加一列，对**已有库**毫无作用，之后读写该列就 `no such column`。
而重跑建库脚本也补不上（演示环境的重置是清空行、不删库文件），应用又没有初始化钩子。

`ddl.execute_schema` 现在会把已有表**对账补齐到 schema.sql 的声明**（只加列、绝不删）。
本脚本用临时库验证这件事，包括边界：

  ① 老库缺列 → 建表语句跑完后，缺的列被补上，**已有数据不动**
  ② 平台注入的审计列同样会被补齐（老表也没有那四列）
  ③ 幂等：再跑一次不重复补、不报错
  ④ 全新库正常建表（对账是空操作）
  ⑤ 不可补的列（NOT NULL 且无默认值）**直接报错**，而不是悄悄降级成可空
  ⑥ 只做加法：schema.sql 里删掉的列**不会**被删（少一列报错是显式的，删一列丢数据是静默的）

用法：`python scripts/verify_ddl_reconcile.py`（退出码 0 全过 / 1 有失败）
"""
import io
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from fde_platform import ddl  # noqa: E402

# 输出编码：控制台代码页在本机默认是 GBK，而本脚本的结论里有 ✓/✗/⚠/⇒ 这类**非 GBK 码位** ——
# 不钉住的话 print 自己会抛 UnicodeEncodeError（**崩在打印结论那一步**），
# 而外层门禁把它显示成「该检查 FAIL」——像判据报了缺陷，其实判据根本没跑完。
# 由 scripts/verify_test_script_encoding.py 守住别忘这一行（它的扫描范围已含 scripts/）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_p = _f = 0


def check(label, ok, detail=""):
    global _p, _f
    if ok:
        _p += 1
        print(f"  ✓ {label}" + (f"  [{detail}]" if detail else ""))
    else:
        _f += 1
        print(f"  ✗ {label}" + (f"  → {detail}" if detail else ""))


def cols(conn, table):
    return {r[1].lower() for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}


def rows(conn, table):
    return conn.execute(f'SELECT * FROM "{table}"').fetchall()


# 老库的表结构：只有两列（模拟"上一版 schema"）
OLD = """
CREATE TABLE IF NOT EXISTS t_demo (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);
"""

# 新声明：多了 qty / note 两列
NEW = """
CREATE TABLE IF NOT EXISTS t_demo (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    qty  REAL,
    note TEXT
);
"""

SAME = """
CREATE TABLE IF NOT EXISTS t_keep (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    gone TEXT
);
"""
SAME_AFTER = """
CREATE TABLE IF NOT EXISTS t_keep (
    id INTEGER PRIMARY KEY AUTOINCREMENT
);
"""

BAD = """
CREATE TABLE IF NOT EXISTS t_bad (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    must TEXT NOT NULL
);
"""


def main():
    print("=" * 74)
    print("DDL 对账补列验收")
    print("=" * 74)

    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "old.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row

        print("\n① 老库缺列 → 补列且不动数据")
        conn.executescript(OLD)
        conn.execute("INSERT INTO t_demo (name) VALUES ('老数据')")
        conn.commit()
        before = cols(conn, "t_demo")
        added = ddl.execute_schema(conn, NEW, "sqlite")
        after = cols(conn, "t_demo")
        check("缺的两列被补上", {"qty", "note"} <= after, f"{sorted(before)} → {sorted(after)}")
        check("返回值报出补了哪些列（含平台注入的审计列）",
              {"t_demo.qty", "t_demo.note"} <= set(added), added)
        rs = rows(conn, "t_demo")
        check("已有数据未被改动", len(rs) == 1 and rs[0]["name"] == "老数据", dict(rs[0]))

        print("\n② 平台注入的审计列同样补齐")
        check("审计列四件套都在",
              {"created_at", "updated_at", "created_by", "updated_by"} <= after,
              sorted(c for c in after if c.endswith(("_at", "_by"))))

        print("\n③ 幂等：再跑一次")
        added2 = ddl.execute_schema(conn, NEW, "sqlite")
        check("第二次不再补、不报错", added2 == [], added2)
        check("列集合不变", cols(conn, "t_demo") == after)

        print("\n④ 全新库正常建表（对账是空操作）")
        db2 = Path(td) / "fresh.db"
        c2 = sqlite3.connect(str(db2))
        c2.row_factory = sqlite3.Row
        added3 = ddl.execute_schema(c2, NEW, "sqlite")
        check("新库列齐", {"id", "name", "qty", "note"} <= cols(c2, "t_demo"))
        check("新库无需补列", added3 == [], added3)

        print("\n⑤ 不可补的列 → 直接报错（不悄悄降级）")
        conn.executescript("CREATE TABLE IF NOT EXISTS t_bad (id INTEGER PRIMARY KEY AUTOINCREMENT);")
        conn.execute("INSERT INTO t_bad (id) VALUES (1)")
        conn.commit()
        err = ""
        try:
            ddl.execute_schema(conn, BAD, "sqlite")   # 声明里多了 must TEXT NOT NULL
        except RuntimeError as e:
            err = str(e)
        check("NOT NULL 无默认值时报错并说清怎么办", "无法自动补" in err and "DEFAULT" in err, err[:90] or "（没报错！）")

        print("\n⑥ 只做加法：schema.sql 里删掉的列不会被删")
        conn.executescript(SAME)
        conn.execute("INSERT INTO t_keep (gone) VALUES ('还在')")
        conn.commit()
        ddl.execute_schema(conn, SAME_AFTER, "sqlite")
        check("列还在（没被自动删）", "gone" in cols(conn, "t_keep"), sorted(cols(conn, "t_keep")))
        check("数据还在", len(rows(conn, "t_keep")) == 1)

        conn.close()
        c2.close()

    print("\n" + "=" * 74)
    print(f"通过 {_p} 项，失败 {_f} 项")
    print("=" * 74)
    return 1 if _f else 0


if __name__ == "__main__":
    sys.exit(main())
