from typing import Dict, List, Any
from app.core.logger import logger
from .base import BaseTool

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' is already registered. Overwriting.")
        self._tools[tool.name] = tool
        logger.info(f"Successfully registered tool: {tool.name}")

    def get_tool(self, name: str) -> BaseTool:
        return self._tools.get(name)

    def get_all_openai_schemas(self) -> List[Dict[str, Any]]:
        """提取所有已注册工具的说明书，发给大模型"""
        return [tool.to_openai_schema() for tool in self._tools.values()]

# 全局单例注册表
tool_registry = ToolRegistry()