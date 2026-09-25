#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""术语表命中率取证：对象清单里的业务对象，有多少能在术语表里匹配到。

    python scripts/term_coverage.py <组> [--line 70]

**它是什么**：**取证 / 报告**工具，**不是门禁**。

术语表被定位成「命名的唯一来源」，但如果没有检查，"下游照表取名"就只是一句声明 ——
规则写得漂亮、执行是空的，正是本平台最忌的失败模式。本脚本让你一眼看到
**核心对象有没有漏在表外**，对应两处检查：

  · 《从材料到BRD.md》完成门禁 #4「核心对象没漏」（报告项）
  · 《工具链使用说明》第 ② 步门禁「业务名合规」（**详设侧那半仍需人工核对**）

⚠ **为什么默认不设分数线**（实测数据逼出来的）：
  一份 297 页手册抽出的清单有 **2189** 个对象，而术语表按设计只覆盖**几十个核心** ——
  整体命中率天然很低。因为分母里大半是**方法论步骤与概念**（`产品验证过程`、`决策分析过程`…），
  它们不会成为任何字段的来源，**本就不该进表**。
  **拿命中率判成败是错的**；要判的是「**★ 未命中里关联数最高的那批有没有要紧对象**」。
  若某个项目的清单本身就是"待管理对象"（而非方法论材料），可用分数线，此时显式传 `--line`。

**匹配用宽松口径**（与规格一致，别因字形不同就判未命中）：
  不区分大小写；忽略空格/连字符/下划线/斜杠；允许互相包含（缩写）；
  允许首字母缩写对应全称（`WBS` ↔ `Work Breakdown Structure`）。

**看什么**：
  · ★ **未命中里关联数最高的那批** —— **先看这个**。核心对象若漏，会出现在这里（如 `SEMP`、`需求`、`V&V Plan`）。
  · **整体命中率**：仅供参考。
  · **「业务名」与「原词」相同的行占比**：**报告项**，跨语言项目接近 100% 才可疑（可能是清单副本）；
    同语言项目高是正常的（本就不需要译名）。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"

# 「业务对象」节的起始标题（export 产出里的固定写法）
_SECTION = re.compile(r"^##\s*一、\s*业务对象")
_TYPE_HEAD = re.compile(r"^###\s+(.+?)\s*[（(](\d+)[）)]\s*$")
_ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*(.*?)\s*\|\s*(\d+)\s*\|")


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_/·]+", "", s or "").lower()


def _initials(s: str) -> str:
    return "".join(w[0] for w in re.findall(r"[A-Za-z]+", s or "")).lower()


def _match(obj: str, key: str) -> bool:
    """宽松匹配：见模块说明。"""
    a, b = _norm(obj), _norm(key)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return _initials(obj) == b or _initials(key) == a


def _objects(group: str) -> list[tuple[str, int]]:
    """读《本体对象.md》→ 「业务对象」节的 [(对象名, 关联数)]（不含「其他类型」节）。

    ⚠ 关联数只用来**排序**（把要紧的排在前面），**不用来筛选** ——
    实测长尾（关联数 ≤1）里确有要紧对象。见模块说明。
    """
    p = APP_DIR / group / "本体对象.md"
    if not p.is_file():
        raise SystemExit(f"✗ 未找到 {p} —— 先 export {group}")
    out: list[tuple[str, int]] = []
    inside = False
    for line in p.read_text(encoding="utf-8").splitlines():
        if _SECTION.match(line):
            inside = True
            continue
        if inside and line.startswith("## "):        # 进入下一节 → 结束
            break
        m = _ROW.match(line) if inside and not line.startswith("|---") else None
        if m:
            out.append((m.group(1), int(m.group(3))))
    return out


def _terms(group: str) -> list[tuple[str, str]]:
    """读《术语表.md》→ [(原词, 业务名)]。

    **按表头定位列**（不硬编码"第一列/最后一列"）—— 表里多一列（如"备注"）也不会取错。
    """
    p = APP_DIR / group / "术语表.md"
    if not p.is_file():
        raise SystemExit(f"✗ 未找到 {p} —— 本项目没有术语表（那就没有可校验的唯一来源）")
    rows: list[tuple[str, str]] = []
    idx = None
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            idx = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):        # 分隔行
            continue
        if idx is None:                              # 找表头
            if any("原词" in c for c in cells):
                i_key = next(i for i, c in enumerate(cells) if "原词" in c)
                i_name = next((i for i, c in enumerate(cells) if "业务名" in c), len(cells) - 1)
                idx = (i_key, i_name)
            continue
        i_key, i_name = idx
        if i_key < len(cells) and cells[i_key]:
            rows.append((cells[i_key], cells[i_name] if i_name < len(cells) else ""))
    return rows


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="术语表取证：核心对象有没有漏在表外")
    ap.add_argument("group")
    ap.add_argument("--line", type=float, default=0.0,
                    help="命中率分数线（%%）。**默认 0 = 不判失败** —— 见模块说明："
                         "本书来源的清单含大量方法论步骤，整体命中率天然很低，用它判成败是错的")
    ap.add_argument("--top", type=int, default=20, help="未命中里按关联数取前 N 条（默认 20）")
    ap.add_argument("--list-miss", action="store_true", help="列出全部未命中")
    args = ap.parse_args()

    objs = _objects(args.group)
    terms = _terms(args.group)
    if not objs:
        raise SystemExit("✗ 清单里「业务对象」节是空的 —— 分类框架可能没配置（kg_config.json）")
    if not terms:
        raise SystemExit("✗ 术语表没解析出任何行 —— 检查它是不是「原词 | 语境 | 业务名」形式的表格")

    hit, miss = [], []
    for o, d in objs:
        # ⚠ **两边都要比**：对象名可能是材料原词，也可能已被抽成产出语言
        # （取决于 `kg_config.json` 的 language 设置与抽取表现）。只比「原词」列会误判未命中。
        ok = any(_match(o, k) or _match(o, v) for k, v in terms)
        (hit if ok else miss).append((o, d))
    rate = 100.0 * len(hit) / len(objs)

    print(f"组 {args.group}")
    print(f"  清单「业务对象」节对象数：{len(objs)}")
    print(f"  术语表行数：{len(terms)}")
    print(f"  命中：{len(hit)}   未命中：{len(miss)}   整体命中率：{rate:.1f}%（**仅供参考，不判成败**）")

    # ★ 这才是要看的东西：未命中里最要紧的那批
    miss.sort(key=lambda x: -x[1])
    print(f"\n★ 未命中里关联数最高的 {min(args.top, len(miss))} 条 —— **先看这批**"
          f"（核心对象若漏，会出现在这里）：")
    for o, d in miss[:args.top]:
        print("    · %-52s 关联 %d" % (o[:50], d))
    if args.list_miss and len(miss) > args.top:
        print(f"\n  其余未命中（{len(miss) - args.top} 条，多为方法论步骤/概念，漏在表外属正常）：")
        for o, d in miss[args.top:]:
            print("    · %-52s 关联 %d" % (o[:50], d))
    elif len(miss) > args.top:
        print(f"    …另有 {len(miss) - args.top} 条未命中（用 --list-miss 看全）")

    # 「业务名 == 原词」的行占比 —— **报告项，不判对错**
    same = sum(1 for k, v in terms if k and v and _norm(k) == _norm(v))
    print("\n  「业务名」与「原词」相同的行：%d/%d（%.0f%%）—— **报告项，不判对错**"
          % (same, len(terms), 100.0 * same / len(terms)))
    print("     · 跨语言项目：**接近 100% 才可疑**（大概率是清单副本，回术语表那步重做）；")
    print("       个别行相同属正常（通用缩写、本来就没有对应译法）。")
    print("     · 同语言项目：**高是正常的**（本就不需要译名）——此时看的是「归一」是否发生，")
    print("       别把这个比例当质量指标。")

    if args.line > 0:
        ok = rate >= args.line
        print("\n" + ("✓ 命中率达标" if ok else f"✗ 命中率低于 {args.line:.0f}%"))
        return 0 if ok else 1
    print("\n（未设分数线：**本项默认不判成败** —— 判的是上面「★ 那批」有没有核心对象漏在表外）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
