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
        """单文档对象名（含存储文件名）。

        Args:
            space_id: 空间 ID。
            kb_id: 知识库 ID。
            document_id: 文档 ID。
            storage_name: 存储文件名（含哈希前缀与扩展名）。

        Returns:
            MinIO 对象名。
        """
        ...

    def document_prefix_for_kb(self, space_id: int, kb_id: int) -> str:
        """知识库下所有对象的列表前缀（用于按 KB 批量删除/列举）。

        Args:
            space_id: 空间 ID。
            kb_id: 知识库 ID。

        Returns:
            前缀字符串（以 / 结尾）。
        """
        ...

    def document_prefix_for_space(self, space_id: int) -> str:
        """空间下所有对象的列表前缀（用于按空间批量删除/列举）。

        Args:
            space_id: 空间 ID。

        Returns:
            前缀字符串（以 / 结尾）。
        """
        ...

    def avatar_object_name(self, user_id: int, extension: str) -> str:
        """用户头像对象名。

        Args:
            user_id: 用户 ID。
            extension: 图片扩展名（不含点号）。

        Returns:
            MinIO 对象名。
        """
        ...

    def avatar_prefix_for_user(self, user_id: int) -> str:
        """用户头像列表前缀（用于删除旧头像）。

        Args:
            user_id: 用户 ID。

        Returns:
            前缀字符串（以 / 结尾）。
        """
        ...

    def temp_object_name(self, session_id: str, filename: str) -> str:
        """临时文件对象名。

        Args:
            session_id: 会话 ID。
            filename: 原始文件名。

        Returns:
            MinIO 对象名。
        """
        ...

    def temp_prefix_for_session(self, session_id: str) -> str:
        """会话临时文件列表前缀（用于清理）。

        Args:
            session_id: 会话 ID。

        Returns:
            前缀字符串（以 / 结尾）。
        """
        ...


class DefaultPathStrategy:
    """默认路径策略：逐字复刻 NovaMind 现行路径方案。

    不注入策略时 ``MinioClient`` 使用本实现，对象路径与端口化前逐字一致。
    宿主如需定制对象路径方案，可注入自己的 ``PathStrategy`` 实现。
    """

    def document_object_name(
        self, space_id: int, kb_id: int, document_id: int, storage_name: str
    ) -> str:
        """文档对象名：spaces/{space_id}/kbs/{kb_id}/documents/{doc_id}/{storage_name}。

        Args:
            space_id: 空间 ID。
            kb_id: 知识库 ID。
            document_id: 文档 ID。
            storage_name: 存储文件名（含哈希前缀与扩展名）。

        Returns:
            形如 spaces/1/kbs/2/documents/3/abc.pdf 的对象名。
        """
        return f"spaces/{space_id}/kbs/{kb_id}/documents/{document_id}/{storage_name}"

    def document_prefix_for_kb(self, space_id: int, kb_id: int) -> str:
        """知识库列表前缀：spaces/{space_id}/kbs/{kb_id}/。

        Args:
            space_id: 空间 ID。
            kb_id: 知识库 ID。

        Returns:
            形如 spaces/1/kbs/2/ 的前缀。
        """
        return f"spaces/{space_id}/kbs/{kb_id}/"

    def document_prefix_for_space(self, space_id: int) -> str:
        """空间列表前缀：spaces/{space_id}/。

        Args:
            space_id: 空间 ID。

        Returns:
            形如 spaces/1/ 的前缀。
        """
        return f"spaces/{space_id}/"

    def avatar_object_name(self, user_id: int, extension: str) -> str:
        """头像对象名：avatars/{user_id}/avatar.{extension}。

        Args:
            user_id: 用户 ID。
            extension: 图片扩展名（不含点号）。

        Returns:
            形如 avatars/9/avatar.png 的对象名。
        """
        return f"avatars/{user_id}/avatar.{extension}"

    def avatar_prefix_for_user(self, user_id: int) -> str:
        """头像列表前缀：avatars/{user_id}/。

        Args:
            user_id: 用户 ID。

        Returns:
            形如 avatars/9/ 的前缀。
        """
        return f"avatars/{user_id}/"

    def temp_object_name(self, session_id: str, filename: str) -> str:
        """临时对象名：temp/{session_id}/{filename}。

        Args:
            session_id: 会话 ID。
            filename: 原始文件名。

        Returns:
            形如 temp/s-abc/report.docx 的对象名。
        """
        return f"temp/{session_id}/{filename}"

    def temp_prefix_for_session(self, session_id: str) -> str:
        """会话临时文件列表前缀：temp/{session_id}/。

        Args:
            session_id: 会话 ID。

        Returns:
            形如 temp/s-abc/ 的前缀。
        """
        return f"temp/{session_id}/"


__all__ = ["PathStrategy", "DefaultPathStrategy"]