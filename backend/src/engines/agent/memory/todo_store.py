"""
TodoStore — 压缩后存活的任务跟踪器

纯内存，key 为 conversation_id。
压缩后 format_for_injection() 将 pending/in_progress 任务重新注入 messages。
"""
from typing import Any

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

_VALID_STATUSES = frozenset({"pending", "in_progress", "completed", "cancelled"})


class TodoStore:
    """压缩后存活的任务跟踪器"""

    def __init__(self) -> None:
        """初始化内存任务表（key 为 conversation_id），仅进程内有效、不持久化。"""
        self._store: dict[int, list[dict[str, str]]] = {}

    def write(
        self,
        conversation_id: int,
        todos: list[dict[str, Any]],
        merge: bool = False,
    ) -> list[dict[str, str]]:
        """写入任务列表。

        Args:
            conversation_id: 会话 ID。
            todos: 任务 dict 列表（id/content/status），非 dict 项忽略、非法 status 归 pending。
            merge: True 按 id 更新合并；False 整表替换。

        Returns:
            写入后的完整任务列表。
        """
        normalized = []
        for item in todos:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "pending")).lower()
            if status not in _VALID_STATUSES:
                status = "pending"
            normalized.append({
                "id": str(item.get("id", "")),
                "content": str(item.get("content", "")),
                "status": status,
            })

        if merge and conversation_id in self._store:
            existing = self._store[conversation_id]
            existing_by_id = {t["id"]: t for t in existing}
            for t in normalized:
                existing_by_id[t["id"]] = t
            self._store[conversation_id] = list(existing_by_id.values())
        else:
            self._store[conversation_id] = normalized

        logger.debug(
            "TodoStore 写入",
            conversation_id=conversation_id,
            count=len(normalized),
            merge=merge,
        )
        return self._store[conversation_id]

    def read(self, conversation_id: int) -> list[dict[str, str]]:
        """读取任务列表。

        Args:
            conversation_id: 会话 ID。

        Returns:
            任务列表副本；无记录为空列表。
        """
        return list(self._store.get(conversation_id, []))

    def format_for_injection(self, conversation_id: int) -> str | None:
        """生成压缩后重新注入的文本（只含 pending/in_progress）。

        Args:
            conversation_id: 会话 ID。

        Returns:
            带序号的注入文本；无待办任务为 None。
        """
        todos = self._store.get(conversation_id, [])
        active = [t for t in todos if t["status"] in ("pending", "in_progress")]
        if not active:
            return None

        lines = ["## 当前任务清单"]
        for i, t in enumerate(active, 1):
            lines.append(f"{i}. [{t['status']}] {t['content']}")
        return "\n".join(lines)

    def clear(self, conversation_id: int) -> None:
        """清除指定会话的任务。

        Args:
            conversation_id: 会话 ID。
        """
        self._store.pop(conversation_id, None)
