"""测试脚本输出编码自检：抓「断言算完了，却崩在打印结果那一步」的脚本。

**为什么存在**（2026-09-25 实测踩到）：`verify_view_nasa_pms_stakeholder.py` 在普通 Windows
控制台（代码页 GBK）跑时，断言算完、往 `print` 里送结果的那一行抛 `UnicodeEncodeError`：

    rec(..., "FE-32 **已冻结 ⇒ 说明 / 类别 / 来源 / 生效期全部 disabled**（BR-07）")
    print(f"    {'[OK]' if ok else '[FAIL]'} {note}", flush=True)
    UnicodeEncodeError: 'gbk' codec can't encode character '\\u21d2'

后果比"脚本挂了"更糟：**FE-32 到底过没过无人知晓**，排在它后面的用例**根本没跑** ——
而报出来的是 traceback，看起来像断言失败。同一根因平台早撞过一次：`scripts/run_gates.py`
必须给子进程传 `PYTHONIOENCODING=utf-8`（否则子检查自身崩），但那次只修了闸门，
没回头管测试脚本与范式样板 ⇒ 被范式**遗传**给了每个新组的每个脚本。

**判据**（只认真正会输出的字符串，不做全文扫 —— docstring / 注释里的符号无害）
  1. 字符串出现在 `print(...)` 实参、`assert` 的消息、`raise` 的实参里（f-string 片段也算）；
  2. 该字符串含**当前代码页编不出**的字符 —— 用 `str.encode("gbk")` **现算**：
     `⇒ ✓ ✗` 编不出，而 `≥ ≤ × →` 在 GBK 里**有码位**（硬编码符号清单会大面积误报，
     实测：手写清单报 20 个，现算只报真正会崩的那几个）；
  3. 文件里**没有** `sys.stdout.reconfigure(encoding="utf-8"…)`。

**修法**（报错信息里给出）：脚本顶部（imports 之后、任何 print 之前）加

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

`errors="replace"` 是**故意**的：测试脚本的产出不该因为一个箭头符号而中断（宁可打成 `?`），
而本检查会保证"写了非 GBK 符号却没钉编码"的新脚本当场被拦下，不需要靠崩来提醒。

用法：python scripts/verify_test_script_encoding.py     （有问题退出码 1，可入 CI/门禁）
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # ⚠ 本脚本自己也钉编码

# 扫描范围：各组测试脚本 + 两个范式样板（样板会被生成器当"范式全文"喂出去，必须自身干净）
# 扫描范围：各组测试脚本 + 两个范式样板 + **平台自己的 scripts/**（2026-09-25 扩）。
# ⚠ `scripts/` 这一支是补的：上一版只扫测试脚本，于是**平台自己的检查脚本**在 GBK 控制台下
#   print ✓/✗ 崩掉（实测 `verify_shadow_isolation.py` 与 `scan_structure.py` 都崩过），
#   而外层门禁把它显示成"该检查 FAIL" —— 像判据报了缺陷，其实判据根本没跑完。
GLOBS = ["app/*/tests/*.py", "design-plus/前端验收样板/*.py",
         "design-plus/后端验收样板/*.py", "scripts/*.py"]

FIX = ('    try:\n'
       '        sys.stdout.reconfigure(encoding="utf-8", errors="replace")\n'
       '    except Exception:\n'
       '        pass')


def _project_root() -> Path:
    p = Path(__file__).resolve().parent
    while not (p / "fde_platform").is_dir():
        if p.parent == p:
            raise SystemExit("找不到项目根（向上未发现 fde_platform/）")
        p = p.parent
    return p


ROOT = _project_root()


def _bad_chars(s: str) -> str:
    """字符串里**代码页编不出**的字符（去重、按首次出现排序）。GBK 现算，不硬编码清单。"""
    out = []
    for ch in s:
        if ch in out:
            continue
        try:
            ch.encode("gbk")
        except UnicodeEncodeError:
            out.append(ch)
    return "".join(out)


def _printed_strings(tree: ast.AST):
    """会真正被输出的字符串字面量 → [(行号, 字符串)]。

    ⚠ 出口**不止 `print`**：本仓的测试脚本都有自己的日志封装（`rec(...)` / `log(...)` / `step(...)`），
    **只认 `print` 会漏掉真凶** —— 实测：`verify_view_nasa_pms_stakeholder.py` 崩掉的那条
    `⇒` 就在 `rec(..., "FE-32 … ⇒ …")` 里，第一版判据（只扫 `print`）**放过了它**。
    故出口定义为：**任何 `Call` 的实参** + `assert` 的消息 + `raise` 的实参。
    宁可多报（误报只需补一行 `reconfigure`，无害），绝不漏报（漏报 = 断言结果无声消失）。
    `ast.walk` 进实参内部即可覆盖 f-string 片段与拼接项。
    """
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            args = list(node.args) + [kw.value for kw in node.keywords]
        elif isinstance(node, ast.Assert):
            args = [node.msg] if node.msg is not None else []
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            args = list(node.exc.args)
        else:
            continue
        for a in args:
            if a is None:
                continue
            for sub in ast.walk(a):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    found.append((sub.lineno, sub.value))
    return found


def _pins_stdout_utf8(tree: ast.AST) -> bool:
    """文件里有没有 `….stdout.reconfigure(encoding="utf-8"…)`（不看 `PYTHONIOENCODING` ——
    那是**跑的人**给的，不是脚本自带的；本条判据要求脚本**自己**钉住编码）。"""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "reconfigure"):
            continue
        for kw in node.keywords:
            if kw.arg == "encoding" and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str) and "utf-8" in kw.value.value.lower():
                return True
    return False


def _is_exec_fragment(tree: ast.AST) -> bool:
    """`verify_chain_<组>_part*.py` 这类**片段文件**：定义 `run_part(...)`、无模块级 import，
    由父脚本 `exec`/import 进**同一进程** —— 编码由父脚本钉住（父脚本已被本检查覆盖）。
    不排除它们的话，插进去的 `sys.stdout.reconfigure` 会在一个**没有 `sys` 的命名空间**里 NameError。
    ⚠ 判据是结构性的（不是文件名匹配）：片段一旦真的变成独立脚本（加了 import），就会自动回到检查范围。
    """
    has_import = any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in tree.body)
    has_run_part = any(isinstance(n, ast.FunctionDef) and n.name == "run_part" for n in tree.body)
    return has_run_part and not has_import


def main() -> int:
    files = []
    for g in GLOBS:
        files += sorted(ROOT.glob(g))
    files = [f for f in files if "__pycache__" not in str(f)]
    skipped = []
    # **判据不许静默塌成空集**：扫不到文件就是自检本身失效，必须报错而不是"全绿"。
    if not files:
        print("[FAIL] 未扫到任何测试脚本 —— 扫描范围写错了？")
        return 1

    offenders = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            print(f"[FAIL] 语法错误，无法自检：{f.relative_to(ROOT)} — {e}")
            return 1
        if _is_exec_fragment(tree):
            skipped.append(f)
            continue
        if _pins_stdout_utf8(tree):
            continue
        hits = []
        for lineno, s in _printed_strings(tree):
            bad = _bad_chars(s)
            if bad:
                cps = " ".join(f"U+{ord(c):04X}({c})" for c in bad)
                hits.append((lineno, cps, s.strip().replace("\n", " ")[:60]))
        if hits:
            offenders.append((f, hits))

    print(f"扫描 {len(files) - len(skipped)} 个脚本（app/*/tests + 两个范式样板）"
          + (f"；跳过 {len(skipped)} 个片段文件（被父脚本 exec，编码由父脚本钉住）："
             f"{[f.name for f in skipped]}" if skipped else ""))
    if not offenders:
        print("✓ 无「打印即崩」脚本：所有含非当前代码页字符的脚本都已钉住 stdout 编码")
        return 0

    print(f"✗ {len(offenders)} 个脚本会**崩在打印断言结果那一步**（其后用例不再执行）：\n")
    for f, hits in offenders:
        print(f"  {f.relative_to(ROOT)}")
        for lineno, cps, sample in hits[:3]:
            print(f"    L{lineno}  {cps}  {sample!r}")
        if len(hits) > 3:
            print(f"    … 另有 {len(hits) - 3} 处")
    print(f"\n修法：在脚本顶部（imports 之后、任何 print 之前）加\n{FIX}")
    return 1


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main())
