"""测试数据库隔离守卫（verify_*.py 共用）。

背景：verify 脚本为保证**可重复**，必须从空库起步，故各自带 clean() 删除 .db。
但库里同时存着用户平时在平台上积累的 demo 数据——直接删等于**跑一次测试就洗一次数据**。

本模块提供 `isolate_dbs()` 上下文：进入时把现存数据库文件（app/**/*.db* 与
config/ 下 auth/chat_history/scheduler 库）**移动**到 fde_platform/.db_backup 暂存，
测试照常在空库上运行；进程退出前（含断言失败，经 atexit）**删除测试残料、原样还回原文件**。
测试的可重复性不变，用户数据分毫不丢。

用法（每个 verify 脚本在 sys.path 设置后、任何 clean()/import web 之前）：

    from fde_platform.dbguard import isolate_dbs
    _iso = isolate_dbs(); _iso.__enter__()
    import atexit; atexit.register(_iso.__exit__, None, None, None)

Windows 上 SQLite 文件偶有短暂锁（WAL 收尾/GC 时机），故删除与移动均带重试；
若仍有文件没还回，**保留** .db_backup 不删——下一次运行会优先重试恢复
（用户原数据永远优先于测试残料）。注意：运行测试期间请别同时开着平台服务器
（持续打开的库文件无法移动）——这与从前直接删库的限制一致。

同样不要**并行**跑多个 verify 脚本：隔离基于共享暂存目录 .db_backup，并行时
测试 B 会把测试 A 正在使用的暂存当成"崩溃残留"先行恢复，A 收尾时又把已恢复的
文件当残料删掉——2026-07-30 曾因此洗掉用户 demo 库。isolate_dbs 现持有独占锁
fde_platform/.dbguard.lock，第二个并发进程干净拒绝（持锁进程已死的陈腐锁自动接管）。
"""
import atexit  # noqa: F401（供调用方按用法引用）
import os
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_HERE = Path(__file__).resolve().parent
BACKUP_DIR = _HERE / ".db_backup"          # 暂存与锁随模块落 fde_platform/（不再依赖 tests/）
LOCK_FILE = _HERE / ".dbguard.lock"

# config/ 下由平台（而非应用）管理的库
# （llm.db 亦在内：否则用户在 /llm 配的模型会泄漏进测试，使"未配置降级"类断言不确定；
#   隔离后测试一律从空 llm.db 起步，原配置退出时原样还回。）
_CONFIG_DBS = ("auth.db*", "chat_history.db*", "scheduler.db*", "llm.db*")

_TRIES = 30          # 文件操作重试次数
_RETRY_WAIT = 0.05   # 每次重试间隔（秒）——等 Windows 释放文件锁


def _db_files() -> list[Path]:
    """当前所有数据库文件（应用库 + 平台库）。"""
    files = list((ROOT / "app").glob("**/*.db*"))
    for pat in _CONFIG_DBS:
        files += list((ROOT / "config").glob(pat))
    return files


def force_remove(path: Path) -> bool:
    """删除文件（带重试，容忍 Windows 短暂文件锁）。已不存在视为成功。"""
    for _ in range(_TRIES):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            time.sleep(_RETRY_WAIT)
    return False


def _force_move(src: Path, dst: Path) -> bool:
    """移动文件到 dst（先清掉 dst 占位；带重试）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not force_remove(dst):
        return False
    for _ in range(_TRIES):
        try:
            src.rename(dst)
            return True
        except OSError:
            time.sleep(_RETRY_WAIT)
    return False


def _pid_alive(pid: int) -> bool:
    """进程存活探测（跨平台）。

    Windows 上绝不能用 os.kill(pid, 0)——CPython 的 Windows 实现对非常规信号
    直接调 TerminateProcess，会把持锁进程杀掉。改用 OpenProcess 查询句柄。
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 存在但属其他用户


def _acquire_lock() -> None:
    """跨进程独占：同一时刻只允许一个测试进程进入隔离。

    2026-07-30 并行回归（多个 verify 脚本同跑）踩踏共享暂存 .db_backup，互相
    把对方的文件搬进搬出，最终洗掉用户 demo 库。此后第二个并发 isolate 被拒绝；
    持锁进程已退出（崩溃/被杀）的陈腐锁自动接管，不会永久卡死。
    """
    while True:
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                holder = int(LOCK_FILE.read_text(encoding="utf-8").strip() or "0")
            except (ValueError, OSError):
                holder = 0
            if holder and _pid_alive(holder):
                raise RuntimeError(
                    f"[dbguard] 另一个测试正在运行（pid {holder} 持有 {LOCK_FILE.name}）。"
                    f"请勿并行运行 verify 脚本——并行踩踏是 2026-07-30 洗掉用户 demo 库的根因；"
                    f"若确认无其他测试在跑，可删除 {LOCK_FILE} 后重试。")
            force_remove(LOCK_FILE)  # 陈腐锁（持锁进程已死）→ 摘除重试
            continue
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return


def _restore_backup() -> None:
    """把 .db_backup 里的文件还回原位（覆盖当前残料）；全部成功才删备份目录。"""
    all_ok = True
    for src in sorted(BACKUP_DIR.rglob("*")):
        if not src.is_file():
            continue
        if not _force_move(src, ROOT / src.relative_to(BACKUP_DIR)):
            all_ok = False
            print(f"[dbguard] 恢复 {src.name} 失败（文件被占用），保留在 {src}",
                  file=sys.stderr)
    if all_ok:
        shutil.rmtree(BACKUP_DIR, ignore_errors=True)


@contextmanager
def isolate_dbs():
    """测试前移走现存库；退出时清掉测试残料并把原库还回。

    全程持有 fde_platform/.dbguard.lock 独占锁——第二个并发的 isolate 会在触碰任何
    数据库文件之前被干净拒绝（见 _acquire_lock）。
    """
    _acquire_lock()
    try:
        if BACKUP_DIR.exists():  # 上次崩溃/锁残留 → 先救回用户数据
            _restore_backup()
        if BACKUP_DIR.exists():  # 仍有文件被占用没能还回 → 终止隔离，绝不覆盖备份
            raise RuntimeError(
                f"[dbguard] {BACKUP_DIR} 内仍有未能还回的数据库文件"
                f"（通常因平台服务器正打开它们）。请关闭平台后重跑测试；\n"
                f"切勿删除该目录——里面是你的原始数据。"
            )

        moved: list[tuple[Path, Path]] = []
        try:
            for f in _db_files():
                dst = BACKUP_DIR / f.relative_to(ROOT)
                if not _force_move(f, dst):
                    raise OSError(f"无法移走 {f}（可能被平台服务器打开）")
                moved.append((f, dst))
        except OSError:
            # 移动半途失败（如库被占用）：把已移走的还回，放弃本次隔离
            for f, dst in moved:
                _force_move(dst, f)
            shutil.rmtree(BACKUP_DIR, ignore_errors=True)
            raise
        try:
            yield
        finally:
            ok = True
            for f in _db_files():  # 删除测试产生的全部残料
                if not force_remove(f):
                    ok = False
            for f, dst in moved:  # 原样还回用户数据
                if not _force_move(dst, f):
                    ok = False
                    print(f"[dbguard] 恢复 {f} 失败（文件被占用），保留在 {dst}",
                          file=sys.stderr)
            if ok:
                shutil.rmtree(BACKUP_DIR, ignore_errors=True)
            else:
                print(f"[dbguard] 有文件未能还回，备份保留在 {BACKUP_DIR}，"
                      f"下次运行测试时自动重试恢复", file=sys.stderr)
    finally:
        force_remove(LOCK_FILE)
