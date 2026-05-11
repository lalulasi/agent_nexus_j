import sys
from pathlib import Path
from loguru import logger

# 自动推导日志存放目录 (项目根目录下的 logs 文件夹)
LOG_DIR = Path(__file__).resolve().parent.parent.parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logger():
    """初始化全局日志配置"""
    # 1. 移除 loguru 默认的配置，防止重复打印
    logger.remove()

    # 2. 配置终端输出 (带颜色，适合开发时看)
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG",
        enqueue=True  # 保证异步安全
    )

    # 3. 配置物理文件持久化 (按天切割，保留30天，适合排查线上问题)
    logger.add(
        LOG_DIR / "agent_{time:YYYY-MM-DD}.log",
        rotation="00:00",  # 每天午夜新建一个文件
        retention="30 days",  # 最多保留 30 天
        level="INFO",  # 文件里只存 INFO 及以上级别的日志，防止文件太大
        encoding="utf-8",
        enqueue=True
    )

    logger.info("🚀 Loguru 探针已启动，全局日志系统初始化完成！")


# 只要有文件引入这个模块，就会自动执行初始化
setup_logger()