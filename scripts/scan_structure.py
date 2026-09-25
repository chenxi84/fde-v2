#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""结构检查 —— 抓「声明了但走不到」的那一类（纯静态，不跑任何服务）。

## 为什么需要它

第⑤步的 `verify_chain_<组>.py` 一律经 `platform.call` **直调公共服务**，所以它
**看不见服务之间的接线**：实测 `TC-ERR-20` 声明测「产能紧张档」却只断言"建单成功"，
而它调的 `demand_pool.create` 没传水位参数 ⇒ 分档逻辑一行没执行。
`BR-06`（产能富余补到组批水位 B）在生产上**永不生效**（16 张补货单补到 B 的 0 张），
89 条用例全过，**没有任何一条会红**。

判据只有一条，但必须收紧，否则天天红：

    某个参数在函数体里**被当作 None 判定条件**（`if x is not None`），
    且它的**全部生产调用点都省略它**，且函数内**没有其它来源**（如 `self.ctx.get(...)`）
    ⇒ 依赖该参数的分支**永不可达**。

「传不传会改变行为」是它和「普通可选参数」的分界线 —— 只看"调用点传的比签名少"会满屏噪音，
因为 Python 里可选参数非常常见。

## 敏感性的传递

一个参数可能只是被**转发**给下游的敏感参数：

    create(..., batch_level_b=None, ...)                     # 自身没判 None
        → self._resolve_replenish_qty(..., batch_level_b, …)  # 下游判了
              if not tight and batch_level_b is not None …    # ← 敏感点在这

所以敏感性要**沿转发链往上游传递**（迭代到不动点）。否则上面这个真实的例子会被漏掉。

## 用法

    python scripts/scan_structure.py            # 扫全部应用组
    python scripts/scan_structure.py -g psc
    python scripts/scan_structure.py --verbose  # 打印扫描规模
"""
import argparse
import ast
import os
import re
import sys
from pathlib import Path

# 输出编码：控制台代码页在本机默认是 GBK，而本文件的判据文案里有 ⇒ 这类**非 GBK 码位** ——
# 不钉住编码的话，print 自己会抛 UnicodeEncodeError（**崩在打印结论那一步**），
# 在外层门禁里表现成「结构检查（不可达分支）FAIL」—— 像判据报了缺陷，其实判据根本没跑完。
# 由 scripts/verify_test_script_encoding.py 守住别忘这一行（它的扫描范围已含 scripts/）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "fde_platform").is_dir():
            return parent
    raise SystemExit("找不到项目根：向上未发现 fde_platform/")


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

MAX_PROPAGATE_ROUNDS = 8

# 已登记为「待决策」的失败项（每行一个靶点前缀，# 注释）。
# 纪律与 `psc_oracles_known.txt` 一致：**修好一项必须立刻删掉** ——
# 留在清单里的已修项会掩盖它日后的回归。
_KNOWN_FILE = Path(__file__).resolve().parent / "structure_known.txt"


def load_known():
    if not _KNOWN_FILE.exists():
        return []
    out = []
    for ln in _KNOWN_FILE.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.append(ln)
    return out


# ---------------------------------------------------------------- 报告
class Report:
    def __init__(self):
        self.rows = []

    def add(self, verdict, target, expect="", actual="", note=""):
        self.rows.append({"v": verdict, "t": target, "e": expect, "a": actual, "n": note})

    def ok(self, t, note=""):
        self.add("PASS", t, note=note)

    def fail(self, t, expect, actual, note=""):
        self.add("FAIL", t, expect, actual, note)

    def skip(self, t, why):
        self.add("SKIP", t, note=why)


REP = Report()
VERBOSE = False


# ---------------------------------------------------------------- AST 抽取
def _arg_names(fn: ast.FunctionDef) -> list:
    """方法参数名（去掉 self）。"""
    return [a.arg for a in fn.args.args if a.arg not in ("self", "cls")]


def _none_checked(fn: ast.FunctionDef, params: set) -> set:
    """函数体里被当作 None 判定条件的参数：`x is None` / `x is not None`。"""
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(comp, ast.Constant) \
                        and comp.value is None:
                    left = node.left
                    if isinstance(left, ast.Name) and left.id in params:
                        out.add(left.id)
    return out


def _has_ctx_fallback(fn: ast.FunctionDef, params: set) -> set:
    """参数名出现在 `...ctx.get("名", ...)` / `ctx["名"]` 里的 —— 视为有其它来源，不算不可达。

    实测 B-08 里 `capacity_tight` 就有 `self.ctx.get("capacity_tight", False)` 兜底，
    所以它不该被报；而 `batch_level_b` / `stock_on_hand` 没有兜底，该被报。
    """
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and node.args:
            a0 = node.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str) and a0.value in params:
                out.add(a0.value)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str) and node.slice.value in params:
            out.add(node.slice.value)
    return out


def _collect_calls(fn: ast.FunctionDef):
    """函数体里的出向调用。

    返回 [(目标种类, 目标名, 位置实参名列表, 关键字实参名集合)]
      种类 self  : self.<name>(...)            —— 同类内调用
      种类 fde   : self.fde.call("<应用>", "<服务>", ...)
    """
    out = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        # ⚠ 必须保留位置：只收 ast.Name 会让位置错位（`f(a, round(b), c)` 里 round(...) 被丢掉，
        # 于是 c 被当成「没传」）——首版就是这么误报了 upsert / calc_baseline / decide。
        pos = [a.id if isinstance(a, ast.Name) else "<expr>" for a in node.args]
        # kw 要带值名：转发链需要知道「我的哪个参数被送进了下游的哪个参数」
        kw = {k.arg: (k.value.id if isinstance(k.value, ast.Name) else None)
              for k in node.keywords if k.arg}
        # self.fde.call("应用", "服务", ...)
        if isinstance(f, ast.Attribute) and f.attr == "call" \
                and isinstance(f.value, ast.Attribute) and f.value.attr == "fde":
            args = node.args
            if len(args) >= 2 and all(isinstance(a, ast.Constant) for a in args[:2]):
                out.append(("fde", (args[0].value, args[1].value),
                            pos[2:], kw))          # 跳过前两个字符串实参
            continue
        # self.<name>(...)
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                and f.value.id in ("self", "cls") and not f.attr.startswith("__"):
            out.append(("self", f.attr, pos, kw))
    return out



def _none_fallback(fn: ast.FunctionDef, params: set) -> set:
    """`if x is None:` 的 body 里给 x 赋了新值 ⇒ 它有其它来源，不算不可达。

    实测 `inventory_projection.refresh` 的 `opening_stock` 就是这类：
        if opening_stock is None:
            opening_stock = self._load_inventory(material_no)      # ← 兜底来源
    而 `_resolve_replenish_qty` 的 `batch_level_b` 没有这种赋值兜底，所以该报。
    """
    out = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        names = set()
        if isinstance(test, ast.Compare):
            for op, comp in zip(test.ops, test.comparators):
                if isinstance(op, ast.Is) and isinstance(comp, ast.Constant) and comp.value is None                         and isinstance(test.left, ast.Name):
                    names.add(test.left.id)
        if not names:
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, ast.Name) and t.id in names:
                        out.add(t.id)
    return out


def _arith_params(fn: ast.FunctionDef, params: set) -> set:
    """参数是否**参与算术**（决定数值结果），而不是只参与拼接 SQL / 过滤条件。

    这是「过滤器参数」与「计算参数」的分界：
      · `list(material_no=None)` → material_no 只进 WHERE 文本 ⇒ None 是合法默认，不该报
      · `_resolve_replenish_qty(..., batch_level_b=None)` → `float(batch_level_b) - sh`
        ⇒ None 会让结果变成另一个值（兜底返回触发方传的补货量）⇒ 该报
    """
    out = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.BinOp):
            continue
        # `Add` 要排除**字符串拼接**：`"%" + old_material_no + "%"` 是在拼 LIKE 模式，
        # 属于过滤器参数的正常用法，不是算术 —— 首版把它当算术，误报了 md_part_replace.list。
        if isinstance(node.op, ast.Add):
            if any(isinstance(s, ast.Constant) and isinstance(s.value, str)
                   for s in (node.left, node.right)):
                continue
        for side in (node.left, node.right):
            if isinstance(side, ast.Name) and side.id in params:
                out.add(side.id)
            if isinstance(side, ast.Call) and isinstance(side.func, ast.Name) \
                    and side.func.id in ("float", "round", "abs", "int", "sum", "max", "min"):
                for a in side.args:
                    if isinstance(a, ast.Name) and a.id in params:
                        out.add(a.id)
    return out


def scan_apps(group=None):
    """{应用名: [方法信息]}，方法信息含 params/none_checked/ctx_fallback/calls。"""
    apps = {}
    files = []
    for group_dir in sorted(Path("app").iterdir()):
        if not group_dir.is_dir():
            continue
        if group == "all" or group_dir.name == group:
            pass
        elif group and group_dir.name != group:
            continue
        for p in sorted(group_dir.glob("*/*.py")):
            if "tests" in p.parts:
                continue          # 只统计**生产**调用点：测试传了参数不代表生产会传
            files.append(p)
    for p in files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        app = p.parent.name
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for fn in node.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if fn.name.startswith("__"):
                    continue
                params = _arg_names(fn)
                pset = set(params)
                apps.setdefault(app, []).append({
                    "app": app, "cls": node.name, "name": fn.name,
                    "file": str(p), "line": fn.lineno,
                    "params": params,
                    "none_checked": _none_checked(fn, pset),
                    "ctx_fallback": _has_ctx_fallback(fn, pset) | _none_fallback(fn, pset),
                    "arith": _arith_params(fn, pset),
                    "calls": _collect_calls(fn),
                })
    return apps


def build_index(apps):
    """(应用, 方法名) -> 方法信息。同名方法在不同应用里不冲突；同类同名取第一个。"""
    idx = {}
    for app, fns in apps.items():
        for m in fns:
            idx.setdefault((app, m["name"]), m)
    return idx


def propagate_sensitivity(apps, idx):
    """把敏感性沿转发链往上游传递，迭代到不动点。

    `create(..., batch_level_b)` 自身不判 None，但它把该参数转发给了
    `_resolve_replenish_qty(..., batch_level_b, ...)`，而下游判了 —— 于是 `create` 的
    这个参数**同样是敏感的**。不做这一步，真实案例（B-08）会被漏掉。
    """
    for _ in range(MAX_PROPAGATE_ROUNDS):
        changed = False
        for app, fns in apps.items():
            for m in fns:
                for kind, target, pos, kw in m["calls"]:
                    if kind == "self":
                        callee = idx.get((app, target))
                    else:
                        # fde.call 里的应用名是**裸名**（不含组前缀），按裸名匹配
                        callee = idx.get((target[0], target[1]))
                    if callee is None:
                        continue
                    cparams = callee["params"]
                    # 本次调用把「我的参数」送进了「下游哪个位置」
                    forwarded = {}
                    for i, nm in enumerate(pos):
                        if i < len(cparams) and nm != "<expr>":
                            forwarded[cparams[i]] = nm
                    for k, v in kw.items():
                        if k in cparams and v:      # v 为 None 表示实参不是简单变量名，跳过
                            forwarded[k] = v
                    for callee_param, my_param in forwarded.items():
                        if my_param not in m["params"]:
                            continue
                        # 敏感性与「参与算术」**都要**沿转发链往上传：
                        # `create` 自己不算术，是下游 `_resolve_replenish_qty` 在算 ——
                        # 只传 none_checked 不传 arith，真实案例 B-08 会被漏掉。
                        if callee_param in callee["none_checked"] \
                                and my_param not in m["none_checked"]:
                            m["none_checked"].add(my_param)
                            changed = True
                        if callee_param in callee.get("arith", set()) \
                                and my_param not in m["arith"]:
                            m["arith"].add(my_param)
                            changed = True
        if not changed:
            break


def call_sites(apps, app, method):
    """全仓（生产代码，排除 tests）对该方法的调用点。"""
    out = []
    for a, fns in apps.items():
        for m in fns:
            for kind, target, pos, kw in m["calls"]:
                if kind == "self":
                    if a == app and target == method:
                        out.append((m, pos, kw))
                else:
                    if target[0] == app and target[1] == method:
                        out.append((m, pos, kw))
    return out


def check_unreachable(apps, only_public=True):
    """对每个方法，检查「敏感且无兜底」的参数是否在所有生产调用点都被省略。

    返回漏斗计数 —— **必须报出来**：判据收得很紧（只认 `is None` + 参与算术），
    进入判据的方法本来就少；若不报规模，将来某次改动把 `sensitive` 收成空集，
    报告会显示「0 失败」而不是「什么都没查」—— 这正是「空规则永远通过」那个坑。
    """
    idx = build_index(apps)
    stat = {"public": 0, "sensitive": 0, "with_sites": 0, "failed": 0}
    for app, fns in apps.items():
        for m in fns:
            if only_public and m["name"].startswith("_"):
                continue          # 私有方法是内部细节，其调用点是同类内转发，见下面的「已检」
            stat["public"] += 1
            # 收紧后的判据：None 敏感 ∧ **参与算术**（决定数值结果）∧ 无兜底来源。
            # 不加「参与算术」这一条，`list(material_no=None)` 这类过滤器参数会全部误报
            # —— 首版 17 条 FAIL 里 12 条是这种。
            sensitive = ((m["none_checked"] - m["ctx_fallback"])
                         & set(m["params"]) & m.get("arith", set()))
            if not sensitive:
                continue
            stat["sensitive"] += 1
            sites = call_sites(apps, app, m["name"])
            if not sites:
                REP.skip(f"{app}.{m['name']} 敏感参数可达性",
                         "无生产调用点（可能是对外服务/由前端调用），静态判不了")
                continue
            # 该参数在**所有**调用点都被省略 ⇒ 永远拿不到非 None
            dead = []
            for p in sorted(sensitive):
                given = False
                for (_m, pos, kw) in sites:
                    if p in kw:
                        given = True
                        break
                    try:
                        pi = m["params"].index(p)
                    except ValueError:
                        continue
                    if pi < len(pos):
                        given = True
                        break
                if not given:
                    dead.append(p)
            stat["with_sites"] += 1
            if dead:
                stat["failed"] += 1
                REP.fail(
                    f"{app}.{m['name']} 敏感参数全部调用点缺省",
                    "被当作 None 判定条件的参数，至少应有一个生产调用点传值",
                    f"以下参数在 {len(sites)} 个生产调用点**全部被省略**：{dead}"
                    f" ⇒ 依赖它们的分支永不可达",
                    f"位置 {m['file']}:{m['line']}；"
                    f"兜底检查已排除有 ctx 来源的参数",
                )
            else:
                REP.ok(f"{app}.{m['name']} 敏感参数可达性",
                       f"{len(sites)} 个调用点，敏感参数 {sorted(sensitive)} 均有传值")
    return stat


def report_funnel(stat, expect=None):
    """漏斗 + 适用性 + **命中数断言**。

    ⚠ 首版把「with_sites == 0」直接判 FAIL，那是**错的**：它把两种情况混为一谈 ——
      · **判据被改窄成空集**（缺陷，要红）
      · **该组本来就没有这类代码**（正常，`app/e2e` 就是：6 个 None 判定全是
        `list(page=None)` 这类过滤器，判据在此组没有适用对象）
    正确的做法是：**适用性用 SKIP**（附漏斗），而「判据自己塌了」改用
    **命中数断言**（`--expect N`）来抓 —— 在已知有命中的组（PSC）上跑时，
    命中数必须等于预期；少报就是判据被改窄了，多报就是有新问题。
    """
    print(f"  · 漏斗：{stat['public']} 个公共方法 → {stat['sensitive']} 个含敏感参数"
          f" → {stat['with_sites']} 个有生产调用点可判 → 报出 {stat['failed']} 条")
    if expect is not None:
        if stat["failed"] == expect:
            REP.ok("S 判据命中数与预期相符", f"预期 {expect} 条，实际 {expect} 条")
        else:
            REP.fail("S 判据命中数与预期不符",
                     f"预期报出 {expect} 条",
                     f"实际 {stat['failed']} 条",
                     "**少报** = 判据被改窄了（或修好后没更新预期）；"
                     "**多报** = 出现了新问题。这条断言就是防「判据静默塌成空集」的")
    if stat["with_sites"] == 0:
        REP.skip("S 判据适用性",
                 f"该组没有「参与算术的 None 判定 + 有生产调用点」的方法"
                 f"（漏斗 {stat['public']}→{stat['sensitive']}→0）"
                 f"—— 判据在此组无适用对象，**不是判据坏了**")
    else:
        REP.ok("S 判据适用性", f"{stat['with_sites']} 个方法进入了判据")


def _balanced(text, i):
    """从 `(` 处开始，返回配对到右括号为止的内容（含嵌套括号）。

    测试脚本里的调用常跨行、且实参里可能嵌函数调用（`round(mape, 4)`），
    所以不能简单地截到第一个 `)`。
    """
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return text[i + 1:j]
    return text[i + 1:]


# 用例编号**两种形态都认**（2026-09-25 加；实测 nasa_pms 因此**崩在 .group() 上**）：
#   · `TC-<字母>-<序号>`：组内**全局**编号（PSC / e2e：TC-DM-01 / TC-MC-04 / TC-ERR-20）
#   · `TC-<序号>`：**逐应用内部**编号（nasa_pms 每个应用从 TC-01 重新起编）
# 只认前者时，后者一条都匹配不到 ⇒ `_TC_RE.search(...)` 返回 None ⇒ 判据**崩在打印之前**，
# 外层门禁把它显示成「结构检查 FAIL」—— 像报了缺陷，其实一条都没判（分母 0）。
_TC_NUM = r"TC-(?:[A-Z]+-)?\d+[a-z]?"
_TC_RE = re.compile(r"(" + _TC_NUM + ")")
_CALL_RE = re.compile(r"\bcall\(\s*\"([a-z_][a-z0-9_]*)\"\s*,\s*\"([a-z_][a-z0-9_]*)\"\s*,")
_DOC_CALL_RE = re.compile(r"`([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\(([^`]*)\)`")


def _kwarg_names(args_text):
    return set(re.findall(r"(?:^|,)\s*([A-Za-z_]\w*)\s*=", args_text))


# TC 编号**必须出现在行的开头**（前面只允许表格/列表标记），否则正文里"见 TC-ERR-05"这种
# 交叉引用会被误当成"当前用例"。
_TC_HEAD_RE = re.compile(r"^\s*[|>\-*#\s]*\**`?\s*(" + _TC_NUM + ")")


def collect_doc_calls(spec: Path):
    """《测试用例.md》里每条 TC 声明的服务调用 → {TC: {(应用,服务): {实参名}}}。

    ⚠ 要**同时支持两种载体**（首版只认列表形态，于是 e2e 的表格形态一行都读不出来，
    分母为空、整条判据静默 SKIP）：
      · 列表载体（`app/psc`）：`- **TC-ERR-20 名称**`
      · 表格载体（PRD 风格）：`` | `TC-MC-04` 名称 | 步骤 | 期望 | ``
    """
    out = {}
    cur = None
    for ln in spec.read_text(encoding="utf-8").splitlines():
        m = _TC_HEAD_RE.match(ln)
        if m:
            cur = m.group(1)
        for cm in _DOC_CALL_RE.finditer(ln):
            app, svc, args = cm.groups()
            if not cur:
                continue
            out.setdefault(cur, {}).setdefault((app, svc), set()).update(_kwarg_names(args))
    return out


def collect_script_calls(scripts):
    """脚本里每条 TC 实际调用的服务 → {TC: {(应用,服务): {实参名}}}。"""
    out = {}
    for sp in scripts:
        text = sp.read_text(encoding="utf-8", errors="replace")
        # 按 step("TC-…") 切块，块内找 call("应用","服务", …)
        marks = [(m.start(), _TC_RE.search(m.group(0)).group(1))
                 for m in re.finditer(r'step\("TC-[^"]*"\)', text)]
        for k, (pos, tc) in enumerate(marks):
            end = marks[k + 1][0] if k + 1 < len(marks) else len(text)
            block = text[pos:end]
            for cm in _CALL_RE.finditer(block):
                app, svc = cm.groups()
                args = _balanced(block, cm.end() - 1)
                out.setdefault(tc, {}).setdefault((app, svc), set()).update(_kwarg_names(args))
    return out


def check_param_parity(group):
    """逐参一致：《测试用例.md》写明的实参，脚本里一个不少。

    规范依据：`design-plus/测试执行.md` 的「入参以代码实际签名为准」**不等于可以删参数**。
    实测代价：`TC-ERR-20` 文档里写了 `stock_on_hand / min_level_a / batch_level_b` 三个水位入参，
    脚本里被"按签名校准"掉了 —— 于是它声称要测的「产能紧张档」一行没执行，
    断言又只检查"建单成功"，**用例通过而规则从未被验证**。
    """
    spec = Path(f"app/{group}/测试用例.md")
    scripts = sorted(Path(f"app/{group}/tests").glob("verify_chain_*.py"))
    if not spec.exists() or not scripts:
        REP.skip("T1 用例文档 → 脚本 逐参一致",
                 f"缺少 {'测试用例.md' if not spec.exists() else 'verify_chain_*.py'}")
        return {"doc": 0, "script": 0, "parity": 0}
    doc = collect_doc_calls(spec)
    scr = collect_script_calls(scripts)
    stat = {"doc": len(doc), "script": len(scr), "parity": 0}
    bad = []
    for tc, calls in sorted(doc.items()):
        for (app, svc), want in sorted(calls.items()):
            if (app, svc) not in scr.get(tc, {}):
                continue          # 脚本里这条 TC 没调这个服务 —— 属"用例未翻译"，不由本判据管
            got = scr[tc][(app, svc)]
            missing = sorted(want - got)
            if missing:
                bad.append((tc, app, svc, missing))
            else:
                stat["parity"] += 1
    if not bad and stat["parity"] == 0:
        REP.skip("T1 用例文档 → 脚本 逐参一致", "分母为空：没有可配对的服务调用")
        return stat
    if bad:
        shown = "；".join(f"{t[0]} {t[1]}.{t[2]} 少传 {t[3]}" for t in bad[:3])
        more = f"（共 {len(bad)} 处，下列前 3）" if len(bad) > 3 else ""
        REP.fail("T1 用例文档 → 脚本 逐参一致",
                 "《测试用例.md》里写明的实参，脚本里一个不少"
                 "（不得因「签名有默认值」而省略）",
                 f"{shown} {more}",
                 f"{stat['parity']} 组配对通过")
    else:
        REP.ok("T1 用例文档 → 脚本 逐参一致", f"{stat['parity']} 组配对通过")
    return stat


# 空转断言：**一整步只有**这类断言 —— 规范见 design-plus/测试执行.md「禁止空转断言」
_DEGENERATE = re.compile(r"is not None|isinstance\(|len\(\w+\) >= 1")
# ⚠ `\.get\("k"\)` 这种写法**不认带默认值的 `.get("k", 0)`** —— 首版就是它把
#   `assert r.get("success", 0) > 0` 误判成「退化断言」（**正则写窄 = 假红**）。
#   放宽为「任何**字符串键**访问」+ 比较符。
_BUSINESS = re.compile(r'\.get\(\s*"[a-z_]+"|\[\s*"[a-z_]+"\s*\]|==|!=|<=|>=|<|>')
# 「有牙」的强信号：引用业务字段，或做了真比较（含 `==`/`!=`/`<`）—— 见 `check_vacuous_assertions`
_STRONG = re.compile(r'\.get\(\s*"[a-z_]+"|\[\s*"[a-z_]+"\s*\]|==|!=|<|>|\bin\b')
# 「退化」的形状：**首个实参**就是 `x is None` / `x is not None` / `isinstance(…)` / `len(…) >= 1`。
# ⚠ 只判**首个实参**，不判"整行含这些词" —— 否则 `record(字段比较 and x is not None)` 这种
#   常见的"保险式写法"会被误判成空转（2026-09-25 实测踩到，nasa_pms 假红 8 处）。
_WEAK_ONLY = re.compile(
    r'^\s*(?:assert|record|rec)\(\s*(?:[\w.\[\]\'"]+\s+is\s+(?:not\s+)?None\s*[,)]'
    r'|isinstance\([^)]*\)\s*[,)]|len\([^)]*\)\s*>=\s*1\s*[,)]'
    r'|True\s*[,)]|False\s*[,)])')


def check_vacuous_assertions(group):
    """T2 空转断言：每个 **TC 用例步**至少要有 1 条**引用业务字段/值**的断言（或 `expect_err`）。

    ⚠ 只查名字以 `TC-` 开头的 step：脚本里还有**非用例的步骤**（如"前置：造数"、
    "MUT-01 变异测试"），它们本来就不该有业务断言 —— 查它们会**假红**（实测踩过）。

    ⚠ 判定是「**只有**退化断言」而不是「出现退化断言」：`isinstance(x, list)` 作为辅助
    （同一步还有 `len(x)==1` 和 `x[0]["no"]==期望`）是正当的 —— 规范条文已按此修正。
    """
    scripts = sorted(Path(f"app/{group}/tests").glob("verify_chain_*.py"))
    if not scripts:
        REP.skip(f"T2 [{group}] 空转断言计数为 0", f"没有 app/{group}/tests/verify_chain_*.py")
        return {"tc": 0, "bad": 0}
    bad, tc_n = [], 0
    for sp in scripts:
        lines = sp.read_text(encoding="utf-8", errors="replace").splitlines()
        cur = None
        steps = []
        for i, ln in enumerate(lines):
            m = re.match(r'\s*step\("([^"]+)"\)', ln)
            if m:
                if cur:
                    steps.append(cur)
                cur = {"n": m.group(1), "ln": i + 1, "b": []}
            elif cur is not None and not re.match(r"\s*step\(", ln):
                cur["b"].append(ln)
        if cur:
            steps.append(cur)
        for st in steps:
            if not st["n"].startswith("TC-"):
                continue          # 非用例步骤（前置造数 / 变异测试）不查
            tc_n += 1
            body = "\n".join(st["b"])
            # **断言词汇表认三种写法**（2026-09-25 加）：`assert <cond>`（PSC）/
            # `record(<cond>, "…")`（**⑤《测试执行.md》模板规定的记录器**）/ `rec(<cond>, "…")`（⑨ 范式）。
            # 只认 `assert` 时，按规格模板写的组整片被判"无断言步"（实测 nasa_pms 报 114 处假警）。
            asserts = [l.strip() for l in st["b"]
                       if re.match(r"\s*(?:assert |(?<![\w.])(?:record|rec)\()", l)]
            has_err = "expect_err(" in body
            # 口径 = **只有退化断言**才算空转（与本文档首段说明一致）。判定一条断言"有没有牙"：
            #   有牙 = 引用了业务字段（`.get("k")` / `["k"]`）**或**做了真的比较（`==` `!=` `<` `>`）；
            #   退化 = **首个实参本身**就是 `x is not None` / `isinstance(…)` / `len(…) >= 1` 这三种形状。
            # ⚠ 2026-09-25 修（首版按行判 `_BUSINESS && !_DEGENERATE`，两处都错）：
            #   · `record(ro["status"] == "obsolete" and call("get", …) is not None)`（**真比较 + is-not-None 保险**）
            #     被整条否掉 ⇒ nasa_pms 报 8 处假红，其中断言其实很有牙；
            #   · 而 `record(src.count("self.fde.call") == 0)` 这种"运算符不是 `<>=`"的又识别不了。
            #   所以改成**看首个实参的形状**，不再"整行含退化词就否"。
            ok = has_err or any(_STRONG.search(a) and not _WEAK_ONLY.match(a) for a in asserts)
            if not ok:
                kind = "无任何断言" if not asserts else "只有退化断言（未引用业务字段）"
                bad.append({"n": st["n"], "f": sp.name, "ln": st["ln"], "k": kind})
    if tc_n == 0:
        REP.skip(f"T2 [{group}] 空转断言计数为 0", "分母为空：没有 TC- 开头的 step")
    else:

        if bad:
            REP.fail(f"T2 [{group}] 空转断言计数为 0（第⑤步门禁）",
                     "每个 TC 用例步至少要有 1 条引用业务字段/值的断言（或 expect_err）",
                     "；".join(f"{t['f']}:{t['ln']} {t['n'][:34]} —— {t['k']}" for t in bad[:3])
                     + (f"（共 {len(bad)} 处）" if len(bad) > 3 else ""),
                     f"{tc_n} 个 TC 步参与比对")
        else:
            REP.ok(f"T2 [{group}] 空转断言计数为 0（第⑤步门禁）", f"{tc_n} 个 TC 步全部有业务断言")
    return {"tc": tc_n, "bad": len(bad)}



_BR_BLOCK_RE = re.compile(r"^####\s+3\.\d+\.\d+\s+`(BR-\d+)`", re.M)
_BR_LIST_RE = re.compile(r"^[-*]\s+BR-\d+[\s:：]", re.M)
_TABLE_HEAD_RE = re.compile(r"^####\s+3\.\d+\.\d+\s+BR\s*结构化信息", re.M)
_TRIO = ("依赖输入", "输出", "生效点")


def check_br_triples(group):
    """T3 详设 BR 三要素完整性 —— 第②步门禁的**机械兜底**（2026-09 新增）。

    规范依据：`design-plus/应用设计.md`「三要素与载体格式无关」——
    每条 BR 的 `依赖输入` / `输出` / `生效点` 必须能从详设里**机器读出**。
    为什么必须机器读：这三条是下游两步唯一的挂钩点（`输出` → 第④步的字段级覆盖；
    `生效点` → 第③步查那条链的实参覆盖）。写成散文就等于没有 —— 实测某组「BR 覆盖度 100%」
    里，补货量的**输出从没有任何断言检查过**，而富余档在生产上**根本走不到**。

    解析两种载体（规格里写明的两种）：
      · 编号小节载体：`#### 3.2.x `BR-nn` 名字` + bullet，要求块内出现三条 bullet
      · PRD 表格载体：BR 表之后另起「BR 结构化信息」表（本判据只认它存在）
    第三种（`- BR-01 …` 这种简陋列表，实测 `sales_history` 是）解析不了 ⇒ **SKIP 并报出**，
    不当通过 —— 它得先有一个能承载三要素的载体。
    """
    root = Path(f"app/{group}")
    parsed = failed = skipped = 0
    for spec in sorted(root.glob("*/应用详设.md")):
        app = spec.parent.name
        text = spec.read_text(encoding="utf-8", errors="replace")
        blocks = list(_BR_BLOCK_RE.finditer(text))
        if _TABLE_HEAD_RE.search(text):
            REP.ok(f"T3 [{app}] BR 三要素完整", "PRD 表格载体：另起「BR 结构化信息」表")
            parsed += 1
            continue
        if not blocks:
            if _BR_LIST_RE.search(text):
                skipped += 1
                REP.skip(f"T3 [{app}] BR 三要素完整",
                         "BR 是「- BR-01 …」这种精简列表，**规格里的两种载体都不是** ⇒ "
                         "判据解析不了，需先给它一个能承载三要素的载体（本项不计入通过）")
            continue
        parsed += 1
        missing = []
        for k, m in enumerate(blocks):
            end = blocks[k + 1].start() if k + 1 < len(blocks) else len(text)
            block = text[m.end():end]
            lack = [f for f in _TRIO if f"- **{f}**:" not in block]
            if lack:
                missing.append(f"{m.group(1)} 缺 {'/'.join(lack)}")
        if missing:
            failed += 1
            REP.fail(f"T3 [{app}] BR 三要素完整",
                     "每条 BR 都要能从详设里机器读出 `依赖输入` / `输出` / `生效点`",
                     f"{len(missing)}/{len(blocks)} 条缺：{'；'.join(missing[:3])}"
                     + ("…" if len(missing) > 3 else ""),
                     "载体：编号小节（三要素写在每条 BR 末尾）")
        else:
            REP.ok(f"T3 [{app}] BR 三要素完整", f"{len(blocks)} 条 BR 三条齐备")
    print(f"  · 漏斗：{parsed + skipped} 份详设 → {parsed} 份可判（{failed} 份缺三要素）"
          f" → {skipped} 份载体解析不了（SKIP）")
    if parsed == 0:
        REP.fail("T3 判据适用性", "至少应有一份详设可判",
                 "可判详设数为 0 ⇒ 判据成了空规则，本次通过不可信")
    else:
        REP.ok("T3 判据适用性", f"{parsed} 份详设进入判据")


def _load_br_coverage():
    """按路径加载 `scripts/br_coverage.py`。

    **刻意不复制判据**：字段级覆盖的取数与比对只有一份实现（本仓库反复踩过
    「同一要求写两遍 = 改一处漏一处」）。这里只是把它当一个模块用。
    """
    import importlib.util
    path = Path(__file__).resolve().parent / "br_coverage.py"
    spec = importlib.util.spec_from_file_location("_br_coverage_for_scan", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_br_output_coverage(group):
    """T4 BR 输出字段级覆盖 —— 第④步门禁（2026-09-17 落地）。

    规格（`design-plus/应用测试.md` / `验证门禁.md` §十一）把覆盖度口径改了：

        旧：每条 BR 能对到至少一条用例            （**文档工作**）
        新：每条 BR 的 `输出` 字段被至少一条用例的**断言**引用过（**测试**）

    判据本体在 `scripts/br_coverage.py`（详设三要素的 `输出` ↔ 脚本里 TC 步的断言）；
    这里只负责把它接进闸。**入闸的前置是先把未覆盖清零** —— 常红的闸比没有闸更坏。
    """
    tests = sorted(Path(f"app/{group}/tests").glob(f"verify_chain_{group}*.py"))
    if not tests:
        REP.skip("T4 BR 输出字段级覆盖（第④步门禁）",
                 f"没有 app/{group}/tests/verify_chain_{group}*.py —— 无从取证")
        return
    try:
        mod = _load_br_coverage()
        mod.GROUP = group
        rows, stats = mod.evaluate()
    except Exception as e:                      # 取证工具自身坏了要**报出来**，不能静默通过
        REP.fail("T4 BR 输出字段级覆盖（第④步门禁）", "取证工具应能正常跑完",
                 f"br_coverage 执行失败：{type(e).__name__}: {e}")
        return
    if stats["total"] == 0:
        REP.skip("T4 BR 输出字段级覆盖（第④步门禁）",
                 f"该组的详设里读不到「三要素·输出」⇒ 判据无适用对象"
                 f"（漏斗 0 条 BR；先跑 T3 补齐三要素）")
        return
    # **按应用 + 按 BR 立项**（不是全组一条，也不是整应用一条）：
    # 修好一条 BR 就能从 known 清单里删一行 —— 粒度粗了会把同应用其它 BR 的回归一起静音。
    by_app = {}
    for r in rows:
        by_app.setdefault(r["app"], []).append(r)
    total_bad = 0
    for app in sorted(by_app):
        bad = []
        for r in by_app[app]:
            if r["kind"] == "covered":
                miss = [f for f, w in r["fields"] if not w]
                if miss:
                    bad.append((r["br"], miss))
            elif r["kind"] == "none":
                bad.append((r["br"], ["`输出` 读不出列名"]))
        n_ok = sum(1 for r in by_app[app] if r["kind"] == "covered" and not any(
            not w for _f, w in r["fields"]))
        if not bad:
            REP.ok(f"T4 [{app}] BR 输出字段级覆盖（第④步门禁）",
                   f"{n_ok} 条有输出字段的 BR 全部被断言引用")
            continue
        for br, miss in bad:
            total_bad += 1
            REP.fail(f"T4 [{app}] {br} 输出字段未被断言引用",
                     "每条 BR 的 `输出` 字段至少被一条用例的**断言**引用过"
                     "（「有编号对应用例」不算覆盖）",
                     f"未被任何断言引用：{'/'.join(miss)}",
                     "取证：python scripts/br_coverage.py（表在《测试用例.md》§4）")
    print(f"  · 漏斗：{stats['total']} 条 BR → 被断言引用 {stats['covered']}"
          f" · 拒绝类 {stats['reject']} · 中间量 {stats['derived']} → 未覆盖 {total_bad} 条")


def _load_view_coverage():
    """按路径加载 `scripts/view_coverage.py`（与 br_coverage 同一做法：判据只有一份）。"""
    import importlib.util
    path = Path(__file__).resolve().parent / "view_coverage.py"
    spec = importlib.util.spec_from_file_location("_view_coverage_for_scan", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_view_traceability(group):
    """V1–V7 前端可追溯性 + `x-if` 单根 + 无断言步（V1–V7，第⑨步门禁，2026-09-17 落地）。

    判据本体在 `scripts/view_coverage.py`（三方对账：用例文档 ↔ 脚本 ↔ **页面元数据**）；
    这里只把它接进闸。**它抓的是后端那套判据抓不到的一类漂移** ——
    前端「用例文档写了但没人测 / 脚本测了但没写 / 豁免被静默吞掉」，
    实测 PSC 首次对账报出 191 条（其中 V3 就 134 条），且**组级脚本因手抄菜单一直是红的**。
    V6 是**模板层**的静默缺陷：`<template x-if>` 顶层多根时 Alpine 只挂载第一个、其余凭空消失
    （实测两处：批量导入的提交按钮、工作台的「最近错误」内容）。
    """
    tests = sorted(Path(f"app/{group}/tests").glob("verify_view_*.py"))
    if not tests:
        REP.skip(f"V1-V7 [{group}] 前端可追溯性（第⑨步门禁）",
                 f"没有 app/{group}/tests/verify_view_*.py —— 无从取证")
        return
    try:
        mod = _load_view_coverage()
        res = mod.evaluate(group)
    except Exception as e:
        REP.fail(f"V1-V7 [{group}] 前端可追溯性（第⑨步门禁）", "取证工具应能正常跑完",
                 f"view_coverage 执行失败：{type(e).__name__}: {e}")
        return
    probs = res["problems"]
    by_kind = {}
    for kind, name, why in probs:
        by_kind.setdefault(kind, []).append((name, why))
    print(f"  · 漏斗：{len(tests)} 个脚本 → 五条判据报出 {len(probs)} 条"
          f"（{'；'.join(f'{k} {len(v)}' for k, v in sorted(by_kind.items())) or '全过'}）")
    if not probs:
        REP.ok(f"V1-V7 [{group}] 前端可追溯性（第⑨步门禁）",
               f"{len(tests)} 个脚本 · 用例文档与脚本双向对得上 · 豁免清单受检")
        return
    for kind in sorted(by_kind):
        items = by_kind[kind]
        shown = "；".join(f"{n}（{w}）" for n, w in items[:3])
        if len(items) > 3:
            shown += f" …共 {len(items)} 条"
        REP.fail(f"{kind} · [{group}] 前端脚本可追溯性", "见该判据的定义（文件头有说明）",
                 shown, "取证：python scripts/view_coverage.py")


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description="结构检查：声明了但走不到")
    ap.add_argument("-g", "--group", default="psc", help="应用组（默认 psc；all=全部）")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--expect", type=int, default=None,
                    help="断言判据的命中数（防「判据静默塌成空集」）；PSC 用 --expect 1")
    args = ap.parse_args()
    VERBOSE = args.verbose

    print("=" * 78)
    print("结构检查 · 不可达分支（纯静态，不跑任何服务）")
    print("  判据：参数被当 None 判定条件 + 全部生产调用点省略 + 无 ctx 兜底 ⇒ 分支不可达")
    print("=" * 78)

    apps = scan_apps(args.group if args.group != "all" else None)
    if not apps:
        print(f"没扫到应用（-g {args.group}）")
        return 1
    n_fn = sum(len(v) for v in apps.values())
    print(f"扫描：{len(apps)} 个应用 / {n_fn} 个方法")
    if VERBOSE:
        idx = build_index(apps)
        sensitive_n = sum(1 for _a, fns in apps.items() for m in fns if m["none_checked"])
        print(f"  · 含 None 判定的方法：{sensitive_n}")
        print(f"  · 索引键数：{len(idx)}")

    propagate_sensitivity(apps, build_index(apps))
    report_funnel(check_unreachable(apps), expect=args.expect)

    print("\n--- 用例文档 → 脚本 逐参一致 ---")
    ps = check_param_parity(args.group)
    if VERBOSE:
        print(f"  · 文档 TC 数 {ps['doc']}，脚本 TC 数 {ps['script']}")

    print("\n--- T2 空转断言（第⑤步门禁）---")
    check_vacuous_assertions(args.group)

    print("\n--- T3 详设 BR 三要素完整性（第②步门禁）---")
    check_br_triples(args.group)

    print("\n--- T4 BR 输出字段级覆盖（第④步门禁）---")
    check_br_output_coverage(args.group)

    print("\n--- V1-V7 前端脚本可追溯性（第⑨步门禁）---")
    check_view_traceability(args.group)

    print("\n" + "=" * 78)
    for r in REP.rows:
        mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "–"}[r["v"]]
        print(f"  {mark} {r['v']:<4} {r['t']}")
        if r["v"] == "FAIL":
            print(f"        期望：{r['e']}")
            print(f"        实际：{r['a']}")
        if r["n"]:
            print(f"        备注：{r['n']}")
    c = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for r in REP.rows:
        c[r["v"]] += 1
    known = load_known()
    fails = [r["t"] for r in REP.rows if r["v"] == "FAIL"]
    registered = [t for t in fails if any(t.startswith(k) for k in known)]
    fresh = [t for t in fails if t not in registered]
    print(f"\n通过 {c['PASS']} · 失败 {c['FAIL']} · 跳过 {c['SKIP']}")
    if registered:
        print(f"其中 {len(registered)} 项已登记为待决策（不判为新回归）：")
        for t in registered:
            print(f"  · {t}")
    if fresh:
        print(f"⚠ {len(fresh)} 项**未登记**的失败：")
        for t in fresh:
            print(f"  · {t}")
    print(f"VERIFY_RESULT: {'FAIL' if fresh else ('PARTIAL' if registered else 'PASS')}")
    print("=" * 78)
    return 0 if not fresh else 1


if __name__ == "__main__":
    sys.exit(main())
