# -*- coding: utf-8 -*-
"""三要素**内容**核对：`输出` 指的字段、`生效点` 指的调用链，在对不对得上代码？

## 与 T3 / T4 的分工（三件事，别混）

| 判据 | 问的是 | 在哪 |
|---|---|---|
| **T3** | 三要素**在不在**（机器读得出来吗） | `scan_structure.py`（字面串） |
| **T4** | `输出` 字段**有没有被断言引用过** | `scan_structure.py` + `br_coverage.py` |
| **本脚本** | 三要素写的**东西存不存在** | 这里 |

**为什么需要它**：T3 只认「三条 bullet 在不在」，于是把 `demand.gross_qty` 拼成
`demand.gross_qtyy`、把 `demand.build_gross` 拼成 `demand.build_grosss`，T3 照样通过 ——
而这两条会把下游（第④步的字段级覆盖、第③步的可达性）**指向一个不存在的东西**，
看上去还特别像对的。

## 判据（只认能机械判定的部分）

- **`输出`**（`无（拒绝…` / 含「派生量」「中间量」的行不判）：
  行内至少要有一个能对上 `schema.sql` 真实列名的名字；**且**任何 `应用.X` / `表.X` 形式
  必须解析得开 —— X 要么是该处真实存在的列，**要么**是那条链上的服务名（详设里常顺手写
  「下游用途：`sales_forecast.calc_baseline` 选算法」，那是散文不是字段）。
- **`生效点`**：行内每个反引号 token 逐个解析 —
  · `应用.服务` → 该应用里得真有这个方法
  · 裸 `服务名` → 组内**任一**应用的公共方法（`_` 前缀 → 任一应用的内部方法）
  · **是应用名 / 表名 / 列名** → 放行（那是散文里提到的名词，如「消费方：`sales_forecast`」）
  · 白名单里的记号（`ctx` / `FdeError` / `md_monthly_version` 等）→ 放行
  解析不开的报 FAIL。

> ⚠ **首版 11 处全是假警报**（2026-09-17，已修）：把散文里的**字段名**（`replenish_qty`）、
> **应用名**（`sales_forecast`）、**返回键**（`errors` / `fail`）当成服务名报了错。
> 与对账器那批自纠同类：**判据要把「散文里提到的名词」与「断言的对象」分开**，
> 否则一上手就是一片假红 —— 而假红多了，人就学会无视它。

## 用法

    python scripts/br_meta_check.py [-g psc] [-a 应用名 …]
"""
import argparse
import ast
import re
import sys
from pathlib import Path

# 输出编码：控制台代码页在本机默认是 GBK，而本脚本的结论里有 ✓/✗/⚠/⇒ 这类**非 GBK 码位** ——
# 不钉住的话 print 自己会抛 UnicodeEncodeError（**崩在打印结论那一步**），
# 而外层门禁把它显示成「该检查 FAIL」——像判据报了缺陷，其实判据根本没跑完。
# 由 scripts/verify_test_script_encoding.py 守住别忘这一行（它的扫描范围已含 scripts/）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
GROUP = "psc"

# 生效点里常见、但不是服务名的记号（放行，不算错）
NOT_SERVICE = {
    "ctx", "self", "db", "fde", "sql", "json", "schema.sql", "应用详设.md",
    "FdeError", "None", "True", "False", "list", "get", "size", "page", "v202608",
    "v202609", "status", "草稿", "发布（锁定）", "冻结", "demand_pool", "n+1",
}

# 生效点行里常见的**非服务名**名词（返回键 / 参数名 / 概念），放行
_EXTRA_NOUNS = {"errors", "fail", "success", "total", "items", "rows", "data",
                "material_no", "version_no", "customer_no", "opening_stock",
                "replenish_qty", "replenish_no", "plan_version", "settled_skipped",
                "settled_rows", "breach_count", "replenishments", "summary_rows",
                "row_count", "material_count", "message", "list_rows", "line_rows"}

_SCHEMA_CACHE, _METHOD_CACHE = {}, {}
# 平台注入的审计列（`ddl.py::AUDIT_COLUMNS`）—— `schema.sql` 里不写，但运行期存在
AUDIT_COLUMNS = ("created_at", "updated_at", "created_by", "updated_by")
_BR_RE = re.compile(r"^####\s+3\.\d+\.\d+\s+`(BR-\d+)`", re.M)
_OUT_RE = re.compile(r"^- \*\*输出\*\*:\s*(.+)$", re.M)
_EFF_RE = re.compile(r"^- \*\*生效点\*\*:\s*(.+)$", re.M)
_TOK_RE = re.compile(r"`([^`]+)`")
_META_HEAD_RE = re.compile(r"^#{3,6}\s*.*BR\s*结构化信息.*$", re.M)


def _structured_table(text):
    """**表格载体**的三要素：{BR: (依赖输入, 输出, 生效点)}。

    本仓有两种载体（`design-plus/应用设计.md`）：PSC 用编号小节 bullet，`app/e2e` 用
    「BR 结构化信息」**表格**。本脚本此前**只认 bullet** ⇒ 对 e2e 报「0 条 BR」还打印
    「✓ 全部对得上」—— **分母为 0 的假绿**。`br_coverage.py` 早就认这张表（`_table_outputs`），
    所以这又是一次「同一套词汇在两个工具里只认一半」。判据必须两种载体都认。

    表头不写死：按表头里含「输出」「生效点」「依赖输入」的列定位；定位不到就不认这一行
    （宁可漏读、也不猜列）。
    """
    m = _META_HEAD_RE.search(text)
    if not m:
        return {}
    rows, header = {}, None
    for ln in text[m.end():].splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            if header is not None:
                break                 # 表格结束
            continue
        # ⚠ **不要剥单元格里的反引号**：下游判据靠 `` ` `` 划出 token（`task.task_no`），
        # 剥掉就变成裸文本、一个 token 都读不出来 ⇒ 全表报"没有能对上的真实列名"（首版就这么错的）。
        cells = [c.strip() for c in s.strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue                  # 分隔行
        if not cells or not re.fullmatch(r"BR-\d+", cells[0].strip("`")):
            continue

        def col(name, fallback):
            for i, h in enumerate(header):
                if name in h:
                    return i
            return fallback

        i_dep, i_out, i_eff = col("依赖输入", 1), col("输出", 2), col("生效点", 3)
        if max(i_out, i_eff) >= len(cells):
            continue
        rows[cells[0].strip("`")] = (cells[i_dep] if i_dep < len(cells) else "",
                                       cells[i_out], cells[i_eff])
    return rows


def app_dirs(group):
    return sorted(p for p in (ROOT / "app" / group).iterdir()
                  if p.is_dir() and (p / "应用详设.md").exists())


def schema(group, app):
    """该应用 schema.sql 里的 {表名: {列名}}（另给一个全部列名的并集）。"""
    if app in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[app]
    tables, cur = {}, None
    path = ROOT / "app" / group / app / "schema.sql"
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*CREATE TABLE (?:IF NOT EXISTS )?([a-z_][a-z0-9_]*)", ln, re.I)
            if m:
                cur = m.group(1).lower()
                tables.setdefault(cur, set())
                continue
            if cur:
                m = re.match(r"\s+([a-z_][a-z0-9_]*)\s+[A-Za-z(]", ln)
                if m:
                    tables[cur].add(m.group(1).lower())
    cols = set().union(*tables.values()) if tables else set()
    # **审计列是平台注入的**（CONVENTION §6 / `ddl.py::AUDIT_COLUMNS`）：`schema.sql` 里不写，
    # 但运行期真的有。`br_coverage.py` 早就把 4 列并进去了，本脚本没并 ⇒ `task.updated_at`
    # （BR-15 的输出）被报成"既不是列也不是方法"。同一件事的工具口径又要对齐一次。
    cols = cols | set(AUDIT_COLUMNS)
    tables = {t: (c | set(AUDIT_COLUMNS)) for t, c in tables.items()}
    _SCHEMA_CACHE[app] = (tables, cols)
    return _SCHEMA_CACHE[app]


def methods(group, app):
    """该应用主文件里 {公共方法} / {全部方法}（含 `_` 前缀）/ {全部参数名}。

    参数名也要收：详设的 `生效点` 行里常写「（`confirm` 未传时抛 `FdeError` 拦截）」——
    那是**参数名**，不是服务名（首版把它当服务名报了假警报）。
    """
    if app in _METHOD_CACHE:
        return _METHOD_CACHE[app]
    pub, allm, params = set(), set(), set()
    path = ROOT / "app" / group / app / f"{app}.py"
    if path.exists():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for fn in node.body:
                    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            or fn.name.startswith("__"):
                        continue
                    allm.add(fn.name)
                    if not fn.name.startswith("_"):
                        pub.add(fn.name)
                    for a in list(fn.args.args) + list(fn.args.kwonlyargs):
                        if a.arg not in ("self", "cls"):
                            params.add(a.arg)
    _METHOD_CACHE[app] = (pub, allm, params)
    return _METHOD_CACHE[app]


def _looks_like_code(tok):
    """像代码片段/算式而不是标识符的 token —— 一律不判（详设里常顺手写 `` `1.65×σ` ``）。"""
    return bool(re.search(r"[()\[\]{}=×÷+\s:;'\"]", tok)) or re.match(r"\d", tok)


def main():
    ap = argparse.ArgumentParser(description="三要素内容核对（字段名/服务名存不存在）")
    ap.add_argument("-g", "--group", default="psc")
    ap.add_argument("-a", "--apps", nargs="*", default=None, help="只查这些应用")
    args = ap.parse_args()
    global GROUP
    GROUP = args.group

    all_apps = [p.name for p in app_dirs(GROUP)]
    group_pub, group_all, group_cols, group_tables, group_params = set(), set(), set(), set(), set()
    for a in all_apps:
        p, al, pa = methods(GROUP, a)
        group_pub |= p
        group_all |= al
        group_params |= pa
        t, c = schema(GROUP, a)
        group_tables |= set(t)
        group_cols |= c
    targets = args.apps or all_apps

    total = bad = 0
    problems = []
    per_app = []
    for app in targets:
        text = (ROOT / "app" / GROUP / app / "应用详设.md").read_text(encoding="utf-8")
        tables, cols = schema(GROUP, app)
        all_tables = {t for a in all_apps for t in schema(GROUP, a)[0]}
        heads = list(_BR_RE.finditer(text))
        meta_tbl = _structured_table(text)
        if not heads and not meta_tbl:
            continue

        # 两种载体汇总成 [(br, 输出行, 生效点行)]：bullet 优先，表格补缺
        pairs, from_bullet = [], set()
        for k, m in enumerate(heads):
            end = heads[k + 1].start() if k + 1 < len(heads) else len(text)
            block = text[m.end():end]
            mo, me = _OUT_RE.search(block), _EFF_RE.search(block)
            if not mo or not me:
                continue                      # 三要素缺失由 T3 管，这里不重复报
            from_bullet.add(m.group(1))
            pairs.append((m.group(1), mo.group(1), me.group(1)))
        for br, (_dep, out_line, eff_line) in meta_tbl.items():
            if br in from_bullet or not out_line or not eff_line:
                continue
            pairs.append((br, out_line, eff_line))

        declared = len(heads) + len([b for b in meta_tbl if b not in from_bullet])
        # **分母闸**：写了 BR 却一条三要素都读不出来 ⇒ 不是"全对"，是"没看"
        if declared and not pairs:
            problems.append(
                f"{app}：声明了 {declared} 条 BR，却没能从任何载体读出三要素 —— "
                f"大概率是**载体形态变了**（本脚本认 bullet 与「BR 结构化信息」表两种），"
                f"**不是「全部对得上」**")
        per_app.append(f"{app} {len(pairs)}/{declared}")

        for br, out_line, eff_line in pairs:
            total += 1

            # ── 输出：要么是拒绝/中间量/行集/显式"填不出"，要么至少有一个真实列名 ──
            # **词表必须与 `br_coverage._classify_output_line` 完全一致**（同一套词汇在两个
            # 工具里各认一半，是本仓踩过最多的自伤）：拒绝 = `无（拒绝`；中间量 = 「派生量」「中间量」；
            # 行集 = 「列表」「行集」；显式填不出 = `—` / `**—**` / 「（填不出）」。
            if not out_line.startswith("无（") and "派生量" not in out_line \
                    and "中间量" not in out_line and "（填不出）" not in out_line \
                    and out_line.strip().strip("*") != "—" \
                    and "列表" not in out_line and "行集" not in out_line:
                resolved = False
                for tok in _TOK_RE.findall(out_line):
                    tok = tok.strip()
                    if not tok or _looks_like_code(tok):
                        continue
                    if "." in tok:
                        parts = tok.split(".")
                        pre, tail = parts[0], parts[1]
                        tail_l = tail.lower()
                        if pre in all_apps:                 # 应用.X（X 可为列 / 方法 / JSON 路径）
                            if tail_l in schema(GROUP, pre)[1]:
                                resolved = True             # `md_material.sigma_l` / `x.detail_json.候选`
                            elif tail in methods(GROUP, pre)[1]:
                                pass                        # 散文里提的"下游用途：某服务"
                            else:
                                problems.append(f"{app} {br} 输出：`{tok}` 既不是列也不是方法")
                        elif pre in all_tables:             # 表.列
                            if tail_l in tables.get(pre, set()) or tail_l in group_cols:
                                resolved = True
                            else:
                                problems.append(f"{app} {br} 输出：`{tok}` 这个列不存在")
                        elif tail in group_all or tail in group_pub:
                            pass                            # 服务名（散文）
                        else:
                            problems.append(f"{app} {br} 输出：`{tok}` 里的 `{pre}` 既不是应用也不是表")
                    elif tok.lower() in cols:
                        resolved = True
                if not resolved:
                    problems.append(f"{app} {br} 输出：整行没有一个能对上的真实列名 —— {out_line[:60]}")

            # ── 生效点：每个 token 都要能解析 ──
            for tok in _TOK_RE.findall(eff_line):
                tok = tok.strip()
                if not tok or _looks_like_code(tok) or tok.lower() in NOT_SERVICE:
                    continue
                # 散文里提到的**名词**（应用 / 表 / 字段 / 参数 / 返回键）放行 ——
                # 首版把它们当服务名，全是假警报（见文件头）
                if tok.lower() in group_cols or tok in group_tables or tok in all_apps \
                        or tok in group_params or tok.lower() in _EXTRA_NOUNS:
                    continue
                if "(" in tok:                       # `md_material.list(status=正常)` 形式
                    tok = tok.split("(")[0].strip()
                if "." in tok:
                    parts = tok.split(".")
                    pre, svc = parts[0], parts[1]
                    if pre not in all_apps:
                        continue                     # 形态像 `a.b` 但 a 不是应用（散文/文件名）
                    pub, allm, _pa = methods(GROUP, pre)
                    if svc in schema(GROUP, pre)[1]:
                        pass                         # 写的是**字段**（`md_material.service_level`）
                    elif svc.startswith("_"):
                        if svc not in allm:
                            problems.append(f"{app} {br} 生效点：`{tok}` 这个内部方法不存在")
                    elif svc not in pub and svc not in allm:
                        problems.append(f"{app} {br} 生效点：`{tok}` 这个方法不存在")
                else:
                    if not re.fullmatch(r"_?[a-z_][a-z0-9_]*", tok):
                        continue
                    if tok.startswith("_"):
                        ok = tok in group_all
                    else:
                        ok = tok in group_pub
                    if not ok:
                        problems.append(f"{app} {br} 生效点：`{tok}` 在全组找不到对应方法")

    print(f"核对：{len(targets)} 个应用 / {total} 条 BR 的三要素内容")
    if per_app:
        print(f"  · 逐应用（核到/声明）：{'、'.join(per_app)}")
    if problems:
        print(f"⚠ {len(problems)} 处对不上代码：")
        for p in problems[:40]:
            print(f"  · {p}")
        if len(problems) > 40:
            print(f"  · …另 {len(problems) - 40} 处")
    else:
        print("✓ 全部对得上：`输出` 的列名与 `生效点` 的服务名都能在代码里找到")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
