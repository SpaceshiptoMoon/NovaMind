"""本地工作区端口装配：按会话的工作区绑定构造 LocalWorkspacePort。

P0 本地形态：无 RunnerDevice 绑定时直接经会话 extra_config.workspace_root
构造进程内执行器（后端与文件同机）。云端 runner 形态随 P1 WorkspaceBinding
落地后切换（RunnerExecutor + 设备在线校验）。
"""
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def build_local_workspace_port(
    db: AsyncSession, user_id: int, conv: Any
) -> Any | None:
    """按会话构造工作区端口；未配置返回 None（工具执行时给引导文案）。

    P0 约定：本地形态在会话 extra_config.workspace 写
    ``{"mode": "local", "root": "<绝对路径>"}``（前端工作区绑定弹窗落库）。
    """
    from novamind.features.agent.services.local_workspace.port import InProcessExecutor

    ws_cfg = (conv.extra_config or {}).get("workspace") or {}
    if ws_cfg.get("mode") != "local" or not ws_cfg.get("root"):
        return None
    root = str(ws_cfg["root"])
    if not ws_cfg.get("root_checked"):
        from pathlib import Path

        if not Path(root).is_dir():
            logger.warning("工作区根目录不存在", root=root)
            return None
    return InProcessExecutor(root=root)
