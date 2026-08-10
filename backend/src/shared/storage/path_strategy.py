"""
MinIO 对象路径策略端口，定义 PathStrategy 协议及 DefaultPathStrategy 默认实现。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PathStrategy(Protocol):
    """对象路径策略端口：引擎经此获取对象名与列表前缀，不硬编码宿主路径方案。"""

    def document_object_name(
        self, space_id: int, kb_id: int, document_id: int, storage_name: str
    ) -> str:
        """单文档对象名（含存储文件名）。"""
        ...

    def document_prefix_for_kb(self, space_id: int, kb_id: int) -> str:
        """知识库下所有对象的列表前缀（用于按 KB 批量删除/列举）。"""
        ...

    def document_prefix_for_space(self, space_id: int) -> str:
        """空间下所有对象的列表前缀（用于按空间批量删除/列举）。"""
        ...

    def avatar_object_name(self, user_id: int, extension: str) -> str:
        """用户头像对象名。"""
        ...

    def avatar_prefix_for_user(self, user_id: int) -> str:
        """用户头像列表前缀（用于删除旧头像）。"""
        ...

    def temp_object_name(self, session_id: str, filename: str) -> str:
        """临时文件对象名。"""
        ...

    def temp_prefix_for_session(self, session_id: str) -> str:
        """会话临时文件列表前缀（用于清理）。"""
        ...


class DefaultPathStrategy:
    """默认路径策略：逐字复刻 NovaMind 现行路径方案。

    不注入策略时 ``MinioClient`` 使用本实现，对象路径与端口化前逐字一致。
    宿主如需定制对象路径方案，可注入自己的 ``PathStrategy`` 实现。
    """

    def document_object_name(
        self, space_id: int, kb_id: int, document_id: int, storage_name: str
    ) -> str:
        return f"spaces/{space_id}/kbs/{kb_id}/documents/{document_id}/{storage_name}"

    def document_prefix_for_kb(self, space_id: int, kb_id: int) -> str:
        return f"spaces/{space_id}/kbs/{kb_id}/"

    def document_prefix_for_space(self, space_id: int) -> str:
        return f"spaces/{space_id}/"

    def avatar_object_name(self, user_id: int, extension: str) -> str:
        return f"avatars/{user_id}/avatar.{extension}"

    def avatar_prefix_for_user(self, user_id: int) -> str:
        return f"avatars/{user_id}/"

    def temp_object_name(self, session_id: str, filename: str) -> str:
        return f"temp/{session_id}/{filename}"

    def temp_prefix_for_session(self, session_id: str) -> str:
        return f"temp/{session_id}/"


__all__ = ["PathStrategy", "DefaultPathStrategy"]