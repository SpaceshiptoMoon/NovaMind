"""宿主 Feature 间公共端口：NotificationPort。

供 skill / knowledge_space / deep_research / app / user 等 feature 发送站内+邮件
通知（替代直接 import NotificationService）。实现侧（notification feature 的
adapter）负责偏好过滤、DB 写入、WS 推送与邮件；发送失败由实现内部吞掉（记
日志），**通知绝不打断调用方的主业务流程**。
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class NotificationPort(Protocol):
    """通知发送端口。"""

    async def send(
        self,
        user_id: int,
        type: str,
        title: str,
        content: str,
        link: Optional[str] = None,
        extra_data: Optional[dict] = None,
    ) -> None:
        """发送单条通知给指定用户。

        Args:
            user_id: 接收用户 ID
            type: 通知类型（NotificationType 枚举字符串值，如 "skill_review"）
            title: 标题
            content: 正文
            link: 前端跳转路径（如 "/home/workspace/skills/1"），无则 None
            extra_data: 扩展数据（随通知持久化并经 WS 推送）
        """
        ...


__all__ = ["NotificationPort"]
