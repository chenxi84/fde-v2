"""view e2e 的**卡住诊断**（测试支撑模块，与 `shadowdb.py` 同类；平台运行时不加载）。

## 它解决什么

view 脚本偶尔会在某一步**静默卡住**：页面冻死或渲染进程崩溃之后，所有 playwright 调用都不返回，
脚本既不抛错也不打印 —— 跑手只能按超时判 FAIL，而**现场全丢**：
脚本里收集的 console 错误 / pageerror / HTTP≥400 只有在末尾断言时才被看到，卡住时一条都看不到。
（2026-09-18 实测：`strategy_fitting` 的「§4 批量拟合」反复出现这种情况，
连"它到底卡在哪一句"都无从判断。后来靠**残留副本的数据库**才证明后端已执行完 —— 见
`app/psc/BUGS_psc_2026-09-15.md` §8。那次教训就是本模块的由来：**卡住时必须留下现场**。）

## 怎么工作

起一个守护线程，每 5 秒看一眼**脚本当前走到哪一步**（`step_getter()` 返回脚本自己的 `STEP`）：

- **步骤变了** ⇒ 有进展，重新计时；
- **连续 `stall_s` 秒没变** ⇒ 打一段诊断（最后完成的步骤 + 已收集的错误明细 + 已卡多久），
  之后每 `repeat_s` 秒再打一次（带上累计卡住时长），直到脚本被跑手强杀。
  ⇒ 于是「超时被强杀」的那份输出里**已经有现场**。

⚠ **只打印、不终止进程**：诊断模块不该改变被测脚本的行为（不引入新的失败方式）。
⚠ 线程里**不碰 playwright**（它非线程安全）；只读脚本自己维护的列表与字符串。

## 用法（view 脚本）

    from fde_platform.view_watchdog import install_watchdog
    ...
    errors, ignored = [], []
    install_watchdog(errors, step_getter=lambda: STEP)      # STEP 由脚本的 step() 维护

若某处长时间没有 `step()`（例如一大段循环），可自行 `wd.progress()` 打点。
"""
import os
import subprocess
import threading
import time
from types import SimpleNamespace


def _renderer_mem_mb() -> str:
    """当前 chromium 各进程内存合计（MB）——**卡住时区分的判据**：

    · 内存**持续爬升** ⇒ 页面里有个"边循环边分配"的东西（渲染进程最后多半被 OOM 杀掉，
      表现就是 `Page crashed`）；
    · 内存**平稳** ⇒ 纯自旋/死锁，排查方向完全不同。
    用 `tasklist` 从**操作系统侧**取（线程里不能碰 playwright）；取不到就返回 `"?"`。
    """
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome-headless-shell.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace",
        ).stdout or ""
        total_kb, n = 0, 0
        for line in out.splitlines():
            cells = [c.strip('"') for c in line.split('","')]
            if len(cells) >= 5:
                digits = "".join(ch for ch in cells[4] if ch.isdigit() or ch == ",")
                if digits:
                    total_kb += int(digits.replace(",", ""))
                    n += 1
        return f"{total_kb / 1024:.0f}MB/{n}进程" if n else "无 chromium 进程"
    except Exception:                          # noqa: BLE001 - 诊断本身不许失败
        return "?"


def _renderer_cpu_s() -> str:
    """chromium 进程的**累计 CPU 秒数**（OS 侧采样）——与内存采样配合，区分两种冻住：

    · 每次采样 CPU 涨约等于墙钟（如 30s 采样涨 ~30s）⇒ **渲染线程在自旋**（JS 死循环），
      这是页面缺陷；
    · CPU 几乎不涨 ⇒ **不是自旋**，而是死锁/管道阻塞（渲染线程闲着，只是没人应答）。
    """
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$p=Get-Process chrome-headless-shell -ErrorAction SilentlyContinue;"
             "if($p){[math]::Round(($p | Measure-Object CPU -Sum).Sum,1)}else{'none'}"],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
        )
        return (r.stdout or "").strip() or "?"
    except Exception:                          # noqa: BLE001 - 诊断本身不许失败
        return "?"


def _env_int(name: str, default: int) -> int:
    """环境变量覆盖（诊断时想快点看到现场就调小，例如 `VIEW_WATCHDOG_STALL_S=60`）。"""
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def install_watchdog(errors, step_getter=None, stall_s: int = None, repeat_s: int = None):
    """安装卡住诊断，返回一个带 `progress()` 的句柄（不需要可忽略返回值）。

    `errors`：脚本收集错误用的 list（诊断时原样打印前若干条）。
    `step_getter`：返回"当前步骤名"的可调用（用它的**变化**当作进展信号）。
    `stall_s`：多久没进展算卡住（默认 120s —— 比任何单步的正常耗时都长）。
    `repeat_s`：卡住后每隔多久再报一次。
    """
    stall_s = stall_s if stall_s else _env_int("VIEW_WATCHDOG_STALL_S", 120)
    repeat_s = repeat_s if repeat_s else _env_int("VIEW_WATCHDOG_REPEAT_S", 60)
    state = {"last_change": time.time(), "last_step": None, "last_report": 0.0, "reports": 0,
             "mem": [], "cpu": []}

    def progress() -> None:
        state["last_change"] = time.time()

    def _step() -> str:
        try:
            return str(step_getter()) if step_getter else ""
        except Exception:                      # noqa: BLE001 - 诊断不许因脚本内部状态失败
            return ""

    def _dump(reason: str) -> None:
        try:
            items = list(errors)[:10]
        except Exception:                      # noqa: BLE001
            items = ["<errors 读不出来>"]
        state["mem"].append(_renderer_mem_mb())
        state["cpu"].append(_renderer_cpu_s())
        print(f"\n⚠ [watchdog] {reason}\n"
              f"  · 最后完成的步骤：{state['last_step']!r}\n"
              f"  · 已收集的错误 {len(items)} 条（最多显示 10 条）："
              f"{items if items else '（空 —— 没有 console/pageerror/HTTP 错误）'}\n"
              f"  · chromium 内存采样（最近 6 次）：{state['mem'][-6:]}\n"
              f"  · chromium 累计 CPU 秒（最近 6 次）：{state['cpu'][-6:]}\n"
              f"  · 提示：错误为空 ⇒ 页面**冻住**而不是抛了 JS 异常；内存持续爬升 ⇒ 页面里有"
              f"「边循环边分配」的东西（渲染进程多半被 OOM 杀掉，即 `Page crashed`）。", flush=True)

    def _loop() -> None:
        while True:
            time.sleep(5)
            cur = _step()
            if cur != state["last_step"]:
                state["last_step"], state["last_change"] = cur, time.time()
                continue
            idle = time.time() - state["last_change"]
            if idle >= stall_s and (time.time() - state["last_report"]) >= repeat_s:
                state["last_report"] = time.time()
                state["reports"] += 1
                first = state["reports"] == 1
                _dump(f"已 {idle:.0f}s 没有进展（第 {state['reports']} 次报告）"
                      if not first else
                      f"疑似卡住：已 {idle:.0f}s 没有进展（脚本可能正卡在这一步里）")

    t = threading.Thread(target=_loop, name="view-watchdog", daemon=True)
    t.start()
    return SimpleNamespace(progress=progress, thread=t)
