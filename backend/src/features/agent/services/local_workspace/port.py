"""本地工作区执行端口：工具层统一入口，屏蔽进程内/runner 两种形态差异。

工具 execute_tool 只认 LocalWorkspacePort；RunnerExecutor 形态下设备离线
等错误以 ``{"error": ..., "error_code": ...}`` dict 返回（能力缺失优于悬死）。
"""
from abc import ABC, abstractmethod
from typing import Any


class LocalWorkspacePort(ABC):
    """工作区工具执行端口（read/glob/grep 及后续 write/edit/bash 共用）。"""

    @abstractmethod
    async def execute(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """执行一次工作区工具调用，返回结果 dict（ok/result 或 ok=False/error）。"""

    @abstractmethod
    async def aclose(self) -> None:
        """释放底层资源（runner 形态无持有资源则空实现）。"""


class InProcessExecutor(LocalWorkspacePort):
    """进程内执行器（本地部署形态）：直接执行，与 runner 共享安全校验。"""

    def __init__(self, root: str, os_type: str = "windows"):
        self.root = root
        self.os_type = os_type

    async def execute(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        from novamind.features.agent.services.local_workspace.ops import execute_local

        return await execute_local(self.root, self.os_type, tool, args)

    async def aclose(self) -> None:
        return None


class RunnerExecutor(LocalWorkspacePort):
    """runner 转发执行器（云端部署形态）：经 RunnerRegistry 派活等回包。"""

    def __init__(self, registry, user_id: int, device_id: int, timeout: float = 60.0):
        self.registry = registry
        self.user_id = user_id
        self.device_id = device_id
        self.timeout = timeout

    async def execute(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        # 云端不下发 root/os_type：路径校验在 runner 侧以其授权根为准执行
        return await self.registry.call(self.user_id, self.device_id, tool, args, self.timeout)

    async def aclose(self) -> None:
        return None
