#!/usr/bin/env python
"""nasa_pms 后端链测试**运行入口**（编排器）—— 第⑤步产物。

    python app/nasa_pms/tests/verify_chain_nasa_pms.py              # 跑全部分片（12 个）
    python app/nasa_pms/tests/verify_chain_nasa_pms.py --app risk   # 只跑一个（逗号分隔可多个）
    python app/nasa_pms/tests/verify_chain_nasa_pms.py --list       # 只看有哪些分片

## 本组的 ⑤ 产物形态：**编排器 + 逐应用分片**

```
app/nasa_pms/tests/
├── verify_chain_nasa_pms.py                 ← 编排器（本文件 · 运行入口）
├── verify_chain_nasa_pms_requirement.py     ← 分片：需求
├── verify_chain_nasa_pms_risk.py            ← 分片：风险
└── …（共 11 个，与 11 个聚合根一一对应）
```

**为什么不是 PSC 那种「编排器 + §段落 partN」**：④《测试用例.md》本身就是**逐应用**组织的
（每个应用一节 `TC-*`，见该文件每节的「应用：xxx」标题），逐应用脚本是它的一一翻译；
分片可单独跑、单独 triage，单应用演进只改一个文件。**分片不是 `part`**：
`*_partN.py` 那种片段没有模块级 import、靠父脚本 `exec` 进同一进程（见 `verify_chain_psc.py`），
而本组分片是**独立脚本**，各自带影子库隔离与造数 —— 所以 `run_gates.py` 取 chain 层时会**排除** `_part*`。

## 编排器做三件事（也解释了它为什么必须存在）

> ⚠ **2026-09-25 补**：此前**没有这个文件** —— 12 个分片各自绿，而
> `run_gates.py --group nasa_pms --tier chain` 的 glob 是**精确名** `verify_chain_nasa_pms.py`，
> 匹配不到任何文件 ⇒ **chain 层是空的、却照样报"通过"**（判据静默塌成空集）。
> 同时 ④《测试用例.md》第 9 行早就写着"执行：`python app/nasa_pms/tests/verify_chain_nasa_pms.py`" ——
> 文档指向了一个不存在的入口。

1. **顺序跑**全部（或 `--app` 指定的）分片；每个分片**自带影子库隔离**
   （`shadow_dbs` + 副本清表：真库零字节接触、**不用停 dev server**，见《验证门禁.md》§四之二）；
2. **解析并汇总**每个分片的 `用例 N 项 · 通过 M · 失败 K` 与 `VERIFY_RESULT`；
3. **任一失败即非零退出**，并按分片名回指（triage 从分片入手，不在此文件里加断言）。

**跑序 = `architecture.md` ① 的聚合根序**（需求→风险→配置项→变更请求→评审→验证项→技术度量→
决策→接口→技术计划→利益相关者）—— 出问题能顺着主链读；未知分片按名兜底排在后面。
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent

# 输出编码：控制台代码页在本机默认 GBK，而分片输出里有 ⇒/✓/✗/⚠ 这类非 GBK 码位 ——
# 本文件只转发分片的 stdout，钉住编码免得在汇总时把好数据打崩（分片自己也有这一行）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

GROUP = "nasa_pms"

# 与 architecture.md ① 同序（12 个聚合根；wbs 是 2026-09-26 并入的第 12 个，排最后）
ORDER = ["requirement", "risk", "configuration_item", "change_request", "review", "verification",
         "technical_measure", "decision", "interface", "tech_plan", "stakeholder", "wbs",
         "activity"]

RESULT_RE = re.compile(r"用例\s*(\d+)\s*项\s*·\s*通过\s*(\d+)\s*·\s*失败\s*(\d+)")
VERDICT_RE = re.compile(r"VERIFY_RESULT:\s*(\S+)")


def shards() -> list[tuple[str, pathlib.Path]]:
    """本组的全部链测试分片 → [(应用名, 路径)]，按 ORDER 排、未知的按名兜底排最后。"""
    out = []
    for p in sorted(HERE.glob(f"verify_chain_{GROUP}_*.py")):
        app = p.stem[len(f"verify_chain_{GROUP}_"):]
        if app.startswith("part"):          # 片段文件（PSC 那种形态）不是独立分片
            continue
        out.append((app, p))
    out.sort(key=lambda t: (ORDER.index(t[0]) if t[0] in ORDER else len(ORDER), t[0]))
    return out


def run_one(app: str, path: pathlib.Path) -> tuple[bool, str, str]:
    """跑一个分片 → (是否通过, 汇总行, 失败明细)。

    分片的隔离与断言都在分片里；这里**只**负责起进程、收输出、解析结论 —— 不重复实现 clean/断言。
    `PYTHONIOENCODING=utf-8` 传给子进程：Windows 下子进程的 stdout 默认按 ANSI 代码页编码，
    打印 `⇒/✓` 会**在打印那一步崩掉**（症状是"断言算完了却报不出来"），父进程的 `encoding=` 只管解码。
    """
    proc = subprocess.run(
        [sys.executable, "-u", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    text = (proc.stdout or "") + (proc.stderr or "")
    m = RESULT_RE.search(text)
    verdict = VERDICT_RE.search(text)
    if m:
        total, ok, bad = m.group(1), m.group(2), m.group(3)
        line = f"{total:>5} 项 · 通过 {ok:>3} · 失败 {bad:>2}"
    else:
        line = "     — 未解析到用例计数（疑似崩溃）"
    passed = bool(m) and m.group(3) == "0" and proc.returncode == 0 \
        and bool(verdict) and verdict.group(1).startswith("PASS")
    detail = ""
    if not passed:
        # 失败明细：优先取分片自己的 FAIL/崩溃行（triage 定位到用例）
        bad_lines = [ln.strip() for ln in text.splitlines()
                     if ln.strip().startswith(("✗", "[FAIL]", "FAIL @", "FAIL_STEP", "Traceback",
                                               "VERIFY_RESULT: FAIL", "VERIFY_RESULT: PARTIAL",
                                               "VERIFY_RESULT: CRASH"))]
        detail = " / ".join(bad_lines[:4]) or f"rc={proc.returncode}（无 FAIL 行 —— 疑似启动期崩溃）"
    return passed, line, detail


def main(argv: list[str]) -> int:
    args = argv[1:]
    if "--list" in args:
        for app, p in shards():
            print(f"  {app:20s} {p.name}")
        return 0
    only = []
    if "--app" in args:
        only = [a.strip() for a in args[args.index("--app") + 1].split(",") if a.strip()]

    all_shards = shards()
    todo = [(a, p) for a, p in all_shards if not only or a in only]
    missing = [a for a in only if a not in {a for a, _ in all_shards}]
    if missing:
        print(f"✗ 未找到分片：{missing}；可用：{[a for a, _ in all_shards]}")
    if not todo:
        # **空判据必须出声**：跑 0 个分片却报"通过"正是本文件要终结的那个缺陷
        print("✗ 没有可跑的分片（过滤条件写错了？）—— 空集不算通过")
        return 1

    print("=" * 78)
    print(f"应用组 {GROUP} 后端链测试（第⑤步 · 编排器）—— 共 {len(todo)} 个分片")
    print(f"  用例唯一来源：app/{GROUP}/测试用例.md（逐应用组织）")
    print("  每个分片自带**影子库**隔离：真库零字节接触、不用停 dev server")
    print("=" * 78)

    rows, failed = [], []
    for app, path in todo:
        print(f"\n▸ [{app}] {path.name}", flush=True)
        ok, line, detail = run_one(app, path)
        rows.append((app, ok, line, detail))
        if not ok:
            failed.append((app, detail))
            print(f"    ✗ {line}")
            if detail:
                print(f"      {detail[:300]}")

    print("\n" + "=" * 78)
    print(f"{'分片':<20s}{'用例':>18s}  结论")
    for app, ok, line, _ in rows:
        print(f"{app:<20s}{line}  {'✓ PASS' if ok else '✗ FAIL'}")
    print("-" * 78)
    print(f"分片 {len(rows)} 个 · 通过 {len(rows) - len(failed)} · 失败 {len(failed)}")
    if failed:
        for app, detail in failed:
            print(f"  ✗ {app} —— {detail[:200]}")
    print(f"VERIFY_RESULT: {'PASS' if not failed else f'FAIL（{len(failed)} 个分片）'}")
    print("=" * 78)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
