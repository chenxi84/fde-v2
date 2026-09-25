# -*- coding: utf-8 -*-
"""前端验收取证：**用例文档 ↔ 脚本 ↔ 页面元数据** 三方对账（第⑧⑨步）。

## 为什么要有它

后端那边（`br_coverage.py` / `scan_structure.py`）证明了一件事：
**「有编号对应用例」不等于「断言真的在验」**。前端这片此前一个判据都没有，实测的漂移是：

- **菜单项在三个地方是三个数**：用例文档一张表、脚本一个 `EXPECTED_MENU`、覆盖度报告又一个数；
- **10 个应用的脚本一条 `VT-xxx` 都不写** —— 用例与断言的对应只存在于作者脑子里；
- **`ignored` 列表收集了却从不校验** —— 任何新出现的 4xx 都可能被静默吞掉；
- **组级页（material_360 / process）有脚本、没用例**；
- **授权清单与页面名漂移**（`_platform:agent` vs `_platform:agent_overview` vs 真实的 `_platform:workbench`）；
- **`<template x-if>` 顶层多根** ⇒ Alpine 只挂载第一个、其余**凭空消失**（实测「批量导入的提交按钮」
  与「工作台的最近错误内容」两处 —— 前者让一个功能在界面上根本用不了，而**读 HTML 读不出来**）。

## 真值从哪来

不用任何一方文档做基准，**取页面自己声明的元数据**：

- 业务页：各 `view.js` / 组级 `<页>.js` 的 `PAGE_META`（key/name/order）——平台扫描的就是它；
- 平台页：`view/lib/shell.js` 的 `PLATFORM_PAGES`（`top:true` 的排在最前）。

## 用法

    python scripts/view_coverage.py            # 打印三方对账
    python scripts/view_coverage.py -g psc
"""
import argparse
import json
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

# 断言强度：未引用任何业务字段/值、只证明"没报错"的形态
_SOFT = re.compile(r"count\(\)\s*>=?\s*[01]\s*$|count\(\)\s*>\s*0|is not None|!= None"
                   r"|len\(\w+\)\s*>=?\s*1\s*$")
# ⚠ 段名可能是**数字**（组级页用 `VT-360-01` / `VT-100-02` 这种按页号命名的写法），
# 首版写 `[A-Z]+` 于是把 material360 脚本里 3 处标记全漏了 —— 又是「正则写窄 = 假红」。
_VT = re.compile(r"VT-[A-Z0-9]+-\d+[a-z]?")
# ⚠ **只认行首的用例编号**（与 `scan_structure.py` 的 `_TC_HEAD_RE` 同一教训）：
# 正文里「与 `VT-LIST-05` 同属一类漂移」这种**交叉引用**不能被当成"本页有这么一条用例" ——
# 实测踩过：`sales_forecast` 的文档里引用了 `md_customer` 的 VT-LIST-05，判据当场报假警报。
# 允许的行首前缀：表格/列表标记、粗体、删除线（作废用例写作 `- ~~**VT-XX-01 …**~~`）。
_VT_HEAD = re.compile(r"^\s*[|>\-*#\s~]*\**`?\s*(VT-[A-Z0-9]+-\d+[a-z]?)")
_MENU_ASSERT = re.compile(r"EXPECTED_MENU|LIMITED_MENU|names\[:|_nav_names")


def _page_meta(path: Path):
    """从 js 文件里刮出 PAGE_META 的 key/name/order（页面自描述，平台的唯一入口）。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"export const PAGE_META\s*=\s*\{(.*?)\};", text, re.S)
    if not m:
        return None
    body = m.group(1)
    def grab(field):
        mm = re.search(rf"{field}\s*:\s*[\"']([^\"']*)[\"']", body)
        return mm.group(1) if mm else None
    order = re.search(r"order\s*:\s*(\d+)", body)
    return {"key": grab("key"), "name": grab("name"),
            "order": int(order.group(1)) if order else None, "file": str(path)}


def business_pages(group):
    """业务页 = 各应用 `view.js` + 组级 `<页>.js`（都带 PAGE_META），按 order 升序。"""
    out = []
    base = ROOT / "app" / group
    for p in sorted(base.glob("*/view.js")):
        meta = _page_meta(p)
        if meta and meta["key"]:
            out.append(meta)
    for p in sorted(base.glob("*.js")):          # 组级聚合页（dashboard/process/material360…）
        meta = _page_meta(p)
        if meta and meta["key"]:
            out.append(meta)
    return sorted(out, key=lambda m: (m["order"] is None, m["order"]))


def platform_pages():
    """平台页（shell.js 的 PLATFORM_PAGES）：`top` 的排在业务页**之前**（实测踩过）。"""
    path = ROOT / "view" / "lib" / "shell.js"
    text = path.read_text(encoding="utf-8")
    block = re.search(r"export const PLATFORM_PAGES\s*=\s*\[(.*?)\n\];", text, re.S)
    out = []
    if block:
        for m in re.finditer(r"\{([^}]*)\}", block.group(1)):
            body = m.group(1)
            key = re.search(r'key:\s*"([^"]+)"', body)
            name = re.search(r'name:\s*"([^"]+)"', body)
            if key and name:
                out.append({"key": key.group(1), "name": name.group(1),
                            "top": "top: true" in body, "hidden": "hidden: true" in body})
    return out


# 脚本里**说明缺口**的注释行（如「⚠ 文档有、本脚本无对应断言：VT-LIST-02/04/06」）——
# 这些行里出现的编号**不算"已被引用"**。
# ⚠ 这是本判据第 4 处自纠（2026-09-17，**代理发现的**）：首版把脚本全文扫编号，
# 于是"缺口说明里提到的编号"被当成已实现，V3 永远报不出来 ——
# 正是本仓反复警告的「判据静默塌成空集」：**绿不代表测了**。
_GAP_NOTE = re.compile(r"无对应断言|缺口|待补|待回写|未编造|脚本独有|独有断言")
# ⚠ 第 5 处自纠：光靠 `_GAP_NOTE` 关键词是**两头都不可靠**的启发式 ——
# 缺口语汇一变（"尚未覆盖"…）就又成了假绿。改成**按行类型**判定（第 6 处自纠：先写成
# "编号必须在行首"又太紧，把「一条标记行列出多条用例」与 `step("§4 导入表单（VT-FORM-01 …）")`
# 这两种合法写法全误杀了）：
#     · 注释行（`#` 开头）或 `step("…")` 调用行 → 行内的编号**都算**已被引用；
#     · 文件头 docstring 与普通散文行 → 不算（缺口说明正藏在那里）。
# 这样"缺口清单里提到编号"不会造成假绿，而两种标记写法都不会被误杀。
def _is_marker_line(ln):
    s = ln.strip()
    return s.startswith("#") or s.startswith('step("') or 'step("' in s


def script_facts(group):
    """逐脚本：VT 编号引用数 / 断言与软断言数 / ignored 是否被校验 / 授权清单字面量。"""
    out = {}
    for p in sorted((ROOT / "app" / group / "tests").glob("verify_view_*.py")):
        text = p.read_text(encoding="utf-8", errors="replace")
        # 断言计数同样认三种写法（口径与 `_ASSERT_RE` 一致；只认 assert 会把 rec 系的脚本数成 0）
        asserts = [ln.strip() for ln in text.splitlines()
                   if re.match(r"\s*(?:assert |(?<![\w.])(?:record|rec)\()", ln)]
        # 只认**标记行**里声明的编号，且排除缺口说明行（见 `_is_marker_line` / `_GAP_NOTE`）
        vts = set()
        for ln in text.splitlines():
            if not _is_marker_line(ln) or _GAP_NOTE.search(ln):
                continue
            vts.update(_VT.findall(ln))
        grants = re.findall(r"\[([^\]]*_platform:[^\]]*)\]", text)
        out[p.name] = {
            "vt": sorted(vts),
            "asserts": len(asserts),
            "soft": sum(1 for a in asserts if _SOFT.search(a)),
            "menu_assert": bool(_MENU_ASSERT.search(text)),
            "ignored_collected": "ignored.append" in text,
            # 「受检」的判定要认三种写法（首版只认 `assert ... ignored`，于是把组级脚本里
            # `for item in ignored: … assert ok` 这种写法漏判成"从不校验" —— 假警报）
            "ignored_checked": bool(re.search(
                r"assert[^\n]*ignored|all\([^\n]*ignored|for\s+\w+\s+in\s+ignored", text)),
            "grants": [g.strip() for g in grants[:1]],
        }
    return out


def doc_facts(group):
    """用例文档：组级一份 + 逐应用若干份 —— 各含哪些 VT 编号、组级菜单表列了几个 key。"""
    out = {"group": None, "apps": {}, "apps_with_script_no_doc": [], "apps_with_doc_no_script": []}
    def _heads(text):
        """只取行首的用例编号（交叉引用不算），见 `_VT_HEAD` 的说明。

        **作废用例**（`- ~~**VT-XX-01 …**~~`，本仓用删除线表示）不计入 —— 它已被显式废除
        且脚本改断其"不存在"，再要求脚本引用它只会逼人补假断言。作废条目数单独报出来（不静默）。
        """
        live, dead = set(), set()
        for ln in text.splitlines():
            m = _VT_HEAD.match(ln)
            if not m:
                continue
            (dead if "~~" in ln else live).add(m.group(1))
        return sorted(live - dead)
    gdoc = ROOT / "app" / group / "前端测试用例.md"
    if gdoc.exists():
        text = gdoc.read_text(encoding="utf-8")
        menu_keys = re.findall(r"^\|\s*\d+\s*\|\s*([a-z_0-9]+)\s*\|", text, re.M)
        out["group"] = {"vt": _heads(text), "menu_keys": menu_keys, "file": str(gdoc)}
    scripts = {p.name for p in (ROOT / "app" / group / "tests").glob("verify_view_*.py")}
    for p in sorted((ROOT / "app" / group).glob("*/前端测试用例.md")):
        app = p.parent.name
        out["apps"][app] = _heads(p.read_text(encoding="utf-8"))
        scripts.discard(f"verify_view_{group}_{app}.py")
    for name, facts in script_facts(group).items():
        if facts["vt"] and name in scripts and name != f"verify_view_{group}.py":
            out["apps_with_script_no_doc"].append(name)
    return out


# ── V6：`<template x-if>` 顶层多根（Alpine 只挂载 firstElementChild ⇒ 其余静默丢弃）──
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "source", "track", "wbr"}
_HTML_TAG = re.compile(r"<(/?)([a-zA-Z][\w:-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>")


def multiroot_xif():
    """扫全部 `view.html`：每个 `<template x-if>` 的**顶层子元素**数 > 1 即报。

    为什么这是**静默**缺陷：Alpine 的 `x-if` 实现是
    `el.content.cloneNode(true).firstElementChild` —— 只挂载**第一个**根元素，
    其余**不报错、不告警、凭空少一块**。实测两处：`app/psc/md_project_part/view.html`
    的批量导入（「开始导入」按钮被丢弃，功能在界面上根本用不了 —— 靠补断言实跑才发现）、
    `view/pages/workbench.html` 的「最近错误」（标题在、消息永远不显示）。
    **靠人读 HTML 读不出来**，故必须机器扫。
    """
    hits = []
    files = sorted(list((ROOT / "app").rglob("*.html")) + list((ROOT / "view").rglob("*.html")))
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        stack = []
        for m in _HTML_TAG.finditer(text):
            closing, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
            if closing:
                if stack:
                    stack.pop()
                continue
            self_closing = tag in _VOID_TAGS or attrs.rstrip().endswith("/")
            if stack and stack[-1]["xif"] and stack[-1]["depth"] == len(stack):
                stack[-1]["roots"].append(tag)
            if not self_closing:
                is_xif = tag == "template" and re.search(r"\bx-if\b", attrs) is not None
                stack.append({"xif": is_xif, "roots": [], "depth": len(stack) + 1})
                if is_xif:
                    hits.append((str(p.relative_to(ROOT)), text[:m.start()].count("\n") + 1,
                                 stack[-1]))
    return [(f, ln, e["roots"]) for f, ln, e in hits if len(e["roots"]) > 1]


_STEP_RE = re.compile(r'\s*step\("([^"]+)"\)')
# **断言词汇表要认三种写法**（2026-09-25 加，实测 nasa_pms 的 V7 因此假红 114 处）：
#   `assert <cond>` / `record(<cond>, "…")`（⑤ 规格模板）/ `rec(<cond>, "…")`（⑨ 前端范式）
# 只认 `assert` 时，按规格模板写的组会被判成"整片无断言步"。
_ASSERT_RE = re.compile(r"^\s*(?:assert\s|(?<![\w.])(?:record|rec)\()")


def step_assert_facts(group):
    """按 `step("…")` 切块，逐块统计断言。返回 (无断言步列表, 仅软断言步数, 总步数)。

    **两条口径要分开**（照后端 T2 的同一教训）：
    · **无断言步** = 该步一条 `assert` 都没有 ⇒ **无歧义缺陷**，可入闸（V7）；
    · **仅软断言步** = 整步只有 `count() > 0` / `is not None` 这类 ⇒ **只作报告项**。
      因为前端有一类用例的**规格本身就是计数断言**：渲染步（`.card > 0` 且 `.kpi == 0`）、
      豁免步（"按钮集合恰为 …"）、终态步（"无可见操作按钮"）—— 把它当闸会误红，
      而**常红的闸会训练人绕过它**（本仓反复强调的口径）。
    """
    no_assert, soft_only, total = [], 0, 0
    for p in sorted((ROOT / "app" / group / "tests").glob(f"verify_view_{group}*.py")):
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        steps, cur = [], None
        for i, ln in enumerate(lines):
            m = _STEP_RE.match(ln)
            if m:
                if cur:
                    steps.append(cur)
                cur = {"n": m.group(1), "ln": i + 1, "a": []}
            elif cur is not None and _ASSERT_RE.match(ln):
                cur["a"].append(ln.strip())
        if cur:
            steps.append(cur)
        for st in steps:
            total += 1
            if not st["a"]:
                no_assert.append(f"{p.name}:{st['ln']} {st['n'][:40]}")
            elif all(_SOFT.search(a) for a in st["a"]):
                soft_only += 1
    return no_assert, soft_only, total


def evaluate(group):
    """判据本体：逐脚本/逐文档列出**问题**（供门禁复用，不在这里判 verdict）。

    六条判据（都是「声明了但走不到」在**前端**那一侧的对应物）：

    1. `V1 可追溯`：每个脚本至少引用一条 `VT-` 编号 —— **一条都不写 = 用例与断言没有对应关系**，
       改用例、删断言都无人能发现（实测 11 个脚本原本如此）。
    2. `V2 脚本→文档`：脚本里引用的 VT 编号必须能在它的用例文档里找到（防自造编号）。
    3. `V3 文档→脚本`：用例文档里的每条 VT 编号必须被脚本引用（防"写了没测"）。
    4. `V4 有脚本必须有文档`：逐应用脚本要有 `app/<组>/<应用>/前端测试用例.md`；
       组级页脚本（dashboard/process/material_360）由组级文档覆盖。
    5. `V5 豁免受检`：收集了 `ignored` 的脚本必须**校验**它（否则"0 报错"这个红线会
       被新形态的 4xx 静默穿过）。
    6. `V6 x-if 单根`：每个 `<template x-if>` 只能有一个顶层子元素 —— 多根会被 Alpine
       **静默丢弃**（见 `multiroot_xif`）。与组无关，全仓扫。
    """
    docs = doc_facts(group)
    facts = script_facts(group)
    problems = []
    group_doc_vt = set(docs["group"]["vt"]) if docs["group"] else set()

    # 组级页（无后端应用，key = 文件名）的用例住在**组级文档**里，不要求逐应用文档
    GROUP_LEVEL_PAGES = {"material360", "process", "dashboard"}
    for name, f in sorted(facts.items()):
        app = name[len(f"verify_view_{group}_"):-3] if name.startswith(f"verify_view_{group}_") else None
        is_group_script = app is None or app in GROUP_LEVEL_PAGES
        if not f["vt"]:
            problems.append(("V1 可追溯", name, "脚本里一条 VT- 编号都没有"))
        if f["ignored_collected"] and not f["ignored_checked"]:
            problems.append(("V5 豁免受检", name, "收集了 ignored 却从不校验它"))
        if is_group_script:
            continue
        doc = docs["apps"].get(app)
        if doc is None:
            problems.append(("V4 有脚本必须有文档", name,
                             f"缺 app/{group}/{app}/前端测试用例.md"))
            continue
        script_vt, doc_vt = set(f["vt"]), set(doc)
        for vt in sorted(script_vt - doc_vt):
            problems.append(("V2 脚本→文档", name, f"引用了文档里没有的 {vt}"))
        for vt in sorted(doc_vt - script_vt):
            problems.append(("V3 文档→脚本", name, f"文档用例 {vt} 在脚本里找不到对应断言"))
    # 组级脚本（含组级页脚本）→ 组级文档
    for name, f in facts.items():
        app = name[len(f"verify_view_{group}_"):-3] if name.startswith(f"verify_view_{group}_") else None
        if app is not None and app not in ("material360", "process"):
            continue
        for vt in sorted(set(f["vt"]) - group_doc_vt):
            if f["vt"]:
                problems.append(("V2 脚本→文档", name, f"引用了组级文档里没有的 {vt}"))
    # ⑦ V7：**无断言步**（一条 `assert` 都没有的 step ⇒ 无歧义缺陷）
    no_assert, soft_only, total_steps = step_assert_facts(group)
    for item in no_assert:
        problems.append(("V7 无断言步", item,
                         "该 step 内一条 `assert` 都没有（只证明「没抛异常」）"))
    # ⑥ V6：`x-if` 多根（与组无关，全仓扫一遍）
    for path, line, roots in multiroot_xif():
        problems.append(("V6 x-if 单根", f"{path}:{line}",
                         f"`<template x-if>` 顶层有 {len(roots)} 个根元素 {roots}"
                         f" —— 除第一个外都会被 Alpine 静默丢弃"))
    return {"problems": problems, "docs": docs, "scripts": facts,
            "biz_pages": business_pages(group), "platform": platform_pages()}


def main():
    ap = argparse.ArgumentParser(description="前端验收三方对账（用例文档 ↔ 脚本 ↔ 页面元数据）")
    ap.add_argument("-g", "--group", default="psc")
    args = ap.parse_args()
    group = args.group

    biz = business_pages(group)
    plat = platform_pages()
    print("=" * 78)
    print(f"前端验收对账 · {group}")
    print("=" * 78)
    print(f"\n【真值·页面元数据】业务页 {len(biz)} 项（PAGE_META order 升序）")
    for m in biz:
        print(f"   {m['order']:>4}  {m['key']:<22} {m['name']}")
    print(f"   平台页：{[p['key'] + ('(top)' if p['top'] else '') for p in plat]}")
    print(f"   ⇒ admin 侧栏应为：{[p['name'] for p in plat if p['top'] and not p['hidden']]}"
          f" + 业务 {len(biz)} 项")

    docs = doc_facts(group)
    print("\n【组级用例文档】")
    if docs["group"]:
        g = docs["group"]
        print(f"   VT 编号：{g['vt']}")
        print(f"   菜单表列出 {len(g['menu_keys'])} 个 key：{g['menu_keys'][:6]}…")
        truth = [m["key"] for m in biz]
        missing = [k for k in truth if k not in g["menu_keys"]]
        extra = [k for k in g["menu_keys"] if k not in truth]
        print(f"   ⚠ 文档缺：{missing or '无'}；文档多（真值里没有）：{extra or '无'}")
    else:
        print("   ⚠ 缺 app/<组>/前端测试用例.md")

    print("\n【逐脚本】")
    facts = script_facts(group)
    print(f"   {'脚本':<44}{'VT数':>5}{'断言':>6}{'软断言':>7}{'菜单断言':>9}{'ignored校验':>11}")
    no_vt = []
    for name, f in facts.items():
        print(f"   {name:<44}{len(f['vt']):>5}{f['asserts']:>6}{f['soft']:>7}"
              f"{('有' if f['menu_assert'] else '—'):>9}"
              f"{('有' if f['ignored_checked'] else ('收' if f['ignored_collected'] else '—')):>11}")
        if not f["vt"]:
            no_vt.append(name)
    print(f"\n   ⚠ **一条 VT 编号都不写**的脚本（{len(no_vt)} 个）：{no_vt}")
    print(f"   ⚠ 授权清单字面量：")
    for name, f in facts.items():
        if f["grants"]:
            print(f"      {name}: {f['grants'][0]}")

    print("\n【用例文档 ↔ 脚本 配对】")
    print(f"   逐应用用例文档 {len(docs['apps'])} 份；"
          f"有脚本无用例文档：{docs['apps_with_script_no_doc'] or '无'}")
    for app, vts in docs["apps"].items():
        print(f"   {app:<24} 用例文档 {len(vts)} 条 VT：{vts[:6]}{'…' if len(vts) > 6 else ''}")

    res = evaluate(group)
    _na, _soft, _steps = step_assert_facts(group)
    print(f"   · 断言密度（报告项，不入闸）：{_steps} 步 · 仅软断言 {_soft} 步"
          f"（渲染/豁免/终态类用例的规格本身就是计数断言，**不当缺陷**）")
    probs = res["problems"]
    print(f"\n【判据】七条（V1 可追溯 / V2 脚本→文档 / V3 文档→脚本 / V4 有脚本必须有文档 / V5 豁免受检 / V6 x-if 单根 / V7 无断言步）")
    if probs:
        by_kind = {}
        for kind, name, why in probs:
            by_kind.setdefault(kind, []).append((name, why))
        for kind in sorted(by_kind):
            print(f"   ⚠ {kind}（{len(by_kind[kind])} 条）")
            for name, why in by_kind[kind][:6]:
                print(f"      · {name}：{why}")
            if len(by_kind[kind]) > 6:
                print(f"      · …另 {len(by_kind[kind]) - 6} 条")
    else:
        print("   ✓ 七条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
