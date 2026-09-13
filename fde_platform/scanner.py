"""FDE v2 静态调用扫描器（CONVENTION §5 / §10.8）。

**不运行应用**，仅用 AST 解析每个应用主文件里的 `self.fde.call("应用", "服务", ...)`，
校验：① 目标应用 / 服务是否真实存在；② **调用参数与目标服务签名的契约**
（未知参数 / 缺必传参数 / 重复传参 / 位置参数过多）——把"按名调用、运行期绑定"
可能带来的运行期错误（目标不存在 / 参数名漂移）**左移到开发期**。
含 `**` 展开的调用无法静态枚举参数，仅校验目标（判为 ok 并在消息中注明）。

结果展示于平台首页（亦经 `/api/scan`），命令行可单独运行：
    python -m fde_platform.scanner        # 输出 JSON 报告；存在问题时退出码为 1（可用于 CI）
"""
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ── 调用点状态 ──────────────────────────────────────────

OK = "ok"                  # 目标应用与服务均存在（且参数契约相符）
NO_APP = "no_app"          # 目标应用不存在
NO_SERVICE = "no_service"  # 目标应用存在，但无此公共服务
CONTRACT = "contract"      # 目标存在，但调用参数与签名契约不符（未知/缺必传/重复/位置过多）
DYNAMIC = "dynamic"        # 目标参数非常量字符串，无法静态判定（警告，需人工确认）
PARSE_ERROR = "parse_error"  # 应用主文件解析失败

STATUS_LABELS = {
    OK: "正常",
    NO_APP: "应用不存在",
    NO_SERVICE: "服务不存在",
    CONTRACT: "参数契约不符",
    DYNAMIC: "动态目标（需人工确认）",
    PARSE_ERROR: "解析失败",
}
# 硬问题（会让运行期调用失败）；dynamic 仅是警告，不计入
PROBLEM_STATUSES = {NO_APP, NO_SERVICE, CONTRACT, PARSE_ERROR}


# ── AST 提取 ────────────────────────────────────────────


def _is_self_fde_call(node: ast.Call) -> bool:
    """判断 Call 节点是否为 `self.fde.call(...)`。"""
    f = node.func
    return (
        isinstance(f, ast.Attribute)
        and f.attr == "call"
        and isinstance(f.value, ast.Attribute)
        and f.value.attr == "fde"
        and isinstance(f.value.value, ast.Name)
        and f.value.value.id == "self"
    )


def _str_literal(node):
    """取字符串字面量值；非常量字符串返回 None（视为动态目标）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def extract_calls(source: str) -> list[dict]:
    """提取源码中全部 `self.fde.call` 调用点。

    Returns:
        [{"line", "target_app", "target_service", "kw_names", "positional", "has_star"}]
        目标非常量时对应字段为 None；kw_names=关键字参数名集合；
        positional=位置参数个数（不含 app/service 两个）；has_star=含 ** 展开。
    """
    tree = ast.parse(source)
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_self_fde_call(node):
            target_app = _str_literal(node.args[0]) if len(node.args) >= 1 else None
            target_service = _str_literal(node.args[1]) if len(node.args) >= 2 else None
            kw_names, has_star = set(), False
            for kw in node.keywords:
                if kw.arg is None:  # **params 展开 → 参数不可静态枚举
                    has_star = True
                else:
                    kw_names.add(kw.arg)
            calls.append(
                {
                    "line": node.lineno,
                    "target_app": target_app,
                    "target_service": target_service,
                    "kw_names": sorted(kw_names),
                    "positional": max(0, len(node.args) - 2),
                    "has_star": has_star,
                }
            )
    return calls


def _check_contract(app_name: str, service: str, params: list, call: dict):
    """调用参数 vs 服务签名契约（参数名/必传/位置层面）。返回 (status, message)。"""
    if call["has_star"]:  # 含 ** 展开：无法静态枚举参数，仅校验目标
        return OK, "目标存在（参数含 ** 展开，未静态校验）"
    pnames = [p["name"] for p in params]
    pset = set(pnames)
    required = {p["name"] for p in params if p["required"]}
    pos = call["positional"]
    if pos > len(pnames):
        return CONTRACT, (f"位置参数过多：{app_name}.{service}"
                          f"（传 {pos} 个，服务仅 {len(pnames)} 个入参）")
    pos_names = set(pnames[:pos])  # 位置参数按序映射到前 pos 个形参
    kw_names = set(call["kw_names"])
    dup = pos_names & kw_names
    if dup:
        return CONTRACT, f"重复传参：{app_name}.{service}({', '.join(sorted(dup))})"
    unknown = kw_names - pset
    if unknown:
        return CONTRACT, f"调用参数不存在：{app_name}.{service}({', '.join(sorted(unknown))})"
    missing = required - pos_names - kw_names
    if missing:
        return CONTRACT, f"缺少必传参数：{app_name}.{service}({', '.join(sorted(missing))})"
    return OK, "目标存在"


# ── 全平台扫描 ──────────────────────────────────────────


# ── 规范引用完整性 ────────────────────────────────────────────
#
# 源码里常写「见 design-plus/<某文档> §N」作为设计依据。这类引用**悬空了没人知道**——
# `agent_roles.py` 与 `agent_service.py` 都引用了 `design-plus/多智能体方案.md`，
# 而那个文件根本不存在，是靠人工 grep 才发现的。
#
# 规范与实现的互指一旦断裂，实现演化了规范却不会有人察觉；这条检查把它变成 CI 红线。
#
# 字符集必须放开到 CJK —— design-plus 下**多数是中文文件名**，用 [A-Za-z0-9_/-]
# 会把它们全漏掉（第一版就漏了，只命中我自己注释里的英文占位符）。
_DOC_REF_RE = re.compile(r"design-plus/([^\s，。、；：）)】」\"'`]+\.md)")


def doc_ref_report(root: Path = None) -> list[dict]:
    """扫源码里对 design-plus 下 md 文档的引用，返回指向**不存在的文件**的那些。"""
    root = root or ROOT
    problems = []
    for sub in ("fde_platform", "app", "scripts", "main.py"):
        target = root / sub
        files = sorted(target.rglob("*.py")) if target.is_dir() else (
            [target] if target.is_file() else [])
        for f in files:
            try:
                src = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in _DOC_REF_RE.finditer(src):
                rel = f"design-plus/{m.group(1)}"
                if not (root / rel).is_file():
                    problems.append({
                        "kind": "doc_ref",
                        "file": str(f.relative_to(root)),
                        "line": src.count("\n", 0, m.start()) + 1,
                        "ref": rel,
                        "message": f"引用了不存在的规范：{rel}",
                    })
    return problems


def scan_report(platform) -> dict:
    """扫描平台已加载的全部应用，返回结构化报告。

    Returns:
        {
          "apps_scanned": int, "total_calls": int, "problems": int, "warnings": int,
          "sites": [{app, file, line, target_app, target_service, status, status_label, message}],
          "parse_errors": [{app, message}],
        }
    """
    known_apps = set(platform.app_names())          # 组限定名（qualname）集合
    # 短名 → qualname 列表（跨组重名时多个）；用于按调用方所在组解析 fde.call 目标（§5）
    by_short: dict[str, list] = {}
    for q in known_apps:
        by_short.setdefault(q.rsplit("/", 1)[-1], []).append(q)
    services_cache = {
        q: {s["name"]: s["parameters"] for s in platform.services(q)}
        for q in known_apps
    }

    def _resolve_target(ta: str, caller_group):
        """按 §5 组内优先解析调用目标短名 → qualname。返回 (qualname, (status,msg) 或 None)。"""
        if caller_group is not None:
            same = f"{caller_group}/{ta}"
            if same in known_apps:
                return same, None
        if ta in known_apps:                       # 未分组应用名或本就是完整 qualname
            return ta, None
        cands = by_short.get(ta, [])
        if len(cands) == 1:
            return cands[0], None
        if len(cands) > 1:
            return None, (NO_APP,
                          f"目标应用 {ta} 在多个组中存在 {sorted(cands)}，"
                          f"调用方所在组无此应用，请用 组/应用 明确指定")
        return None, (NO_APP, f"目标应用不存在：{ta}")

    sites = []
    parse_errors = []
    for q in sorted(known_apps):
        handle = platform.handle(q)
        caller_group = handle.group
        main_file = handle.folder / f"{handle.name}.py"
        # 展示路径含应用组：app/<组>/<名>/<名>.py（未分组为 app/<名>/<名>.py）
        try:
            rel = f"{handle.folder.relative_to(ROOT)}/{handle.name}.py"
        except ValueError:  # apps_dir 在仓库外（测试临时目录）→ 退绝对路径
            rel = str(main_file)

        try:
            calls = extract_calls(main_file.read_text(encoding="utf-8"))
        except Exception as e:  # 语法错误等
            parse_errors.append({"app": q, "message": f"{type(e).__name__}: {e}"})
            sites.append(
                _site(q, rel, 0, "", "", PARSE_ERROR, f"主文件解析失败：{e}")
            )
            continue

        for c in calls:
            ta, ts = c["target_app"], c["target_service"]
            if ta is None or ts is None:
                sites.append(_site(q, rel, c["line"], ta or "?", ts or "?",
                                   DYNAMIC, "目标为动态表达式，无法静态判定，请人工确认"))
                continue
            resolved, err = _resolve_target(ta, caller_group)
            if err is not None:
                status, msg = err
                sites.append(_site(q, rel, c["line"], ta, ts, status, msg))
            elif ts.startswith("_") or ts not in services_cache[resolved]:
                sites.append(_site(q, rel, c["line"], resolved, ts,
                                   NO_SERVICE, f"应用 {resolved} 无此公共服务：{ts}"))
            else:
                status, msg = _check_contract(resolved, ts, services_cache[resolved][ts], c)
                sites.append(_site(q, rel, c["line"], resolved, ts, status, msg))

    doc_refs = doc_ref_report()

    return {
        "apps_scanned": len(known_apps),
        "total_calls": sum(1 for s in sites if s["status"] != PARSE_ERROR),
        "problems": (sum(1 for s in sites if s["status"] in PROBLEM_STATUSES)
                     + len(doc_refs)),          # 悬空规范引用也算问题（CI 应失败）
        "warnings": sum(1 for s in sites if s["status"] == DYNAMIC),
        "sites": sites,
        "parse_errors": parse_errors,
        "doc_refs": doc_refs,
    }


def _site(app, file, line, target_app, target_service, status, message) -> dict:
    return {
        "app": app,
        "file": file,
        "line": line,
        "target_app": target_app,
        "target_service": target_service,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "message": message,
    }


# ── CLI ─────────────────────────────────────────────────


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    from fde_platform.runtime import FdePlatform

    pf = FdePlatform()
    pf.load_all()
    report = scan_report(pf)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        f"\n扫描 {report['apps_scanned']} 个应用 · 跨应用调用 {report['total_calls']} 处 · "
        f"问题 {report['problems']} 处 · 警告 {report['warnings']} 处",
        file=sys.stderr,
    )
    sys.exit(1 if report["problems"] else 0)  # 供 CI：有问题即失败
