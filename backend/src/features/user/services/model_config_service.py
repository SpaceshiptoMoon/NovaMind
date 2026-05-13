"""
用户模型配置服务

核心职责：
1. 模型配置的 CRUD 操作
2. 根据模型名称获取对应的凭证（核心方法）
3. 模型连接测试
4. 系统配置同步
"""
import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.features.user.models.user_model_config import UserModelConfig, ModelType
from src.features.user.repository.model_config_repository import (
    ModelConfigRepository, MODEL_TYPE_MAP, MODEL_TYPE_STR
)
from src.features.user.schemas.model_config_schema import (
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelConfigResponse,
    ModelConfigListResponse,
    ModelTestRequest,
    ModelTestResponse,
)
from src.shared.ai_models.llm import create_llm_client, BaseLLM
from src.shared.ai_models.embedding import create_embedding_client, BaseEmbedding
from src.shared.ai_models.rerank import create_rerank_client, BaseRerank
from src.setting.yaml_config import get_config
from src.shared.utils.crypto import encrypt_api_key_async, decrypt_api_key_async
from src.core.middleware.structured_logging import get_logger
from src.features.user.api.exceptions import (
    ModelConfigNotFoundError,
    ModelConfigAlreadyExistsError,
    ModelConfigTestFailedError,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 模块级客户端缓存
#
# 设计约定（所有操作必须遵守）：
# 1. _client_cache 的所有读写操作必须在 _cache_lock 保护下进行，
#    防止并发创建重复客户端或竞态条件导致缓存不一致。
# 2. _cache_lock 是 asyncio.Lock（协程锁），适用于同一事件循环内的并发协程，
#    不适用于多线程/多进程场景。当前 FastAPI 默认单线程事件循环，因此足够。
# 3. 若未来部署多线程/多进程，需将缓存迁移至 Redis 等外部共享存储。
# 4. _cleanup_expired_cache() 仅在已持有 _cache_lock 的上下文中调用，
#    不可单独加锁（asyncio.Lock 不可重入，会导致死锁）。
# ---------------------------------------------------------------------------
_client_cache: Dict[str, Tuple[float, Any]] = {}  # key -> (timestamp, client)
_CACHE_TTL = 3600  # 客户端缓存 TTL（秒）
_MAX_CACHE_SIZE = 100  # 最大缓存条数
_cache_lock = asyncio.Lock()  # 缓存操作锁，防止并发协程的竞态条件




async def _clear_client_cache_global(user_id: int, model_type: str, model: str) -> None:
    """清除指定模型的客户端缓存（全局，异步安全）"""
    cache_key = f"{user_id}:{model_type}:{model}"
    async with _cache_lock:
        if cache_key in _client_cache:
            del _client_cache[cache_key]
            logger.debug("客户端缓存已清除", cache_key=cache_key)




async def _cleanup_expired_cache() -> None:
    """清理过期的缓存条目，并关闭旧客户端连接

    注意：此函数仅在 _get_client_by_model() 内部调用，
    调用方已持有 _cache_lock，因此这里不能再加锁（asyncio.Lock 不可重入，会导致死锁）。
    """
    now = time.time()
    expired_keys = [
        k for k, (ts, _) in _client_cache.items()
        if now - ts > _CACHE_TTL
    ]
    for k in expired_keys:
        _, old_client = _client_cache[k]
        if hasattr(old_client, 'aclose'):
            try:
                await old_client.aclose()
            except Exception:
                pass
        del _client_cache[k]
    if expired_keys:
        logger.debug("清理过期客户端缓存", count=len(expired_keys))


@dataclass
class ModelCredentials:
    """
    模型凭证（用于创建客户端）

    包含创建 AI 客户端所需的所有信息
    """
    protocol: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    extra_config: Optional[Dict[str, Any]] = None


class ModelConfigService:
    """用户模型配置服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ModelConfigRepository(db)
        # 使用模块级缓存（实例引用）
        # 注意：不再创建新的缓存实例，而是引用模块级缓存

    # ========== 核心方法：根据模型名称获取凭证 ==========

    async def get_credentials_by_model(
        self,
        user_id: int,
        model_type: str,
        model: str,
    ) -> Optional[ModelCredentials]:
        """
        根据模型名称获取凭证

        查找优先级：
        1. 用户私有配置（user_id + model_type + model）
        2. 系统配置（user_id = NULL + model_type + model）
        3. 返回 None（调用方使用全局默认）

        Args:
            user_id: 用户 ID
            model_type: 模型类型 (llm/embedding/rerank)
            model: 模型名称（如 gpt-4o）

        Returns:
            ModelCredentials 或 None
        """
        # 1. 先查找用户私有配置
        config = await self.repo.get_by_user_and_model(user_id, model_type, model)
        if config:
            return ModelCredentials(
                protocol=config.protocol,
                model=config.model,
                api_key=await decrypt_api_key_async(config.api_key) if config.api_key else None,
                base_url=config.base_url,
                extra_config=config.extra_config,
            )

        # 2. 再查找系统配置
        config = await self.repo.get_system_config(model_type, model)
        if config:
            return ModelCredentials(
                protocol=config.protocol,
                model=config.model,
                api_key=await decrypt_api_key_async(config.api_key) if config.api_key else None,
                base_url=config.base_url,
                extra_config=config.extra_config,
            )

        # 3. 未找到，返回 None
        logger.debug(
            "未找到模型配置",
            user_id=user_id,
            model_type=model_type,
            model=model,
        )
        return None

    async def list_available_models(
        self,
        user_id: int,
        model_type: str,
    ) -> List[str]:
        """
        获取用户可用的模型名称列表（用于前端下拉框）

        返回：系统模型 + 用户私有模型（去重）
        """
        models = set()

        # 1. 获取系统配置
        system_configs = await self.repo.list_system_configs(model_type)
        models.update(c.model for c in system_configs)

        # 2. 获取用户私有配置
        user_configs = await self.repo.list_by_user(user_id, model_type)
        models.update(c.model for c in user_configs)

        return sorted(list(models))

    # ========== 配置 CRUD ==========

    async def list_configs(
        self,
        user_id: int,
        model_type: Optional[str] = None
    ) -> ModelConfigListResponse:
        """获取用户的模型配置列表"""
        configs = await self.repo.list_by_user(user_id, model_type)
        total = await self.repo.count_by_user(user_id, model_type)

        items = [self._build_response(c) for c in configs]
        return ModelConfigListResponse(total=total, items=items)

    async def get_config(self, user_id: int, config_id: int) -> ModelConfigResponse:
        """获取单个配置"""
        config = await self.repo.get_by_id(config_id)

        if not config or config.user_id != user_id:
            raise ModelConfigNotFoundError(config_id)

        return self._build_response(config)

    async def create_config(
        self,
        data: ModelConfigCreate,
        user_id: Optional[int] = None,
    ) -> ModelConfigResponse:
        """创建模型配置"""
        # 检查是否已存在相同模型
        if user_id is None:
            # 系统配置（user_id=NULL）：唯一索引无效，需 Service 层校验
            existing = await self.repo.get_system_config(data.model_type, data.model)
        else:
            existing = await self.repo.get_by_user_and_model(
                user_id, data.model_type, data.model
            )
        if existing:
            raise ModelConfigAlreadyExistsError(data.model)

        # AES 加密 API Key 后存储（避免修改原始 Schema 对象）
        if data.api_key:
            data = data.model_copy(update={"api_key": await encrypt_api_key_async(data.api_key)})

        config = await self.repo.create(user_id, data)

        # 清除客户端缓存
        await self._clear_client_cache(user_id, data.model_type, data.model)

        logger.info(
            "用户模型配置已创建",
            user_id=user_id,
            config_id=config.id,
            model_type=data.model_type,
            model=config.model,
        )

        return self._build_response(config)

    async def update_config(
        self,
        user_id: int,
        config_id: int,
        data: ModelConfigUpdate
    ) -> ModelConfigResponse:
        """更新模型配置"""
        config = await self.repo.get_by_id(config_id)

        if not config or config.user_id != user_id:
            raise ModelConfigNotFoundError(config_id)

        # 如果要更新模型名称，检查是否重复
        if data.model is not None and data.model != config.model:
            existing = await self.repo.get_by_user_and_model(
                user_id,
                MODEL_TYPE_STR.get(ModelType(config.model_type), ""),
                data.model
            )
            if existing:
                raise ModelConfigAlreadyExistsError(data.model)

        old_model = config.model

        # AES 加密 API Key（如果更新了 api_key，避免修改原始 Schema 对象）
        if data.api_key is not None:
            data = data.model_copy(update={"api_key": await encrypt_api_key_async(data.api_key)})

        config = await self.repo.update(config, data)

        # 清除客户端缓存
        await self._clear_client_cache(
            user_id,
            MODEL_TYPE_STR.get(ModelType(config.model_type), ""),
            old_model
        )
        if data.model and data.model != old_model:
            await self._clear_client_cache(
                user_id,
                MODEL_TYPE_STR.get(ModelType(config.model_type), ""),
                data.model
            )

        logger.info(
            "用户模型配置已更新",
            user_id=user_id,
            config_id=config.id,
            model=config.model,
        )

        return self._build_response(config)

    async def delete_config(self, user_id: int, config_id: int) -> None:
        """删除模型配置"""
        config = await self.repo.get_by_id(config_id)

        if not config or config.user_id != user_id:
            raise ModelConfigNotFoundError(config_id)

        model_type = MODEL_TYPE_STR.get(ModelType(config.model_type), "")
        model = config.model

        await self.repo.delete(config_id)

        # 清除客户端缓存
        await self._clear_client_cache(user_id, model_type, model)

        logger.info("用户模型配置已删除", user_id=user_id, config_id=config_id)

    async def delete_config_with_check(
        self,
        user_id: int,
        config_id: int,
    ) -> tuple[bool, Optional[list[dict]]]:
        """带影响检查的删除配置

        Args:
            user_id: 用户 ID
            config_id: 配置 ID

        Returns:
            (deleted, impacts) 元组：
            - deleted: 是否执行了删除
            - impacts: 影响列表（非空表示有影响，未删除）

        Raises:
            ModelConfigNotFoundError: 配置不存在或不属于当前用户
        """
        config = await self.repo.get_by_id(config_id)
        if not config or config.user_id != user_id:
            raise ModelConfigNotFoundError(config_id)

        impacts = await self._check_delete_impact(config)
        if impacts:
            return False, impacts

        await self.delete_config(user_id, config_id)
        return True, None

    async def delete_config_by_model(
        self,
        user_id: int,
        model_type: str,
        model: str
    ) -> None:
        """根据模型类型和名称删除配置"""
        config = await self.repo.get_by_user_and_model(user_id, model_type, model)
        if not config:
            raise ModelConfigNotFoundError(message=f"{model_type}/{model} 不存在")

        await self.repo.delete(config.id)
        await self._clear_client_cache(user_id, model_type, model)

        logger.info(
            "用户模型配置已删除",
            user_id=user_id,
            model_type=model_type,
            model=model,
        )

    # ========== 客户端获取（支持凭证查找） ==========

    async def _get_client_by_model(
        self,
        user_id: int,
        model: str,
        model_type: str,
        create_from_credentials,
    ):
        """
        通用的客户端缓存查找 + 创建逻辑

        Args:
            user_id: 用户ID
            model: 模型名称
            model_type: 模型类型（llm/embedding/rerank）
            create_from_credentials: 从凭据创建客户端的回调函数

        Raises:
            ModelConfigNotFoundError: 未找到模型配置
        """
        global _client_cache
        cache_key = f"{user_id}:{model_type}:{model}"

        async with _cache_lock:
            await _cleanup_expired_cache()
            if cache_key in _client_cache:
                timestamp, client = _client_cache[cache_key]
                if time.time() - timestamp < _CACHE_TTL:
                    return client

            credentials = await self.get_credentials_by_model(user_id, model_type, model)

            if credentials:
                client = create_from_credentials(credentials)
            else:
                raise ModelConfigNotFoundError(message=f"{model_type}/{model} 不存在")

            # 写入缓存前检查容量上限，淘汰最旧条目
            if len(_client_cache) >= _MAX_CACHE_SIZE:
                await _cleanup_expired_cache()
                if len(_client_cache) >= _MAX_CACHE_SIZE:
                    oldest_key = min(_client_cache, key=lambda k: _client_cache[k][0])
                    old_ts, old_client = _client_cache[oldest_key]
                    if hasattr(old_client, 'aclose'):
                        try:
                            await old_client.aclose()
                        except Exception:
                            pass
                    del _client_cache[oldest_key]

            _client_cache[cache_key] = (time.time(), client)
            return client

    async def get_llm_client_by_model(
        self,
        user_id: int,
        model: str
    ) -> BaseLLM:
        """根据模型名称获取 LLM 客户端"""
        return await self._get_client_by_model(
            user_id, model, "llm",
            create_from_credentials=lambda c: create_llm_client(
                protocol=c.protocol,
                api_key=c.api_key or "",
                base_url=c.base_url or "",
                model_name=c.model,
                timeout=(c.extra_config or {}).get("timeout", 120),
                max_retries=(c.extra_config or {}).get("max_retries", 3),
                max_concurrent=(c.extra_config or {}).get("max_concurrent", 5),
            ),
        )

    async def get_embedding_client_by_model(
        self,
        user_id: int,
        model: str
    ) -> BaseEmbedding:
        """根据模型名称获取 Embedding 客户端"""
        return await self._get_client_by_model(
            user_id, model, "embedding",
            create_from_credentials=lambda c: create_embedding_client(
                protocol=c.protocol,
                api_key=c.api_key or "",
                base_url=c.base_url or "",
                model_name=c.model,
                expected_dimension=(c.extra_config or {}).get("dimension"),
                timeout=(c.extra_config or {}).get("timeout", 60),
                max_retries=(c.extra_config or {}).get("max_retries", 3),
                max_concurrent=(c.extra_config or {}).get("max_concurrent", 5),
            ),
        )

    async def get_rerank_client_by_model(
        self,
        user_id: int,
        model: str
    ) -> BaseRerank:
        """根据模型名称获取 Rerank 客户端"""
        return await self._get_client_by_model(
            user_id, model, "rerank",
            create_from_credentials=lambda c: create_rerank_client(
                protocol=c.protocol,
                api_key=c.api_key or "",
                base_url=c.base_url or "",
                model_name=c.model,
                timeout=(c.extra_config or {}).get("timeout", 30),
                max_retries=(c.extra_config or {}).get("max_retries", 3),
            ),
        )

    # ========== 连接测试 ==========

    async def test_connection(
        self,
        user_id: int,
        request: ModelTestRequest
    ) -> ModelTestResponse:
        """测试模型连接"""
        start_time = time.time()

        try:
            detected_dimension = None
            if request.model_type == "llm":
                await self._test_llm(request)
            elif request.model_type == "embedding":
                detected_dimension = await self._test_embedding(request)
            elif request.model_type == "rerank":
                await self._test_rerank(request)

            latency = (time.time() - start_time) * 1000

            logger.info(
                "模型连接测试成功",
                user_id=user_id,
                model_type=request.model_type,
                model=request.model,
                latency_ms=round(latency, 2),
                detected_dimension=detected_dimension,
            )

            return ModelTestResponse(
                success=True,
                message="连接成功",
                latency_ms=round(latency, 2),
                detected_dimension=detected_dimension,
            )

        except Exception as e:
            latency = (time.time() - start_time) * 1000
            error_msg = str(e)

            logger.warning(
                "模型连接测试失败",
                user_id=user_id,
                model_type=request.model_type,
                model=request.model,
                error=error_msg,
            )

            raise ModelConfigTestFailedError(request.model_type, error_msg)

    async def _test_llm(self, request: ModelTestRequest) -> None:
        """测试 LLM 连接"""
        client = create_llm_client(
            protocol=request.protocol,
            api_key=request.api_key,
            base_url=request.base_url or "",
            model_name=request.model,
        )
        await client.generate_text(prompt="Hello", max_tokens=10, temperature=0.1)

    async def _test_embedding(self, request: ModelTestRequest) -> int:
        """测试 Embedding 连接，返回检测到的维度"""
        client = create_embedding_client(
            protocol=request.protocol,
            api_key=request.api_key,
            base_url=request.base_url or "",
            model_name=request.model,
        )
        embedding = await client.generate_embedding("Hello")
        return len(embedding)

    async def _detect_embedding_dimension(
        self,
        protocol: str,
        api_key: str,
        base_url: str,
        model_name: str,
        fallback: Optional[int] = None,
    ) -> Optional[int]:
        """
        调用 Embedding 模型 API 自动检测向量维度

        Args:
            protocol: 通信协议
            api_key: API Key
            base_url: Base URL
            model_name: 模型名称
            fallback: YAML 中配置的维度（可选兜底值）

        Returns:
            检测到的维度，失败时返回 fallback
        """
        try:
            client = create_embedding_client(
                protocol=protocol,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
            )
            vector = await client.generate_embedding("test")
            dim = len(vector)
            logger.info("自动检测 Embedding 维度", model=model_name, dimension=dim)
            return dim
        except Exception as e:
            logger.warning(
                "Embedding 维度自动检测失败，使用 fallback",
                model=model_name,
                fallback=fallback,
                error=str(e),
            )
            return fallback

    async def _test_rerank(self, request: ModelTestRequest) -> None:
        """测试 Rerank 连接"""
        client = create_rerank_client(
            protocol=request.protocol,
            api_key=request.api_key,
            base_url=request.base_url or "",
            model_name=request.model,
        )
        await client.rerank(query="test", documents=["Hello", "World"])

    # ========== 系统配置同步 ==========

    async def sync_system_configs_from_yaml(self) -> Dict[str, Any]:
        """
        从 YAML 配置同步系统模型凭证到数据库

        全量覆盖系统配置，不影响用户配置。
        每个模型条目独立携带 api_key/base_url。

        Returns:
            同步结果统计
        """
        yaml_config = get_config()
        model_configs = getattr(yaml_config, "model_configs", None)

        if not model_configs:
            logger.warning("YAML 中未找到 model_configs 配置，跳过同步")
            return {}

        result = {}
        yaml_models = {}  # 记录 YAML 中出现的所有系统模型

        for model_type in ["llm", "embedding", "rerank"]:
            configs = getattr(model_configs, model_type, [])
            if not configs:
                continue

            type_result = {"created": 0, "updated": 0, "deleted": 0}
            yaml_models[model_type] = set()

            for item in configs:
                model = item.model
                yaml_models[model_type].add(model)

                # 构建 extra_config
                extra_config = {}
                if item.timeout != 60:
                    extra_config["timeout"] = item.timeout
                if item.max_retries != 3:
                    extra_config["max_retries"] = item.max_retries
                if item.max_concurrent != 5:
                    extra_config["max_concurrent"] = item.max_concurrent

                # Embedding 模型：自动检测 dimension
                if model_type == "embedding":
                    detected_dim = await self._detect_embedding_dimension(
                        protocol=item.protocol,
                        api_key=item.api_key,
                        base_url=item.base_url,
                        model_name=model,
                        fallback=item.dimension,
                    )
                    if detected_dim is not None:
                        extra_config["dimension"] = detected_dim

                if not extra_config:
                    extra_config = None

                # AES 加密 API Key
                encrypted_api_key = await encrypt_api_key_async(item.api_key) if item.api_key else None

                existing = await self.repo.get_system_config(model_type, model)

                if existing:
                    # 全量覆盖
                    await self.repo.update_system_config(
                        model_type,
                        model,
                        protocol=item.protocol,
                        base_url=item.base_url,
                        api_key=encrypted_api_key,
                        extra_config=extra_config,
                    )
                    type_result["updated"] += 1
                else:
                    # 新增
                    await self.repo.create_system_config(
                        model_type=model_type,
                        protocol=item.protocol,
                        model=model,
                        api_key=encrypted_api_key,
                        base_url=item.base_url,
                        extra_config=extra_config,
                    )
                    type_result["created"] += 1

            result[model_type] = type_result

        # 删除 YAML 中已无但数据库中存在的系统配置
        for model_type, yaml_model_set in yaml_models.items():
            db_system_configs = await self.repo.list_system_configs(model_type)
            for db_config in db_system_configs:
                if db_config.model not in yaml_model_set:
                    await self.repo.delete(db_config.id)
                    result[model_type]["deleted"] += 1
                    logger.info(
                        "已删除YAML中不存在的系统模型配置",
                        model_type=model_type,
                        model=db_config.model,
                    )

        # 清除所有系统配置相关的客户端缓存
        await self._clear_all_system_cache()

        logger.info("系统模型凭证同步完成", result=result)
        return result

    async def _clear_all_system_cache(self) -> None:
        """清除所有系统配置相关的客户端缓存"""
        global _client_cache
        async with _cache_lock:
            # 系统配置的 user_id 为 None，缓存 key 中 user_id 部分为 "None" 字符串
            keys_to_remove = [k for k in _client_cache if k.startswith("None:")]
            for k in keys_to_remove:
                del _client_cache[k]
            if keys_to_remove:
                logger.debug("已清除系统配置客户端缓存", count=len(keys_to_remove))

    # ========== 辅助方法 ==========

    def _build_response(self, config: UserModelConfig) -> ModelConfigResponse:
        """构建配置响应"""
        model_type_str = MODEL_TYPE_STR.get(ModelType(config.model_type), "unknown")

        return ModelConfigResponse(
            id=config.id,
            user_id=config.user_id,
            model_type=model_type_str,
            protocol=config.protocol,
            model=config.model,
            base_url=config.base_url,
            api_key="****" if config.api_key else "",
            extra_config=config.extra_config,
            is_system=config.is_system_config,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

    async def _clear_client_cache(
        self,
        user_id: int,
        model_type: str,
        model: str
    ) -> None:
        """清除指定模型的客户端缓存（使用全局缓存）"""
        await _clear_client_cache_global(user_id, model_type, model)

    async def list_available_models_with_info(
        self,
        user_id: int
    ) -> "AvailableModelsWithInfoResponse":
        """获取可用模型的详细信息"""
        from src.features.user.schemas.model_config_schema import (
            ModelInfo,
            AvailableModelsWithInfoResponse,
        )

        result = AvailableModelsWithInfoResponse()

        for model_type in ["llm", "embedding", "rerank"]:
            configs = await self.repo.list_available_configs(user_id, model_type)
            seen = set()
            infos = []

            for config in configs:
                if config.model not in seen:
                    seen.add(config.model)
                    infos.append(ModelInfo(
                        model=config.model,
                        protocol=config.protocol,
                        is_system=config.is_system_config,
                    ))

            setattr(result, model_type, infos)

        return result

    # ========== 默认模型动态获取 ==========

    async def get_default_model_name(self, model_type: str) -> Optional[str]:
        """
        获取系统默认模型名称

        从数据库查询 user_id=NULL 且对应 model_type 的第一条记录。
        如果无系统配置，返回 None。

        Args:
            model_type: 模型类型 (llm/embedding/rerank)

        Returns:
            模型名称或 None
        """
        configs = await self.repo.list_system_configs(model_type)
        if configs:
            return configs[0].model
        return None

    # ========== 删除影响检查 ==========

    async def _check_delete_impact(
        self,
        config: UserModelConfig,
    ) -> List[Dict[str, Any]]:
        """
        检查删除模型配置的影响

        Args:
            config: 要删除的模型配置

        Returns:
            影响列表（空列表表示无影响，可安全删除）
        """
        impacts = []
        model_type = ModelType(config.model_type)

        if model_type == ModelType.EMBEDDING:
            # 检查空间绑定（Embedding 配置由空间级别统一管理）
            try:
                from src.features.knowledge_space.models.knowledge_space import KnowledgeSpace

                stmt = select(
                    KnowledgeSpace.id, KnowledgeSpace.name, KnowledgeSpace.config
                ).where(KnowledgeSpace.deleted_at.is_(None))
                result = await self.db.execute(stmt)
                all_spaces = result.all()

                for space_id, space_name, space_config in all_spaces:
                    space_config = space_config or {}
                    embedding_model = (space_config.get("embedding") or {}).get("model")
                    if embedding_model == config.model:
                        impacts.append({
                            "type": "space",
                            "id": space_id,
                            "name": space_name,
                            "reason": f"空间 '{space_name}' 正在使用此 Embedding 模型",
                        })
            except Exception as e:
                logger.error("检查删除影响失败，可能返回不完整结果", error=str(e))

        elif model_type == ModelType.LLM:
            # LLM 模型仅警告，不阻止删除（会话使用已缓存客户端）
            logger.info(
                "删除 LLM 模型配置",
                model=config.model,
                note="活跃会话可能仍在使用此模型",
            )

        return impacts
