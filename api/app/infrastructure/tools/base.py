from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseTool(ABC):
    """
    所有 Agent 工具的抽象基类。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称 (必须是唯一的，且只能包含 a-z, 0-9, 下划线)"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具的详细描述，大模型就是靠这段话来判断什么时候该用这个工具"""
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """兼容 OpenAI 规范的 JSON Schema，定义该工具需要接收什么参数"""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """FastAPI 后端真实执行的 Python 业务逻辑"""
        pass

    def to_openai_schema(self) -> Dict[str, Any]:
        """将 Python 类转换为大模型能看懂的 JSON Schema 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }