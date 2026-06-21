"""
Session 管理器

管理用户 session → ClawMateSessionState 映射。
纯内存管理，不存数据库。
支持定时清理空闲 session。
"""

import asyncio
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.core.middleware.structured_logging import get_logger
from src.features.clawmate.core.environment import LocalEnvironment
from src.features.clawmate.core.file_operations import FileOperations

logger = get_logger(__name__)


@dataclass
class ClawMateSessionState:
    """ClawMate 会话状态

    包含 Shell 环境、对话历史、冻结的记忆快照和 Todo 追踪。
    """
    env: LocalEnvironment
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    frozen_memory: str = ""             # MEMORY.md 快照（创建时冻结）
    frozen_user: str = ""               # USER.md 快照（创建时冻结）
    todo_store: Any = None              # ClawMateTodoStore 实例
    chat_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    created_at: float = 0.0


class SessionManager:
    """用户 Session 管理器

    - 每个用户最多一个活跃 session（user_id → ClawMateSessionState）
    - 空闲超时自动清理
    - 线程安全（同步操作）+ 异步安全（chat_lock per session）
    """

    def __init__(self, default_timeout: int = 30, max_idle_seconds: int = 600):
        """
        Args:
            default_timeout: 命令执行默认超时（秒）
            max_idle_seconds: session 最大空闲时间（秒），超时后清理
        """
        self._sessions: Dict[int, ClawMateSessionState] = {}
        self._last_activity: Dict[int, float] = {}
        self._default_timeout = default_timeout
        self._max_idle_seconds = max_idle_seconds
        self._lock = threading.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    # ==================== 向后兼容方法 ====================

    def get_or_create(
        self,
        user_id: int,
        cwd: Optional[str] = None,
    ) -> LocalEnvironment:
        """获取或创建用户环境（返回 LocalEnvironment，向后兼容 REST 端点）"""
        state = self.get_or_create_state(user_id, cwd)
        return state.env

    def get(self, user_id: int) -> Optional[LocalEnvironment]:
        """获取用户环境（不创建）"""
        with self._lock:
            state = self._sessions.get(user_id)
            if state is not None:
                self._last_activity[user_id] = time.monotonic()
                return state.env
            return None

    # ==================== 新方法 ====================

    def get_or_create_state(
        self,
        user_id: int,
        cwd: Optional[str] = None,
    ) -> ClawMateSessionState:
        """获取或创建完整的会话状态

        首次创建时自动加载 MEMORY.md / USER.md 冻结快照。
        """
        with self._lock:
            state = self._sessions.get(user_id)
            if state is not None:
                self._last_activity[user_id] = time.monotonic()
                return state

            # 创建新环境
            effective_cwd = cwd or self._get_default_cwd()
            env = LocalEnvironment(
                cwd=effective_cwd,
                timeout=self._default_timeout,
            )

            # 加载记忆快照
            file_ops = FileOperations(env)
            from src.features.clawmate.core.memory_store import MemoryStore
            memory_store = MemoryStore(env.cwd, file_ops)
            frozen_memory, frozen_user = memory_store.load_snapshot()

            # 创建 TodoStore
            from src.features.clawmate.core.tools.todo_tool import ClawMateTodoStore

            state = ClawMateSessionState(
                env=env,
                frozen_memory=frozen_memory,
                frozen_user=frozen_user,
                todo_store=ClawMateTodoStore(),
                created_at=time.monotonic(),
            )

            self._sessions[user_id] = state
            self._last_activity[user_id] = time.monotonic()

            logger.info(
                "ClawMate 会话状态已创建",
                user_id=user_id,
                session_id=env.session_id,
                cwd=effective_cwd,
                memory_chars=len(frozen_memory),
                user_chars=len(frozen_user),
            )
            return state

    def get_state(self, user_id: int) -> Optional[ClawMateSessionState]:
        """获取完整会话状态（不创建）"""
        with self._lock:
            state = self._sessions.get(user_id)
            if state is not None:
                self._last_activity[user_id] = time.monotonic()
            return state

    # ==================== 通用方法 ====================

    def destroy(self, user_id: int) -> bool:
        """销毁用户 session

        Returns:
            是否成功销毁（False = session 不存在）
        """
        with self._lock:
            state = self._sessions.pop(user_id, None)
            self._last_activity.pop(user_id, None)

        if state is not None:
            state.env.cleanup()
            logger.info("ClawMate session 已销毁", user_id=user_id, session_id=state.env.session_id)
            return True

        return False

    def touch(self, user_id: int):
        """更新用户活跃时间"""
        with self._lock:
            if user_id in self._sessions:
                self._last_activity[user_id] = time.monotonic()

    def get_status(self, user_id: int) -> Optional[dict]:
        """获取用户 session 状态"""
        with self._lock:
            state = self._sessions.get(user_id)
            if state is None:
                return None

            last = self._last_activity.get(user_id, 0)
            idle_seconds = time.monotonic() - last

            return {
                "session_id": state.env.session_id,
                "cwd": state.env.cwd,
                "is_alive": state.env.is_alive,
                "idle_seconds": round(idle_seconds, 1),
                "history_count": len(state.conversation_history),
            }

    def cleanup_idle(self) -> int:
        """清理所有空闲超时的 session

        Returns:
            清理的 session 数量
        """
        now = time.monotonic()
        to_remove = []

        with self._lock:
            for user_id, last in self._last_activity.items():
                if now - last > self._max_idle_seconds:
                    to_remove.append(user_id)

            cleaned_envs = []
            for user_id in to_remove:
                state = self._sessions.pop(user_id, None)
                self._last_activity.pop(user_id, None)
                if state:
                    cleaned_envs.append(state.env)

        for env in cleaned_envs:
            env.cleanup()

        if to_remove:
            logger.info(
                "ClawMate 空闲 session 已清理",
                count=len(to_remove),
                user_ids=to_remove,
            )

        return len(to_remove)

    @property
    def active_count(self) -> int:
        """当前活跃 session 数量"""
        with self._lock:
            return len(self._sessions)

    @staticmethod
    def _get_default_cwd() -> str:
        """获取默认工作目录"""
        return os.path.expanduser("~")

    async def start_cleanup_loop(self, interval: int = 60):
        """启动定时清理任务（异步）

        Args:
            interval: 清理间隔（秒）
        """
        logger.info("ClawMate session 清理任务已启动", interval=interval)
        while True:
            await asyncio.sleep(interval)
            try:
                self.cleanup_idle()
            except Exception as e:
                logger.error("ClawMate session 清理失败", error=str(e))

    def start_cleanup_loop_sync(self, interval: int = 60):
        """启动定时清理任务（同步，用于线程）"""
        logger.info("ClawMate session 清理线程已启动", interval=interval)
        while True:
            time.sleep(interval)
            try:
                self.cleanup_idle()
            except Exception as e:
                logger.error("ClawMate session 清理失败", error=str(e))
