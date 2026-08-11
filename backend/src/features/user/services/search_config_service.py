"""
用户搜索配置服务

核心职责：
1. 搜索配置 CRUD（加密入库 / 解密读取 / 脱敏响应）
2. 实现 ``shared.search_config_ports.SearchConfigPort``：``get_primary_search_config``
   返回解密后凭证，供宿主构造 ``WebSearchPort``
3. 搜索连接测试（调 ``engines.build_web_search_port_from_provider`` 实搜验证）

加密：复用 ``shared/utils/crypto.py`` 的 ``encrypt_api_key_async`` /
``decrypt_api_key_async``（AES-256-GCM + HKDF-SHA256），与模型配置同套机制。
"""
import time
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.user.models.user_search_config import UserSearchConfig
from novamind.features.user.repository.search_config_repository import SearchConfigRepository
from novamind.features.user.schemas.search_config_schema import (
    SearchConfigCreate,
    SearchConfigUpdate,
    SearchConfigResponse,
    SearchConfigListResponse,
    SearchTestRequest,
    SearchTestResponse,
)
from novamind.shared.search_config_ports import SearchCredentials
from novamind.shared.utils.crypto import encrypt_api_key_async, decrypt_api_key_async
from novamind.engines.search_ports import build_web_search_port_from_provider
from novamind.engines.search_errors import (
    WebSearchError,
    WebSearchProviderNotConfiguredError,
)
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.user.exceptions import (
    SearchConfigNotFoundError,
    SearchConfigAlreadyExistsError,
    SearchConfigTestFailedError,
)

logger = get_logger(__name__)


class SearchConfigService:
    """用户搜索配置服务。

    结构化满足 ``shared.search_config_ports.SearchConfigPort``（查询面
    ``get_primary_search_config``）；CRUD 面供路由层使用。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SearchConfigRepository(db)

    # ========== SearchConfigPort 实现 ==========

    async def get_primary_search_config(self, user_id: int) -> Optional[SearchCredentials]:
        """获取用户首选搜索凭证（解密后明文 api_key），供宿主构造 WebSearchPort。

        无首选配置返回 None（宿主降级到 YAML 全局配置，由 AIChatService 处理）。
        """
        config = await self.repo.get_primary(user_id)
        if not config:
            return None
        api_key = await decrypt_api_key_async(config.api_key) if config.api_key else None
        return SearchCredentials(
            provider=config.provider,
            api_key=api_key,
            extra_config=config.extra_config,
        )

    # ========== 配置 CRUD ==========

    async def list_configs(self, user_id: int) -> SearchConfigListResponse:
        """获取用户的搜索配置列表"""
        configs = await self.repo.list_by_user(user_id)
        total = await self.repo.count_by_user(user_id)
        items = [self._build_response(c) for c in configs]
        return SearchConfigListResponse(total=total, items=items)

    async def get_config(self, user_id: int, config_id: int) -> SearchConfigResponse:
        """获取单个配置（校验归属）"""
        config = await self.repo.get_by_id(config_id)
        if not config or config.user_id != user_id:
            raise SearchConfigNotFoundError(config_id)
        return self._build_response(config)

    async def create_config(
        self,
        data: SearchConfigCreate,
        user_id: int,
    ) -> SearchConfigResponse:
        """创建搜索配置"""
        # 同 user 同 provider 唯一
        existing = await self.repo.get_by_user_and_provider(user_id, data.provider)
        if existing:
            raise SearchConfigAlreadyExistsError(data.provider)

        # 设为首选时先清旧 primary（保证唯一 primary）
        if data.is_primary:
            await self.repo.clear_primary(user_id)

        # AES 加密 api_key（避免修改原始 Schema 对象）
        if data.api_key:
            data = data.model_copy(
                update={"api_key": await encrypt_api_key_async(data.api_key)}
            )

        config = await self.repo.create(user_id, data)
        logger.info(
            "用户搜索配置已创建",
            user_id=user_id,
            config_id=config.id,
            provider=config.provider,
            is_primary=config.is_primary,
        )
        return self._build_response(config)

    async def update_config(
        self,
        user_id: int,
        config_id: int,
        data: SearchConfigUpdate,
    ) -> SearchConfigResponse:
        """更新搜索配置

        api_key 留空（None）= 不改；显式传值则加密后覆盖。
        """
        config = await self.repo.get_by_id(config_id)
        if not config or config.user_id != user_id:
            raise SearchConfigNotFoundError(config_id)

        # 设为首选时先清旧 primary
        if data.is_primary:
            await self.repo.clear_primary(user_id)

        # api_key 非 None 则加密（None 表示不改，保留原密文）
        if data.api_key is not None:
            data = data.model_copy(
                update={"api_key": await encrypt_api_key_async(data.api_key)}
            )

        config = await self.repo.update(config, data)
        logger.info(
            "用户搜索配置已更新",
            user_id=user_id,
            config_id=config.id,
            provider=config.provider,
        )
        return self._build_response(config)

    async def set_primary(self, user_id: int, config_id: int) -> SearchConfigResponse:
        """将指定配置设为用户首选 provider（原子清旧 + 设新）"""
        config = await self.repo.get_by_id(config_id)
        if not config or config.user_id != user_id:
            raise SearchConfigNotFoundError(config_id)
        config = await self.repo.set_primary(user_id, config_id)
        if config is None:
            raise SearchConfigNotFoundError(config_id)
        logger.info(
            "用户搜索配置设为首选",
            user_id=user_id,
            config_id=config.id,
            provider=config.provider,
        )
        return self._build_response(config)

    async def delete_config(self, user_id: int, config_id: int) -> None:
        """删除搜索配置（校验归属）"""
        config = await self.repo.get_by_id(config_id)
        if not config or config.user_id != user_id:
            raise SearchConfigNotFoundError(config_id)
        await self.repo.delete(config_id)
        logger.info("用户搜索配置已删除", user_id=user_id, config_id=config_id)

    # ========== 连接测试 ==========

    async def test_connection(
        self,
        user_id: int,
        request: SearchTestRequest,
    ) -> SearchTestResponse:
        """测试搜索连接（用提交的凭据实搜一次，不入库）。

        调 ``engines.build_web_search_port_from_provider`` 构造端口后实搜 ``test``，
        验证 provider 凭证可用性。引擎中立异常映射为 ``SearchConfigTestFailedError``。
        """
        start = time.time()
        provider = request.provider

        try:
            port = build_web_search_port_from_provider(
                provider=provider,
                api_key=request.api_key,
                extra_config=request.extra_config,
            )
            results = await port.search("test", max_results=3)
            latency = (time.time() - start) * 1000
            await port.close()

            logger.info(
                "搜索连接测试成功",
                user_id=user_id,
                provider=provider,
                latency_ms=round(latency, 2),
                results_count=len(results),
            )
            return SearchTestResponse(
                success=True,
                message="连接成功",
                latency_ms=round(latency, 2),
                results_count=len(results),
            )
        except WebSearchProviderNotConfiguredError as e:
            raise SearchConfigTestFailedError(provider, str(e))
        except WebSearchError as e:
            raise SearchConfigTestFailedError(provider, str(e))
        except Exception as e:
            raise SearchConfigTestFailedError(provider, str(e))

    # ========== 辅助方法 ==========

    def _build_response(self, config: UserSearchConfig) -> SearchConfigResponse:
        """构建配置响应（api_key 脱敏，对齐 model_config _build_response 写法）"""
        return SearchConfigResponse(
            id=config.id,
            user_id=config.user_id,
            provider=config.provider,
            api_key="****" if config.api_key else "",
            extra_config=config.extra_config,
            is_primary=config.is_primary,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )