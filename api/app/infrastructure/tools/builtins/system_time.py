from datetime import datetime, timezone
from typing import Any

from api.app.infrastructure.tools.base import BaseTool


class SystemTimeTool(BaseTool):
    name = "get_system_time"
    description = "Returns the current UTC time and the local timezone offset."
    input_schema = {"type": "object", "properties": {}, "required": []}

    async def run(self, **kwargs: Any) -> str:
        now = datetime.now(timezone.utc)
        return f"Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}"
