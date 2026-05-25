from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolInput(BaseModel):
    pass


class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict

    @abstractmethod
    async def run(self, **kwargs: Any) -> str:
        ...

    def to_anthropic_tool(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
