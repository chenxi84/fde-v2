"""nasa_pms 演示环境 · 一键重建（清空 → 造数 → 体检）。

    python app/nasa_pms/demo/demo_build.py             # 重建并体检
    python app/nasa_pms/demo/demo_build.py --keep      # 不清空，仅追加以调试造数脚本
    python app/nasa_pms/demo/demo_build.py --start     # 重建后顺便起平台（:4000）

**不用停 dev server**（与 `app/psc` 的 `宣传/demo_build.py` 的差别）：那个脚本要停服是因为它
走 dbguard 移库；本脚本是**直接经服务写业务库**，SQLite/WAL 支持并发写。不过演示/造数期间
最好别在浏览器里同时改同一批数据（那会撞 BR 校验，报错倒是会明确指出来）。

与 PSC 演示环境的分工：
  · 本脚本只负责**业务数据**（11 个聚合根的故事线）；
  · **智能体资产**（技能库 / 定时任务 / 集成接口）没有对应产物 —— nasa_pms 未声明
    `_roles.py` / `_flow_*.yaml`（九步法第⑩⑪步是可选增强），见 `README.md` §未做。
"""
from __future__ import annotations

import argparse
import pathlib
import socket
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _project_root() -> pathlib.Path:
    p = HERE
    while not (p / "fde_platform").is_dir():
        if p.parent == p:
            raise SystemExit("找不到项目根：向上未发现 fde_platform/")
        p = p.parent
    return p


ROOT = _project_root()
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="nasa_pms 演示环境一键重建")
    ap.add_argument("--keep", action="store_true", help="不清空，直接追加（调试造数脚本用）")
    ap.add_argument("--start", action="store_true", help="重建后起平台（python main.py）")
    args = ap.parse_args()

    if listening(4000):
        sys.stdout.write("· :4000 上已有服务在跑 —— 本脚本是**普通写库**，不需要停服；\n"
                         "  只是提醒：重建期间别在浏览器里同时改演示数据。\n")

    import demo_seed

    if not args.keep:
        sys.stdout.write("\n① 清空本组 11 个应用库的表\n")
        demo_seed.clear()
    else:
        sys.stdout.write("\n① （--keep）跳过清空\n")

    sys.stdout.write("\n② 造数（按《demo_seed.py》的故事线，经真实服务）\n")
    import os
    os.chdir(ROOT)
    from fde_platform.runtime import FdePlatform
    pf = FdePlatform()
    pf.load_all()
    for app in demo_seed.APPS:
        assert pf.handle(f"{demo_seed.GROUP}/{app}") is not None, f"{app} 未加载"
    want = demo_seed.seed(pf)
    sys.stdout.write("   设计态：%s\n" % {k: want[k] for k in ("requirement", "risk", "configuration_item",
                                                          "change_request", "verification",
                                                          "technical_measure", "review", "decision",
                                                          "interface", "tech_plan", "stakeholder")})

    sys.stdout.write("\n③ 体检（verify_demo.py）\n")
    rc = subprocess.run([sys.executable, str(HERE / "verify_demo.py")]).returncode
    if rc != 0:
        sys.stdout.write("✗ 体检未通过 —— 造数与 `verify_demo.py` 的口径不一致，先对齐再演。\n")
        return rc

    if args.start:
        sys.stdout.write("\n④ 起平台（Ctrl-C 结束）\n")
        return subprocess.run([sys.executable, "main.py"], cwd=str(ROOT)).returncode

    sys.stdout.write("\n✓ 演示环境就绪。起服务：python main.py → http://127.0.0.1:4000 （admin/admin）\n"
                     "  看板会显示各应用状态分布；11 个台账都有数据可点。\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
