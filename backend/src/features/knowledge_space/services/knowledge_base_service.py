"""
知识库管理服务

处理知识库的创建、更新、删除等操作
支持多租户和 RBAC 权限控制
"""

import copy
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from novamind.features.knowledge_space.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseStatus,
)
from novamind.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.member_repository import MemberRepository
from novamind.features.knowledge_space.services.permission_service import PermissionService
from novamind.features.knowledge_space.api.exceptions import (
    KnowledgeBaseNotFoundError,
    KnowledgeBaseAlreadyExistsError,
    KnowledgeBaseAccessDeniedError,
    KnowledgeBaseLimitExceededError,
    InvalidParameterError,
)
from novamind.shared.storage.elasticsearch_client import ElasticsearchClient
from novamind.shared.storage.minio_client import MinioClient
from novamind.features.knowledge_space.schemas.knowledge_base_schema import KnowledgeBaseConfigUpdate


def get_effective_space_types(kb_config: Optional[dict] = None) -> List[str]:
    """
    获取知识库有效的数据模态列表。

    优先级：KB.config.space_type → 默认 ["text"]
    """
    if kb_config:
        types = kb_config.get("space_type")
        if types and isinstance(types, list):
            return types

    return ["text"]
from novamind.core.middleware.structured_logging import get_logger


class KnowledgeBaseService:
    """
    知识库管理服务

    处理知识库的完整生命周期管理
    支持多租户和 RBAC 权限控制
    """

    def __init__(
        self,
        session: AsyncSession,
        es_client: ElasticsearchClient,
        minio_client: MinioClient,
    ):
        self.session = session
        self.kb_repo = KnowledgeBaseRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.member_repo = MemberRepository(session)
        self.permission_service = PermissionService()
        self.es_client = es_client
        self.minio_client = minio_client
        self.logger = get_logger(__name__)

    async def create_knowledge_base(
        self,
        space_id: int,
        creator_id: int,
        name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeBase:
        """
        创建知识库

        Args:
            space_id: 空间 ID
            creator_id: 创建者 ID
            name: 知识库名称
            config: 知识库配置（切分、解析、向量化、检索）

        Returns:
            创建的知识库实例

        Raises:
            KnowledgeBaseAlreadyExistsError: 知识库名称已存在
            KnowledgeBaseLimitExceededError: 达到知识库数量上限
        """
        # 0. 权限检查：创建知识库需要 EDITOR+ 权限
        member = await self.member_repo.get_by_space_and_user(space_id, creator_id)
        if not member or not member.is_active():
            raise KnowledgeBaseAccessDeniedError(0, creator_id, "无权在此空间创建知识库")
        if not self.permission_service.can_manage_knowledge_base(member):
            raise KnowledgeBaseAccessDeniedError(0, creator_id, "需要编辑者或更高权限才能创建知识库")

        # 1. 检查是否已存在同名知识库
        existing = await self.kb_repo.get_by_name(space_id, name)
        if existing:
            raise KnowledgeBaseAlreadyExistsError(name)

        # 1.1 释放同名软删除记录的唯一约束占位
        # 唯一约束 (space_id, name) 不区分软删除，需将旧记录重命名以腾出名称
        soft_deleted = await self.kb_repo.get_deleted_by_name(space_id, name)
        if soft_deleted:
            for record in soft_deleted:
                record.name = f"{record.name}_deleted_{record.id}"
                self.logger.info(
                    "重命名软删除知识库以释放唯一约束",
                    old_name=name,
                    new_name=record.name,
                    kb_id=record.id,
                )
            await self.session.flush()

        # 2. 检查知识库数量限制（从配置获取）
        max_kb_per_space = 50  # 默认值

        kb_count = await self.kb_repo.count_by_space(space_id)
        if kb_count >= max_kb_per_space:
            raise KnowledgeBaseLimitExceededError(max_kb_per_space)

        # 3. 创建知识库记录
        kb = await self.kb_repo.create({
            "space_id": space_id,
            "name": name,
            "creator_id": creator_id,
            "config": config or self._get_default_config(),
            "storage": {},  # 临时空值，下面立即更新
            "status": KnowledgeBaseStatus.ACTIVE,
        })

        # 4. 设置存储配置
        kb.storage = {
            "minio_prefix": f"kb/{kb.id}",
        }

        # 5. 补充问题生成 LLM 模型配置
        kb_config = kb.get_config()
        config_updated = False

        from novamind.features.user.services.model_config_service import ModelConfigService
        model_config_service = ModelConfigService(self.session)
        qg_config = kb_config.get("question_generation") or {}
        qg_llm_config = qg_config.get("llm") or {}
        qg_llm_model = qg_llm_config.get("model")

        if not qg_llm_model:
            default_llm_name = await model_config_service.get_user_default_model_name(creator_id, "llm")
            if default_llm_name:
                if not kb_config.get("question_generation"):
                    kb_config["question_generation"] = {}
                if not kb_config["question_generation"].get("llm"):
                    kb_config["question_generation"]["llm"] = {}
                kb_config["question_generation"]["llm"]["model"] = default_llm_name
                config_updated = True
                self.logger.info(
                    "回写问题生成默认 LLM 模型",
                    model=default_llm_name,
                )

        if config_updated:
            # SQLAlchemy 的 JSON 列存在「可变对象陷阱」：
            # kb_config 与 kb.config 是同一个 dict 对象（由 get_config() 返回）
            # 原地修改 kb_config 时，SQLAlchemy 内部的 committed_state 引用也被修改
            # 导致后续赋值 kb.config = {**kb_config} 时，新旧值相同，不生成 UPDATE
            # 因此必须用 flag_modified 显式标记列已变更
            flag_modified(kb, "config")
        # 6. 提交事务（ES 索引已在空间创建时建立）
        await self.session.commit()

        self.logger.info(
            "知识库创建成功",
            kb_id=kb.id,
            space_id=space_id,
            name=name,
        )

        return kb

    async def get_knowledge_base(
        self,
        kb_id: int,
    ) -> Optional[KnowledgeBase]:
        """
        获取知识库信息

        Args:
            kb_id: 知识库 ID

        Returns:
            知识库实例或 None
        """
        return await self.kb_repo.get_by_id(kb_id)

    async def update_knowledge_base(
        self,
        kb_id: int,
        user_id: int,
        data: Dict[str, Any],
    ) -> Optional[KnowledgeBase]:
        """
        更新知识库信息

        Args:
            kb_id: 知识库 ID
            user_id: 操作用户 ID
            data: 更新数据

        Returns:
            更新后的知识库或 None

        Raises:
            KnowledgeBaseNotFoundError: 知识库不存在
            KnowledgeBaseAccessDeniedError: 无权限更新
        """
        kb = await self.get_knowledge_base(kb_id)
        if not kb:
            raise KnowledgeBaseNotFoundError(kb_id)

        # 检查用户权限
        member = await self.member_repo.get_by_space_and_user(kb.space_id, user_id)
        if not member or not member.is_active():
            raise KnowledgeBaseAccessDeniedError(kb_id, user_id, "无权更新此知识库")

        # 使用 PermissionService 检查权限
        if not self.permission_service.can_manage_knowledge_base(member):
            raise KnowledgeBaseAccessDeniedError(kb_id, user_id, "需要编辑者或以上权限才能更新知识库")

        # 不允许直接更新某些字段
        protected_fields = ["space_id", "creator_id", "id"]
        for field in protected_fields:
            data.pop(field, None)

        kb = await self.kb_repo.update(kb_id, data)
        await self.session.commit()

        self.logger.info(
            "知识库更新成功",
            kb_id=kb_id,
            user_id=user_id,
        )

        return kb

    async def delete_knowledge_base(
        self,
        kb_id: int,
        user_id: int,
    ) -> bool:
        """
        删除知识库（软删除）

        Args:
            kb_id: 知识库 ID
            user_id: 操作用户 ID

        Returns:
            是否成功

        Raises:
            KnowledgeBaseNotFoundError: 知识库不存在
            KnowledgeBaseAccessDeniedError: 无权限删除
        """
        kb = await self.get_knowledge_base(kb_id)
        if not kb:
            raise KnowledgeBaseNotFoundError(kb_id)

        # 检查用户权限
        member = await self.member_repo.get_by_space_and_user(kb.space_id, user_id)
        if not member or not member.is_active():
            raise KnowledgeBaseAccessDeniedError(kb_id, user_id, "无权删除此知识库")

        # 使用 PermissionService 检查权限（需要空间 ADMIN 权限才能删除知识库）
        if not self.permission_service.is_admin(member):
            raise KnowledgeBaseAccessDeniedError(kb_id, user_id, "需要空间管理员权限才能删除知识库")

        # 1. 先软删除知识库和关联文档（保证用户视角一致性）
        await self.doc_repo.delete_by_kb(kb_id)
        await self.kb_repo.delete(kb_id)
        await self.session.commit()

        # 2. 删除 Elasticsearch 中该知识库的文档（允许失败，后台可重试）
        try:
            deleted_chunks = await self.es_client.delete_kb_chunks(
                space_id=kb.space_id,
                kb_id=kb_id,
            )
            self.logger.info("ES 知识库文档删除成功", kb_id=kb_id, deleted_count=deleted_chunks)
        except Exception as e:
            self.logger.warning(
                "ES 知识库文档删除失败，需要后台清理",
                kb_id=kb_id,
                error=str(e),
            )

        # 3. 删除 MinIO 中的文件（允许失败，后台可重试）
        try:
            deleted_count = await self.minio_client.delete_knowledge_base_documents(
                space_id=kb.space_id,
                kb_id=kb_id,
            )
            self.logger.info(
                "MinIO 文件删除成功",
                kb_id=kb_id,
                deleted_count=deleted_count,
            )
        except Exception as e:
            self.logger.warning(
                "MinIO 文件删除失败，需要后台清理",
                kb_id=kb_id,
                error=str(e),
            )

        self.logger.info(
            "知识库删除成功",
            kb_id=kb_id,
            user_id=user_id,
        )

        return True

    async def restore_knowledge_base(
        self,
        kb_id: int,
    ) -> Optional[KnowledgeBase]:
        """
        恢复已删除的知识库

        Args:
            kb_id: 知识库 ID

        Returns:
            恢复后的知识库或 None
        """
        kb = await self.kb_repo.restore(kb_id)
        if kb:
            await self.session.commit()
            self.logger.info("知识库恢复成功", kb_id=kb_id)
            return kb
        return None

    async def get_space_knowledge_bases(
        self,
        space_id: int,
        status: Optional[KnowledgeBaseStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[KnowledgeBase]:
        """
        获取空间内的知识库列表

        Args:
            space_id: 空间 ID
            status: 状态过滤
            skip: 跳过数量
            limit: 返回数量

        Returns:
            知识库列表
        """
        return await self.kb_repo.get_by_space(space_id, status, skip, limit)

    async def search_knowledge_bases(
        self,
        keyword: str,
        skip: int = 0,
        limit: int = 20,
    ) -> List[KnowledgeBase]:
        """
        按名称搜索知识库

        Args:
            keyword: 搜索关键词
            skip: 跳过数量
            limit: 返回数量

        Returns:
            知识库列表
        """
        return await self.kb_repo.search_by_name(keyword, skip, limit)

    async def get_full_stats(self, kb_id: int) -> Dict[str, Any]:
        """获取知识库完整统计（实时查询，排除软删除文档）"""
        return await self.doc_repo.get_kb_realtime_stats(kb_id)

    # ========== 配置管理方法 ==========

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """深度合并字典（递归，override 值为 None 时删除对应 key）"""
        result = copy.deepcopy(base)
        for key, value in override.items():
            if value is None:
                result.pop(key, None)
            elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = KnowledgeBaseService._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _validate_config_updates(self, config_updates: dict, kb=None) -> None:
        """校验配置更新请求"""
        splitting = config_updates.get("splitting", {})
        if "strategy" in splitting:
            valid_strategies = {"recursive", "fixed_size", "markdown", "semantic"}
            if splitting["strategy"] not in valid_strategies:
                raise InvalidParameterError(f"不支持的切分策略: {splitting['strategy']}")
        if "chunk_size" in splitting:
            if not (100 <= splitting["chunk_size"] <= 4000):
                raise InvalidParameterError("chunk_size 必须在 100-4000 之间")
        if "chunk_overlap" in splitting:
            chunk_size = splitting.get("chunk_size")
            if chunk_size is None and kb:
                chunk_size = (kb.config or {}).get("splitting", {}).get("chunk_size", 500)
            if chunk_size is not None and splitting["chunk_overlap"] >= chunk_size:
                raise InvalidParameterError("chunk_overlap 必须小于 chunk_size")
        # 音频切分覆盖
        splitting_audio = splitting.get("audio")
        if splitting_audio:
            if "strategy" in splitting_audio:
                if splitting_audio["strategy"] not in ("sentence", "fixed"):
                    raise InvalidParameterError(f"不支持的音频切分策略: {splitting_audio['strategy']}")
            if "chunk_size" in splitting_audio:
                if not (100 <= splitting_audio["chunk_size"] <= 4000):
                    raise InvalidParameterError("audio.chunk_size 必须在 100-4000 之间")
        # 视频切分覆盖
        splitting_video = splitting.get("video")
        if splitting_video:
            if "strategy" in splitting_video:
                if splitting_video["strategy"] not in ("fixed",):
                    raise InvalidParameterError(f"不支持的视频切分策略: {splitting_video['strategy']}")
            if "chunk_size" in splitting_video:
                if not (100 <= splitting_video["chunk_size"] <= 4000):
                    raise InvalidParameterError("video.chunk_size 必须在 100-4000 之间")

        try:
            KnowledgeBaseConfigUpdate.model_validate(config_updates)
        except Exception as exc:
            raise InvalidParameterError(str(exc)) from exc

    async def update_config(
        self,
        kb_id: int,
        config_updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        部分更新知识库配置（深度合并 + 校验）

        Args:
            kb_id: 知识库 ID
            config_updates: 要更新的配置片段

        Returns:
            {"message": "..."}

        Raises:
            InvalidParameterError: 切分配置参数不合法（strategy/chunk_size/chunk_overlap）
        """
        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb:
            raise KnowledgeBaseNotFoundError(kb_id)

        current_config = kb.get_config()

        # 1. 校验
        self._validate_config_updates(config_updates, kb=kb)

        # 2. 过滤 embedding 字段（由空间级别管理）
        config_updates.pop("embedding", None)

        # 3. 深度合并
        merged_config = self._deep_merge(current_config, config_updates)

        # 4. 保存
        kb.config = merged_config
        flag_modified(kb, "config")
        await self.session.commit()

        return {"message": "配置更新成功，新配置将在下次拆分解析时生效"}

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认知识库配置（从 Schema 统一生成）"""
        from novamind.features.knowledge_space.schemas.knowledge_base_schema import KnowledgeBaseConfig
        return KnowledgeBaseConfig().model_dump()

    async def get_kb_document_stats(self, kb_id: int) -> Dict[str, int]:
        """获取知识库的文档统计信息（基于 document_tasks 的最新状态）"""
        from novamind.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository
        from novamind.features.knowledge_space.models.document_task import TaskStatus

        task_repo = DocumentTaskRepository(self.session)
        stats = {
            "pending_documents": await task_repo.count_by_status(kb_id, TaskStatus.PENDING),
            "completed_documents": await task_repo.count_by_status(kb_id, TaskStatus.COMPLETED),
            "failed_documents": await task_repo.count_by_status(kb_id, TaskStatus.FAILED),
            "processing_documents": await task_repo.count_by_status(kb_id, TaskStatus.PROCESSING),
        }
        return stats
