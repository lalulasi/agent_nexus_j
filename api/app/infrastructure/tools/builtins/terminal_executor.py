import asyncio
import platform
import sys
from pathlib import Path
from typing import Any

from api.app.core.logger import logger
from api.app.infrastructure.tools.base import BaseTool

_OS = platform.system()  # "Darwin" | "Linux" | "Windows"

# 超时：下载/安装可能较慢
_TIMEOUT = 120

# 系统级危险操作，无论如何都拒绝
_BLOCKED_PATTERNS = [
    # Unix
    "mkfs", "fdisk", ":(){ :|:& };:",
    # Windows
    "format c:", "format d:", "diskpart",
    # 通用
    "shutdown", "reboot", "halt", "poweroff",
]

# rm -rf 保护的系统目录
_PROTECTED_UNIX_PATHS = [
    " /", "~/", " /etc", " /usr", " /bin", " /sbin",
    " /sys", " /proc", " /dev", " /boot",
]


def _os_hint() -> str:
    hints = {
        "Darwin":  "macOS — 使用 bash 语法；下载用 curl；安装包用 brew 或 pip；路径分隔符为 /",
        "Linux":   "Linux — 使用 bash 语法；下载用 curl 或 wget；安装包用 apt/yum/pip；路径分隔符为 /",
        "Windows": "Windows — 使用 PowerShell 语法；下载用 Invoke-WebRequest 或 curl；安装包用 winget/choco/pip；路径分隔符为 \\",
    }
    return hints.get(_OS, _OS)


class TerminalExecutorTool(BaseTool):
    name = "execute_terminal"
    description = (
        f"在用户的 {_OS} 系统上执行 shell 命令，完成系统操作任务。\n"
        f"当前系统：{_os_hint()}\n"
        "支持的操作类型：\n"
        "- 文件操作：创建、读取、写入、移动、复制文件和目录\n"
        "- 下载文件：通过 URL 下载资源到指定目录\n"
        "- 安装软件：通过包管理器安装应用或依赖\n"
        "- 目录管理：创建目录、列出内容、查看路径\n"
        "- 系统信息：查询磁盘空间、进程、网络等\n"
        "- 运行脚本：执行 Python、Shell 脚本等\n"
        "触发时机：用户明确要求执行系统操作，或任务明确需要操作文件/安装软件时自动调用。\n"
        "安全限制：磁盘格式化、系统关机/重启、删除系统根目录等操作被禁止。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    f"适用于 {_OS} 的 shell 命令。"
                    "macOS/Linux 使用 bash 语法，Windows 使用 PowerShell 语法。"
                    "写文件示例(mac): echo '内容' > /path/to/file.txt"
                    "写文件示例(win): Set-Content -Path 'C:\\path\\file.txt' -Value '内容'"
                ),
            },
            "working_dir": {
                "type": "string",
                "description": "命令的工作目录（可选）。不存在时自动创建。默认为用户主目录。",
            },
        },
        "required": ["command"],
    }

    async def run(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        # 安全检查
        block_reason = self._check_blocked(command)
        if block_reason:
            logger.warning(f"命令被拒绝: {command!r} 原因: {block_reason}")
            return f"❌ 命令被拒绝（安全限制）：该操作涉及 {block_reason}，不允许执行。"

        # 工作目录处理
        cwd: str | None = None
        if working_dir:
            cwd_path = Path(working_dir).expanduser().resolve()
            if not cwd_path.exists():
                try:
                    cwd_path.mkdir(parents=True, exist_ok=True)
                    logger.info(f"自动创建目录: {cwd_path}")
                except Exception as e:
                    return f"❌ 无法创建工作目录 '{working_dir}': {e}"
            cwd = str(cwd_path)

        logger.info(f"执行命令 [{_OS}]: {command}" + (f"  cwd={cwd}" if cwd else ""))

        try:
            if _OS == "Windows":
                stdout, stderr, returncode = await self._run_windows(command, cwd)
            else:
                stdout, stderr, returncode = await self._run_unix(command, cwd)
        except asyncio.TimeoutError:
            return f"⏱ 命令超时（{_TIMEOUT}s），可能仍在后台运行。"
        except Exception as e:
            logger.exception("命令执行异常")
            return f"❌ 执行错误：{e}"

        return self._format_output(stdout, stderr, returncode)

    # ── 平台执行 ──────────────────────────────────────────────────────────────

    async def _run_unix(self, command: str, cwd: str | None) -> tuple[str, str, int]:
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        return (
            stdout_b.decode("utf-8", errors="replace").strip(),
            stderr_b.decode("utf-8", errors="replace").strip(),
            proc.returncode or 0,
        )

    async def _run_windows(self, command: str, cwd: str | None) -> tuple[str, str, int]:
        # 强制 PowerShell 使用 UTF-8 输出
        wrapped = f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {command}"
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-NoProfile", "-NonInteractive", "-Command", wrapped,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        enc = "utf-8"
        return (
            stdout_b.decode(enc, errors="replace").strip(),
            stderr_b.decode(enc, errors="replace").strip(),
            proc.returncode or 0,
        )

    # ── 输出格式化 ────────────────────────────────────────────────────────────

    def _format_output(self, stdout: str, stderr: str, returncode: int) -> str:
        parts: list[str] = []
        if stdout:
            parts.append(stdout)
        if stderr:
            # 很多程序把正常信息写入 stderr（如 pip install 进度）
            parts.append(f"[stderr]\n{stderr}")
        if not parts:
            status = "✅ 命令执行成功（无输出）" if returncode == 0 else f"⚠️ 命令退出码: {returncode}"
            return status
        result = "\n".join(parts)
        if returncode != 0 and not stdout:
            result = f"⚠️ 退出码 {returncode}\n{result}"
        return result[:5000]

    # ── 安全检查 ──────────────────────────────────────────────────────────────

    def _check_blocked(self, command: str) -> str | None:
        low = command.lower()

        for pattern in _BLOCKED_PATTERNS:
            if pattern in low:
                return pattern

        # Unix: 阻止 rm -rf 指向系统路径
        if _OS != "Windows":
            if "rm" in low and ("-rf" in low or "-fr" in low or "-r" in low):
                for sys_path in _PROTECTED_UNIX_PATHS:
                    if sys_path.rstrip() in command:
                        return f"rm 删除系统路径 ({sys_path.strip()})"

        # Windows: 阻止删除系统盘根目录
        if _OS == "Windows":
            import re
            if re.search(r"remove-item\s+[cC]:\\?\s", command):
                return "删除 Windows 系统盘根目录"

        return None
