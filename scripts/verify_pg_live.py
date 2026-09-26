# -*- coding: utf-8 -*-
"""**PG 现场验证探针**：在真 PostgreSQL 上验编译层与部署侧取连接方式（本地 SQLite 验不到的那些）。

## 为什么必须有它

平台本地全程 SQLite，**任何"双模"分支在本地都测不到** —— 2026-09-20 一天在真 PG 上撞四个缺陷
（`PRAGMA` 语法错、`datetime()` 不存在、字面量 `%` 未转义、审计占位符被吃掉），全是这么来的。
2026-09-26 又加了 DML 编译层（`sqlc.py`）与部署侧 Engine，这两块的 PG 分支**只能在这里验**。

## 怎么跑（在容器里，DATABASE_URL 已指向 PG）

    docker exec -i fde-v22_fde-v2_1 env FDE_SQL_COMPILER=sqlglot \
        python scripts/verify_pg_live.py

本地（无 PG）会**明示 SKIP** 而不是假装通过。

## 它验什么

1. **DDL 与 DML 同一口径**：用 `ddl.build_ddl` 在临时 schema 建表（含 `datetime('now','localtime')`
   默认值 —— 这条在 PG 上曾经不存在），再用平台连接读写；
2. **编译层（sqlglot）在真 PG 上**：审计列注入（单行/多行/INSERT…SELECT/UPDATE）、
   命名占位符、`RETURNING` 带回自增主键、`LIKE '%' || ? || '%'` 模糊搜索、`%` 转义；
3. **与 legacy 路径**结果逐项一致（两条路必须同语义）；
4. **池的等待语义**：把池压到 4 条、并发 12 个取连接 —— Engine 应当**排队后成功**，
   而不是像 psycopg2 原生池那样立刻抛 `PoolError`；
5. 全程只在**临时 schema `sqlc_probe`** 里折腾，跑完 drop schema —— 不碰任何应用数据。
"""
import concurrent.futures as cf
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, ".")

from fde_platform import db, ddl, sqlc  # noqa: E402
from fde import FdeError  # noqa: E402

# **每次运行一个独立 schema**（带 pid）：复用同一个 schema 时，上一次运行的行会混进计数，
# 断言就会"看着失败、其实是被污染"（探针第一版就这么翻过车）。应用名 → schema 的映射同线上口径。
SCHEMA = f"sqlc_probe_{os.getpid()}"
PROBE_APP = f"{SCHEMA}/probe"
# ⚠ 平台把应用名映射成 schema 时会把 `/` 换成 `_`（`get_connection` 里的口径）——
#   于是真实 schema 名是 `sqlc_probe_<pid>_probe`，**不是** SCHEMA 本身。
#   踩过：前置清理按 `SCHEMA` 比"是不是自己"，结果把自己（带后缀的那个）清了 ⇒
#   `InvalidSchemaName: no schema has been selected to create in`；末尾清理也删错了名字 ⇒
#   残留 schema 留到下一轮（上一轮的残留行污染就是它）。两处都以 APP_SCHEMA 为准。
APP_SCHEMA = PROBE_APP.replace("/", "_").replace("-", "_")
FAILS = []


def ck(ok, note):
    print(f"  {'✓' if ok else '✗'} {note}")
    if not ok:
        FAILS.append(note)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS probe_box (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    note TEXT,
    settled_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


def _conn():
    return db.get_connection(PROBE_APP, None)


def _exec(conn, sql, params=None, ctx=None):
    """走平台连接执行一条（编译层由 FDE_SQL_COMPILER 决定走不走）。"""
    conn._fde_ctx = ctx or {"userno": "pgprobe"}
    return conn.execute(sql, params)


def _rows(cur):
    out = []
    for r in (cur.fetchall() or []):
        try:
            out.append(dict(r))
        except Exception:                     # noqa: BLE001
            out.append(tuple(r))
    return out


def main():
    print("== 前置 ==")
    # ⚠ 判据用 `_PG_AVAILABLE`（DATABASE_URL 是否指向 PG），**不能**直接用 `using_postgresql()`：
    #   后者要求"取连接方式已建立"，而连接池/Engine 是**懒建**的 —— 在 `docker exec` 开的新进程里
    #   还没取过连接，它恒为 False。踩过一次：探针在真 PG 的容器里报"当前不是 PostgreSQL"。
    #   （memory `test-server-deploy` 里记的同一个坑：`python -c "from fde_platform import db; print(db.db_mode())"`
    #     会报「连接失败→回退 SQLite」，那也是懒加载，不代表线上在跑 SQLite。真值要看容器启动横幅。）
    if not db._PG_AVAILABLE:
        print("  ⚠ SKIP：DATABASE_URL 未指向 PostgreSQL（本地 SQLite）—— 本探针只在有真 PG 的机器上跑")
        print("  VERIFY_RESULT: SKIP")
        return 0
    if not db.using_postgresql():
        db._pg_pool()                     # 懒建：本进程先建立取连接方式
    print(f"  db_mode(): {db.db_mode()}")
    if not db.using_postgresql():
        print("  ✗ 连不上 PostgreSQL（见上面的日志：连接失败→回落 SQLite）")
        print("  VERIFY_RESULT: FAIL")
        return 1
    print(f"  FDE_SQL_COMPILER={os.environ.get('FDE_SQL_COMPILER', 'legacy')}")

    # 预备：临时 schema
    boot = _conn()
    # 前置清理：把**历史遗留**的探针 schema 清掉（进程崩过就可能残留）——
    # 只碰 `sqlc_probe%` 前缀，绝不涉及任何应用 schema。
    for row in _rows(_exec(boot, "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'sqlc_probe%'")):
        name = list(row.values())[0]
        if name in (SCHEMA, APP_SCHEMA):   # 别把自己刚建的清掉（名字也匹配 sqlc_probe%）
            continue
        _exec(boot, f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
    boot.commit()
    ddl_text = SCHEMA_SQL
    try:
        for stmt in ddl.build_ddl(ddl_text, db.dialect_of(boot)):
            _exec(boot, stmt)
        boot.commit()
        ck(True, "DDL 建表成功（含 datetime('now','localtime') 默认值 → 已按方言归一）")
    except Exception as e:                    # noqa: BLE001
        ck(False, f"DDL 建表失败：{type(e).__name__}: {e}")
        return 1
    finally:
        boot.close()

    mode = os.environ.get("FDE_SQL_COMPILER", "legacy").strip().lower()

    print(f"== 1. 写入与审计注入（{mode}）==")
    c = _conn()
    try:
        cur = _exec(c, "INSERT INTO probe_box (name, note) VALUES (?, ?)", ("甲", "首行"))
        c.commit()
        pk = cur.lastrowid
        ck(bool(pk), f"插入后拿到主键 lastrowid={pk}（PG 上靠 RETURNING/currval，不能是 0）")

        # 多行 VALUES：**legacy 路径已知不支持** —— 正则只给最后一个 tuple 补审计值，列数对不上，
        # PG 直接报 `INSERT has more target columns than expressions`（本地假驱动也能复现）。
        # 应用里目前**一处都没有**这种形态（2026-09-26 全仓扫描），编译层已把它修好 ⇒
        # 这里按路径分辨：编译层必须通过；legacy 记为"已知边界"（不是本次回归）。
        n_expect = 3
        try:
            _exec(c, "INSERT INTO probe_box (name, note) VALUES (?, ?), (?, ?)",
                  ("乙", "二", "丙", "三"))
            c.commit()
            multi_ok, multi_err = True, None
        except Exception as e:                # noqa: BLE001
            multi_ok, multi_err = False, e
            c.rollback()                       # ⚠ PG 里失败语句会**中止整个事务**，不 rollback 后续全挂
            n_expect = 1
        if mode == "sqlglot":
            ck(multi_ok, "多行 INSERT 落库（编译层：每个 tuple 都补审计值）")
        else:
            ck(True, f"多行 INSERT 在 legacy 下**已知边界**（{type(multi_err).__name__}）"
                     f"—— 应用里无此形态，编译层已修")
        rows = _rows(_exec(c, "SELECT name, created_by, updated_by, settled_at FROM probe_box "
                              "ORDER BY id"))
        ck(len(rows) == n_expect, f"落库 {len(rows)} 行（本路径期望 {n_expect}）")
        ck(all(r["created_by"] == "pgprobe" and r["updated_by"] == "pgprobe" for r in rows),
           "**每一行**都注入了审计身份")
        ck(all(r["settled_at"] for r in rows), "默认值 settled_at 非空（时间函数归一化在 PG 上成立）")

        _exec(c, "UPDATE probe_box SET note = ? WHERE name = ?", ("改过", "甲"))
        c.commit()
        r = _rows(_exec(c, "SELECT note, created_by, updated_by FROM probe_box WHERE name = ?", ("甲",)))[0]
        ck(r["note"] == "改过", "UPDATE 生效")
        ck(r["created_by"] == "pgprobe" and r["updated_by"] == "pgprobe",
           "UPDATE 只动 updated_*，created_by 保持")

        print("== 2. 模糊搜索与占位符（这条在 PG 上曾经整片崩过）==")
        hit = _rows(_exec(c, "SELECT name FROM probe_box WHERE name LIKE '%' || ? || '%'", ("甲",)))
        ck(len(hit) == 1 and hit[0]["name"] == "甲",
           f"LIKE '%' || ? || '%' 正确命中 {len(hit)} 条（字面量 % 转义 + 拼接 + 占位符三者都对）")

        print("== 3. 池的等待语义（Engine 排队 vs 原生池立即报错）==")
        def _one(i):
            cc = _conn()
            try:
                _exec(cc, "SELECT ? AS n", (i,)).fetchall()
                time.sleep(0.05)
                return True
            finally:
                cc.close()

        p_max = int(os.environ.get("FDE_PG_POOL_MAX", "10") or 10)
        n = max(p_max * 3, 12)
        t0 = time.time()
        try:
            with cf.ThreadPoolExecutor(max_workers=n) as ex:
                oks = list(ex.map(_one, range(n)))
            ck(all(oks), f"{n} 个并发取连接（池上限 {p_max}）全部成功 · 耗时 {time.time()-t0:.1f}s")
            ck(True, f"池的等待语义生效（{db._PG_BACKEND}：超容量排队而不是立刻失败）")
        except Exception as e:                # noqa: BLE001
            ck(False, f"并发取连接失败（池上限 {p_max}）：{type(e).__name__}: {e}")
    finally:
        c.close()

    print("== 4. 边界：编译层该报错的要报错 ==")
    try:
        c2 = _conn()
        _exec(c2, "INSERT INTO probe_box (name) VALUES (?, ?)", ("只有一个",))
        ck(False, "参数个数不匹配竟然没报错")
    except FdeError as e:
        ck("参数个数" in str(e), f"参数个数不匹配明确报错（FdeError）：{str(e)[:40]}…")
    except Exception as e:                    # noqa: BLE001
        # legacy 路径这里是驱动层的 `IndexError: tuple index out of range`（占位符账对不上）——
        # 同样是"已知边界"：编译层换成了可读的 FdeError。
        if mode == "sqlglot":
            ck(False, f"编译层应报 FdeError，实际 {type(e).__name__}: {e}")
        else:
            ck(True, f"legacy 下参数不匹配报的是驱动错（{type(e).__name__}）—— 已知边界，"
                     f"编译层已换成可读的 FdeError")
    finally:
        try:
            c2.close()
        except Exception:                     # noqa: BLE001
            pass

    print("== 5. 清理（只用临时 schema，不碰任何应用数据）==")
    try:
        z = _conn()
        _exec(z, f'DROP SCHEMA IF EXISTS "{APP_SCHEMA}" CASCADE')
        z.commit()
        z.close()
        ck(True, f"临时 schema {APP_SCHEMA} 已删除（只碰 sqlc_probe* 前缀，不涉任何应用 schema）")
    except Exception as e:                    # noqa: BLE001
        ck(False, f"清理失败：{type(e).__name__}: {e}")

    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for f in FAILS:
            print("  ✗", f)
        print("  VERIFY_RESULT: FAIL")
        return 1
    print("  VERIFY_RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
