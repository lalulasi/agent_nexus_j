import sys
from pathlib import Path

from loguru import logger


def setup_logger(debug: bool = False) -> None:
    logger.remove()
    Path("logs").mkdir(exist_ok=True)

    level = "DEBUG" if debug else "INFO"
    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(sys.stdout, level=level, format=fmt, colorize=True)
    logger.add(
        "logs/agent_nexus_{time:YYYY-MM-DD}.log",
        level="INFO",
        format=fmt,
        rotation="00:00",
        retention="30 days",
        compression="gz",
        encoding="utf-8",
    )


__all__ = ["logger", "setup_logger"]
