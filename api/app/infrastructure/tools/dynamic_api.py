import httpx
from typing import Dict, Any
from app.core.logger import logger
from .base import BaseTool


class DynamicAPITool(BaseTool):
    """
    万能 API 适配器。
    它能将用户的任意 HTTP 接口，包装成大模型可以理解并执行的本地工具。
    """
    def __init__(self, name: str, description: str, parameters: dict, target_url: str):
        self._name = name
        self._description = description
        self._parameters = parameters
        self._target_url = target_url

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs) -> str:
        logger.info(f"Executing DynamicAPITool '{self.name}' -> POST {self._target_url}")
        logger.debug(f"Payload to user API: {kwargs}")

        try:
            # 使用异步客户端发起 POST 请求
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._target_url,
                    json=kwargs,
                    timeout=15.0  # 设置 15 秒超时，防止用户的接口卡死我们的系统
                )

                # 如果用户接口报错（如 404, 500），抛出异常
                response.raise_for_status()

                # 尝试解析 JSON，如果不是 JSON 就返回纯文本
                try:
                    result_data = response.json()
                    logger.success(f"DynamicAPITool '{self.name}' returned JSON response successfully.")
                    return str(result_data)
                except ValueError:
                    logger.success(f"DynamicAPITool '{self.name}' returned text response successfully.")
                    return response.text

        except httpx.TimeoutException:
            logger.error(f"DynamicAPITool '{self.name}' timed out after 15 seconds.")
            return f"Error: The API endpoint '{self._target_url}' timed out."
        except Exception as e:
            logger.error(f"DynamicAPITool '{self.name}' failed: {str(e)}")
            return f"Error calling API: {str(e)}"