from api.app.infrastructure.tools.base import BaseTool
from api.app.infrastructure.tools.builtins.system_time import SystemTimeTool
from api.app.infrastructure.tools.builtins.terminal_executor import TerminalExecutorTool

_BUILTIN_TOOLS: list[BaseTool] = [
    SystemTimeTool(),
    TerminalExecutorTool(),
]

_registry: dict[str, BaseTool] = {t.name: t for t in _BUILTIN_TOOLS}


def get_tool(name: str) -> BaseTool | None:
    return _registry.get(name)


def list_tools() -> list[BaseTool]:
    return list(_registry.values())


def register_tool(tool: BaseTool) -> None:
    _registry[tool.name] = tool
