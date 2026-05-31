"""
QA业务逻辑服务层

使用结构化日志记录，支持会话压缩功能
集成多级缓存（L1 本地 + L2 Redis）减少数据库访问
"""
import uuid
from typing import List, Optional, Dict, Any, Tuple, TYPE_CHECKING
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError

from src.core.middleware.structured_logging import get_logger
from src.features.qa.repository.question_answer_repository import QuestionAnswerRepository
from src.features.qa.repository.session_config_repository import SessionConfigRepository
from src.features.qa.repository.session_summary_repository import SessionSummaryRepository
from src.features.qa.services.qa_cache_service import QACacheService
from src.features.qa.schemas.qa import QARequest, QAResponse, QAUpdateRequest
from src.features.qa.api.exceptions import (
    QAError,
    DatabaseOperationError,
    SessionNotFoundError,
    MessageNotFoundError,
    InvalidMessageContentError,
)
from src.shared.utils.text_processing import TextCompressor
from src.shared.utils.text_processing.token_counter import TokenCounter

if TYPE_CHECKING:
    from src.features.qa.models.session_config import SessionConfig
    from src.features.qa.models.session_summary import SessionSummary


class QAService:
    """QA业务逻辑服务"""

    def __init__(
        self,
        repository: QuestionAnswerRepository,
        session_config_repo: SessionConfigRepository,
        session_summary_repo: SessionSummaryRepository,
        cache_service: Optional[QACacheService] = None,
        model_config_service: Optional[Any] = None,
    ):
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
        """添加消息到用户会话"""
        try:
            if not request.content or not request.content.strip():
                raise InvalidMessageContentError("消息内容不能为空")

            session_id = request.session_id or str(uuid.uuid4())

            message = await self.repository.create(
                content=request.content,
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
    ) -> List[QAResponse]:
        """获取用户特定会话的所有消息（带缓存）"""
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
                        return [QAResponse.model_validate(msg) for msg in cached]
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

            # 写入缓存
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

    async def get_user_sessions(
        self, user_id: int, limit: int = 20, offset: int = 0
    ) -> Tuple[List[Dict[str, str]], int]:
        """获取用户的所有会话列表（含预览，支持分页）"""
        try:
            return await self.repository.get_user_sessions_with_preview(user_id, limit, offset)
        except SQLAlchemyError as e:
            raise DatabaseOperationError("获取用户会话失败", str(e)) from e
        except QAError:
            raise
        except Exception as e:
            self.logger.error("获取用户会话失败", user_id=user_id, error=str(e))
            raise QAError(f"获取用户会话失败: {str(e)}") from e

    async def update_message(
        self,
        message_id: int,
        request: QAUpdateRequest,
        user_id: int,
    ) -> Optional[QAResponse]:
        """更新消息"""
        try:
            message = await self.repository.get_by_id(message_id)
            if not message or message.user_id != user_id:
                raise MessageNotFoundError(message_id)

            if request.content is not None:
                if not request.content.strip():
                    raise InvalidMessageContentError("消息内容不能为空")

            updated_message = await self.repository.update(
                message_id=message_id,
                content=request.content,
                role=request.role,
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
        """删除消息"""
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
        """清理残留消息（用于异常恢复场景）"""
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
        """删除会话中的所有消息"""
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
                cc = cached.pop("compression_config", {}) or {}
                return SimpleNamespace(
                    **cached,
                    enable_compression=cc.get("enable_compression", True),
                    compression_strategy=cc.get("strategy", "summary"),
                    compression_threshold=cc.get("threshold", 3000),
                    compression_target_tokens=cc.get("target_tokens", 500),
                    keep_recent_messages=cc.get("keep_recent", 2),
                    custom_summary_prompt=cc.get("custom_prompt"),
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
        from src.setting.yaml_config import get_config

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
        limit: Optional[int] = None,
        enable_compression: Optional[bool] = None,
        compression_threshold: Optional[int] = None,
        keep_recent_messages: Optional[int] = None,
    ) -> List[dict]:
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

            # 根据策略分发压缩逻辑（使用字符串比较）
            if actual_strategy == "summary":
                return await self._compress_with_summary(
                    session_id, user_id, context_messages, config,
                    actual_keep_recent, total_tokens
                )
            elif actual_strategy == "sliding_window":
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
                # 未知策略，默认使用 summary
                self.logger.warning(
                    "未知的压缩策略，使用默认 summary",
                    session_id=session_id,
                    strategy=actual_strategy,
                )
                return await self._compress_with_summary(
                    session_id, user_id, context_messages, config,
                    actual_keep_recent, total_tokens
                )

        except QAError:
            raise
        except Exception as e:
            self.logger.error("压缩对话失败", session_id=session_id, error=str(e))
            raise QAError(f"压缩对话失败: {str(e)}") from e

    # ========== 压缩策略实现 ==========

    async def _compress_with_summary(
        self,
        session_id: str,
        user_id: int,
        context_messages: List[dict],
        config: Any,
        keep_recent: int,
        total_tokens: int,
    ) -> List[dict]:
        """
        SUMMARY 策略：使用 LLM 生成摘要

        支持缓存摘要，避免重复压缩
        """
        # 检查是否有缓存的摘要（带缓存）
        cached_summary = await self._get_session_summary_with_cache(session_id)
        if cached_summary and cached_summary.last_compressed_message_id:
            # 获取最后被压缩消息之后的消息
            last_compressed_id = cached_summary.last_compressed_message_id
            recent_msgs = [m for m in context_messages if m["id"] > last_compressed_id]

            # 如果最近消息数量合理,使用缓存的摘要
            if len(recent_msgs) <= keep_recent * 2:
                self.logger.info(
                    "使用缓存的摘要",
                    session_id=session_id,
                    summary_version=cached_summary.version,
                    recent_message_count=len(recent_msgs),
                )

                result_context = [
                    {"role": "system", "content": f"对话历史摘要: {cached_summary.summary_content}"}
                ]

                # 添加最近的消息
                for msg in recent_msgs[-keep_recent:]:
                    result_context.append({
                        "role": msg["role"],
                        "content": msg["content"],
                    })

                return result_context

        # 需要重新压缩 — 通过 ModelConfigService 获取 LLM 客户端
        if self.model_config_service:
            default_model = await self.model_config_service.get_user_default_model_name(user_id, "llm")
            if default_model:
                llm_client = await self.model_config_service.get_llm_client_by_model(user_id, default_model)
            else:
                raise QAError("未配置 LLM 模型，无法执行压缩")
        else:
            raise QAError("未配置 ModelConfigService，无法执行压缩")
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
                        compressed_message_count=len(context_messages) - keep_recent,
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
                {"role": "system", "content": f"对话历史摘要: {result.summary}"}
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
        context_messages: List[dict],
        keep_recent: int,
        total_tokens: int,
    ) -> List[dict]:
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
        context_messages: List[dict],
        keep_recent: int,
        total_tokens: int,
    ) -> List[dict]:
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
        context_messages: List[dict],
        target_tokens: int,
        total_tokens: int,
    ) -> List[dict]:
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
