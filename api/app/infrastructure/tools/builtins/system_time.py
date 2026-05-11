from datetime import datetime
from typing import Dict, Any
from app.core.logger import logger
from ..base import BaseTool
from ..registry import tool_registry

class GetSystemTimeTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_current_system_time"

    @property
    def description(self) -> str:
        return "Use this tool to get the current date, time, and timezone of the server. Call this whenever the user asks about the current time or date."

    @property
    def parameters(self) -> Dict[str, Any]:
        # 这个工具不需要大模型传任何参数给我们
        return {
            "type": "object",
            "properties": {},
            "required": []
        }

    async def execute(self, **kwargs) -> str:
        logger.info("Executing GetSystemTimeTool to fetch local time.")
        now = datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"Fetched time: {current_time_str}")
        # 返回给大模型的字符串
        return f"The current system time is {current_time_str}"

# 当这个模块被引入时，自动将自己注册到注册表中
tool_registry.register(GetSystemTimeTool())