from typing import Dict, List, Any
from app.core.logger import logger
from .base import BaseTool
from .builtins.system_time import GetSystemTimeTool
from .builtins.terminal_executor import TerminalExecutorTool


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        # 初始化时自动注册所有内置工具
        self._register_builtins()

    def _register_builtins(self):
        """
        在这里注册系统自带的底层核心工具
        """
        # 1. 注册时间感知工具
        time_tool = GetSystemTimeTool()
        self.register(time_tool)

        # 2. 🌟 注册跨平台本地终端执行工具 (高危)
        terminal_tool = TerminalExecutorTool()
        self.register(terminal_tool)

    def register(self, tool: BaseTool):
        """将工具注册到系统中"""
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' is already registered. Overwriting.")
        self._tools[tool.name] = tool
        logger.info(f"Successfully registered tool: {tool.name}")

    def get_tool(self, name: str) -> BaseTool:
        """根据名称获取工具实例"""
        return self._tools.get(name)

    def get_all_openai_schemas(self) -> List[Dict[str, Any]]:
        """提取所有已注册工具的说明书，发送给大模型"""
        return [tool.to_openai_schema() for tool in self._tools.values()]


# 全局单例注册表
tool_registry = ToolRegistry()