import datetime
from app.core.logger import logger
from app.infrastructure.tools.base import BaseTool


class GetSystemTimeTool(BaseTool):
    """获取系统当前时间的工具"""

    @property
    def name(self) -> str:
        return "get_current_system_time"

    @property
    def description(self) -> str:
        return "Get the current local system time. Use this when you need to know the current date or time."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {}
        }

    async def execute(self, **kwargs) -> str:
        logger.info("Executing GetSystemTimeTool to fetch local time.")
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"Fetched time: {current_time}")
        return f"The current system time is: {current_time}"