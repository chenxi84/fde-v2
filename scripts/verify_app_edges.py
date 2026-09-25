"""跨应用边对账：**架构声明的边 ↔ 代码里真实存在的边**（纯静态，不跑任何服务）。

## 为什么需要它

架构声明的「跨应用调用方向」是第①步的产物，**后面所有设计都照着它推**（详设的弱引用、
绑定的应用集、flow 节点的工具面）。而"声明与实现之间没有对账"正是本仓反复踩的那一族：
`order` 并列静默按字母序（#43）、门禁空层静默通过（#45）、判据词汇表与规格不一致（#46）、
`risk.close` 缺状态闸（详设画着 `mitigating → close`）、`obsolete(reason)` 传了不落库……
架构声明的边尤其值得对账：它错了，下游全错，而且**没有任何测试会红**（因为测试也是照它写的）。

## 判据（三类，口径不同）

| 类 | 形态 | 处置 |
|---|---|---|
| **① 假声明（FAIL）** | 文档声明了 `A → B`，但**后端与前端都没有**这条边 | 文档在说一件不存在的事：要么补实现，要么订正文档 |
| **② 漏声明（FAIL）** | **后端**真实存在 `self.fde.call("B", …)`，文档没声明 | 架构漏了这条边（下游的设计都少了一个约束） |
| **③ 仅视图层（说明，不判失败）** | 文档声明了，后端没有、但**前端**页面里有字面量 `svc("B", …)` | 这是**视图层依赖**（如"责任人候选来自利益相关者"）：值仍是文本、后端不校验。**必须在文档里写明是视图层**，否则读者会以为后端也校验 |

## 声明的正本格式（缺表 → **SKIP 并说明**，不假装通过）

`app/<组>/architecture.md` 里一节，节标题含「跨应用调用」，随后一张表：

```markdown
**跨应用调用方向**（`self.fde.call`，全部为**读**）：

| 调用方 | 被调用 | 用途 |
|---|---|---|
| `verification` | `requirement.get` | 取被验证的需求 |
| `requirement` / `review` | `stakeholder.list`（**视图层**，见备注） | 选相关方 |
```

- 一格里可并列多个：调用方 `a` / `b`、被调用 `x.svc1` / `y.svc2`。
- **在格里注明「视图层」**的条目走第③类口径（只在前端存在不算缺陷）。
- 本表是**声明**；代码是**事实**。两者不一致就按上表报。

用法：python scripts/verify_app_edges.py [--group nasa_pms]      （有问题退出码 1）
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parents[1]
# 「视图层」标记：格里写明后，该条按第③类口径判
VIEWONLY = re.compile(r"视图层|前端|页面")
# 声明节 = **组级**的那一处：`##`/`###` 标题含「跨应用调用」，或粗体行 `**跨应用调用方向**（…）：`。
# ⚠ **不认 `####` 卡片**：逐卡片的小表是"这张卡自己的边"，列语义也不同（`| 本聚合操作 | 调用目标 | 用途 |`），
#   拿它当组级声明会既漏又误（实测 e2e：卡片里有 `task.create → member.get`，被判成"漏声明"）。
#   组级声明表是**唯一**对账入口（正本见 design-plus/架构设计.md §②b）。
SEC = re.compile(r"^(?:#{2,3}(?=\s)[^\n]*跨应用调用|\s*\*\*跨应用调用)")
# ⚠ `#{2,3}` 不加 `(?=\s)` 会**前缀匹配**到 `#### 跨应用调用`（那是卡片）——
#   实测踩到：e2e 的卡片被当成组级声明节，于是"有表却没解析出来"（同类错：判据正则写宽/写窄）
ROW = re.compile(r"^\|([^|]+)\|([^|]+)\|([^|]*)\|([^|]*)\|")
CODE = re.compile(r"`([^`]+)`")


def _clean(s: str) -> str:
    return s.strip().strip("*").strip()


def declared_edges(group: str):
    """→ ({(caller, callee): {svc…}}, {(caller, callee)} 视图层声明)。没表 → (None, None)。"""
    doc = ROOT / "app" / group / "architecture.md"
    if not doc.exists():
        return None, None
    lines = doc.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if SEC.match(l)), None)
    if start is None:
        return None, None
    edges, view = {}, set()
    # ⚠ 从标题的**下一行**开始：否则第一行就是 `## …`，会立刻被下面的 break 吃掉（实测踩到）
    for ln in lines[start + 1:start + 80]:
        if ln.startswith("## ") or ln.startswith("---"):
            break
        m = ROW.match(ln)
        if not m or set(m.group(1)) <= set("-: "):
            continue
        callers = [c for c in CODE.findall(m.group(1))] or [c.strip() for c in m.group(1).split("/")]
        for spec in CODE.findall(m.group(2)):
            if "." not in spec:
                continue
            callee, svc = spec.split(".", 1)
            # 「视图层」标记写在哪一列都认（用途列或「在哪一层」列）——
            # 但**不能看被调用列**：那一列是服务名，本来就不该出现这两个词
            is_view = bool(VIEWONLY.search(" ".join(x or "" for x in m.groups()[2:])))
            for c in (callers or []):
                c = _clean(c)
                callee = _clean(callee)
                if not c or not callee:
                    continue
                if is_view:
                    view.add((c, callee))
                edges.setdefault((c, callee), set()).add(svc)
    # ⚠ 只有**表**才算声明（正本格式）：散文 / 逐卡片格式的组归入「未覆盖」，
    #   否则会把「格式不同」误报成「漏声明」（实测：e2e 的卡片式 `#### 跨应用调用` 被当成空声明）。
    return (edges, view) if edges else (None, None)


def backend_edges(group: str):
    """后端的跨应用边：扫 `app/<组>/<应用>/<应用>.py` 的 `self.fde.call` 字面量。"""
    from fde_platform.scanner import extract_calls
    out = {}
    for f in sorted((ROOT / "app" / group).glob("*/*.py")):
        caller = f.parent.name
        try:
            calls = extract_calls(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                   # noqa: BLE001
            continue
        for c in calls:
            target = (c.get("target_app") or "").split("/")[-1]
            if not target or target == caller:
                continue
            out.setdefault((caller, target), set()).add(c.get("target_service") or "?")
    return out


def frontend_edges(group: str):
    """前端的跨应用边：页面字面量 `svc("应用", …)`（注册表已经把「页→服务」扫出来了）。"""
    from fde_platform import view_registry as vr
    vr.invalidate()
    out = {}
    for page in (vr.registry() or {}).get("modules", []):
        pass                                                # 保留：不同版本的注册表结构
    for page_id in sorted(vr.all_page_ids()):
        if not page_id.startswith(f"{group}:"):
            continue
        owner = page_id.split(":", 1)[1]
        for app, svc in vr.page_services(page_id):
            if app and app != owner:
                out.setdefault((owner, app), set()).add(svc)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default=None)
    args = ap.parse_args()
    groups = [args.group] if args.group else sorted(
        p.name for p in (ROOT / "app").iterdir()
        if p.is_dir() and not (p / f"{p.name}.py").exists())

    failed, skipped = [], []
    for g in groups:
        dec, view = declared_edges(g)
        if dec is None:
            skipped.append(g)
            continue
        be, fe = backend_edges(g), frontend_edges(g)
        print(f"\n══ {g}：声明 {len(dec)} 条边 · 后端 {len(be)} · 前端（跨应用）{len(fe)}")
        for (c, t), svcs in sorted(dec.items()):
            in_be, in_fe = (c, t) in be, (c, t) in fe
            if in_be:
                print(f"  ✓ {c} → {t}.{'/'.join(sorted(svcs))}（后端有）")
            elif in_fe:
                tag = "已在文档里标了视图层 ✓" if (c, t) in view else "**文档没写「视图层」** ← 补一句"
                print(f"  · {c} → {t}.{'/'.join(sorted(svcs))}（只在前端页面里；{tag}）")
                if (c, t) not in view:
                    failed.append(f"{g}: 声明 `{c} → {t}` 只在前端存在，文档需注明「视图层」")
            else:
                failed.append(f"{g}: **假声明** —— `{c} → {t}` 后端与前端都不存在（补实现或订正架构）")
        for (c, t), svcs in sorted(be.items()):
            if (c, t) not in dec:
                failed.append(f"{g}: **漏声明** —— 后端 {c} → {t}.{'/'.join(sorted(svcs))} 未写进架构声明")

    print("\n" + "=" * 70)
    if skipped:
        print(f"· SKIP：{skipped} —— 这些组的 architecture.md 没有「跨应用调用」**声明表**。")
        # 让**外层门禁**也能看见这次 SKIP（否则 run_gates 只显示 PASS，SKIP 就静默了 —— 见 pitfalls #45）
        print(f"VERIFY_NOTE: {len(skipped)} 个组未覆盖（无声明表）：{'、'.join(skipped)}")
        print("  ⚠ **这不是通过**：本节是声明与实现的对账入口，缺了它本判据无从对账。")
        print("  补法（正本见 design-plus/架构设计.md 的『输出结构』**§②b**）：加**表**，"
              "列 `| 调用方 | 被调用(app.service) | 用途 | 在哪一层 |`（散文 / 逐卡片格式不算 —— 它们没声明『在哪一层』）。")
    if failed:
        print(f"✗ {len(failed)} 处不一致：")
        for x in failed:
            print(f"    · {x}")
        print("VERIFY_RESULT: FAIL")
        return 1
    print(f"✓ 已声明且对账通过（{len(groups) - len(skipped)} 个组有声明节）")
    print("VERIFY_RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
