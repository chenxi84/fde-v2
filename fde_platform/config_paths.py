"""`config/` 下平台文件的**唯一解析入口** —— 让测试隔离变量覆盖全部平台模块。

## 为什么要有这个模块

`FDE_CONFIG_ROOT` 是测试隔离用的环境变量（见 `shadowdb.py`：把 `config/` 指到副本，
测试起的平台就写在副本上、真配置零接触）。但它原先**只有 `users.py` 认**，
其余模块一律硬编码 `Path(__file__).parents[1] / "config" / …` ⇒ 后果实测（2026-09-18）：

- 测试脚本起的平台子进程会 `scheduler.start_engine()` → **读真 jobs、按真 cron 触发**，
  run 记录落进**真** `config/scheduler.db`（当时并没有 dev server 在跑）；
- `config/logs/`、`flow_runs.db`、`agent_alerts.db` 同样被测试进程写；
- 更麻烦的是 **eval**（按设计用真库 + 数据指纹、不设隔离变量）：它跑的时候若恰逢 cron，
  定时任务的**真实写入**会改真库、**打破指纹**，表现为"eval 莫名其妙失败"。

⇒ 把解析收成 `config_path()` 一处，各模块都来调它。**未设 `FDE_CONFIG_ROOT` 时行为与过去逐字一致**
（`PROJECT_ROOT/config/<名字>`），所以生产/开发路径零变化。

## 用法

    from fde_platform.config_paths import config_path

    conn = sqlite3.connect(str(config_path("scheduler.db")))     # ✅ 调用时解析
    LOG_DIR = config_path("logs")                                # ✅ 目录同理

⚠ **不要写成模块级常量再复用它**（`DB_PATH = config_path("x.db")` 在 import 期求值）：
环境变量若在该模块 import **之后**才设（进程内测试的常见顺序），常量就被冻在真路径上了 ——
这正是这个模块要根治的那类问题。要么每次调用 `config_path(...)`，要么在使用点现算。
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def config_dir() -> Path:
    """`config/` 的**实际**目录：受 `FDE_CONFIG_ROOT` 影响（未设=真 `config/`）。"""
    root = os.environ.get("FDE_CONFIG_ROOT", "").strip()
    return Path(root) if root else (PROJECT_ROOT / "config")


def config_path(name: str) -> Path:
    """`config/<name>` 的实际路径（`name` 可以是文件名或子目录名）。"""
    return config_dir() / name
