"""契约冻结工具：dump 组内各应用服务契约 + 尽力真实返回样例 → app/<组>/_contracts.md。

前端设计（九步法第⑥步）的硬依赖屏障：`_contracts.md` 冻结后才可开工前端详设。
两个入口（共用一份实现）：

  ① CLI 调用：`python -m fde_platform.contract_dump <组名>`——沙箱子进程内 dump 契约——
     沙箱复制排除一切 `*.db*`，应用在沙箱内建全新空库，造数链产出签名 + 真实 payload；
     **一次性副本即隔离，不 import dbguard、不依赖 tests/**。
  ② 手工 CLI（design 手工工具链路径）：`python -m fde_platform.contract_dump <组>`
     默认**不造数**（seed=False）：仅签名内省 + 库中现有数据尽力取 list 样例，
     不搬移 / 不污染真实库，无需停平台服务器（WAL 并发读）。
     `--seed` 按组造数链写库取样——仅建议空库 / 测试库场景手工使用。

输出格式与旧 `tests/_dump_contracts.py` 逐节一致（便于 diff）；旧脚本随 tests/ 废弃退场。
造数链为**组侧可选钩子**：`app/<组>/seed_contracts.py` 暴露 `seed(call, ctx)`——
平台只定义钩子契约、不内嵌任何组的业务逻辑（本模块对应用组完全独立）；
无造数链的组仅 dump 服务签名 + 尽力 list 样例（标注读源码）。
"""
import json
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
APPS_DIR = PROJECT_ROOT / "app"


def _jd(obj):
    """紧凑 JSON（限幅，防超长）。"""
    s = json.dumps(obj, ensure_ascii=False, indent=1, default=str)
    return s if len(s) < 3500 else s[:3500] + "\n  …（已截断）"


# ────────────────────────────────────────────────────────────
# 造数链：组侧可选钩子（平台不内嵌任何组业务逻辑，本模块对应用组完全独立）
# ────────────────────────────────────────────────────────────
def _load_group_seed(group: str):
    """发现组造数链：`app/<组>/seed_contracts.py` 暴露的 `seed(call, ctx)`。

    钩子不存在返回 None → dump 退化为签名级（list 示例尽力取库中现有数据）。"""
    path = APPS_DIR / group / "seed_contracts.py"
    if not path.is_file():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"_seed_contracts_{group}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "seed", None)


def dump(group: str, seed: bool = False, out=None):
    """dump 组内各应用服务契约 + 尽力真实返回样例 → app/<组>/_contracts.md。

    seed=True  按组造数链（app/<组>/seed_contracts.py，缺则退化签名级）造数后取样；
    seed=False 仅签名内省 + 库中现有数据尽力取 list 样例（手工默认，不污染真实库）。
    返回 (输出路径, 应用短名列表)。"""
    from fde_platform.runtime import FdePlatform

    pf = FdePlatform()
    pf.load_all()

    def call(app, svc, **kw):
        # 短名一律加组限定名（跨组重名时短名有歧义，如 crm/demo 皆有 customer）
        name = app if "/" in app else f"{group}/{app}"
        return pf.call(name, svc, **kw)

    # ── 应用清单：目录扫描（与平台装配同源）；组目录缺失时退路取已加载的本组应用 ──
    group_dir = APPS_DIR / group
    if group_dir.is_dir():
        pairs = [(d.name, f"{group}/{d.name}") for d in sorted(group_dir.iterdir())
                 if d.is_dir() and (d / f"{d.name}.py").exists()]
    else:
        pairs = []
    if not pairs:
        pairs = [(n.split("/")[-1], n) for n in pf.app_names()
                 if pf.handle(n).group == group]
    if not pairs:
        raise RuntimeError(f"app/{group} 下没有任何应用代码（<应用>/<应用>.py），"
                           f"请先完成应用编码（九步法第③步）。")

    # ── 造数（按组分派；失败即跳过该单据，dump 标注见源码）──
    ctx = {}
    if seed:
        fn = _load_group_seed(group)
        if fn:
            fn(call, ctx)
        else:
            print(f"[warn] 组 {group!r} 无造数链（app/{group}/seed_contracts.py），仅 dump 服务签名（list 示例尽力取库中现有数据）")

    # ── 生成 Markdown ──
    note = ("get/list 示例为真实返回（造数失败的项以源码为准）。" if seed else
            "list 示例取自库中现有数据（无数据项以源码为准；造数级样例经平台⑧契约冻结任务生成）。")
    lines = [f"# {group} 模块契约速查（自动生成 · 视图生成参照）\n",
             f"> 字段以此文件与 `app/{group}/<应用>/<应用>.py` 源码为准；{note}\n"]
    for short, qname in pairs:
        lines.append(f"\n## {short}\n")
        lines.append("### 服务契约\n```")
        for s in pf.services(qname):
            ps = ", ".join(
                p["name"] + ("*" if p["required"]
                             else f"={p['default']!r}:{p['json_type']}")
                for p in s["parameters"])
            lines.append(f"{s['name']}({ps})")
            if s["description"]:
                lines.append(f"    — {s['description']}")
        lines.append("```\n")
        sample = ctx.get(short, "__none__")
        if sample == "__none__":
            lines.append("### get/list 示例\n（未造出样例 —— 字段请读源码 get()/INSERT 语句）\n")
        else:
            lines.append("### 真实返回示例\n```json")
            lines.append(_jd(sample))
            lines.append("```\n")
        try:
            lst = call(qname, "list")
            items = lst["items"] if isinstance(lst, dict) and "items" in lst else lst
            if isinstance(items, list) and items:
                lines.append("### list 返回项示例\n```json")
                lines.append(_jd(items[0]))
                lines.append("```\n")
        except Exception:
            pass  # 无 list 服务或参数不符则跳过

    out = pathlib.Path(out) if out else (APPS_DIR / group / "_contracts.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    missing = [short for short, _ in pairs if ctx.get(short) is None]
    print(f"已生成 {out}（{len(pairs)} 个应用）")
    if seed:
        print("缺样例应用: " + ("无" if not missing else "、".join(missing)))
    return out, [p[0] for p in pairs]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="契约冻结：dump 组内各应用服务契约 + 尽力真实返回样例 → app/<组>/_contracts.md")
    ap.add_argument("group", nargs="?", default="crm", help="应用组名（默认 crm）")
    ap.add_argument("--seed", action="store_true",
                    help="按组造数链 app/<组>/seed_contracts.py 造数后取样（会写入当前库——仅建议空库/测试库使用；"
                         "默认不造数，取库中现有数据样例，不污染真实库）")
    ap.add_argument("--out", default=None, help="输出路径（默认 app/<组>/_contracts.md）")
    args = ap.parse_args()
    dump(args.group, seed=args.seed, out=args.out)
