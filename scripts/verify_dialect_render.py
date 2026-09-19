r"""多方言渲染检查（平台级，自包含，**不需要安装任何数据库**）。

## 为什么它能不装库就验方言

「覆盖一个方言」不等于「装一个数据库」。建表 DDL 的生成是一个**纯函数**
（`schema.sql 文本 → 目标方言的 SQL 文本`），所以断言它的输出根本不需要连着那个库。
本脚本就是这么做的：把 `app/**/schema.sql` 逐个渲染成每个目标方言，
检查产物里**有没有留下源方言（SQLite）专有的东西**。

## 它抓的是哪一类问题

源方言里能写、到了目标方言却不存在的东西 —— 例如 `datetime('now','localtime')`：

  · 2026-09-20 实测：`sales_forecast.settled_at` 用了它，PG 侧建表直接
    `function datetime(unknown, unknown) does not exist`，平台起不来；
  · 当天先写成「仅 PG 需要归一化」，随后把 19 个 schema 渲染成 mysql / tsql / oracle
    一看 —— **同样的残留一个不少**。只修脚下那个方言，等于同一件事只做了一半。
    本脚本存在的意义就是让这种「只做一半」当场变红。

## 边界（如实声明）

只验**生成出来的 SQL 文本**，不验它在目标库上是否**语义正确**（那要真库）。
具体说，它能抓「写法残留」（`datetime(`、`strftime(`、`AUTOINCREMENT`…），
抓不到「语法合法但语义不同」（连接池、事务隔离、类型往返）——
后者属于必须在真库上跑的范畴，见 `scripts/verify_pg_translate.py` 的姊妹篇说明。

用法：`python scripts/verify_dialect_render.py`（退出码 0 全过 / 1 有失败）
"""
import io
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from fde_platform import ddl  # noqa: E402

# 目标方言。**加一个方言就在这里加一个字符串** —— 不需要安装那个数据库。
DIALECTS = ["postgres", "mysql", "tsql", "oracle"]

# 源方言（SQLite）专有、且到目标方言必然报错的写法。
# 判据故意放宽成「函数名 + 左括号」：与其漏报，不如让人来确认。
SQLITE_ONLY = re.compile(
    r"\b(strftime|datetime|julianday|ifnull|group_concat|printf|randomblob|zeroblob"
    r"|last_insert_rowid|sqlite_version|total_changes)\s*\(|\bAUTOINCREMENT\b",
    re.I,
)

_fail = []
_checked = 0


def main():
    schemas = sorted(pathlib.Path(ROOT / "app").glob("*/*/schema.sql"))
    if not schemas:
        print("没有找到任何 schema.sql —— 判据成了空规则，本次 PASS 不可信")
        return 1
    print(f"渲染 {len(schemas)} 个 schema × {len(DIALECTS)} 个方言 = "
          f"{len(schemas) * len(DIALECTS)} 份产物\n")

    per_dialect = {}
    for d in DIALECTS:
        bad, empty = [], []
        for f in schemas:
            app = f"{f.parent.parent.name}/{f.parent.name}"
            try:
                out = "\n".join(ddl.build_ddl(f.read_text(encoding="utf-8"), d))
            except Exception as e:
                _fail.append(f"[{d}] {app}：渲染抛错 {type(e).__name__}: {str(e)[:80]}")
                continue
            if not out.strip():
                empty.append(app)
                continue
            hits = sorted({m.group(0).strip().rstrip("(").upper()
                           for m in SQLITE_ONLY.finditer(out)})
            if hits:
                bad.append(f"{app}（残留 {hits}）")
        per_dialect[d] = (len(schemas) - len(bad) - len(empty), bad, empty)
        for x in bad:
            _fail.append(f"[{d}] {x}")
        for x in empty:
            _fail.append(f"[{d}] {x}：渲染结果为空")

    global _checked
    for d, (ok, bad, empty) in per_dialect.items():
        mark = "✓" if not bad and not empty else "⚠"
        line = f"  {mark} {d:9} 干净 {ok}/{len(schemas)}"
        if bad:
            line += f" · 残留源方言写法 {len(bad)}"
        if empty:
            line += f" · 空产物 {len(empty)}"
        print(line)
        _checked += ok

    print()
    if _fail:
        print(f"失败 {len(_fail)} 项：")
        for f in _fail:
            print("  ✗", f)
        print("\n提示：源方言专有的写法要么改 schema.sql、要么在 ddl 的归一化里处理——"
              "**别只给某一个方言开口子**，其余方言会一模一样地残留。")
        return 1
    print(f"多方言渲染：全部通过（{_checked} 份产物，"
          f"{len(DIALECTS)} 个方言，未安装任何数据库）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
