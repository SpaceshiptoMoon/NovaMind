"""
用户模型配置服务

核心职责：
1. 模型配置的 CRUD 操作
2. 根据模型名称获取对应的凭证（核心方法）
3. 模型连接测试
"""
import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novamind.features.user.models.user_model_config import UserModelConfig, ModelType
from novamind.features.user.repository.model_config_repository import (
    ModelConfigRepository, MODEL_TYPE_STR
)
from novamind.features.user.schemas.model_config_schema import (
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelConfigResponse,
    ModelConfigListResponse,
    ModelTestRequest,
    ModelTestResponse,
)
from novamind.shared.ai_models.llm import create_llm_client, BaseLLM
from novamind.shared.ai_models.embedding import create_embedding_client, BaseEmbedding
from novamind.shared.ai_models.rerank import create_rerank_client, BaseRerank
from novamind.shared.ai_models.base_model import PROXY_INHERIT

from novamind.shared.utils.crypto import encrypt_api_key_async, decrypt_api_key_async
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.user.api.exceptions import (
    ModelConfigNotFoundError,
    ModelConfigAlreadyExistsError,
    ModelConfigTestFailedError,
)


def _proxy_from_extra(extra_config: Optional[Dict[str, Any]]) -> Any:
    """从 extra_config 读取 proxy 配置。

    未配置（键不存在）时返回 PROXY_INHERIT 哨兵，表示继承环境变量代理；
    显式配置为 null / "" 时返回 None / ""，表示禁用代理；
    配置为字符串时作为代理 URL 使用。
    """
    return (extra_config or {}).get("proxy", PROXY_INHERIT)

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

        只查找用户配置，不再有系统配置降级。

        Args:
            user_id: 用户 ID
            model_type: 模型类型 (llm/embedding/rerank)
            model: 模型名称（如 gpt-4o）

        Returns:
            ModelCredentials 或 None
        """
        config = await self.repo.get_by_user_and_model(user_id, model_type, model)
        if config:
            return ModelCredentials(
                protocol=config.protocol,
                model=config.model,
                api_key=await decrypt_api_key_async(config.api_key) if config.api_key else None,
                base_url=config.base_url,
                extra_config=config.extra_config,
            )

        # 未找到，返回 None
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

        返回：用户自己配置的模型列表
        """
        configs = await self.repo.list_by_user(user_id, model_type)
        return sorted(list(set(c.model for c in configs)))

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
        user_id: int,
    ) -> ModelConfigResponse:
        """创建模型配置"""
        # 检查是否已存在相同模型
        existing = await self.repo.get_by_user_and_model(
            user_id, data.model_type, data.model
        )
        if existing:
            raise ModelConfigAlreadyExistsError(data.model)

        # 强制连接验证 —— 验证失败直接抛异常，不存 DB
        if data.api_key:
            await self._verify_model_connection(data)
            logger.info(
                "模型连接验证通过",
                model_type=data.model_type,
                model=data.model,
            )

        # embedding 类型：自动探测向量维度（需要明文 api_key）
        if data.model_type == "embedding" and data.api_key:
            detected_dim = await self._detect_embedding_dimension(
                protocol=data.protocol,
                api_key=data.api_key,
                base_url=data.base_url,
                model_name=data.model,
            )
            if detected_dim is None:
                raise ModelConfigTestFailedError(
                    data.model_type,
                    f"无法检测模型 {data.model} 的向量维度，请检查模型配置",
                )
            extra_config = dict(data.extra_config or {})
            extra_config["dimension"] = detected_dim
            data = data.model_copy(update={"extra_config": extra_config})
            logger.info(
                "自动探测到向量维度",
                model_type=data.model_type,
                model=data.model,
                dimension=detected_dim,
            )

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

        # 如果关键连接字段变更，强制重新验证连接
        if self._connection_fields_changed(data, config):
            effective_api_key = (
                data.api_key if data.api_key
                else await decrypt_api_key_async(config.api_key) if config.api_key
                else ""
            )
            verify_data = ModelConfigCreate(
                model_type=self._model_type_str(config.model_type),
                protocol=data.protocol or config.protocol,
                model=data.model or config.model,
                base_url=data.base_url if data.base_url is not None else config.base_url,
                api_key=effective_api_key,
            )
            await self._verify_model_connection(verify_data)
            logger.info(
                "更新时模型连接验证通过",
                model=verify_data.model,
            )

        # embedding 类型：model 或 base_url 变更时重新检测维度
        if ModelType(config.model_type) == ModelType.EMBEDDING:
            model_changed = data.model is not None and data.model != config.model
            url_changed = data.base_url is not None and data.base_url != config.base_url
            if model_changed or url_changed:
                # 解密后的明文 api_key 用于调用 embedding API 检测维度
                raw_api_key = data.api_key if data.api_key else await decrypt_api_key_async(config.api_key)
                effective_url = data.base_url or config.base_url
                effective_model = data.model or config.model
                try:
                    detected_dim = await self._detect_embedding_dimension(
                        protocol=config.protocol,
                        api_key=raw_api_key,
                        base_url=effective_url,
                        model_name=effective_model,
                    )
                    if detected_dim is not None:
                        extra_config = dict(data.extra_config or config.extra_config or {})
                        extra_config["dimension"] = detected_dim
                        data = data.model_copy(update={"extra_config": extra_config})
                        logger.info(
                            "更新时重新检测到向量维度",
                            model=effective_model,
                            dimension=detected_dim,
                        )
                except Exception as e:
                    logger.warning(
                        "更新时维度检测失败，保留原值",
                        model=effective_model,
                        error=str(e),
                    )

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
                proxy=_proxy_from_extra(c.extra_config),
            ),
        )

    async def get_vlm_client_by_model(
        self,
        user_id: int,
        model: str
    ) -> BaseLLM:
        """根据模型名称获取 VLM 客户端（复用 LLM 工厂）"""
        return await self._get_client_by_model(
            user_id, model, "vlm",
            create_from_credentials=lambda c: create_llm_client(
                protocol=c.protocol,
                api_key=c.api_key or "",
                base_url=c.base_url or "",
                model_name=c.model,
                timeout=(c.extra_config or {}).get("timeout", 120),
                max_retries=(c.extra_config or {}).get("max_retries", 3),
                max_concurrent=(c.extra_config or {}).get("max_concurrent", 5),
                proxy=_proxy_from_extra(c.extra_config),
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
                proxy=_proxy_from_extra(c.extra_config),
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

    # ========== 连接验证 & 测试 ==========

    async def _verify_model_connection(self, data: ModelConfigCreate) -> None:
        """
        创建/更新前强制验证模型连接，失败则抛 ModelConfigTestFailedError

        复用已有的 _test_llm / _test_embedding / _test_rerank 方法。
        """
        request = ModelTestRequest(
            model_type=data.model_type,
            protocol=data.protocol,
            model=data.model,
            base_url=data.base_url,
            api_key=data.api_key,
            proxy=_proxy_from_extra(data.extra_config),
        )

        try:
            if data.model_type in ("llm", "vlm"):
                await self._test_llm(request)
            elif data.model_type == "embedding":
                await self._test_embedding(request)
            elif data.model_type == "rerank":
                await self._test_rerank(request)
            elif data.model_type == "asr":
                await self._test_asr(request)
        except Exception as e:
            raise ModelConfigTestFailedError(data.model_type, str(e)) from e

    @staticmethod
    def _connection_fields_changed(data: ModelConfigUpdate, config: "UserModelConfig") -> bool:
        """检查是否有关键连接字段（model/base_url/api_key/protocol）变更"""
        key_changed = data.api_key is not None
        model_changed = data.model is not None and data.model != config.model
        url_changed = data.base_url is not None and data.base_url != config.base_url
        protocol_changed = data.protocol is not None and data.protocol != config.protocol
        return key_changed or model_changed or url_changed or protocol_changed

    @staticmethod
    def _model_type_str(model_type_int: int) -> str:
        """ModelType 整数 → 字符串"""
        mapping = {
            ModelType.LLM: "llm",
            ModelType.EMBEDDING: "embedding",
            ModelType.RERANK: "rerank",
            ModelType.VLM: "vlm",
            ModelType.ASR: "asr",
        }
        return mapping.get(model_type_int, "llm")

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
            elif request.model_type == "vlm":
                await self._test_llm(request)
            elif request.model_type == "asr":
                await self._test_asr(request)

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
            proxy=request.proxy,
        )
        # 某些模型（如 qwen3）强制要求 enable_thinking=True，测试时默认开启
        try:
            await client.generate_text(prompt="Hello", max_tokens=10, temperature=0.1)
        except Exception as e:
            error_msg = str(e)
            if "enable_thinking" in error_msg.lower():
                await client.generate_text(prompt="Hello", max_tokens=10, temperature=0.1, enable_thinking=True)
            else:
                raise

    async def _test_embedding(self, request: ModelTestRequest) -> int:
        """测试 Embedding 连接，返回检测到的维度"""
        client = create_embedding_client(
            protocol=request.protocol,
            api_key=request.api_key,
            base_url=request.base_url or "",
            model_name=request.model,
            proxy=request.proxy,
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

    async def _test_asr(self, request: ModelTestRequest) -> None:
        """测试 ASR 连接（按协议路由：local / openai / dashscope）"""
        protocol = request.protocol or "openai"
        if protocol == "local":
            await self._test_asr_local(request)
        elif protocol == "dashscope":
            await self._test_asr_dashscope(request)
        else:
            await self._test_asr_openai(request)

    async def _test_asr_local(self, request: ModelTestRequest) -> None:
        """测试本地 ASR 模型是否可用（检查模型文件完整性）"""
        from pathlib import Path

        # 模型路径与 media_utils._get_local_whisper_model 一致
        model_dir = Path(__file__).resolve().parent.parent.parent.parent.parent / "models" / "faster-whisper" / "tiny"

        if not model_dir.exists():
            raise ValueError(
                f"本地 ASR 模型目录不存在: {model_dir}，"
                f"请先下载 faster-whisper tiny 模型到 backend/models/faster-whisper/tiny/"
            )

        required_files = ["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"]
        missing = [f for f in required_files if not (model_dir / f).exists()]
        if missing:
            raise ValueError(
                f"本地 ASR 模型文件缺失: {missing}，"
                f"模型目录: {model_dir}"
            )

        # 快速验证模型可以加载（不执行实际推理）
        try:
            from faster_whisper import WhisperModel
            import asyncio
            model = await asyncio.to_thread(
                WhisperModel,
                str(model_dir),
                device="cpu",
                compute_type="int8",
                local_files_only=True,
            )
            del model
        except Exception as e:
            raise ValueError(f"本地 ASR 模型加载失败: {e}") from e

    async def _test_asr_openai(self, request: ModelTestRequest) -> None:
        """测试 ASR 连接（OpenAI Whisper API）"""
        import httpx
        import io
        import struct

        # 生成最小有效 WAV：0.1 秒 8000Hz 16-bit 单声道静音
        sample_rate = 8000
        duration = 0.1  # 秒
        num_samples = int(sample_rate * duration)
        pcm_data = b"\x00\x00" * num_samples  # 静音

        wav = io.BytesIO()
        wav.write(b"RIFF")
        wav.write(struct.pack("<I", 36 + len(pcm_data)))
        wav.write(b"WAVE")
        wav.write(b"fmt ")
        wav.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate,
                              sample_rate * 2, 2, 16))
        wav.write(b"data")
        wav.write(struct.pack("<I", len(pcm_data)))
        wav.write(pcm_data)
        test_wav = wav.getvalue()

        base_url = (request.base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {request.api_key}",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                headers=headers,
                data={"model": request.model, "response_format": "json"},
                files={"file": ("test.wav", test_wav, "audio/wav")},
            )
            if resp.status_code == 401:
                raise ValueError("ASR API Key 无效（401）")
            if resp.status_code == 403:
                raise ValueError("ASR API Key 无权限（403）")
            if resp.status_code >= 500:
                raise ValueError(f"ASR 服务端错误（{resp.status_code}）")
            # 2xx 或 4xx（模型不存在等）均视为连接可达

    async def _test_asr_dashscope(self, request: ModelTestRequest) -> None:
        """测试 ASR 连接（DashScope Paraformer API，HTTP URL → async_call → wait）"""
        from http import HTTPStatus
        import dashscope
        from dashscope.audio.asr import Transcription

        if request.api_key:
            dashscope.api_key = request.api_key

        # 百炼平台需要设置 workspace 级别的 base URL
        if request.base_url:
            url = request.base_url.rstrip("/")
            # 去掉用户误填的兼容模式路径（/compatible-mode/v1 → OpenAI 协议用的）
            if url.endswith("/compatible-mode/v1"):
                url = url[:-len("/compatible-mode/v1")]
            if not url.endswith("/api/v1"):
                url += "/api/v1"
            dashscope.base_http_api_url = url

        # 使用 DashScope 官方示例音频（公开 HTTP URL，与生产路径一致）
        sample_url = "https://dashscope.oss-cn-beijing.aliyuncs.com/samples/audio/paraformer/hello_world_female2.wav"

        # 提交转写任务
        task_response = Transcription.async_call(
            model=request.model,
            file_urls=[sample_url],
            language_hints=["zh", "en"],
        )

        if task_response.output is None:
            raise ValueError(
                f"DashScope 转写任务提交失败: status={task_response.status_code}, "
                f"message={getattr(task_response, 'message', 'unknown')}"
            )

        if task_response.status_code != HTTPStatus.OK:
            raise ValueError(
                f"DashScope 转写任务提交失败: status={task_response.status_code}, "
                f"message={getattr(task_response, 'message', 'unknown')}"
            )

        # 等待转写完成（验证真实可用性，而非仅提交成功）
        transcribe_response = Transcription.wait(task=task_response.output.task_id)

        if transcribe_response.status_code != HTTPStatus.OK:
            raise ValueError(
                f"DashScope 转写失败: status={transcribe_response.status_code}, "
                f"message={getattr(transcribe_response, 'message', 'unknown')}"
            )
        # 转写成功 = 连接可达

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
        from novamind.features.user.schemas.model_config_schema import (
            ModelInfo,
            AvailableModelsWithInfoResponse,
        )

        result = AvailableModelsWithInfoResponse()

        for model_type in ["llm", "embedding", "rerank", "vlm", "asr"]:
            configs = await self.repo.list_by_user(user_id, model_type)
            seen = set()
            infos = []

            for config in configs:
                if config.model not in seen:
                    seen.add(config.model)
                    infos.append(ModelInfo(
                        model=config.model,
                        protocol=config.protocol,
                    ))

            setattr(result, model_type, infos)

        return result

    # ========== 默认模型动态获取 ==========

    async def get_user_default_model_name(self, user_id: int, model_type: str) -> Optional[str]:
        """
        获取用户在指定类型下配置的第一个模型名（作为用户默认）

        Args:
            user_id: 用户ID
            model_type: 模型类型 (llm/embedding/rerank/vlm/asr)

        Returns:
            模型名称或 None
        """
        configs = await self.repo.list_by_user(user_id, model_type)
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
                from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace

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
