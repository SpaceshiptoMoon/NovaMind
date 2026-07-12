"""
TodoStore — 压缩后存活的任务跟踪器

纯内存，key 为 conversation_id。
压缩后 format_for_injection() 将 pending/in_progress 任务重新注入 messages。
"""
from typing import Any, Dict, List, Optional

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

_VALID_STATUSES = frozenset({"pending", "in_progress", "completed", "cancelled"})


class TodoStore:
    """压缩后存活的任务跟踪器"""

    def __init__(self) -> None:
        self._store: Dict[int, List[Dict[str, str]]] = {}

    def write(
        self,
        conversation_id: int,
        todos: List[Dict[str, Any]],
        merge: bool = False,
    ) -> List[Dict[str, str]]:
        """写入任务列表"""
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

    def read(self, conversation_id: int) -> List[Dict[str, str]]:
        """读取任务列表"""
        return list(self._store.get(conversation_id, []))

    def format_for_injection(self, conversation_id: int) -> Optional[str]:
        """生成压缩后重新注入的文本（只含 pending/in_progress）"""
        todos = self._store.get(conversation_id, [])
        active = [t for t in todos if t["status"] in ("pending", "in_progress")]
        if not active:
            return None

        lines = ["## 当前任务清单"]
        for i, t in enumerate(active, 1):
            lines.append(f"{i}. [{t['status']}] {t['content']}")
        return "\n".join(lines)

    def clear(self, conversation_id: int) -> None:
        """清除指定会话的任务"""
        self._store.pop(conversation_id, None)
