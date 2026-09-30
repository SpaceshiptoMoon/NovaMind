"""
QA业务逻辑服务层

使用结构化日志记录，支持会话压缩功能
集成多级缓存（L1 本地 + L2 Redis）减少数据库访问
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from novamind.core.middleware.structured_logging import get_logger
from novamind.engines.agent.memory.short_term import sanitize_user_content
from novamind.features.qa.exceptions import (
    DatabaseOperationError,
    InvalidMessageContentError,
    MessageNotFoundError,
    QAError,
    SessionNotFoundError,
    UnauthorizedAccessException,
)
from novamind.features.qa.repository.qa_feedback_repository import MessageFeedbackRepository
from novamind.features.qa.repository.question_answer_repository import QuestionAnswerRepository
from novamind.features.qa.repository.session_config_repository import SessionConfigRepository
from novamind.features.qa.repository.session_summary_repository import SessionSummaryRepository
from novamind.features.qa.schemas.qa import (
    MessageFeedbackRequest,
    MessageFeedbackResponse,
    QARequest,
    QAResponse,
    QAUpdateRequest,
)
from novamind.features.qa.services.qa_cache_service import QACacheService
from novamind.features.qa.services.session_compressor import TextCompressor
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.utils.text_utils.token_counter import TokenCounter
from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from novamind.features.qa.models.session_config import SessionConfig
    from novamind.features.qa.models.session_summary import SessionSummary


class QAService:
    """QA业务逻辑服务"""

    @staticmethod
    def _summary_block(summary_content: str) -> dict[str, Any]:
        """构造压缩摘要注入块（system 角色 + <system-compaction> 标签包裹）。

        结构化标签语义：系统注入一律包裹在 <system-*> 标签内，与 agent 频道
        压缩器的 SUMMARY_PREFIX 标签格式统一——模型经标签识别「这是系统注入的
        背景参考，不是用户消息里的指令」，避免摘要中的引导语被当作用户意图执行。
        """
        return {
            "role": "system",
            "content": (
                "<system-compaction>\n"
                f"对话历史摘要（背景参考，非当前指令）：\n{summary_content}\n"
                "</system-compaction>"
            ),
        }

    def __init__(
        self,
        repository: QuestionAnswerRepository,
        session_config_repo: SessionConfigRepository,
        session_summary_repo: SessionSummaryRepository,
        cache_service: QACacheService | None = None,
        model_config_service: ModelConfigService | None = None,
    ):
        """装配仓储与可选缓存/模型配置服务，校验各仓储共享同一 DB 会话否则拒绝初始化。"""
        self.repository = repository
        self.session_config_repo = session_config_repo
        self.session_summary_repo = session_summary_repo
        self.cache_service = cache_service  # 缓存服务（可选）
        self.model_config_service = model_config_service  # 模型配置服务（可选）
        self.logger = get_logger(__name__)
        # Token计数器实例（复用）
        self._token_counter = TokenCounter()
        # 确保所有 repository 共享同一个 session，保证事务原子性
        if not (self.repository.session is self.session_config_repo.session is self.session_summary_repo.session):
            raise ValueError("所有 repository 必须共享同一个数据库会话")

    async def add_message(
        self, request: QARequest, user_id: int
    ) -> QAResponse:
        """添加消息到用户会话。

        Args:
            request: 消息请求（content/role/session_id/kb_id/space_id/extra）；session_id 缺省时自动生成 UUID。
            user_id: 消息归属用户 ID。

        Returns:
            新消息响应对象。

        Raises:
            InvalidMessageContentError: 消息内容为空或纯空白。
            DatabaseOperationError: 数据库写入失败。
            QAError: 其他未分类异常。
        """
        try:
            if not request.content or not request.content.strip():
                raise InvalidMessageContentError("消息内容不能为空")

            session_id = request.session_id or str(uuid.uuid4())

            # 写入时消毒（与 agent 频道 sanitize-at-write 架构对齐）：user 消息
            # 转义 '<' 防伪造系统标签 + 裸 compaction 前缀降格。DB 存安全形态后，
            # get_conversation_context 组装链路无需再对历史消息做 per-message 变换
            # （前缀字节恒定→prompt cache 稳定），assistant 消息不消毒（非注入面）。
            content_to_store = (
                sanitize_user_content(request.content)
                if request.role == "user"
                else request.content
            )

            message = await self.repository.create(
                content=content_to_store,
                role=request.role,
                user_id=user_id,
                session_id=session_id,
                kb_id=request.kb_id,
                space_id=request.space_id,
                extra=request.extra,
            )

            # 失效消息缓存（因为有新消息）
            if self.cache_service:
                await self.cache_service.invalidate_session_messages(session_id, user_id)

            return QAResponse(
                id=message.id,
                content=message.content,
                role=message.role,
                user_id=message.user_id,
                session_id=message.session_id,
                space_id=message.space_id,
                kb_id=message.kb_id,
                extra=message.extra,
                created_at=message.created_at
            )
        except SQLAlchemyError as e:
            raise DatabaseOperationError("创建消息失败", str(e)) from e
        except QAError:
            raise
        except Exception as e:
            self.logger.error("创建消息失败", error=str(e))
            raise QAError(f"创建消息失败: {str(e)}") from e

    async def get_session_messages(
        self, session_id: str, user_id: int
    ) -> list[QAResponse]:
        """获取用户特定会话的所有消息（带缓存，附当前用户反馈回显）。

        Args:
            session_id: 会话 ID。
            user_id: 用户 ID（SQL 层过滤，避免跨用户泄露）。

        Returns:
            按时间序的消息响应列表，会话无消息返回空列表。

        Raises:
            SessionNotFoundError: 会话 ID 为空或会话已被删除。
            DatabaseOperationError: 数据库查询失败。
            QAError: 其他未分类异常。
        """
        feedback_repo = MessageFeedbackRepository(self.repository.session)
        try:
            if not session_id:
                raise SessionNotFoundError(session_id)

            # 检查会话是否已被删除
            if self.cache_service:
                if await self.cache_service.is_session_deleted(session_id, user_id):
                    raise SessionNotFoundError(session_id)

            # 尝试从缓存获取
            if self.cache_service:
                cached = await self.cache_service.get_session_messages(session_id, user_id)
                if cached is not None:
                    self.logger.debug("从缓存获取消息列表", session_id=session_id)
                    try:
                        result = [QAResponse.model_validate(msg) for msg in cached]
                        # 反馈不在缓存（投反馈即失效缓存，此处兜底补齐）
                        return await self._attach_feedback(result, feedback_repo, user_id)
                    except Exception as cache_err:
                        self.logger.warning("缓存数据反序列化失败，降级到数据库查询", error=str(cache_err))

            # 从数据库获取（用户过滤，在 SQL 层完成过滤避免跨用户数据泄露）
            messages = await self.repository.get_by_session_and_user(
                session_id, user_id
            )

            if not messages:
                return []

            result = [
                QAResponse(
                    id=msg.id,
                    content=msg.content,
                    role=msg.role,
                    user_id=msg.user_id,
                    session_id=msg.session_id,
                    space_id=msg.space_id,
                    kb_id=msg.kb_id,
                    extra=msg.extra,
                    created_at=msg.created_at
                )
                for msg in messages
            ]

            result = await self._attach_feedback(result, feedback_repo, user_id)

            # 写入缓存（feedback 已附）——模型 dump 含嵌套 feedback 序列化正常
            if self.cache_service and result:
                cache_data = [msg.model_dump() for msg in result]
                await self.cache_service.set_session_messages(session_id, user_id, cache_data)

            return result
        except SQLAlchemyError as e:
            raise DatabaseOperationError("获取会话消息失败", str(e)) from e
        except QAError:
            raise
        except Exception as e:
            self.logger.error("获取会话消息失败", session_id=session_id, error=str(e))
            raise QAError(f"获取会话消息失败: {str(e)}") from e

    async def _attach_feedback(
        self,
        result: list[QAResponse],
        feedback_repo: MessageFeedbackRepository,
        user_id: int,
    ) -> list[QAResponse]:
        """批量回显当前用户对 assistant 消息的反馈（单查询，不改缓存行为）"""
        try:
            feedback_map = await feedback_repo.get_by_messages(
                [m.id for m in result if m.role == "assistant"], user_id
            )
        except Exception as fb_err:
            # 反馈回显失败不阻塞消息列表
            self.logger.warning("反馈回显失败（忽略）", session_error=str(fb_err))
            return result
        for m in result:
            fb = feedback_map.get(m.id)
            if fb:
                m.feedback = MessageFeedbackResponse(
                    message_id=fb.message_id, rating=fb.rating, comment=fb.comment,
                )
        return result

    async def get_user_sessions(
        self, user_id: int, limit: int = 20, offset: int = 0
    ) -> tuple[list[dict[str, str]], int]:
        """获取用户的所有会话列表（含预览，支持分页）。

        Args:
            user_id: 用户 ID。
            limit: 每页数量，默认 20。
            offset: 偏移量，默认 0。

        Returns:
            (会话预览字典列表, 总数) 二元组。

        Raises:
            DatabaseOperationError: 数据库查询失败。
            QAError: 其他未分类异常。
        """
        try:
            return await self.repository.get_user_sessions_with_preview(user_id, limit, offset)
        except SQLAlchemyError as e:
            raise DatabaseOperationError("获取用户会话失败", str(e)) from e
        except QAError:
            raise
        except Exception as e:
            self.logger.error("获取用户会话失败", user_id=user_id, error=str(e))
            raise QAError(f"获取用户会话失败: {str(e)}") from e

    async def set_message_feedback(
        self,
        message_id: int,
        request: MessageFeedbackRequest,
        user_id: int,
    ) -> MessageFeedbackResponse:
        """设置/撤销消息反馈（批次 2a：点赞点踩）。

        - rating=null 撤销（幂等：无反馈也返回成功）
        - 仅 assistant 消息可反馈，且消息必须属于当前用户
        - 写走独立 feedback repository（SAVEPOINT），事务由调用方（路由 get_db）提交
        """
        feedback_repo = MessageFeedbackRepository(self.repository.session)
        try:
            message = await self.repository.get_by_id(message_id)
            if not message or message.user_id != user_id:
                raise MessageNotFoundError(message_id)
            if message.role != "assistant":
                raise UnauthorizedAccessException("只能对 AI 回答反馈")

            if request.rating is None:
                await feedback_repo.delete(message_id, user_id)
                # 失效会话消息缓存（feedback 回显随消息列表下发）
                if self.cache_service:
                    await self.cache_service.invalidate_session_messages(message.session_id, user_id)
                return MessageFeedbackResponse(message_id=message_id, rating=None, comment=None)

            await feedback_repo.upsert(
                message_id=message_id,
                user_id=user_id,
                session_id=message.session_id,
                rating=request.rating,
                comment=request.comment,
                space_id=message.space_id,
                kb_id=message.kb_id,
            )
            if self.cache_service:
                await self.cache_service.invalidate_session_messages(message.session_id, user_id)
            return MessageFeedbackResponse(
                message_id=message_id, rating=request.rating, comment=request.comment,
            )
        except SQLAlchemyError as e:
            raise DatabaseOperationError("保存消息反馈失败", str(e)) from e
        except QAError:
            raise
        except Exception as e:
            self.logger.error("保存消息反馈失败", message_id=message_id, user_id=user_id, error=str(e))
            raise QAError(f"保存消息反馈失败: {str(e)}") from e

    async def update_message(
        self,
        message_id: int,
        request: QAUpdateRequest,
        user_id: int,
    ) -> QAResponse | None:
        """更新消息内容（校验归属，非本人消息视为不存在；role 不可改）。

        Args:
            message_id: 消息 ID。
            request: 更新请求（content，None 跳过）；role 字段已从 schema 移除。
            user_id: 当前用户 ID，用于归属校验。

        Returns:
            更新后的消息响应；消息不存在返回 None（由路由转 404）。

        Raises:
            MessageNotFoundError: 消息不存在或不属于当前用户。
            InvalidMessageContentError: 新内容为空或纯空白。
            DatabaseOperationError: 数据库更新失败。
            QAError: 其他未分类异常。
        """
        try:
            message = await self.repository.get_by_id(message_id)
            if not message or message.user_id != user_id:
                raise MessageNotFoundError(message_id)

            if request.content is not None:
                if not request.content.strip():
                    raise InvalidMessageContentError("消息内容不能为空")

                # 编辑路径同样过写入时消毒：API 编辑可把已消毒的历史消息改回
                # 任意内容（伪造 <system-*> 标签/裸 compaction 前缀），是
                # sanitize-at-write 的旁路；仅 user 角色消毒（与 add_message 判据一致）
                content_to_update = (
                    sanitize_user_content(request.content)
                    if message.role == "user"
                    else request.content
                )
            else:
                content_to_update = None

            # role 已从 QAUpdateRequest 移除（客户端翻转 user/assistant 会重构
            # 会话指令结构并绕过按角色判据的消毒）；存量 DB 行可能有旧 role 值，
            # update 显式传 None 不触碰 role 列
            updated_message = await self.repository.update(
                message_id=message_id,
                content=content_to_update,
                role=None,
            )

            if updated_message:
                # 失效消息缓存
                if self.cache_service:
                    await self.cache_service.invalidate_session_messages(
                        updated_message.session_id, user_id
                    )

                return QAResponse(
                    id=updated_message.id,
                    content=updated_message.content,
                    role=updated_message.role,
                    user_id=updated_message.user_id,
                    session_id=updated_message.session_id,
                    space_id=updated_message.space_id,
                    kb_id=updated_message.kb_id,
                    extra=updated_message.extra,
                    created_at=updated_message.created_at
                )
            return None
        except SQLAlchemyError as e:
            raise DatabaseOperationError("更新消息失败", str(e)) from e
        except QAError:
            raise
        except Exception as e:
            self.logger.error("更新消息失败", message_id=message_id, error=str(e))
            raise QAError(f"更新消息失败: {str(e)}") from e

    async def delete_message(
        self, message_id: int, user_id: int
    ) -> bool:
        """删除单条消息并失效会话缓存（校验归属）。

        Args:
            message_id: 消息 ID。
            user_id: 当前用户 ID，用于归属校验。

        Returns:
            是否实际删除。

        Raises:
            MessageNotFoundError: 消息不存在或不属于当前用户。
            DatabaseOperationError: 数据库删除失败。
            QAError: 其他未分类异常。
        """
        try:
            message = await self.repository.get_by_id(message_id)
            if not message or message.user_id != user_id:
                raise MessageNotFoundError(message_id)

            session_id = message.session_id
            success = await self.repository.delete(message_id)

            if success:
                # 失效消息缓存
                if self.cache_service:
                    await self.cache_service.invalidate_session_messages(session_id, user_id)

            return success
        except SQLAlchemyError as e:
            raise DatabaseOperationError("删除消息失败", str(e)) from e
        except QAError:
            raise
        except Exception as e:
            self.logger.error("删除消息失败", message_id=message_id, error=str(e))
            raise QAError(f"删除消息失败: {str(e)}") from e

    async def cleanup_message(self, message_id: int) -> None:
        """清理残留消息（用于异常恢复场景）。

        Args:
            message_id: 消息 ID。

        Returns:
            无返回；删除失败仅记告警不抛出。
        """
        try:
            await self.repository.delete(message_id)
        except Exception as e:
            self.logger.warning("清理消息失败", message_id=message_id, error=str(e))

    async def commit(self) -> None:
        """提交当前事务"""
        await self.repository.session.commit()

    async def rollback(self) -> None:
        """回滚当前事务"""
        await self.repository.session.rollback()

    async def delete_session(
        self, session_id: str, user_id: int
    ) -> int:
        """删除会话（消息/配置/摘要一并清除并失效全部缓存）。

        Args:
            session_id: 会话 ID。
            user_id: 当前用户 ID。

        Returns:
            删除的消息条数。

        Raises:
            SessionNotFoundError: 会话 ID 为空。
            DatabaseOperationError: 数据库删除失败。
            QAError: 其他未分类异常。
        """
        try:
            if not session_id:
                raise SessionNotFoundError(session_id)

            # 删除会话配置
            await self.session_config_repo.delete(session_id)
            # 删除摘要
            await self.session_summary_repo.delete_summaries(session_id)
            # 删除消息
            count = await self.repository.delete_session(
                session_id, user_id
            )

            # 失效所有缓存
            if self.cache_service:
                await self.cache_service.invalidate_session(session_id, user_id)
                # 标记会话已删除（用于查询时返回 404）
                await self.cache_service.mark_session_deleted(session_id, user_id)

            return count
        except SQLAlchemyError as e:
            raise DatabaseOperationError("删除会话失败", str(e)) from e
        except QAError:
            raise
        except Exception as e:
            self.logger.error("删除会话失败", session_id=session_id, error=str(e))
            raise QAError(f"删除会话失败: {str(e)}") from e

    async def _get_session_config_with_cache(
        self, session_id: str, user_id: int
    ) -> "SessionConfig":
        """获取会话配置（带缓存）"""
        cache_key = session_id

        # 尝试从缓存获取
        if self.cache_service:
            cached = await self.cache_service.get_session_config(cache_key)
            if cached is not None:
                # 反序列化 datetime 字段
                for field in ["created_at", "updated_at"]:
                    if field in cached and isinstance(cached[field], str):
                        try:
                            cached[field] = datetime.fromisoformat(cached[field])
                        except (ValueError, TypeError):
                            pass
                # 返回轻量配置对象（避免 ORM session 绑定问题）
                # 将 compression_config 嵌套字段展开为顶层属性，兼容 ORM @property 访问方式
                from types import SimpleNamespace
                cc = cached.get("compression_config", {}) or {}
                kb = cached.get("kb_bindings", {}) or {}
                lc = cached.get("llm_config", {}) or {}
                ws = cached.get("web_search_config", {}) or {}
                return SimpleNamespace(
                    **cached,
                    # 压缩配置（对齐 ORM property）
                    enable_compression=cc.get("enable_compression", True),
                    compression_strategy=cc.get("strategy", "summary"),
                    compression_threshold=cc.get("threshold", 70000),
                    compression_target_tokens=cc.get("target_tokens", 2000),
                    keep_recent_messages=cc.get("keep_recent", 6),
                    custom_summary_prompt=cc.get("custom_prompt"),
                    # RAG 绑定配置（对齐 ORM property，补齐缓存层遗漏）
                    auto_rag=kb.get("auto_rag", False),
                    rag_space_id=kb.get("space_id"),
                    rag_kb_ids=kb.get("kb_ids", []) or [],
                    rag_refusal_enabled=kb.get("refusal_enabled", False),
                    rag_score_threshold=(
                        kb.get("score_threshold")
                        if kb.get("score_threshold") is not None
                        else 0.3
                    ),
                    rag_search_mode=kb.get("search_mode", "content_hybrid"),
                    rag_top_k=kb.get("top_k", 5),
                    rag_vector_weight=(
                        kb.get("vector_weight") if kb.get("vector_weight") is not None else 0.7
                    ),
                    rag_bm25_weight=(
                        kb.get("bm25_weight") if kb.get("bm25_weight") is not None else 0.3
                    ),
                    # LLM 生成参数（对齐 ORM property，null 兜底默认值）
                    llm_max_tokens=(
                        lc.get("max_tokens") if lc.get("max_tokens") is not None else 2048
                    ),
                    llm_temperature=(
                        lc.get("temperature") if lc.get("temperature") is not None else 0.7
                    ),
                    llm_top_p=(lc.get("top_p") if lc.get("top_p") is not None else 0.8),
                    llm_system_prompt=lc.get("system_prompt"),
                    # 联网搜索引擎配置（对齐 ORM property，null 兜底默认值）
                    web_search_provider=ws.get("provider"),
                    web_search_max_results=(
                        ws.get("max_results") if ws.get("max_results") is not None else 5
                    ),
                )

        # 从数据库获取或创建默认配置（统一使用 ensure_session_config）
        config = await self.ensure_session_config(session_id, user_id)

        # 写入缓存
        if self.cache_service and config.id is not None:
            await self.cache_service.set_session_config(
                cache_key,
                config.to_dict(),
            )

        return config

    async def ensure_session_config(self, session_id: str, user_id: int) -> Any:
        """
        确保会话配置存在（如果不存在则创建默认配置并保存到数据库）

        Args:
            session_id: 会话 ID
            user_id: 用户 ID

        Returns:
            会话配置
        """
        # 检查是否已存在配置
        existing = await self.session_config_repo.get_by_session_id(session_id)
        if existing:
            return existing

        # 从 YAML 配置读取默认值
        from novamind.setting.yaml_config import get_config

        yaml_config = get_config()
        llm_config = yaml_config.llm

        # 构建压缩配置
        compression_config = {
            "enable_compression": llm_config.enable_compression,
            "strategy": llm_config.compression_strategy,
            "threshold": llm_config.compression_threshold,
            "target_tokens": llm_config.compression_target_tokens,
            "keep_recent": llm_config.keep_recent_messages,
            "custom_prompt": llm_config.custom_summary_prompt,
        }

        try:
            config = await self.session_config_repo.create(
                session_id=session_id,
                user_id=user_id,
                compression_config=compression_config,
            )

            self.logger.info("已创建会话默认配置", session_id=session_id, user_id=user_id)

            # 写入缓存
            if self.cache_service:
                await self.cache_service.set_session_config(
                    session_id,
                    config.to_dict(),
                )

            return config
        except Exception as e:
            self.logger.error("创建会话配置失败", session_id=session_id, error=str(e))
            raise

    # ========== 会话配置写入（写库 + 失效缓存） ==========
    # 配置写入必须同时失效 Redis 缓存，否则 get_conversation_context 的
    # _get_session_config_with_cache 仍读旧值，导致改了配置不立即生效。

    async def create_session_config(
        self, session_id: str, user_id: int, compression_config: dict,
    ) -> Any:
        """创建会话配置并失效缓存，保证后续读立即生效。

        Args:
            session_id: 会话 ID。
            user_id: 归属用户 ID。
            compression_config: 压缩配置字典（strategy/threshold/target_tokens/keep_recent 等）。

        Returns:
            创建的会话配置（只 flush，事务由路由层提交）。

        Raises:
            SessionConfigAlreadyExistsError: 该会话已有配置（仓储层唯一冲突时）。
        """
        config = await self.session_config_repo.create(
            session_id, user_id, compression_config,
        )
        await self.invalidate_session_config_cache(session_id)
        return config

    async def verify_session_owner(self, session_id: str, user_id: int) -> None:
        """会话归属校验（create / PATCH 共用）：若该会话已有其他用户的消息，则拒绝。

        用「消息归属」而非「config 归属」，因为 config 可能尚不存在（首次创建）。
        """
        from novamind.features.qa.exceptions import UnauthorizedAccessException

        existing_messages = await self.repository.get_by_session(session_id)
        if existing_messages and existing_messages[0].user_id != user_id:
            raise UnauthorizedAccessException("无权操作此会话配置")

    async def get_session_config(self, session_id: str, user_id: int):
        """读会话配置；无记录返回 None（调用方回落默认值）。

        Args:
            session_id: 会话 ID。
            user_id: 当前用户 ID，用于归属校验。

        Returns:
            会话配置，无记录返回 None。

        Raises:
            UnauthorizedAccessException: 配置存在但归属其他用户（映射 403）。
        """
        from novamind.features.qa.exceptions import UnauthorizedAccessException

        config = await self.session_config_repo.get_by_session_id(session_id)
        if config and config.user_id != user_id:
            raise UnauthorizedAccessException("无权访问此会话配置")
        return config

    async def delete_session_config(self, session_id: str, user_id: int) -> bool:
        """删会话配置（归属校验 + 删 + 失效缓存）。

        Args:
            session_id: 会话 ID。
            user_id: 当前用户 ID，用于归属校验。

        Returns:
            是否实际删除（本就无配置返回 False）。

        Raises:
            UnauthorizedAccessException: 配置归属其他用户（映射 403）。
        """
        from novamind.features.qa.exceptions import UnauthorizedAccessException

        existing = await self.session_config_repo.get_by_session_id(session_id)
        if not existing:
            return False
        if existing.user_id != user_id:
            raise UnauthorizedAccessException("无权操作此会话配置")
        await self.session_config_repo.delete(session_id)
        await self.invalidate_session_config_cache(session_id)
        return True

    async def update_compression_config(
        self, session_id: str, user_id: int, compression_config: dict,
    ) -> Any:
        """更新会话压缩配置并失效缓存。

        Args:
            session_id: 会话 ID。
            user_id: 归属用户 ID。
            compression_config: 压缩配置字典（strategy/threshold/target_tokens/keep_recent 等）。

        Returns:
            更新后的会话配置（不存在则按默认创建）。
        """
        config = await self.session_config_repo.update_compression(
            session_id, user_id, compression_config,
        )
        await self.invalidate_session_config_cache(session_id)
        return config

    async def update_llm_config(
        self, session_id: str, user_id: int, llm_config: dict,
    ) -> Any:
        """更新会话模型生成参数并失效缓存。

        Args:
            session_id: 会话 ID。
            user_id: 归属用户 ID。
            llm_config: 生成参数字典（max_tokens/temperature/top_p/system_prompt 等）。

        Returns:
            更新后的会话配置。
        """
        config = await self.session_config_repo.update_llm_config(
            session_id, user_id, llm_config,
        )
        await self.invalidate_session_config_cache(session_id)
        return config

    async def update_web_search_config(
        self, session_id: str, user_id: int, web_search_config: dict,
    ) -> Any:
        """更新会话联网搜索配置并失效缓存。

        Args:
            session_id: 会话 ID。
            user_id: 归属用户 ID。
            web_search_config: 联网搜索配置字典（provider/max_results 等）。

        Returns:
            更新后的会话配置。
        """
        config = await self.session_config_repo.update_web_search_config(
            session_id, user_id, web_search_config,
        )
        await self.invalidate_session_config_cache(session_id)
        return config

    async def upsert_rag_binding(
        self, session_id: str, user_id: int, rag_config: dict,
    ) -> Any:
        """更新会话知识库绑定（自动 RAG）并失效缓存。

        Args:
            session_id: 会话 ID。
            user_id: 归属用户 ID。
            rag_config: RAG 绑定配置字典（auto_rag/space_id/kb_ids/refusal_enabled 等）。

        Returns:
            更新后的会话配置。
        """
        config = await self.session_config_repo.upsert_rag_binding(
            session_id, user_id, rag_config,
        )
        await self.invalidate_session_config_cache(session_id)
        return config

    async def invalidate_session_config_cache(self, session_id: str) -> None:
        """失效会话配置缓存（Redis 不可用时静默跳过）。

        Args:
            session_id: 会话 ID。
        """
        if self.cache_service:
            try:
                await self.cache_service.invalidate_session_config(session_id)
            except Exception as e:
                self.logger.warning("失效会话配置缓存失败", session_id=session_id, error=str(e))

    async def _get_session_summary_with_cache(
        self, session_id: str
    ) -> Optional["SessionSummary"]:
        """获取会话摘要（带缓存）"""
        # 尝试从缓存获取
        if self.cache_service:
            cached = await self.cache_service.get_session_summary(session_id)
            if cached is not None:
                # 反序列化 datetime 字段
                for field in ["created_at", "updated_at"]:
                    if field in cached and isinstance(cached[field], str):
                        try:
                            cached[field] = datetime.fromisoformat(cached[field])
                        except (ValueError, TypeError):
                            pass
                # 返回轻量配置对象（避免 ORM session 绑定问题）
                from types import SimpleNamespace
                return SimpleNamespace(**cached)

        # 从数据库获取
        summary = await self.session_summary_repo.get_latest_summary(
            session_id
        )

        # 写入缓存
        if self.cache_service and summary:
            await self.cache_service.set_session_summary(
                session_id,
                {
                    "id": summary.id,
                    "session_id": summary.session_id,
                    "user_id": summary.user_id,
                    "summary_content": summary.summary_content,
                    "summary_tokens": summary.summary_tokens,
                    "compressed_message_count": summary.compressed_message_count,
                    "original_tokens": summary.original_tokens,
                    "last_compressed_message_id": summary.last_compressed_message_id,
                    "version": summary.version,
                }
            )

        return summary

    async def get_conversation_context(
        self,
        session_id: str,
        user_id: int,
        limit: int | None = None,
        enable_compression: bool | None = None,
        compression_threshold: int | None = None,
        keep_recent_messages: int | None = None,
    ) -> list[dict]:
        """
        获取对话上下文，用于 AI 对话

        支持通过参数覆盖会话配置中的默认值。
        压缩策略从数据库 session_config 表读取。

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            limit: 返回消息数量限制（可选）
            enable_compression: 是否启用压缩（可选，覆盖配置）
            compression_threshold: 压缩阈值（可选，覆盖配置）
            keep_recent_messages: 保留最近消息数（可选，覆盖配置）

        Returns:
            对话上下文消息列表
        """
        try:
            messages = await self.get_session_messages(session_id, user_id)

            # 纵深兜底：role="system" 是服务端注入面专属（压缩摘要/检索资料）。
            # schema 已禁止客户端直写 system，但存量 DB 行（旧 schema 时代）可能
            # 残留客户端伪造的 system 消息——组装进上下文即成为真 system 角色
            # 指令（最强注入原语），此处按白名单过滤，只放行 user/assistant。
            messages = [m for m in messages if m.role in ("user", "assistant")]

            if not messages:
                return []

            # 应用 limit 限制
            if limit is not None and limit > 0:
                messages = messages[-limit:]

            # 读取会话配置（带缓存）
            config = await self._get_session_config_with_cache(session_id, user_id)

            # 使用参数覆盖配置（如果提供）
            actual_enable_compression = enable_compression if enable_compression is not None else config.enable_compression
            actual_threshold = compression_threshold if compression_threshold is not None else config.compression_threshold
            actual_keep_recent = keep_recent_messages if keep_recent_messages is not None else config.keep_recent_messages
            actual_strategy = config.compression_strategy

            # 如果未启用压缩,直接返回原始消息
            if not actual_enable_compression:
                self.logger.debug("会话未启用压缩，返回原始消息", session_id=session_id)
                return [{"id": msg.id, "role": msg.role, "content": msg.content} for msg in messages]

            # summary 策略：先组合(摘要+新消息)再判断阈值
            # 避免用全部原始历史算 token 虚高（已摘要的旧消息不该重复算/重复喂给 LLM）
            if actual_strategy == "summary":
                return await self._get_summary_context(
                    messages, config, user_id, session_id,
                    actual_threshold, actual_keep_recent,
                )

            # 将消息转换为 dict 格式（用于压缩处理）
            context_messages = [{"id": msg.id, "role": msg.role, "content": msg.content} for msg in messages]

            # 计算 token 数（使用类属性复用实例）
            total_tokens = self._token_counter.count_messages_tokens(context_messages)

            # 如果未超过阈值,直接返回
            if total_tokens <= actual_threshold:
                self.logger.debug(
                    "上下文未超过阈值,无需压缩",
                    total_tokens=total_tokens,
                    threshold=actual_threshold,
                )
                return context_messages

            # 根据策略分发压缩逻辑（summary 已在上方提前走 _get_summary_context，此处只剩其余策略）
            if actual_strategy == "sliding_window":
                return await self._compress_with_sliding_window(
                    session_id, context_messages, actual_keep_recent, total_tokens
                )
            elif actual_strategy == "keep_recent":
                return await self._compress_with_keep_recent(
                    session_id, context_messages, actual_keep_recent, total_tokens
                )
            elif actual_strategy == "truncate":
                return await self._compress_with_truncate(
                    session_id, context_messages, config.compression_target_tokens, total_tokens
                )
            else:
                # 未知策略，默认走 summary 流程（组合判断 + 增量/全量）
                self.logger.warning(
                    "未知的压缩策略，使用默认 summary",
                    session_id=session_id,
                    strategy=actual_strategy,
                )
                return await self._get_summary_context(
                    messages, config, user_id, session_id,
                    actual_threshold, actual_keep_recent,
                )

        except QAError:
            raise
        except Exception as e:
            self.logger.error("压缩对话失败", session_id=session_id, error=str(e))
            raise QAError(f"压缩对话失败: {str(e)}") from e

    # ========== 压缩策略实现 ==========

    async def _get_summary_context(
        self,
        messages: list[Any],
        config: Any,
        user_id: int,
        session_id: str,
        threshold: int,
        keep_recent: int,
    ) -> list[dict]:
        """
        summary 策略的上下文获取：先组合(摘要+新消息)再判断阈值。

        与"读全部原始消息算 token"不同，这里基于**实际喂给 LLM 的组合输入**判断：
        - 有摘要：组合 = [摘要] + 上次边界之后的新消息
        - 无摘要：组合 = 全部消息
        组合 token 超阈值才压缩（增量/全量），避免已摘要的旧消息被重复读、重复算、重复喂。
        """
        summary = await self._get_session_summary_with_cache(session_id)

        if summary and summary.last_compressed_message_id:
            last_id = summary.last_compressed_message_id
            new_msg_dicts = [
                {"id": m.id, "role": m.role, "content": m.content}
                for m in messages
                if m.id > last_id
            ]
            # 组合输入 = 摘要 + 新消息（实际喂给 LLM 的内容）
            combined = (
                [self._summary_block(summary.summary_content)]
                + new_msg_dicts
            )
            combined_tokens = self._token_counter.count_messages_tokens(combined)

            if combined_tokens <= threshold:
                # 组合没超 → 摘要 + 全部新消息原样返回。
                # 不截 keep_recent：中间新消息既没进摘要也没进窗口会被静默丢
                # （当轮 LLM 看不到自己上一问）；且截取起点随消息数滑动会改写
                # 历史前缀破坏 prompt cache。组合 token 已 ≤ 阈值，无超窗风险。
                self.logger.debug(
                    "摘要+新消息未超阈值，返回组合",
                    session_id=session_id, combined_tokens=combined_tokens, threshold=threshold,
                )
                return [
                    self._summary_block(summary.summary_content),
                    *[{"role": m["role"], "content": m["content"]} for m in new_msg_dicts],
                ]

            # 组合超了（新消息积累多）→ 增量压缩：旧摘要 + 新消息 → 新摘要
            return await self._incremental_compress_and_return(
                session_id, user_id, config, keep_recent, summary, new_msg_dicts,
            )

        # 无摘要 → 全部消息，基于全部判断，超了全量压缩
        context_messages = [{"id": m.id, "role": m.role, "content": m.content} for m in messages]
        total_tokens = self._token_counter.count_messages_tokens(context_messages)
        if total_tokens <= threshold:
            return context_messages
        return await self._compress_with_summary(
            session_id, user_id, context_messages, config, keep_recent, total_tokens,
        )

    async def get_compression_llm_client(self, user_id: int):
        """获取用于压缩摘要的 LLM 客户端（用户默认 LLM）。

        Args:
            user_id: 用户 ID，用于查其默认 LLM 配置。

        Returns:
            用户默认模型的 LLM 客户端。

        Raises:
            QAError: 未配置 ModelConfigService 或用户未配置 LLM 模型。
        """
        if not self.model_config_service:
            raise QAError("未配置 ModelConfigService，无法执行压缩")
        default_model = await self.model_config_service.get_user_default_model_name(user_id, "llm")
        if not default_model:
            raise QAError("未配置 LLM 模型，无法执行压缩")
        return await self.model_config_service.get_llm_client_by_model(user_id, default_model)

    async def _incremental_compress_and_return(
        self,
        session_id: str,
        user_id: int,
        config: Any,
        keep_recent: int,
        cached_summary: Any,
        recent_msgs: list[dict],
    ) -> list[dict]:
        """
        增量压缩：旧摘要 + 新消息 → 新摘要。

        只把「旧摘要 + 自上次边界之后的新消息」喂给 LLM 生成更新摘要，
        不再把全部历史重新压缩——省 LLM 调用，且基于旧摘要融合，信息保留更连贯。

        小增量短路：recent 不超过 keep_recent 条时无新消息可并入摘要，
        此时绝不推进边界（推进会让这些从未进摘要的消息被 ``id > last_id``
        永久排除出上下文），直接返回旧摘要 + 全部 recent 原文。
        """
        if len(recent_msgs) <= keep_recent:
            return [
                self._summary_block(cached_summary.summary_content),
                *[{"role": m["role"], "content": m["content"]} for m in recent_msgs],
            ]

        llm_client = await self.get_compression_llm_client(user_id)
        compressor = TextCompressor(
            llm_client=llm_client,
            custom_prompt=config.custom_summary_prompt,
        )

        # 需并入摘要的新消息 = recent 中除最近 keep_recent 条（它们保留原文）
        # 当 recent 不足 keep_recent 条时，无新消息可压缩，返回空列表
        new_msgs_to_compress = (
            recent_msgs[:-keep_recent] if len(recent_msgs) > keep_recent else []
        )

        self.logger.info(
            "开始增量 SUMMARY 压缩",
            session_id=session_id,
            new_message_count=len(new_msgs_to_compress),
            target_tokens=config.compression_target_tokens,
        )

        result = await compressor.compress_with_base_summary(
            base_summary=cached_summary.summary_content,
            new_messages=new_msgs_to_compress,
            target_tokens=config.compression_target_tokens,
        )

        # 新边界 = 最近 keep_recent 条之前那条
        new_last_id = (
            recent_msgs[-(keep_recent + 1)]["id"]
            if len(recent_msgs) > keep_recent
            else recent_msgs[-1]["id"]
        )

        # 存更新后的摘要
        try:
            async with self.session_summary_repo.session.begin_nested():
                new_summary = await self.session_summary_repo.create_summary(
                    session_id=session_id,
                    user_id=user_id,
                    summary_content=result.summary,
                    summary_tokens=result.compressed_tokens,
                    compressed_message_count=(cached_summary.compressed_message_count or 0)
                    + len(new_msgs_to_compress),
                    original_tokens=result.original_tokens,
                    last_compressed_message_id=new_last_id,
                    last_message_id=new_last_id,
                )
                if self.cache_service and new_summary:
                    await self.cache_service.set_session_summary(
                        session_id,
                        {
                            "id": new_summary.id,
                            "session_id": new_summary.session_id,
                            "user_id": new_summary.user_id,
                            "summary_content": new_summary.summary_content,
                            "summary_tokens": new_summary.summary_tokens,
                            "compressed_message_count": new_summary.compressed_message_count,
                            "original_tokens": new_summary.original_tokens,
                            "last_compressed_message_id": new_summary.last_compressed_message_id,
                            "version": new_summary.version,
                        },
                    )
        except Exception as save_error:
            self.logger.error(
                "增量摘要保存失败，继续使用压缩结果",
                error=str(save_error), session_id=session_id,
            )

        self.logger.info(
            "增量 SUMMARY 压缩完成",
            session_id=session_id,
            new_message_count=len(new_msgs_to_compress),
            compressed_tokens=result.compressed_tokens,
        )

        # 返回 [新摘要] + 最近 keep_recent 条原文
        result_context = [
            self._summary_block(result.summary)
        ]
        for msg in recent_msgs[-keep_recent:]:
            result_context.append({"role": msg["role"], "content": msg["content"]})
        return result_context

    async def _compress_with_summary(
        self,
        session_id: str,
        user_id: int,
        context_messages: list[dict],
        config: Any,
        keep_recent: int,
        total_tokens: int,
    ) -> list[dict]:
        """
        全量压缩：把全部对话消息压成摘要（首次压缩、尚无摘要时使用）。

        有摘要的「组合判断 / 增量压缩」由 _get_summary_context 处理，本方法只负责全量。
        """
        llm_client = await self.get_compression_llm_client(user_id)
        compressor = TextCompressor(
            llm_client=llm_client,
            custom_prompt=config.custom_summary_prompt,
        )

        self.logger.info(
            "开始 SUMMARY 压缩",
            session_id=session_id,
            total_tokens=total_tokens,
            target_tokens=config.compression_target_tokens,
            keep_recent=keep_recent,
        )

        # 执行压缩
        result = await compressor.compress_messages(
            context_messages,
            target_tokens=config.compression_target_tokens,
            keep_recent=keep_recent,
        )

        if result.summary:
            # 存储新的摘要
            last_msg_id = (
                context_messages[-(keep_recent + 1)]["id"]
                if len(context_messages) > keep_recent
                else context_messages[-1]["id"]
            )

            try:
                # begin_nested() 创建 savepoint，依赖外层已有活动事务。
                # 此处依赖 get_db() 依赖注入时隐式开启的事务，
                # 若外层无活动事务，begin_nested() 将抛出
                # "no transaction in progress" 异常。
                async with self.session_summary_repo.session.begin_nested():
                    new_summary = await self.session_summary_repo.create_summary(
                        session_id=session_id,
                        user_id=user_id,
                        summary_content=result.summary,
                        summary_tokens=result.compressed_tokens,
                        compressed_message_count=max(0, len(context_messages) - keep_recent),
                        original_tokens=result.original_tokens,
                        last_compressed_message_id=last_msg_id,
                        last_message_id=last_msg_id,
                    )

                    # create_summary 内部已有 flush，此处不再冗余 flush

                    # 更新摘要缓存
                    if self.cache_service and new_summary:
                        await self.cache_service.set_session_summary(
                            session_id,
                            {
                                "id": new_summary.id,
                                "session_id": new_summary.session_id,
                                "user_id": new_summary.user_id,
                                "summary_content": new_summary.summary_content,
                                "summary_tokens": new_summary.summary_tokens,
                                "compressed_message_count": new_summary.compressed_message_count,
                                "original_tokens": new_summary.original_tokens,
                                "last_compressed_message_id": new_summary.last_compressed_message_id,
                                "version": new_summary.version,
                            }
                        )
            except QAError:
                raise
            except Exception as save_error:
                self.logger.error("保存摘要失败,但继续使用压缩结果", error=str(save_error), session_id=session_id)

            # 构建压缩后的上下文
            compressed_context = [
                self._summary_block(result.summary)
            ]

            for msg in result.kept_messages:
                compressed_context.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

            self.logger.info(
                "SUMMARY 压缩完成",
                session_id=session_id,
                original_tokens=result.original_tokens,
                compressed_tokens=result.compressed_tokens,
                compression_ratio=round(result.compression_ratio, 2),
            )

            return compressed_context
        else:
            # 压缩失败,返回最近的消息
            return [
                {"role": msg["role"], "content": msg["content"]}
                for msg in context_messages[-keep_recent:]
            ]

    async def _compress_with_sliding_window(
        self,
        session_id: str,
        context_messages: list[dict],
        keep_recent: int,
        total_tokens: int,
    ) -> list[dict]:
        """
        SLIDING_WINDOW 策略：滑动窗口

        只保留最近 N 条消息，丢弃更早的消息
        """
        self.logger.info(
            "执行 SLIDING_WINDOW 压缩",
            session_id=session_id,
            original_count=len(context_messages),
            keep_recent=keep_recent,
            total_tokens=total_tokens,
        )

        kept_messages = context_messages[-keep_recent:] if len(context_messages) > keep_recent else context_messages

        self.logger.info(
            "SLIDING_WINDOW 压缩完成",
            session_id=session_id,
            kept_count=len(kept_messages),
        )

        return [
            {"role": msg["role"], "content": msg["content"]}
            for msg in kept_messages
        ]

    async def _compress_with_keep_recent(
        self,
        session_id: str,
        context_messages: list[dict],
        keep_recent: int,
        total_tokens: int,
    ) -> list[dict]:
        """
        KEEP_RECENT 策略：仅保留最近消息

        严格只保留最近 N 条，完全丢弃历史
        注意：当前实现与 sliding_window 相同，保留独立方法以便未来差异化
        """
        # 复用 sliding_window 实现，两者当前行为一致
        return await self._compress_with_sliding_window(
            session_id, context_messages, keep_recent, total_tokens
        )

    async def _compress_with_truncate(
        self,
        session_id: str,
        context_messages: list[dict],
        target_tokens: int,
        total_tokens: int,
    ) -> list[dict]:
        """
        TRUNCATE 策略：按 token 数截断

        从最新消息开始保留，直到达到目标 token 数
        """
        self.logger.info(
            "执行 TRUNCATE 压缩",
            session_id=session_id,
            original_count=len(context_messages),
            total_tokens=total_tokens,
            target_tokens=target_tokens,
        )

        # 初始化压缩器（不需要 LLM）
        compressor = TextCompressor(llm_client=None)
        result = await compressor.compress_with_strategy(
            context_messages,
            strategy="truncate",
            target_tokens=target_tokens,
        )

        self.logger.info(
            "TRUNCATE 压缩完成",
            session_id=session_id,
            kept_count=len(result.kept_messages),
            kept_tokens=result.compressed_tokens,
            compression_ratio=round(result.compression_ratio, 2),
        )

        return [
            {"role": msg["role"], "content": msg["content"]}
            for msg in result.kept_messages
        ]
