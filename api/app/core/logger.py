import sys
import os
from loguru import logger
from app.core.config import settings

def setup_logging():
    """
    初始化全局日志配置
    """
    # 确保日志文件夹存在
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
    os.makedirs(log_dir, exist_ok=True)

    # 移除 Loguru 默认的终端输出拦截，防止重复打印
    logger.remove()

    # 1. 终端输出：带颜色的高颜值格式
    logger.add(
        sys.stdout,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG" # 开发环境下，打印所有细节
    )

    # 2. 写入文件：常规运行日志 (每天按时轮转/拆分文件，保留 30 天)
    logger.add(
        os.path.join(log_dir, "agent_nexus_{time:YYYY-MM-DD}.log"),
        rotation="00:00",      # 每天午夜 0点 创建新文件
        retention="30 days",   # 最多保留 30 天
        level="INFO",          # 文件里只记录 INFO 及以上级别，避免文件过大
        encoding="utf-8"
    )

    # 3. 写入文件：专门的错误日志 (便于快速排查宕机原因)
    logger.add(
        os.path.join(log_dir, "error.log"),
        rotation="10 MB",      # 只要达到 10MB 就拆分
        retention="30 days",
        level="ERROR",         # 只记录 ERROR 级别
        encoding="utf-8"
    )

    logger.info("🚀 AgentNexus-J 系统日志初始化成功！")