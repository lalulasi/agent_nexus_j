import platform
import asyncio
import os
from app.core.logger import logger
from app.infrastructure.tools.base import BaseTool

MAX_OUTPUT_LENGTH = 3000

class TerminalExecutorTool(BaseTool):
    """
    跨平台本地终端执行工具。
    让大模型拥有控制宿主机的能力（支持 Windows/macOS/Linux）。
    """

    @property
    def name(self) -> str:
        return "execute_local_terminal_command"

    @property
    def description(self) -> str:
        return """Execute shell/terminal commands on the local machine. 
                CRITICAL RULES:
                1. STATELESS: Each execution is a fresh session. To run in a specific folder, use chaining: `cd /path && your_command`.
                2. NON-INTERACTIVE: You MUST use flags to avoid user prompts (e.g., `-y`, `--quiet`, `-f`).
                3. PERMISSION: If a command requires sudo/admin, try it without first. If it fails, STOP and ask the human to run it manually.
                4. LARGE FILES: Use `head`, `tail`, or `grep` to read files. DO NOT use `cat` on large files.
                """

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The exact terminal command to execute."
                }
            },
            "required": ["command"]
        }

    async def execute(self, command: str, **kwargs) -> str:
        system_os = platform.system()
        logger.warning(f"⚠️ 正在 {system_os} 系统上执行高危命令: {command}")

        try:
            # 创建异步子进程来执行命令
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.getcwd()  # 在当前项目目录下执行
            )

            # 增加 15 秒超时机制，防止大模型执行如 ping -t 这种死循环命令拖垮服务器
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15.0)
            except asyncio.TimeoutError:
                process.kill()
                logger.error(f"命令执行超时 (15s): {command}")
                return "Error: Command execution timed out after 15 seconds. Process killed."

            # 解码输出 (Windows 通常是 gbk，但现代系统 utf-8 兼容性更好，这里用 errors='replace' 防止崩溃)
            out_str = stdout.decode('utf-8', errors='replace').strip()
            if len(out_str) > MAX_OUTPUT_LENGTH:
                out_str = out_str[
                              :MAX_OUTPUT_LENGTH] + f"\n\n...[OUTPUT TRUNCATED] The output exceeded {MAX_OUTPUT_LENGTH} chars. Please refine your command using `grep`, `head`, or `tail`."
            if process.returncode == 0:
                logger.success("命令执行成功")
                return f"Execution Successful.\nOutput:\n{out_str}"
            else:
                logger.error(f"命令执行失败，状态码 {process.returncode}")
                # 即使失败了，也要把错误信息返回给大模型，大模型会根据错误信息自动修 Bug 并重试！
                return f"Execution Failed (Exit code {process.returncode}).\nError:\n{err_str}\nOutput:\n{out_str}"

        except Exception as e:
            logger.error(f"执行终端工具时发生系统错误: {str(e)}")
            return f"System Error executing command: {str(e)}"