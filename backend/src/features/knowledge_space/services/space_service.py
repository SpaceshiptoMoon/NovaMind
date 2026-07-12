"""
空间管理服务

处理知识空间的创建、更新、删除等操作
支持多租户和 RBAC 权限控制
"""

from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
from novamind.features.knowledge_space.models.space_member import SpaceRole
from novamind.features.knowledge_space.repository.space_repository import SpaceRepository
from novamind.features.knowledge_space.repository.member_repository import MemberRepository
from novamind.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.audit_repository import AuditRepository
from novamind.features.knowledge_space.services.permission_service import PermissionService
from novamind.features.knowledge_space.api.exceptions import (
    SpaceNotFoundError,
    SpaceAlreadyExistsError,
    SpaceAccessDeniedError,
    KnowledgeSpaceError,
    InvalidParameterError,
)
from novamind.shared.storage.elasticsearch_client import ElasticsearchClient
from novamind.shared.storage.minio_client import MinioClient
from novamind.core.middleware.structured_logging import get_logger
from novamind.setting.yaml_config import get_config
from novamind.features.user.services.model_config_service import ModelConfigService

def _resolve_model_type(modalities=None) -> str:
    """决定嵌入模型类型，统一用 embedding"""
    return "embedding"


class SpaceService:
    """
    知识空间管理服务

    处理知识空间的生命周期管理
    支持多租户和 RBAC 权限控制
    """

    def __init__(
        self,
        session: AsyncSession,
        es_client: ElasticsearchClient = None,
        minio_client: MinioClient = None,
        model_config_service: Optional[ModelConfigService] = None,
    ):
        self.session = session
        self.space_repo = SpaceRepository(session)
        self.member_repo = MemberRepository(session)
        self.kb_repo = KnowledgeBaseRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.permission_service = PermissionService()
        self.es_client = es_client
        self.minio_client = minio_client
        self.model_config_service = model_config_service
        self.logger = get_logger(__name__)

    async def _get_embedding_dimension(
        self,
        model_name: str,
        owner_id: int,
        fallback: Optional[int] = None,
        model_type: str = "embedding",
    ) -> Optional[int]:
        """
        从数据库模型配置表读取 Embedding 模型的检测维度

        Args:
            model_name: Embedding 模型名称
            owner_id: 空间创建者 ID
            fallback: 兜底维度
            model_type: 模型类型

        Returns:
            模型维度，失败时返回 fallback
        """
        if not self.model_config_service:
            self.logger.warning(
                "ModelConfigService 未注入，使用 fallback 维度",
                fallback=fallback,
            )
            return fallback

        try:
            credentials = await self.model_config_service.get_credentials_by_model(
                owner_id, model_type, model_name
            )
            if credentials and credentials.extra_config:
                dimension = credentials.extra_config.get("dimension")
                if dimension:
                    self.logger.info(
                        "从模型配置表读取 Embedding 维度",
                        model=model_name,
                        dimension=dimension,
                    )
                    return dimension
            self.logger.warning(
                "模型配置表中未找到维度信息",
                model=model_name,
                fallback=fallback,
            )
            return fallback
        except Exception as e:
            self.logger.warning(
                "读取模型配置表维度失败",
                model=model_name,
                fallback=fallback,
                error=str(e),
            )
            return fallback

    async def create_space(
        self,
        name: str,
        owner_id: int,
        visibility: int = 0,
        config: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeSpace:
        """
        创建知识空间

        Args:
            name: 空间名称
            owner_id: 创建者 ID
            visibility: 可见性 (0-私有, 1-团队, 2-公开)
            config: 空间配置

        Returns:
            创建的知识空间

        Raises:
            SpaceAlreadyExistsError: 空间名称已存在
        """
        # 1. 检查是否已存在同名空间
        existing = await self.space_repo.get_by_name(name)
        if existing:
            raise SpaceAlreadyExistsError(name)

        # 2. 使用嵌套事务（savepoint）包裹创建空间和添加成员操作
        async with self.session.begin_nested():
            # 创建空间记录
            space = await self.space_repo.create({
                "name": name,
                "owner_id": owner_id,
                "visibility": visibility,
                "config": config or {},
            })

            # 添加创建者为空间所有者成员
            await self.member_repo.add_member(
                space_id=space.id,
                user_id=owner_id,
                role=SpaceRole.ADMIN,  # 创建者为管理员
                invited_by=owner_id,
            )

        # 3. 自动填充默认 Embedding 模型（如果用户未指定）
        embedding_model_name = space.embedding_model
        if not embedding_model_name and self.model_config_service:
            model_type = _resolve_model_type()
            available_models = await self.model_config_service.list_available_models(
                owner_id, model_type,
            )
            if available_models:
                default_model = available_models[0]
                space_config = space.get_config()
                space_config["embedding"] = {
                    "model": default_model,
                    "batch_size": 32,
                    "normalize": True,
                }
                space.config = space_config
                flag_modified(space, "config")
                embedding_model_name = default_model
                self.logger.info(
                    "自动填充默认 Embedding 模型",
                    model=default_model,
                    owner_id=owner_id,
                )
                await self.session.flush()

        # 4. 自动回填 Embedding 维度（从模型配置表读取）
        if embedding_model_name:
            dim_model_type = _resolve_model_type()
            embedding_dim = await self._get_embedding_dimension(
                model_name=embedding_model_name,
                owner_id=owner_id,
                model_type=dim_model_type,
            )
            if embedding_dim:
                self._write_embedding_dimension(space, embedding_dim)
                self.logger.info(
                    "自动回填 Embedding 维度",
                    model=embedding_model_name,
                    dimension=embedding_dim,
                )
                await self.session.flush()

        # 5. 创建 ES 空间索引（在 commit 之前，失败则整个事务回滚）
        if self.es_client:
            embedding_dim = space.embedding_dimension
            model_type = _resolve_model_type()

            # 从模型配置表重新查询维度（确保拿到真实值）
            if not embedding_dim and embedding_model_name and self.model_config_service:
                embedding_dim = await self._get_embedding_dimension(
                    model_name=embedding_model_name,
                    owner_id=owner_id,
                    model_type=model_type,
                )
                # 查到了就回写到 space config
                if embedding_dim:
                    self._write_embedding_dimension(space, embedding_dim)
                    await self.session.flush()

            # 最终兜底：使用 YAML 配置的默认维度
            if not embedding_dim:
                embedding_dim = self.es_client.default_embedding_dim

            try:
                create_kwargs = self._build_es_create_kwargs(space.id, embedding_dim)
                await self.es_client.create_index(**create_kwargs)
                self.logger.info(
                    "ES 空间索引创建成功",
                    space_id=space.id,
                    embedding_dim=embedding_dim,
                    embedding_model=embedding_model_name,
                )
            except Exception as e:
                self.logger.error(
                    "ES 空间索引创建失败，数据库事务将回滚",
                    space_id=space.id,
                    error=str(e),
                )
                raise

        await self.session.commit()

        self.logger.info(
            "知识空间创建成功",
            space_id=space.id,
            space_name=name,
            owner_id=owner_id,
        )

        return space

    async def delete_space(
        self,
        space_id: int,
        user_id: int,
    ) -> bool:
        """
        删除知识空间（软删除）

        权限检查已在路由层依赖注入中完成，此处仅做业务规则校验。

        owner_id 的特殊地位说明：
        - owner_id 是空间创建者，拥有不可撤销的最高权限
        - 删除空间需要 ADMIN 角色，路由层已确保操作者是空间管理员
        - owner 状态检查：如果 owner 已被停用，仅允许 ADMIN 角色执行删除

        Args:
            space_id: 空间 ID
            user_id: 操作用户 ID

        Returns:
            是否成功

        Raises:
            SpaceAccessDeniedError: owner 已停用且操作者非 ADMIN
            SpaceNotFoundError: 空间不存在
        """
        # 1. 获取空间信息
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise SpaceNotFoundError(space_id)

        # 权限检查已在路由层依赖注入中完成（AdminMemberRequired），
        # 此处不再重复查询成员记录和权限校验

        # 2. 检查 owner 是否仍为 ACTIVE 状态（防御性校验）
        owner_member = await self.member_repo.get_by_space_and_user(space_id, space.owner_id)
        if owner_member and not owner_member.is_active():
            # owner 已被停用，检查操作者是否为 ADMIN
            operator_member = await self.member_repo.get_by_space_and_user(space_id, user_id)
            if not operator_member or operator_member.role != SpaceRole.ADMIN:
                raise SpaceAccessDeniedError(
                    space_id, user_id,
                    "空间创建者已停用，需要管理员权限才能删除空间",
                )

        # 3. 获取关联知识库列表（在软删除之前，确保查询到未删除的 KB）
        kbs = await self.kb_repo.get_by_space(space_id)

        # 4. 级联软删除：空间、关联知识库、文档（使用 SAVEPOINT 保证原子性）
        async with self.session.begin_nested():
            for kb in kbs:
                kb.soft_delete()
                await self.doc_repo.delete_by_kb(kb.id)
            await self.space_repo.soft_delete(space_id)

            # 4.1 清理成员记录
            deleted_members = await self.member_repo.delete_by_space(space_id)
            self.logger.info("清理空间成员记录", space_id=space_id, deleted_count=deleted_members)

            # 4.2 清理审计日志
            audit_repo = AuditRepository(self.session)
            deleted_logs = await audit_repo.delete_by_space(space_id)
            self.logger.info("清理空间审计日志", space_id=space_id, deleted_count=deleted_logs)

        await self.session.commit()

        # 5. 清理检索缓存
        await self.space_repo.invalidate_space_cache(space_id)

        # 6. 异步清理 ES 空间索引（不阻塞主事务）
        if self.es_client:
            try:
                await self.es_client.delete_index(space_id)
                self.logger.info("ES 空间索引删除成功", space_id=space_id)
            except Exception as e:
                self.logger.warning(
                    "ES 空间索引删除失败，需要后台清理",
                    space_id=space_id,
                    error=str(e),
                )

        # 7. 清理 MinIO 文件
        if self.minio_client:
            try:
                deleted_count = await self.minio_client.delete_space_documents(
                    space_id=space_id,
                )
                self.logger.info(
                    "删除空间文件成功",
                    space_id=space_id,
                    deleted_count=deleted_count,
                )
            except Exception as e:
                self.logger.error(
                    "删除空间文件失败",
                    space_id=space_id,
                    error=str(e),
                )

        self.logger.info(
            "知识空间删除成功",
            space_id=space_id,
            user_id=user_id,
        )

        return True

    async def get_space(
        self,
        space_id: int,
    ) -> Optional[KnowledgeSpace]:
        """
        获取空间信息

        Args:
            space_id: 空间 ID

        Returns:
            知识空间或 None
        """
        return await self.space_repo.get_by_id(space_id)

    async def update_space(
        self,
        space_id: int,
        user_id: int,
        data: Dict[str, Any],
    ) -> Optional[KnowledgeSpace]:
        """
        更新空间信息

        权限检查已在路由层依赖注入中完成，此处仅做业务规则校验。

        owner_id 的特殊地位说明：
        - owner_id 是空间创建者，拥有不可撤销的最高权限
        - 更新空间需要 ADMIN 角色，路由层已确保操作者是空间管理员
        - owner_id 字段不可通过此方法修改

        Args:
            space_id: 空间 ID
            user_id: 操作用户 ID
            data: 更新数据

        Returns:
            更新后的空间或 None

        Raises:
            SpaceNotFoundError: 空间不存在
        """
        # 获取空间
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise SpaceNotFoundError(space_id)

        # 权限检查已在路由层依赖注入中完成（AdminMemberRequired），
        # 此处不再重复查询成员记录和权限校验

        # 过滤保护字段
        _protected = {"id", "owner_id", "created_at", "deleted_at"}
        data = {k: v for k, v in data.items() if k not in _protected}

        space = await self.space_repo.update(space_id, data)
        await self.session.commit()

        self.logger.info(
            "知识空间更新成功",
            space_id=space_id,
            user_id=user_id,
        )

        return space

    async def get_user_spaces(
        self,
        user_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> List[KnowledgeSpace]:
        """
        获取用户的空间列表

        Args:
            user_id: 用户 ID
            skip: 跳过数量
            limit: 返回数量

        Returns:
            空间列表
        """
        return await self.space_repo.get_user_spaces(
            user_id=user_id,
            skip=skip,
            limit=limit,
        )

    async def count_user_spaces(self, user_id: int) -> int:
        """
        统计用户所属的空间数量

        Args:
            user_id: 用户 ID

        Returns:
            空间数量
        """
        return await self.space_repo.count_user_spaces(user_id)

    async def get_public_spaces(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> List[KnowledgeSpace]:
        """
        获取公开空间列表

        Args:
            skip: 跳过数量
            limit: 返回数量

        Returns:
            公开空间列表
        """
        return await self.space_repo.get_public_spaces(
            skip=skip,
            limit=limit,
        )

    async def count_public_spaces(self) -> int:
        """
        统计公开空间数量

        Returns:
            公开空间数量
        """
        return await self.space_repo.count_public_spaces()

    async def search_spaces(
        self,
        keyword: str,
        user_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[KnowledgeSpace]:
        """
        搜索知识空间

        Args:
            keyword: 搜索关键词
            user_id: 用户 ID（限制为用户可访问的空间）
            skip: 跳过数量
            limit: 返回数量

        Returns:
            匹配的空间列表
        """
        return await self.space_repo.search(
            keyword=keyword,
            user_id=user_id,
            skip=skip,
            limit=limit,
        )

    async def count_search_spaces(
        self,
        keyword: str,
        user_id: Optional[int] = None,
    ) -> int:
        """
        统计搜索结果数量

        Args:
            keyword: 搜索关键词
            user_id: 用户 ID

        Returns:
            匹配的空间数量
        """
        return await self.space_repo.count_search(
            keyword=keyword,
            user_id=user_id,
        )

    async def get_space_stats(
        self,
        space_id: int,
    ) -> Dict[str, Any]:
        """
        获取空间统计信息

        实时从 Document 表聚合，排除软删除文档。

        Args:
            space_id: 空间 ID

        Returns:
            统计信息字典
        """
        space = await self.get_space(space_id)
        if not space:
            raise SpaceNotFoundError(space_id)

        from sqlalchemy import func, select
        from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase

        # 知识库数量
        kb_count_result = await self.session.execute(
            select(func.count(KnowledgeBase.id)).where(
                KnowledgeBase.space_id == space_id,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
        kb_count = kb_count_result.scalar() or 0

        # 实时统计文档/分块/存储（排除软删除和失败的文档）
        doc_stats = await self.doc_repo.get_space_realtime_stats(space_id)

        # 获取成员数量
        member_count = await self.member_repo.count_by_space(space_id)

        return {
            "kb_count": kb_count,
            "document_count": doc_stats["document_count"],
            "chunk_count": doc_stats["chunk_count"],
            "total_size_mb": doc_stats["total_size_mb"],
            "member_count": member_count,
        }

    # ========== 配置管理方法 ==========

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """深度合并字典（递归，深拷贝避免污染原始字典）"""
        import copy
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = SpaceService._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    async def _check_embedding_change_allowed(self, space_id: int) -> None:
        """检查空间是否允许修改 Embedding 配置（无已完成文档时才允许）"""
        stats = await self.get_space_stats(space_id)
        total_documents = stats.get("document_count", 0)

        if total_documents > 0:
            raise InvalidParameterError(
                f"无法修改 Embedding 配置：空间中存在 {total_documents} 个已处理的文档。"
                "不同模型的向量不兼容，会导致检索失效。"
                "请创建新空间使用不同的 Embedding 模型。"
            )

    def _is_embedding_changed(self, config_updates: dict, current_config: dict) -> bool:
        """检查配置更新是否涉及 embedding 模型变更（dimension 由后端自动管理，不算用户变更）"""
        embedding_update = config_updates.get("embedding")
        if not isinstance(embedding_update, dict) or not embedding_update:
            return False

        current_embedding = current_config.get("embedding") or {}
        return (
            embedding_update.get("model") is not None
            and embedding_update.get("model") != current_embedding.get("model")
        )

    async def get_config(self, space_id: int) -> Dict[str, Any]:
        """
        获取空间配置及统计信息

        Args:
            space_id: 空间 ID

        Returns:
            包含 space、config、stats 的字典
        """
        space = await self.get_space(space_id)
        if not space:
            raise SpaceNotFoundError(space_id)

        config = space.get_config()
        stats = await self.get_space_stats(space_id)

        return {
            "space": space,
            "config": config,
            "stats": stats,
        }

    async def update_config(
        self,
        space_id: int,
        config_updates: Dict[str, Any],
    ) -> KnowledgeSpace:
        """
        部分更新空间配置（深度合并 + 校验）

        Args:
            space_id: 空间 ID
            config_updates: 要更新的配置片段

        Returns:
            更新后的空间实例

        Raises:
            SpaceNotFoundError: 空间不存在
            InvalidParameterError: 存在已完成文档时尝试修改 embedding
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise SpaceNotFoundError(space_id)

        current_config = space.get_config()

        # 1. 校验 embedding 变更
        if self._is_embedding_changed(config_updates, current_config):
            await self._check_embedding_change_allowed(space_id)

        # 2. 深度合并
        merged_config = self._deep_merge(current_config, config_updates)

        # 2.1 embedding 模型变更时，自动从模型配置表回填维度
        embedding_update = config_updates.get("embedding")
        new_model = embedding_update.get("model") if isinstance(embedding_update, dict) else None
        if new_model:
            model_type = _resolve_model_type()
            auto_dim = await self._get_embedding_dimension(
                model_name=new_model,
                owner_id=space.owner_id,
                model_type=model_type,
            )
            if auto_dim:
                if not merged_config.get("embedding"):
                    merged_config["embedding"] = {}
                merged_config["embedding"]["dimension"] = auto_dim
                self.logger.info(
                    "配置更新：自动回填 Embedding 维度",
                    model=new_model,
                    dimension=auto_dim,
                )

        # 2.2 embedding 变更且维度改变时，重建 ES 索引
        embedding_changed = self._is_embedding_changed(config_updates, current_config)
        if embedding_changed and self.es_client:
            old_dim = (current_config.get("embedding") or {}).get("dimension")
            new_dim = (merged_config.get("embedding") or {}).get("dimension")
            if old_dim != new_dim:
                await self.es_client.delete_index(space_id)
                model_type = _resolve_model_type()
                create_kwargs = self._build_es_create_kwargs(space_id, new_dim)
                await self.es_client.create_index(**create_kwargs)
                self.logger.info(
                    "Embedding 变更：已重建 ES 索引",
                    space_id=space_id,
                    old_dim=old_dim,
                    new_dim=new_dim,
                )

        # 3. 保存
        space.config = merged_config
        flag_modified(space, "config")
        await self.session.commit()

        # 4. 失效缓存
        await self.space_repo.invalidate_space_cache(space_id)

        self.logger.info(
            "空间配置更新成功",
            space_id=space_id,
            updated_keys=list(config_updates.keys()),
        )

        return space

    # ---------- 配置共享辅助方法 ----------

    @staticmethod
    def _write_embedding_dimension(space, dimension: int):
        """回写 Embedding 维度到 space config"""
        space_config = space.get_config()
        if not space_config.get("embedding"):
            space_config["embedding"] = {}
        space_config["embedding"]["dimension"] = dimension
        space.config = space_config
        flag_modified(space, "config")

    @staticmethod
    def _build_es_create_kwargs(space_id: int, embedding_dim: int) -> Dict[str, Any]:
        """构建 ES 索引创建参数。"""
        return {"space_id": space_id, "embedding_dim": embedding_dim}
