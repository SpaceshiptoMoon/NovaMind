"""
工作记忆实现

纯内存级的状态存储，以 conversation_id 为命名空间，支持 TTL 自动过期。
用于保存工具调用中间结果、当前任务计划等瞬态数据。
"""
import time
from typing import Any, Dict, Optional, Tuple

from src.features.agent.core.memory.interfaces import IWorkingMemory
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class WorkingMemory(IWorkingMemory):
    """
    工作记忆

    存储结构：{conversation_id: {key: (value, expires_at)}}
    默认 TTL 为 1 小时，到期后惰性清理。
    """

    def __init__(self, default_ttl: int = 3600):
        self._store: Dict[int, Dict[str, Tuple[Any, float]]] = {}
        self._default_ttl = default_ttl

    async def get_state(
        self, conversation_id: int, key: str
    ) -> Optional[Any]:
        states = self._store.get(conversation_id, {})
        entry = states.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() > expires_at:
            del states[key]
            return None
        return value

    async def set_state(
        self,
        conversation_id: int,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> None:
        if conversation_id not in self._store:
            self._store[conversation_id] = {}
        expires_at = time.time() + (ttl or self._default_ttl)
        self._store[conversation_id][key] = (value, expires_at)

    async def get_all_states(
        self, conversation_id: int
    ) -> Dict[str, Any]:
        states = self._store.get(conversation_id, {})
        now = time.time()
        result = {}
        for key, (value, expires_at) in states.items():
            if now <= expires_at:
                result[key] = value
        return result

    async def clear(self, conversation_id: int) -> None:
        self._store.pop(conversation_id, None)
