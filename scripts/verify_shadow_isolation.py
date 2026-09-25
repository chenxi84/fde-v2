# -*- coding: utf-8 -*-
"""隔离机制自检：**影子库真的在起作用吗**？（只读；不 import `app/` 下任何代码）

## 为什么需要这一层

`fde_platform/shadowdb.py` 是所有测试的**安全底座**：它把业务库复制一份、把读写导向副本，
于是「真库零字节接触」成立。但它曾经有一个**谁都不报错的偏差**：

- 复制按**仓库树形**落盘（`<影子>/app/<组>/<应用>/<应用>.db`）
- 运行期按**扁平**去找（`runtime.py` 的 `Path(FDE_DB_ROOT) / f"{name}.db"`）

⇒ 找不到副本，SQLite 就在 `<影子>/<应用>.db` **新建一个空库**顶上。
真库确实没被碰（安全承诺成立），但**"跑在副本上"是假的** ——
凡是「想读真演示数据、又不想有任何风险」的用法，会**静默拿到空库**：不报错、不变红，
只会得出"数据是空的"这种结论。2026-09-18 修掉，本脚本就是那次的**回归守卫**。

## 五条判据（每条都能失败）

| # | 判据 | 失败意味着 |
|---|---|---|
| ① | 副本按**运行期规则**都找得到（业务库 + `config=True` 时的平台库） | 布局与解析规则脱节（上面那类偏差回来了） |
| ② | 副本内容 == 真库内容（逐库「全表行数总和」；直连 SQLite，不复用被测代码） | 复制漏了库 / 复制的是旧快照 |
| ③ | `env` 路径下平台解析出的 `db_path` **全在影子目录内** | 环境变量穿透失效（子进程会写到真库） |
| ④ | 平台各模块（users/scheduler/llm/flow/alerts/logs）解析出的 config 路径**都在影子目录内** | 某个模块还硬编码真 `config/`（测试会写真库、真发定时任务） |
| ⑤ | 全程真库文件 `(size, mtime_ns)` 不变 | **红线破了**：测试碰到了真库 |

> ③ 是"穿透真的生效"的直接证据，比"调一次服务看行数"更贴近机制本身（而且不依赖任何应用语义）。
> ④ 是 2026-09-18 补的：它红了就说明**某个平台模块还硬编码真 `config/`**（测试会写真库、真发定时任务）。
> ⑤ 是红线判据：它红了就没有"跑在副本上"这回事，别的都不用看了。

用法：`python scripts/verify_shadow_isolation.py`（**不停服、不动业务数据**）
"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fde_platform.shadowdb import (  # noqa: E402
    business_dbs, platform_dbs, shadow_dbs, missing_shadows,
)

# 输出编码：控制台代码页在本机默认是 GBK，而本脚本的结论里有 ✓/✗/⚠/⇒ 这类**非 GBK 码位** ——
# 不钉住的话 print 自己会抛 UnicodeEncodeError（**崩在打印结论那一步**），
# 而外层门禁把它显示成「该检查 FAIL」——像判据报了缺陷，其实判据根本没跑完。
# 由 scripts/verify_test_script_encoding.py 守住别忘这一行（它的扫描范围已含 scripts/）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAILS = []


def ok(cond, msg, detail=""):
    print(f"  {'✓' if cond else '✗'} {msg}" + (f" —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(msg)
    return cond


def total_rows(db: Path) -> int:
    """该库全部用户表的行数总和（**只读**打开：`mode=ro`，不会写 -wal/-shm）。"""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return sum(conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables)
    finally:
        conn.close()


def snapshot(paths) -> dict:
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in paths if p.exists()}


def main() -> int:
    real_dbs = [p for p in business_dbs() if p.suffix == ".db"]      # 排除 -wal/-shm
    cfg_dbs = [p for p in platform_dbs() if p.suffix == ".db"]
    print(f"业务库 {len(real_dbs)} 个 · 平台库 {len(cfg_dbs)} 个")
    if not real_dbs:
        print("⚠ 一个业务库都没有 —— 判据成了空规则，本次 PASS 不可信")
        return 1

    before = snapshot(real_dbs + cfg_dbs)
    real_totals = {p.name: total_rows(p) for p in real_dbs}

    print("\n① 副本按运行期规则可解析（业务库 / 平台库）")
    with shadow_dbs(env=True, inprocess=False, config=True) as shadow:
        miss_b = missing_shadows(shadow, config=False)
        miss_c = missing_shadows(shadow, config=True)
        ok(not miss_b, f"业务库副本 {len(real_dbs)} 个全部可解析", f"缺 {miss_b[:5]}")
        ok(not miss_c, f"平台库副本随 config=True 一起可解析（共 {len(cfg_dbs)} 个）", f"缺 {miss_c[:5]}")

        print("\n② 副本内容 == 真库内容（全表行数总和）")
        bad = []
        for name, n in real_totals.items():
            copy = shadow / name
            if not copy.exists():
                bad.append(f"{name}: 副本不存在")
                continue
            m = total_rows(copy)
            if m != n:
                bad.append(f"{name}: 真库 {n} 行 vs 副本 {m} 行")
        ok(not bad, f"{len(real_totals)} 个业务库逐一比对（合计 {sum(real_totals.values())} 行）",
           "；".join(bad[:5]))

        print("\n③ env 路径下平台解析出的 db_path 全在影子目录内")
        from fde_platform.runtime import FdePlatform
        pf = FdePlatform()
        pf.load_all()
        names = list(pf.app_names())
        outside = []
        for qn in names:
            p = Path(pf.handle(qn).db_path)
            try:
                p.relative_to(shadow)
            except ValueError:
                outside.append(f"{qn} → {p}")
        ok(names and not outside,
           f"{len(names)} 个应用的库路径都指向副本（影子目录 {shadow.name}）",
           "；".join(outside[:5]))

        print("\n④ 平台各模块解析出的 config 路径也都在影子目录内")
        # 这条是 2026-09-18 补的（当天更晚）：原先 `FDE_CONFIG_ROOT` 只有 users.py 认，
        # 于是测试起的平台**真读真 cron、把 run 记录写进真 scheduler.db**。现在各模块统一走
        # `config_paths.config_path()`，这里逐个模块把"它实际会用的路径"要出来核对一遍 ——
        # ⚠ **必须调函数/现算，不能读模块级常量**：常量是 import 期求值的，刚好绕过这条判据。
        from fde_platform import users, scheduler, integration, llm, flow, alerts, logging_config
        from fde_platform.config_paths import config_path
        probes = [
            ("users/auth", Path(users.db_path())),
            ("scheduler", config_path("scheduler.db")),
            ("integration", config_path("integration.db")),
            ("llm", config_path("llm.db")),
            ("llm 主密钥", config_path("llm_master.key")),
            ("flow 进度库", config_path("flow_runs.db")),
            ("alerts", config_path("agent_alerts.db")),
            ("日志目录", config_path("logs")),
        ]
        escaped = []
        for name, path in probes:
            try:
                path.relative_to(shadow)
            except ValueError:
                escaped.append(f"{name} → {path}")
        ok(not escaped, f"{len(probes)} 处平台路径都指向副本", "；".join(escaped))

    after = snapshot(real_dbs + cfg_dbs)
    print("\n⑤ 真库零接触（size + mtime_ns 全程不变）")
    changed = [k for k in before if before[k] != after.get(k)]
    ok(not changed, f"{len(before)} 个真库文件逐一比对", "；".join(changed[:5]))

    print()
    if FAILS:
        print(f"VERIFY_RESULT: FAIL（{len(FAILS)} 条）")
        return 1
    print("VERIFY_RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
