"""
Mem0 调和管线：包装 mem0ai AsyncMemory 做写入期「提取+语义调和」，事件应用到 MySQL 真源。

Mem0 是第三方写入管线而非存储真源：ADD/UPDATE/DELETE 事件经安全扫描与上限
检查后应用到 HostMemoryStorePort（MySQL）+ ES hybrid 索引；Mem0 自身的工作
存储（ES collection）只服务调和时的相似比对，可随时从 MySQL 回灌重建。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from novamind.shared.logging import get_logger

if TYPE_CHECKING:
    from novamind.engines.agent.memory.interfaces import MemoryMessage

logger = get_logger(__name__)

# 记忆上限口径对齐 memory 工具（builtins/memory.py）
_MAX_MEMORIES_PER_AGENT_USER = 50


def split_es_host(host_url: str) -> tuple[str, int]:
    """拆 ES host URL 为（不带端口 host, 端口）——mem0 ES provider 拼 host:port。

    Args:
        host_url: 形如 http://localhost:9200 的地址。

    Returns:
        (host, port) 元组，端口无法解析时默认 9200。
    """
    parsed = host_url.rsplit(":", 1)
    if len(parsed) == 2 and parsed[1].isdigit():
        return parsed[0], int(parsed[1])
    return host_url, 9200


class Mem0Reconciler:
    """Mem0 写入期调和器：AsyncMemory 实例 LRU + 事件应用器。"""

    def __init__(
        self,
        llm_params: dict[str, Any],
        embedding_params: dict[str, Any],
        es_params: dict[str, Any],
        store: Any,
        search: Any | None = None,
        embedding_factory: Any | None = None,
        es_collection: str = "novamind_mem0",
        history_size: int = 5,
        lru_size: int = 16,
        owner_user_id: int | None = None,
        owner_agent_id: int | None = None,
    ):
        """注入模型连接参数与存储端口（构造期不建 AsyncMemory，首次 reconcile 懒建）。

        Args:
            llm_params: Mem0 LLM 配置（model/openai_base_url/api_key，进程内传递禁落日志）。
            embedding_params: Mem0 embedder 配置（同上）。
            es_params: ES 连接参数（host 不带端口/port/user/password，mem0 provider 拼 host:port）。
            store: HostMemoryStorePort（MySQL 真源读写）。
            search: HostMemorySearchPort（ES hybrid），None 时事件只写 MySQL 不索引。
            embedding_factory: embedding 客户端工厂，可空；None 时事件不索引 ES。
            es_collection: Mem0 工作 ES collection 名。
            history_size: 调和参考的存量相似记忆条数。
            lru_size: AsyncMemory 实例 LRU 缓存数（键为模型参数指纹）。
            owner_user_id: 归属用户 ID（管理联动按内容检索时的命名空间），可空。
            owner_agent_id: 归属 Agent ID（同上），可空。
        """
        self._llm_params = llm_params
        self._embedding_params = embedding_params
        self._es_params = es_params
        self._store = store
        self._search = search
        self._embedding_factory = embedding_factory
        self._es_collection = es_collection
        self._history_size = history_size
        self._lru_size = max(1, lru_size)
        self._owner_user_id = owner_user_id
        self._owner_agent_id = owner_agent_id
        self._memory_cache: dict[tuple, Any] = {}
        self._cache_order: list[tuple] = []

    # ==================== 对外入口 ====================

    async def reconcile(
        self,
        agent_id: int,
        user_id: int,
        conversation_id: int | None,
        messages: list[MemoryMessage],
    ) -> int:
        """跑 Mem0 提取+调和管线，把产出事件应用到 MySQL 真源。

        Args:
            agent_id: Agent 主键 ID。
            user_id: 属主用户 ID。
            conversation_id: 来源会话 ID，可空。
            messages: 待巩固的对话消息（user/assistant）。

        Returns:
            应用成功的 ADD/UPDATE 事件数（DELETE/NOOP 不计）。

        Raises:
            Exception: mem0ai 未安装或管线失败时向上抛，由调用方决定降级。
        """
        mem0_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant") and m.content
        ]
        if not mem0_messages:
            return 0

        memory = await self._get_memory(agent_id, user_id)
        result = await memory.add(
            mem0_messages,
            user_id=str(user_id),
            agent_id=str(agent_id),
            metadata={"conversation_id": conversation_id},
        )

        events = result.get("results", []) if isinstance(result, dict) else result
        if not isinstance(events, list):
            logger.warning("Mem0 事件结构异常，跳过应用", result_type=type(result).__name__)
            return 0

        applied = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            try:
                handled = await self._apply_event(agent_id, user_id, conversation_id, event)
                if handled:
                    applied += 1
            except Exception as e:
                # 单事件失败不阻断其余事件；真源不动是安全方向
                logger.warning(
                    "Mem0 事件应用失败",
                    mem0_event=event.get("event"),
                    error=str(e),
                )
        return applied

    async def delete_by_mem0_id(self, memory_id: str, content: str | None = None) -> None:
        """删除 Mem0 工作存储条目（管理端点删 MySQL 后联动，防幽灵记忆）。

        v1.1 的 add 事件 ID 与 collection 文档 ID 不一致（实测），ID 直删 404 时
        按内容在 (user_id, agent_id) 命名空间检索找真实文档 ID 兜底。

        Args:
            memory_id: Mem0 事件返回的记忆 ID（extra_data.mem0_id）。
            content: 记忆内容（MySQL 侧），ID 直删失败时的检索键，可空。

        Raises:
            Exception: mem0ai 未安装或 ID 直删失败且无内容兜底/检索无命中。
        """
        memory = await self._get_memory_any()
        try:
            await memory.delete(memory_id=memory_id)
            return
        except Exception as e:
            if not content:
                raise
            logger.info(
                "Mem0 按 ID 直删未命中，转内容检索兜底",
                mem0_id=memory_id,
                error=str(e),
            )
        # v1.1 get_all 只认 filters dict（顶层 user_id/agent_id 参数已移除），
        # 返回 {"results": [...]} 包装（实测）
        filters: dict[str, Any] = {}
        if self._owner_user_id is not None:
            filters["user_id"] = str(self._owner_user_id)
        if self._owner_agent_id is not None:
            filters["agent_id"] = str(self._owner_agent_id)
        payload = await memory.get_all(filters=filters) if filters else await memory.get_all()
        rows = payload.get("results", []) if isinstance(payload, dict) else payload
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            # get_all 输出行字段名是 memory（非存储层的 data），兜底 data 兼容
            text = row.get("memory") or row.get("data") or ""
            if text.strip() == content.strip() and row.get("id"):
                await memory.delete(memory_id=str(row["id"]))
                return
        raise RuntimeError(f"Mem0 工作存储未找到匹配内容条目: {content[:50]}")

    async def rebuild_from_mysql(self, agent_id: int, user_id: int) -> int:
        """从 MySQL 真源回灌重建 Mem0 工作存储（collection 损坏/换 embedding 维度后）。

        按 list_by_agent 全量 add（带 metadata），产出新 mem0_id 后回写
        extra_data.mem0_id。阶段 1 内部函数，不暴露端点。

        Args:
            agent_id: Agent 主键 ID。
            user_id: 属主用户 ID。

        Returns:
            回灌条数。
        """
        memories, _ = await self._store.list_by_agent(agent_id, user_id, limit=1000)
        memory = await self._get_memory(agent_id, user_id)
        rebuilt = 0
        for m in memories:
            try:
                result = await memory.add(
                    [{"role": "user", "content": m.content}],
                    user_id=str(user_id),
                    agent_id=str(agent_id),
                    metadata={"category": m.category, "mysql_memory_id": m.id},
                )
                new_id = self._first_memory_id(result)
                if not new_id:
                    # mem0 判定与 collection 现有条语义重复（NOOP）时无新 ID；
                    # 保留原 mem0_id，不洗成 null（否则 DELETE/UPDATE 定位断链）
                    old_id = (m.extra_data or {}).get("mem0_id")
                    if not old_id:
                        continue
                    rebuilt += 1
                    continue
                await self._store.update_extra_data(m.id, {"mem0_id": new_id})
                rebuilt += 1
            except Exception as e:
                logger.warning("回灌单条记忆失败", memory_id=m.id, error=str(e))
        logger.info("Mem0 工作存储回灌完成", agent_id=agent_id, rebuilt=rebuilt)
        return rebuilt

    # ==================== 事件应用 ====================

    async def _apply_event(
        self,
        agent_id: int,
        user_id: int,
        conversation_id: int | None,
        event: dict[str, Any],
    ) -> bool:
        """应用单个 Mem0 事件；返回是否实际改动真源。"""
        from novamind.engines.agent.memory.security import scan_memory_content

        event_type = event.get("event")
        # DELETE 事件携带 removed_memory（无 memory/data 字段）；安全扫描对删除
        # 无意义但门禁统一走 content 提取，故一并取出
        content = (
            event.get("memory") or event.get("data") or event.get("removed_memory") or ""
        ).strip()
        mem0_id = event.get("id")

        if not content or event_type == "NOOP":
            return False

        scan = scan_memory_content(content)
        if not scan:
            logger.warning(
                "Mem0 产出被安全扫描拦截", mem0_event=event_type, threats=scan.threats
            )
            return False

        if event_type == "ADD":
            return await self._apply_add(
                agent_id, user_id, conversation_id, content, mem0_id
            )
        if event_type == "UPDATE":
            return await self._apply_update(agent_id, user_id, content, mem0_id, event)
        if event_type == "DELETE":
            return await self._apply_delete(agent_id, user_id, mem0_id, event)
        logger.debug("忽略未知 Mem0 事件类型", mem0_event=event_type)
        return False

    async def _apply_add(
        self,
        agent_id: int,
        user_id: int,
        conversation_id: int | None,
        content: str,
        mem0_id: Any,
    ) -> bool:
        """ADD：安全扫描已过 → 上限检查 → MySQL create（extra_data.mem0_id）→ ES 索引。"""
        _, total = await self._store.list_by_agent(agent_id, user_id, limit=1)
        if total >= _MAX_MEMORIES_PER_AGENT_USER:
            logger.warning(
                "Mem0 ADD 超记忆上限，拒绝",
                agent_id=agent_id,
                total=total,
            )
            return False

        entry = await self._store.create(
            agent_id=agent_id,
            user_id=user_id,
            category="fact",
            content=content,
            source_conversation_id=conversation_id,
            source_type="consolidate",
            extra_data={"mem0_id": str(mem0_id)} if mem0_id else None,
        )
        await self._store.flush()
        await self._index_entry(agent_id, entry)
        logger.info("Mem0 ADD 已应用", agent_id=agent_id, memory_id=entry.id)
        return True

    async def _apply_update(
        self,
        agent_id: int,
        user_id: int,
        content: str,
        mem0_id: Any,
        event: dict[str, Any],
    ) -> bool:
        """UPDATE：按 extra_data.mem0_id 定位，悬空则内容子串二跳，仍找不到放弃。"""
        entry = await self._find_by_mem0_id(agent_id, user_id, mem0_id)
        if entry is None:
            previous = event.get("previous_memory") or ""
            if previous:
                entry = await self._store.find_by_content_contains(
                    agent_id, user_id, previous[:100]
                )
        if entry is None:
            logger.warning(
                "Mem0 UPDATE 定位失败，放弃该事件", mem0_id=str(mem0_id)
            )
            return False

        await self._store.update_content(entry.id, content)
        await self._store.flush()
        await self._index_entry(agent_id, entry)
        logger.info("Mem0 UPDATE 已应用", agent_id=agent_id, memory_id=entry.id)
        return True

    async def _apply_delete(
        self,
        agent_id: int,
        user_id: int,
        mem0_id: Any,
        event: dict[str, Any],
    ) -> bool:
        """DELETE：按 mem0_id 定位 MySQL 行删除 + ES 删文档；悬空时放弃（不动真源）。"""
        entry = await self._find_by_mem0_id(agent_id, user_id, mem0_id)
        if entry is None:
            removed_text = event.get("removed_memory") or event.get("memory") or ""
            if removed_text:
                entry = await self._store.find_by_content_contains(
                    agent_id, user_id, removed_text[:100]
                )
        if entry is None:
            logger.warning(
                "Mem0 DELETE 定位失败，放弃该事件", mem0_id=str(mem0_id)
            )
            return False

        await self._store.delete(entry.id)
        await self._store.flush()
        if self._search:
            try:
                await self._search.delete_memory(agent_id, entry.id)
            except Exception as e:
                logger.warning("ES 记忆删除失败", memory_id=entry.id, error=str(e))
        logger.info("Mem0 DELETE 已应用", agent_id=agent_id, memory_id=entry.id)
        return True

    # ==================== 辅助 ====================

    async def _find_by_mem0_id(self, agent_id: int, user_id: int, mem0_id: Any):
        """按 extra_data.mem0_id 在 MySQL 精确找记忆行，找不到返回 None。"""
        if not mem0_id:
            return None
        entries, _ = await self._store.list_by_agent(
            agent_id, user_id, limit=_MAX_MEMORIES_PER_AGENT_USER
        )
        for e in entries:
            extra = e.extra_data or {}
            if extra.get("mem0_id") == str(mem0_id):
                return e
        return None

    async def _index_entry(self, agent_id: int, entry) -> None:
        """ADD/UPDATE 后生成 embedding 索引 ES（缺工厂或失败仅告警，MySQL 已写）。"""
        if not self._search or not self._embedding_factory:
            return
        try:
            embedding_client = await self._embedding_factory()
            embedding = await embedding_client.generate_embedding(entry.content)
            if not embedding:
                return
            await self._search.index_memory(
                agent_id=agent_id,
                memory_id=entry.id,
                user_id=entry.user_id,
                category=entry.category,
                content=entry.content,
                embedding=embedding,
                source_type=entry.source_type,
                source_conversation_id=entry.source_conversation_id,
                created_at=entry.created_at,
            )
        except Exception as e:
            logger.warning(
                "ES 记忆索引失败", memory_id=entry.id, error=str(e)
            )

    async def _get_memory(self, agent_id: int, user_id: int) -> Any:
        """取（或懒建）当前模型参数对应的 AsyncMemory 实例（LRU）。"""
        cache_key = self._cache_key()
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]
        instance = await self._build_memory()
        self._memory_cache[cache_key] = instance
        self._cache_order.append(cache_key)
        if len(self._cache_order) > self._lru_size:
            oldest = self._cache_order.pop(0)
            self._memory_cache.pop(oldest, None)
        return instance

    async def _get_memory_any(self) -> Any:
        """管理联动路径（delete_by_mem0_id）用：任意已缓存实例，无则现建。"""
        if self._memory_cache:
            return next(iter(self._memory_cache.values()))
        return await self._build_memory()

    def _cache_key(self) -> tuple:
        """模型参数指纹（api_key 只取长度，不落明文）。"""
        return (
            self._llm_params.get("model"),
            self._llm_params.get("openai_base_url"),
            len(self._llm_params.get("api_key") or ""),
            self._embedding_params.get("model"),
            self._embedding_params.get("openai_base_url"),
            len(self._embedding_params.get("api_key") or ""),
        )

    async def _build_memory(self) -> Any:
        """按当前连接参数构造 AsyncMemory（mem0ai 懒 import，builtin 部署零依赖）。"""
        try:
            from mem0 import AsyncMemory
        except ImportError as e:
            raise RuntimeError(
                "agent.memory.backend=mem0 需要 mem0 extra：uv sync --extra mem0"
            ) from e

        config = {
            "llm": {
                "provider": "openai",
                "config": {
                    "model": self._llm_params["model"],
                    "openai_base_url": self._llm_params["openai_base_url"],
                    "api_key": self._llm_params["api_key"],
                    "temperature": 0.1,
                    "max_tokens": 2000,
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": self._embedding_params["model"],
                    "openai_base_url": self._embedding_params["openai_base_url"],
                    "api_key": self._embedding_params["api_key"],
                },
            },
            "vector_store": {
                "provider": "elasticsearch",
                "config": {
                    "collection_name": self._es_collection,
                    "host": self._es_params["host"],
                    "port": self._es_params["port"],
                    "user": self._es_params.get("user"),
                    "password": self._es_params.get("password"),
                    "embedding_model_dims": self._es_params["embedding_model_dims"],
                },
            },
            # history_size 非 mem0 config schema 键（PoC 实测），调和参考存量由
            # mem0 内部检索控制；本字段保留为后续自定义 infer prompt 时的语境参数
            "version": "v1.1",
        }
        return AsyncMemory.from_config(config)

    @staticmethod
    def _first_memory_id(result: Any) -> str | None:
        """从 mem0 add/get 返回结构中取首个记忆 ID（防御性）。"""
        rows = result.get("results", []) if isinstance(result, dict) else result
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("id"):
                    return str(row["id"])
        return None
