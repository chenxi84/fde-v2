# -*- coding: utf-8 -*-
"""BR 输出字段级覆盖取证：把「详设三要素里的 `输出`」与「测试脚本里 TC 步的断言」对上。

## 为什么要有它

`design-plus/应用测试.md` 与 `验证门禁.md` 把覆盖度的口径改了：

    旧：每条 BR 能对到至少一条用例          → 100% ✅   （这是**文档工作**）
    新：每条 BR 的 `输出` 字段被至少一条用例的**断言**引用过 → 才是**测试**

「有编号对应用例」与「规则被验证」是两件事 —— 实测某组"BR 覆盖度 100%"里，
`补货量分档` 的输出**从没有任何断言检查过**，两条用例只断言「建单成功」。

## 判据（只认断言，不认实参）

- 取数：各应用《应用详设》「业务规则」节里每条 BR 的 **`- **输出**:`** 那一行；
  只有能对上 `schema.sql` 真实列名的名字才参与判定（表名/服务名/散文自动排除）。
- 比对：`verify_chain_<组>_part*.py` 里按 `step("TC-…")` 切块，
  **块内含 `assert` 且出现该列名**才算引用。
- 因此「字段只作实参出现」**不算覆盖** —— 实测 PSC 有 6 条 BR 栽在这里
  （`replenish_type` / `required_inbound` / `promised_inbound` / `biz_date` …）。
- `输出` 为「无（拒绝）」（产物就是报错）或含「派生量」的 BR 不参与本判据。

## 用法

    python scripts/br_coverage.py            # 逐条打印 + 汇总
    python scripts/br_coverage.py --md       # 只输出 markdown 表格（贴进《测试用例.md》）
    python scripts/br_coverage.py --write    # 直接把表格写回《测试用例.md》的标记之间

⚠ 本脚本与 `verify_psc_oracles.py` 一样**是 PSC 专属的**（应用清单写死）；
推广到别的组要按 `design-plus/验证门禁.md` §九 参数化。
"""
import argparse
import re
import sys
from collections import defaultdict
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

def apps(group=None):
    """取数范围：**该组有 schema.sql 的全部应用**（不写死清单）。

    ⚠ 必须是**函数**而不是模块级常量：常量在 import 时按当时的 `GROUP` 定死，
    跑别的组时会去 `app/<别的组>/<本组应用>/` 里找 schema.sql 与详设 —— 直接炸。
    （2026-09-17 给 e2e 组接入判据时踩到：T4 报「取证工具执行失败 FileNotFoundError」。）
    """
    base = ROOT / "app" / (group or GROUP)
    return tuple(sorted(p.name for p in base.iterdir() if (p / "schema.sql").exists()))         if base.exists() else ()


def all_apps(group=None):
    """该组**全部**应用目录（含无 schema.sql 的），用于解析 `应用.列` 形式。"""
    base = ROOT / "app" / (group or GROUP)
    return tuple(sorted(p.name for p in base.iterdir() if p.is_dir())) if base.exists() else ()

def spec_path(group=None):
    return ROOT / "app" / (group or GROUP) / "测试用例.md"


BEGIN, END = "<!-- BR-COVERAGE:BEGIN -->", "<!-- BR-COVERAGE:END -->"

_SCHEMA_CACHE = {}


def schema_columns(app):
    """该应用 schema.sql 里的列名 —— 只有真列才参与覆盖判定（排除表名/服务名/散文）。"""
    if app in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[app]
    path = ROOT / "app" / GROUP / app / "schema.sql"
    cols = set()
    if path.exists():
        for m in re.finditer(r"^\s+([a-z_][a-z0-9_]*)\s+[A-Za-z]",
                            path.read_text(encoding="utf-8"), re.M):
            cols.add(m.group(1))
    # ⚠ **审计列是平台注入的**（CONVENTION §1：自动追加 created_at/updated_at/created_by/updated_by），
    # schema.sql 里查不到，但运行期真实存在 ⇒ 必须认，否则把 `task.updated_at` 误判成"列名不存在"
    # （2026-09-17 给 e2e 组接入时踩到）。
    _SCHEMA_CACHE[app] = (cols | {"created_at", "updated_at", "created_by", "updated_by"}) - {"id"}
    return _SCHEMA_CACHE[app]




def _classify_output_line(line, cols):
    """把「输出」那一行的文字判成 (kind, [(显示名, 匹配列名)])。两种载体共用。"""
    line = (line or "").strip()
    if line.startswith("无（拒绝"):
        return ("reject", [])
    # **显式声明"填不出"**（`—（填不出）` / `—`）：不是缺陷，是"这条不是可校验的规则"
    # —— e2e 的 `member BR-11/BR-12` 正是如此（能力缺失声明 + 架构约束），
    # 详设里写明了理由。单独归一档，免得判据把它们当"待修"。
    if line in ("—", "**—**") or "（填不出）" in line:
        return ("na", [])
    # 「派生量」与「中间量」两个词都认 —— 口径要与 `br_meta_check.py` 和给执行体的模板一致。
    # （2026-09-17 踩过：本脚本只认「派生量」，于是把 4 条写成「中间量（…，不落库）」的
    #   BR 报成「输出读不出列名」——**同一套词汇在两个工具里各认一半**，是最典型的自伤。）
    if line.startswith("无（") or "派生量" in line or "中间量" in line:
        return ("derived", [])
    names = []
    for tok in re.findall(r"`([^`]+)`", line):
        tok = tok.strip()
        if "." in tok:                      # `表.列` 或 `应用.列`
            app2, col = tok.rsplit(".", 1)
            if app2 in all_apps() and col in schema_columns(app2):
                names.append((f"{app2}.{col}", col))
            elif col in cols:
                names.append((col, col))
            continue
        if tok in cols:
            names.append((tok, tok))
    if not names and ("列表" in line or "行集" in line):
        return ("derived", [])          # 返回的是行集，不落单个字段
    return ("fields", names)


def _table_outputs(text):
    """**PRD 表格载体**：`BR 结构化信息` 表的第 3 列（输出）。

    本仓有两种三要素载体（`design-plus/应用设计.md`）：PSC 用编号小节（bullet），
    `app/e2e` 用 PRD 表格。**判据要认两种** —— 否则换个组就静默读不到（T4 会 SKIP 而不是查）。
    """
    m = re.search(r"^#{3,6}\s*.*BR\s*结构化信息.*$", text, re.M)
    if not m:
        return {}
    out = {}
    for ln in text[m.end():].splitlines():
        s = ln.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) >= 3 and re.fullmatch(r"`?BR-\d+`?", cells[0]):
                out[cells[0].strip("`")] = cells[2]
        elif out and s:
            break                            # 表格结束
    return out


def br_output_fields(app):
    """{BR: (kind, [(显示名, 匹配用的列名)])} —— 读详设三要素里的「输出」那一行。

    kind ∈ {reject（产物=报错）, derived（派生量/中间量，不落字段）, fields}

    词汇表（与 `br_meta_check.py` 必须一致）：`无（拒绝…` = reject；
    含「派生量」或「中间量」或 `无（` 开头 = derived；其余按字段行解析。
    """
    text = (ROOT / "app" / GROUP / app / "应用详设.md").read_text(encoding="utf-8")
    cols = schema_columns(app)
    out = {}
    # 块边界 = 下一个**任意层级**的标题（或文末）。⚠ 2026-09-18 修：原边界只认 `^#### 3.2.`
    # 与 `^### `，于是**每节最后一条 BR 被静默丢掉** —— 若它后面跟的是 `#### 3.3.x`（既不是 3.2.x、
    # 也不是 3 个 #），lookahead 无处可落 ⇒ 整个 finditer 匹配失败 ⇒ 该 BR 不进报告，
    # 而报告照样打印「0 条未覆盖」。`sales_history BR-11` 就是这样长期不在分母里的。
    for m in re.finditer(r"^####\s+3\.\d+\.\d+\s+`(BR-\d+)`.*?(?=^#{2,6}\s|\Z)",
                         text, re.M | re.S):
        br, block = m.group(1), m.group(0)
        mm = re.search(r"^- \*\*输出\*\*:\s*(.+)$", block, re.M)
        out[br] = _classify_output_line(mm.group(1), cols) if mm else ("none", [])
    # **PRD 表格载体**兜底：bullet 里没有的 BR，去「BR 结构化信息」表里取（见 `_table_outputs`）
    for br, cell in _table_outputs(text).items():
        if br not in out:
            out[br] = _classify_output_line(cell, cols)
    # **分母自检**：详设里声明了 BR 标题、却没进上面的字典 ⇒ 一律报出来（宁可吵，不可静默漏）
    for m in re.finditer(r"^####\s+3\.\d+\.\d+\s+`(BR-\d+)`", text, re.M):
        if m.group(1) not in out:
            out[m.group(1)] = ("none", [])
    return out


# **断言词汇表要认三种写法**（2026-09-25 加，实测 nasa_pms 因只认 `assert` 被判「79 条 BR 里 77 条未覆盖」）：
#   · `assert <cond>`                       —— PSC 的写法
#   · `record(<cond>, "…")`                 —— **⑤《测试执行.md》模板规定的记录器**
#   · `rec(<cond>, "…")`                    —— ⑨ 前端范式（view 脚本）的记录器
# 只认第一种时，按规格模板写的组会被整片误判成"BR 输出没被任何断言引用"。
_HAS_ASSERT = re.compile(r"\bassert\b|(?<![\w.])(?:record|rec)\(")


def tc_asserts():
    """{TC: [该步的代码文本]}（按 step() 切块）。"""
    out = defaultdict(list)
    for sp in sorted((ROOT / "app" / GROUP / "tests").glob(f"verify_chain_{GROUP}*.py")):
        text = sp.read_text(encoding="utf-8", errors="replace")
        marks = [(m.start(), m.group(1)) for m in re.finditer(r'step\("(TC-[^" ]+)', text)]
        for k, (pos, tc) in enumerate(marks):
            end = marks[k + 1][0] if k + 1 < len(marks) else len(text)
            out[tc].append(text[pos:end])
    return out


def evaluate():
    """返回 (rows, stats)。rows 每项 = {app, br, kind, fields:[(显示名,[TC])]}"""
    tcs = tc_asserts()
    rows, stats = [], {"total": 0, "covered": 0, "reject": 0, "derived": 0, "na": 0, "none": 0}
    for app in apps():
        for br, (kind, fields) in br_output_fields(app).items():
            stats["total"] += 1
            if kind == "reject":
                stats["reject"] += 1
                rows.append({"app": app, "br": br, "kind": "reject", "fields": []})
                continue
            if kind == "derived":
                stats["derived"] += 1
                rows.append({"app": app, "br": br, "kind": "derived", "fields": []})
                continue
            if kind == "na":
                stats["na"] += 1
                rows.append({"app": app, "br": br, "kind": "na", "fields": []})
                continue
            if kind == "none" or not fields:
                stats["none"] += 1
                rows.append({"app": app, "br": br, "kind": "none", "fields": []})
                continue
            got = []
            for disp, term in fields:
                pat = re.compile(r'[\["(.]%s\b' % re.escape(term))
                where = [tc for tc, blocks in tcs.items()
                         if any(pat.search(b) and _HAS_ASSERT.search(b) for b in blocks)]
                got.append((disp, where))
            if all(w for _f, w in got):
                stats["covered"] += 1
            rows.append({"app": app, "br": br, "kind": "covered", "fields": got})
    return rows, stats


def _fmt_tcs(tcs, limit=3):
    if not tcs:
        return "—"
    shown = "、".join(f"`{t}`" for t in sorted(tcs)[:limit])
    return shown + (f" 等 {len(tcs)} 条" if len(tcs) > limit else "")


def render_md(rows, stats):
    """生成 markdown 表格（贴进《测试用例.md》的 §4 标记之间）。"""
    ap = stats
    out = [f"**总量：{ap['total']} 条 BR** —— 输出字段被断言引用 **{ap['covered']}** · "
           f"拒绝类 {ap['reject']}（产物=报错）· 中间量 {ap['derived']}（派生量、不落字段）· "
           f"显式填不出 {ap['na']} · "
           f"**未覆盖 {sum(1 for r in rows if r['kind'] == 'covered' and any(not w for _f, w in r['fields']))}**"]
    by_app = defaultdict(list)
    for r in rows:
        by_app[r["app"]].append(r)
    for app in apps():
        rs = by_app[app]
        bad = sum(1 for r in rs if r["kind"] == "covered" and any(not w for _f, w in r["fields"]))
        out.append("")
        out.append(f"#### {app}（{len(rs)} 条 BR，未覆盖 {bad}）")
        out.append("")
        out.append("| BR | 输出字段 → 被哪条用例的**断言**引用 | 状态 |")
        out.append("|---|---|---|")
        for r in rs:
            if r["kind"] == "reject":
                out.append(f"| `{r['br']}` | 无（拒绝：产物就是报错） | ✅ 拒绝类 |")
            elif r["kind"] == "derived":
                out.append(f"| `{r['br']}` | 中间量（派生量、不落字段） | ✅ 不适用 |")
            elif r["kind"] == "na":
                out.append(f"| `{r['br']}` | ——（详设显式声明「填不出」：不是可校验规则） | ✅ 不适用 |")
            elif r["kind"] == "none":
                out.append(f"| `{r['br']}` | ⚠ 三要素的 `输出` 读不出列名 | ⚠ 待修 |")
            else:
                cell, missing = [], []
                for disp, where in r["fields"]:
                    if where:
                        cell.append(f"`{disp}` → {_fmt_tcs(where)}")
                    else:
                        cell.append(f"`{disp}` → **无**")
                        missing.append(disp)
                mark = "✗ **未覆盖**" if missing else "✅"
                out.append(f"| `{r['br']}` | {'；'.join(cell)} | {mark} |")
    return "\n".join(out)


def render_text(rows, stats):
    lines = [f"脚本里共 {len(tc_asserts())} 个 TC 步", ""]
    for r in rows:
        if r["kind"] in ("reject", "derived"):
            lines.append(f"  {r['app']} {r['br']}: {r['kind']}")
        elif r["kind"] == "none":
            lines.append(f"  {r['app']} {r['br']}: ⚠ 三要素的输出读不出列名")
        else:
            txt = "；".join(f"{f}→{','.join(w) if w else '✗'}" for f, w in r["fields"])
            lines.append(f"  {r['app']} {r['br']}: {txt}")
    lines.append("")
    lines.append(f"合计 {stats['total']} 条 BR：输出字段被断言引用 {stats['covered']} · "
                 f"拒绝类 {stats['reject']} · 中间量 {stats['derived']} · 判不了 {stats['none']}")
    unc = [r for r in rows if r["kind"] == "covered" and any(not w for _f, w in r["fields"])]
    if unc:
        lines.append(f"⚠ {len(unc)} 条 BR 的输出字段没有任何断言引用：")
        for r in unc:
            bad = [f for f, w in r["fields"] if not w]
            lines.append(f"  · {r['app']} {r['br']}: {bad}")
    return "\n".join(lines)


def write_into_spec(md):
    spec = spec_path()
    text = spec.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        raise SystemExit(
            f"{spec} 里找不到标记 {BEGIN} … {END}，无法写回。\n"
            f"  首次为某组启用 `--write` 时，先手工在《测试用例.md》§4 的两张逐应用表**外侧**\n"
            f"  补上这两行标记（标记区间内的内容会被整个覆盖，故区间要恰好包住要生成的部分）。")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    # ⚠ 2026-09-18 修：这里原本写 `SPEC.write_text` —— 没有这个全局名，`--write` 一路 NameError。
    # 即「文档里推荐的刷新方式」从来跑不起来，于是 §4 的表只能手抄 ⇒ 手抄必漂（e2e BR-11/12 互换）。
    spec.write_text(f"{head}{BEGIN}\n{md}\n{END}{tail}", encoding="utf-8")
    print(f"已写回 {spec}（{len(md.splitlines())} 行）")


def main():
    ap = argparse.ArgumentParser(description="BR 输出字段级覆盖取证（断言视角）")
    ap.add_argument("-g", "--group", default="psc", help="应用组（默认 psc）")
    ap.add_argument("--md", action="store_true", help="只输出 markdown 表格")
    ap.add_argument("--write", action="store_true", help="写回《测试用例.md》的标记之间")
    args = ap.parse_args()

    global GROUP
    GROUP = args.group
    rows, stats = evaluate()
    if args.write:
        write_into_spec(render_md(rows, stats))
        return 0
    print(render_md(rows, stats) if args.md else render_text(rows, stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
