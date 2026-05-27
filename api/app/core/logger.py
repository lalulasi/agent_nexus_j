import sys
from pathlib import Path

from loguru import logger


# 对外请求专用 logger：绑定 channel="outbound" 路由到独立文件
outbound_logger = logger.bind(channel="outbound")


def setup_logger(debug: bool = False) -> None:
    logger.remove()
    Path("logs").mkdir(exist_ok=True)

    level = "DEBUG" if debug else "INFO"

    # 主日志格式
    _main_fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    # 对外请求日志格式：去掉代码位置，突出时间和内容
    _outbound_fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<magenta>OUTBOUND</magenta> | "
        "{message}"
    )

    # ── 控制台：主日志（过滤掉 outbound，避免重复）────────────────────────────
    logger.add(
        sys.stdout,
        level=level,
        format=_main_fmt,
        colorize=True,
        filter=lambda r: r["extra"].get("channel") != "outbound",
    )

    # ── 文件：主日志（同样过滤 outbound）────────────────────────────────────────
    logger.add(
        "logs/agent_nexus_{time:YYYY-MM-DD}.log",
        level="INFO",
        format=_main_fmt,
        rotation="00:00",
        retention="30 days",
        compression="gz",
        encoding="utf-8",
        filter=lambda r: r["extra"].get("channel") != "outbound",
    )

    # ── 文件：对外请求专用日志 ────────────────────────────────────────────────
    logger.add(
        "logs/outbound_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        format=_outbound_fmt,
        rotation="00:00",
        retention="30 days",
        compression="gz",
        encoding="utf-8",
        filter=lambda r: r["extra"].get("channel") == "outbound",
    )


__all__ = ["logger", "outbound_logger", "setup_logger"]
