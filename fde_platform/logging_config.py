"""FDE 平台日志配置。

统一入口：控制台输出 + 文件按天轮转（保留 30 天）。
其他模块通过 ``logging.getLogger(__name__)`` 获取 logger。
"""
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import sys

# 路径**调用时解析**（认 `FDE_CONFIG_ROOT`，见 `config_paths.py`）：日志目录也要被隔离，
# 否则测试起的平台会往真 config/logs/ 写日志。
from fde_platform.config_paths import config_path  # noqa: E402


def init_logging() -> logging.Logger:
    """配置 root logger：控制台 INFO + 文件 DEBUG（轮转保留 30 天）。"""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 控制台：INFO 及以上（简洁）
    if not root.handlers:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter(
            "[%(levelname)s] %(name)s %(message)s"
        ))
        root.addHandler(console)

        # 文件：DEBUG 及以上（详细，按天轮转，保留 30 天）
        try:
            log_dir = config_path("logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = TimedRotatingFileHandler(
                str(log_dir / "fde.log"),
                when="midnight",
                interval=1,
                backupCount=30,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s %(message)s"
            ))
            root.addHandler(file_handler)
        except Exception:
            pass  # 文件日志不是关键路径，失败不影响运行

    return logging.getLogger("fde")
