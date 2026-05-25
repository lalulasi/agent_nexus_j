import asyncio
import shlex
from typing import Any

from api.app.infrastructure.tools.base import BaseTool

# Commands that are never allowed regardless of context
_BLOCKLIST = frozenset(
    ["rm", "rmdir", "dd", "mkfs", "fdisk", "shutdown", "reboot", "halt", "poweroff", "kill"]
)

_TIMEOUT_SECONDS = 30


class TerminalExecutorTool(BaseTool):
    name = "execute_terminal"
    description = (
        "Execute a safe, read-only shell command. "
        "Destructive commands (rm, dd, shutdown, etc.) are blocked."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to execute."}
        },
        "required": ["command"],
    }

    async def run(self, command: str, **kwargs: Any) -> str:
        try:
            tokens = shlex.split(command)
        except ValueError as e:
            return f"Error parsing command: {e}"

        if not tokens:
            return "Empty command."

        if tokens[0] in _BLOCKLIST:
            return f"Command '{tokens[0]}' is blocked for safety reasons."

        try:
            proc = await asyncio.create_subprocess_exec(
                *tokens,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return f"Command timed out after {_TIMEOUT_SECONDS}s."
        except Exception as e:
            return f"Execution error: {e}"

        output = stdout.decode().strip() or stderr.decode().strip()
        return output[:4000] if output else "(no output)"
