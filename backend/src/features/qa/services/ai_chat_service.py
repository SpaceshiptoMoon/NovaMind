"""
AI对话服务层
使用结构化日志记录
支持用户配置的 LLM 模型
支持文档附件上传和分析
"""
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, AsyncGenerator, TYPE_CHECKING
from uuid import uuid4
import base64
import json
import tempfile
import os

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.middleware.structured_logging import get_logger

if TYPE_CHECKING:
    from src.features.user.services.model_config_service import ModelConfigService
    from src.shared.storage.minio_client import MinioClient
from src.shared.ai_models.llm import BaseLLM
from src.shared.prompts.templates import PromptTemplate, PromptManager
from src.shared.utils.heartbeat import stream_with_heartbeat, stream_with_heartbeat_structured
from src.features.qa.services.qa_service import QAService
from src.features.qa.schemas.qa import QARequest
from src.features.qa.repository.chat_attachment_repository import ChatAttachmentRepository
from src.features.qa.api.exceptions import (
    QAError,
    LLMServiceError,
    InvalidMessageContentError,
    SessionManagementError,
)


@dataclass
class ChatPreparation:
    """对话预处理的共享结果"""
    session_id: str
    user_message: Any
    conversation_history: list
    llm_client: BaseLLM
    context: list
    attachment_ids: Optional[List[int]] = None
    attachments: Optional[list] = None
    attachments_info: Optional[list] = None
    display_content: str = ""  # 已废弃，保留兼容


class AIChatService:
    """AI对话服务，集成LLM客户端，支持用户配置模型"""

    def __init__(
        self,
        qa_service: QAService,
        model_config_service: Optional["ModelConfigService"] = None,
        db: Optional[AsyncSession] = None,
        minio_client: Optional["MinioClient"] = None,
    ):
        """
        初始化 AI Chat 服务

        Args:
            qa_service: QA 服务
            model_config_service: 模型配置服务（用于获取用户配置的模型）
            db: 数据库会话（用于附件存储）
            minio_client: MinIO 客户端（用于文件存储）
        """
        self.qa_service = qa_service
        self.model_config_service = model_config_service
        self.db = db
        self.minio_client = minio_client
        self.attachment_repo = ChatAttachmentRepository(db) if db else None
        self.logger = get_logger(__name__)

    async def _get_llm_client(
        self,
        user_id: int,
        llm_model: Optional[str]
    ) -> BaseLLM:
        """
        获取 LLM 客户端

        通过 ModelConfigService 从数据库解析凭证，无配置时抛异常

        Args:
            user_id: 用户 ID
            llm_model: 模型名称（可选）

        Returns:
            LLM 客户端

        Raises:
            LLMServiceError: 未配置模型
        """
        if self.model_config_service:
            # 如果没有指定模型，获取系统默认
            if not llm_model:
                llm_model = await self.model_config_service.get_default_model_name("llm")

            if llm_model:
                # 优先按 LLM 查找，找不到再按 VLM 查找
                try:
                    return await self.model_config_service.get_llm_client_by_model(
                        user_id, llm_model
                    )
                except Exception:
                    return await self.model_config_service.get_vlm_client_by_model(
                        user_id, llm_model
                    )

        raise LLMServiceError("未配置 LLM 模型，请在模型配置中添加")

    async def _prepare_chat(
        self,
        user_id: int,
        session_id: Optional[str],
        content: str,
        llm_model: Optional[str],
        system_prompt: str,
        attachment_ids: Optional[List[int]] = None,
    ) -> ChatPreparation:
        """
        流式/非流式对话共享的预处理逻辑

        Args:
            user_id: 用户ID
            session_id: 会话ID
            content: 用户消息内容
            llm_model: LLM 模型名称
            system_prompt: 系统提示词

        Returns:
            ChatPreparation: 预处理结果
        """
        # 验证输入
        if not content or not content.strip():
            raise InvalidMessageContentError("消息内容不能为空")

        # 创建或获取会话ID
        session_id = session_id or str(uuid4())

        # 确保会话配置存在
        await self.qa_service.ensure_session_config(session_id, user_id)

        # 解析附件，构造 extra（不修改 content）
        attachments_data = None
        attachments_info = None
        extra = None
        if attachment_ids and self.attachment_repo:
            attachments_data = await self.attachment_repo.get_by_ids_and_user(attachment_ids, user_id)
            if attachments_data:
                attachments_info = [
                    {"id": a.id, "filename": a.filename, "file_type": a.file_type, "file_size": a.file_size, "storage_path": a.storage_path}
                    for a in attachments_data
                ]
                extra = {"attachments": attachments_info}

        # 添加用户消息到会话（content 保持原始输入）
        user_message = await self.qa_service.add_message(
            QARequest(content=content, role="user", session_id=session_id, extra=extra),
            user_id,
        )

        # 获取对话上下文（从数据库加载）
        context = await self.qa_service.get_conversation_context(session_id, user_id)

        # 动态注入附件文本到上下文（扫描所有带 extra.attachments 的消息）
        # 用 try/except 包裹，注入失败不应阻塞对话
        try:
            is_vlm = await self._is_vlm_model(llm_model, user_id)
            context = await self._inject_attachments_to_context(session_id, context, user_id, is_vlm)
        except Exception as inject_err:
            self.logger.warning("附件文本注入失败，跳过注入", error=str(inject_err))

        # 构建对话历史
        conversation_history = [
            {"role": "system", "content": system_prompt}
        ] + context

        # 获取 LLM 客户端
        llm_client = await self._get_llm_client(user_id, llm_model)

        self.logger.debug(
            "使用 LLM 客户端",
            user_id=user_id,
            llm_model=llm_model,
            session_id=session_id,
        )

        return ChatPreparation(
            session_id=session_id,
            user_message=user_message,
            conversation_history=conversation_history,
            llm_client=llm_client,
            context=context,
            attachment_ids=attachment_ids,
            attachments=attachments_data,
            attachments_info=attachments_info,
            display_content=content,
        )

    async def chat(self,
                   user_id: int,
                   session_id: Optional[str] = None,
                   content: Optional[str] = None,
                   llm_model: Optional[str] = None,
                   max_tokens: int = 2048,
                   temperature: float = 0.7,
                   top_p: float = 0.8,
                   system_prompt: Optional[str] = None,
                   enable_thinking: bool = False,
                   attachment_ids: Optional[List[int]] = None) -> Dict[str, Any]:
        """
        执行AI对话

        Args:
            user_id: 用户ID
            session_id: 会话ID，如果为None则创建新会话
            content: 用户输入的消息
            llm_model: LLM 模型名称（可选）
            max_tokens: 生成文本的最大长度
            temperature: 温度参数
            top_p: top_p参数
            system_prompt: 系统提示词

        Returns:
            包含用户消息、AI回复和会话信息的字典
        """
        system_prompt = system_prompt or PromptManager.get_template(PromptTemplate.QA_AI_CHAT_SYSTEM.value)
        user_message = None
        try:
            # 共享预处理
            prep = await self._prepare_chat(user_id, session_id, content, llm_model, system_prompt, attachment_ids)
            user_message = prep.user_message

            # 在 LLM 调用前提交预处理数据，释放数据库锁
            # 避免 LLM API 卡住时事务锁阻塞其他请求
            await self.qa_service.commit()
            self.logger.info("预处理数据已提交，数据库锁已释放", session_id=prep.session_id)

            # 使用 savepoint 保护 LLM 调用和 AI 消息保存
            # LLM 失败时 savepoint 自动回滚，避免部分写入
            async with self.db.begin_nested():
                # 生成AI回复
                self.logger.debug("[调试] 开始调用 LLM generate_text", session_id=prep.session_id)
                ai_response_content = await prep.llm_client.generate_text(
                    prompt=prep.conversation_history,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    enable_thinking=enable_thinking,
                )
                self.logger.debug(
                    "[调试] LLM 返回内容",
                    session_id=prep.session_id,
                    content_len=len(ai_response_content) if ai_response_content else 0,
                    content_preview=(ai_response_content or "")[:100],
                )

                # 添加AI回复到会话
                self.logger.debug("[调试] 开始 add_message 保存 AI 回复", session_id=prep.session_id)
                ai_message = await self.qa_service.add_message(
                    QARequest(
                        content=ai_response_content,
                        role="assistant",
                        session_id=prep.session_id
                    ),
                    user_id,
                )
                self.logger.debug(
                    "[调试] add_message 完成",
                    session_id=prep.session_id,
                    message_id=ai_message.id,
                    role=ai_message.role,
                    content_len=len(ai_message.content) if ai_message.content else 0,
                )
                # savepoint 成功退出时自动释放，无需手动 commit
                # 最终由 get_db 统一 commit

            result = {
                "session_id": prep.session_id,
                "user_message": {
                    "id": prep.user_message.id,
                    "content": prep.user_message.content,
                    "role": prep.user_message.role,
                    "created_at": prep.user_message.created_at,
                    "attachments": prep.attachments_info,
                },
                "ai_message": {
                    "id": ai_message.id,
                    "content": ai_message.content,
                    "role": ai_message.role,
                    "created_at": ai_message.created_at
                },
                "conversation_history": prep.conversation_history,
                "llm_model": llm_model,
            }

            return result

        except LLMServiceError:
            # LLM 调用失败：savepoint 已回滚 AI 消息部分
            # 清理已提交的用户消息作为安全网
            await self._cleanup_user_message(user_message)
            raise
        except Exception as e:
            # 其他异常：savepoint 已回滚 AI 消息部分
            # 同样清理已提交的用户消息作为安全网
            await self._cleanup_user_message(user_message)
            error_msg = f"对话服务异常: {str(e)}"
            self.logger.error(error_msg)
            raise LLMServiceError(error_msg, e)

    async def get_chat_history(
        self, session_id: str, user_id: int
    ) -> List[Dict[str, Any]]:
        """
        获取会话的聊天历史

        Args:
            session_id: 会话ID
            user_id: 用户ID

        Returns:
            聊天历史列表，包含用户和AI的消息
        """
        try:
            messages = await self.qa_service.get_session_messages(
                session_id, user_id
            )

            history = []
            for msg in messages:
                history.append({
                    "id": msg.id,
                    "content": msg.content,
                    "role": msg.role,
                    "created_at": msg.created_at
                })

            return history
        except QAError:
            raise
        except Exception as e:
            error_msg = f"获取聊天历史失败: {str(e)}"
            self.logger.error(error_msg, session_id=session_id, user_id=user_id)
            raise SessionManagementError(error_msg)

    async def clear_chat_history(
        self, session_id: str, user_id: int
    ) -> int:
        """
        清除聊天历史

        Args:
            session_id: 会话ID
            user_id: 用户ID

        Returns:
            删除的消息数量
        """
        try:
            count = await self.qa_service.delete_session(
                session_id, user_id
            )
            return count
        except QAError:
            raise
        except Exception as e:
            error_msg = f"清除聊天历史失败: {str(e)}"
            self.logger.error(error_msg, session_id=session_id, user_id=user_id)
            raise SessionManagementError(error_msg)

    async def chat_stream(
        self,
        user_id: int,
        session_id: Optional[str] = None,
        content: Optional[str] = None,
        llm_model: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        system_prompt: Optional[str] = None,
        enable_thinking: bool = False,
        attachment_ids: Optional[List[int]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式执行AI对话

        Args:
            user_id: 用户ID
            session_id: 会话ID，如果为None则创建新会话
            content: 用户输入的消息
            llm_model: LLM 模型名称（可选）
            max_tokens: 生成文本的最大长度
            temperature: 温度参数
            top_p: top_p参数
            system_prompt: 系统提示词

        Yields:
            str: SSE格式的流式数据
        """
        system_prompt = system_prompt or PromptManager.get_template(PromptTemplate.QA_AI_CHAT_SYSTEM.value)
        user_message = None
        try:
            # 共享预处理
            prep = await self._prepare_chat(user_id, session_id, content, llm_model, system_prompt, attachment_ids)
            user_message = prep.user_message
            session_id = prep.session_id

            # 在 LLM 调用前提交预处理数据，释放数据库锁
            # 避免 LLM 流式调用长时间占用时事务锁阻塞其他请求
            await self.qa_service.commit()
            self.logger.info("预处理数据已提交，数据库锁已释放（流式）", session_id=session_id)

            # 发送用户消息信息
            yield self._format_sse({
                "type": "user_message",
                "data": {
                    "id": prep.user_message.id,
                    "content": prep.user_message.content,
                    "role": prep.user_message.role,
                    "session_id": session_id,
                    "created_at": prep.user_message.created_at,
                    "attachments": prep.attachments_info,
                }
            })

            # 收集完整的AI回复
            full_response = ""

            # 流式生成AI回复（带心跳机制 + thinking 模式适配）
            raw_stream = prep.llm_client.generate_text_stream_structured(
                prompt=prep.conversation_history,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                enable_thinking=enable_thinking,
            )

            from src.shared.ai_models.base_model import StreamChunk
            async for chunk in stream_with_heartbeat_structured(raw_stream):
                # 心跳注释直接透传
                if isinstance(chunk, str):
                    yield chunk
                    continue
                if chunk.type == "reasoning":
                    yield self._format_sse({
                        "type": "reasoning",
                        "data": {
                            "content": chunk.text,
                            "session_id": session_id,
                        }
                    })
                else:
                    full_response += chunk.text
                    yield self._format_sse({
                        "type": "content",
                        "data": {
                            "content": chunk.text,
                            "session_id": session_id,
                        }
                    })

            # 保存完整的AI回复到数据库
            self.logger.debug(
                "[调试-流式] 开始 add_message 保存 AI 回复",
                session_id=session_id,
                content_len=len(full_response),
                content_preview=full_response[:100],
            )
            ai_message = await self.qa_service.add_message(
                QARequest(
                    content=full_response,
                    role="assistant",
                    session_id=session_id
                ),
                user_id,
            )
            self.logger.debug(
                "[调试-流式] add_message 完成",
                session_id=session_id,
                message_id=ai_message.id,
                role=ai_message.role,
            )
            # 显式提交 AI 消息（flush 不等于 commit）
            self.logger.debug("[调试-流式] 开始 commit AI 消息", session_id=session_id, message_id=ai_message.id)
            await self.qa_service.commit()
            self.logger.debug("[调试-流式] AI 回复已成功 commit 到数据库", session_id=session_id, message_id=ai_message.id)

            # 发送完成消息
            yield self._format_sse({
                "type": "done",
                "data": {
                    "id": ai_message.id,
                    "content": full_response,
                    "role": ai_message.role,
                    "created_at": ai_message.created_at,
                    "session_id": session_id,
                    "llm_model": llm_model,
                }
            })

        except LLMServiceError as e:
            # LLM 调用失败：用户未看到完整回复，清理用户消息
            self.logger.warning("流式对话 LLM 异常", session_id=session_id, error=str(e))
            await self._cleanup_user_message(user_message)
            yield self._format_sse({"type": "error", "content": str(e)})
        except QAError as e:
            # QA 服务异常：清理已提交的用户消息，避免残留孤立数据
            self.logger.warning("流式对话 QA 异常，清理用户消息", session_id=session_id, error=str(e))
            await self._cleanup_user_message(user_message)
            yield self._format_sse({"type": "error", "content": str(e)})
        except Exception as e:
            # 未知异常：清理已提交的用户消息，避免残留孤立数据
            error_msg = f"流式对话服务异常: {str(e)}"
            self.logger.error(error_msg, session_id=session_id, user_id=user_id)
            await self._cleanup_user_message(user_message)
            yield self._format_sse({"type": "error", "content": error_msg})

    async def _cleanup_user_message(self, user_message) -> None:
        """清理流式异常时残留的用户消息"""
        if user_message is None:
            return
        try:
            await self.qa_service.cleanup_message(user_message.id)
            await self.qa_service.commit()
        except Exception as e:
            self.logger.warning("清理用户消息失败", error=str(e))
            try:
                await self.qa_service.rollback()
            except Exception as rb_err:
                self.logger.warning("清理回滚失败", error=str(rb_err))

    # ========== 附件相关方法 ==========

    # 允许的文件类型及扩展名
    ALLOWED_FILE_TYPES = {"pdf", "docx", "txt", "md", "markdown", "jpg", "jpeg", "png", "gif", "webp"}
    IMAGE_FILE_TYPES = {"jpg", "jpeg", "png", "gif", "webp"}
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
    MAX_EXTRACTED_TEXT_LENGTH = 50000  # 50000 字符

    async def upload_attachment(
        self,
        user_id: int,
        file: UploadFile,
    ) -> Dict[str, Any]:
        """
        上传聊天附件

        Args:
            user_id: 用户ID
            file: 上传的文件

        Returns:
            上传结果（attachment_id, filename, file_type, file_size, status, message）
        """
        if not self.db or not self.minio_client:
            raise LLMServiceError("附件上传服务未初始化")

        # 验证文件类型
        filename = file.filename or "unknown"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "markdown":
            ext = "md"
        if ext not in self.ALLOWED_FILE_TYPES:
            raise InvalidMessageContentError(f"不支持的文件类型: {ext}，仅支持 {', '.join(sorted(self.ALLOWED_FILE_TYPES))}")

        # 读取文件内容
        file_data = await file.read()
        if len(file_data) > self.MAX_FILE_SIZE:
            raise InvalidMessageContentError(f"文件过大: {len(file_data)} 字节，最大允许 {self.MAX_FILE_SIZE // (1024*1024)}MB")

        # 上传到 MinIO
        storage_path = f"chat-attachments/{user_id}/{uuid4().hex}.{ext}"
        content_type = self.minio_client._get_content_type(filename)
        await self.minio_client.upload_file(storage_path, file_data, content_type)
        self.logger.info("附件已上传到 MinIO", user_id=user_id, path=storage_path, size=len(file_data))

        # 提取文本（图片类型跳过）
        extracted_text = None
        if ext not in self.IMAGE_FILE_TYPES:
            try:
                extracted_text = await self._extract_text_from_bytes(file_data, ext)
                if extracted_text and len(extracted_text) > self.MAX_EXTRACTED_TEXT_LENGTH:
                    extracted_text = extracted_text[:self.MAX_EXTRACTED_TEXT_LENGTH] + "\n\n[... 文档内容已截断 ...]"
            except Exception as e:
                self.logger.warning("提取文档文本失败", filename=filename, error=str(e))

        # 创建数据库记录
        attachment = await self.attachment_repo.create(
            user_id=user_id,
            filename=filename,
            file_type=ext,
            file_size=len(file_data),
            storage_path=storage_path,
            extracted_text=extracted_text,
        )

        self.logger.info(
            "聊天附件创建成功",
            attachment_id=attachment.id,
            filename=filename,
            text_length=len(extracted_text) if extracted_text else 0,
        )

        return {
            "attachment_id": attachment.id,
            "filename": filename,
            "file_type": ext,
            "file_size": len(file_data),
            "message": "附件上传成功" if extracted_text else "附件上传成功，但文本提取失败",
        }

    async def _extract_text_from_bytes(self, file_data: bytes, file_type: str) -> Optional[str]:
        """从文件字节中提取文本"""
        if file_type in ("txt", "md"):
            # 文本文件直接解码
            for encoding in ("utf-8", "gbk", "gb2312", "latin-1"):
                try:
                    return file_data.decode(encoding)
                except (UnicodeDecodeError, LookupError):
                    continue
            return None

        # PDF / DOCX 需要通过 DocumentProcessor 处理
        from src.shared.utils.document_readers.document_loader import DocumentProcessor

        with tempfile.NamedTemporaryFile(suffix=f".{file_type}", delete=False) as tmp:
            tmp.write(file_data)
            tmp_path = tmp.name

        try:
            processor = DocumentProcessor()
            docs = await processor.load_with_strategy(
                tmp_path,
                strategy="recursive",
                chunk_size=10000,
                chunk_overlap=0,
            )
            texts = [doc.get("text", "") or doc.get("content", "") for doc in docs]
            return "\n\n".join(texts) if texts else None
        finally:
            os.unlink(tmp_path)

    def _format_attachments_prompt(self, attachments: list) -> str:
        """将附件文本格式化为 XML 结构的 LLM 提示"""
        docs = []
        for att in attachments:
            text = att.extracted_text or "(无法提取文档文本)"
            docs.append(f'  <document filename="{att.filename}">\n{text}\n  </document>')
        return "<documents>\n" + "\n".join(docs) + "\n</documents>"

    async def _inject_attachments_to_context(
        self, session_id: str, context: list, user_id: Optional[int] = None, is_vlm: bool = False
    ) -> list:
        """扫描上下文中所有消息，为有附件的用户消息动态注入文档文本或图片"""
        if not self.attachment_repo or not self.db:
            return context

        from sqlalchemy import select
        from src.features.qa.models.question_answer import QuestionAnswer

        stmt = select(QuestionAnswer).where(
            QuestionAnswer.session_id == session_id,
            QuestionAnswer.role == "user",
            QuestionAnswer.extra.isnot(None),
        ).order_by(QuestionAnswer.created_at.asc())
        result = await self.db.execute(stmt)
        messages_with_extra = {m.id: m for m in result.scalars().all()}

        if not messages_with_extra:
            return context

        all_att_ids = []
        msg_att_map = {}
        for msg_id, msg in messages_with_extra.items():
            atts = msg.get_attachments() or []
            if atts:
                ids = [a["id"] for a in atts if "id" in a]
                if ids:
                    msg_att_map[msg_id] = ids
                    all_att_ids.extend(ids)

        if not all_att_ids:
            return context

        att_records = await self.attachment_repo.get_by_ids_and_user(all_att_ids, user_id) if user_id else await self.attachment_repo.get_by_ids(all_att_ids)
        att_by_id = {a.id: a for a in att_records}

        IMAGE_TYPES = {"jpg", "jpeg", "png", "gif", "webp"}
        injected = 0
        for item in context:
            if item.get("role") != "user":
                continue
            msg_id = item.get("id")
            if msg_id not in msg_att_map:
                continue
            records = [att_by_id[aid] for aid in msg_att_map[msg_id] if aid in att_by_id]
            if not records:
                continue

            doc_records = [r for r in records if r.file_type not in IMAGE_TYPES]
            img_records = [r for r in records if r.file_type in IMAGE_TYPES]

            parts: list = []
            original_content = item.get("content", "")

            # 文档 → XML
            if doc_records:
                xml = self._format_attachments_prompt(doc_records)
                parts.append({"type": "text", "text": xml})

            # 图片 → multimodal（仅 VLM）
            if img_records and is_vlm and self.minio_client:
                for img in img_records:
                    try:
                        b64_data = await self._download_attachment_as_base64(img)
                        if b64_data:
                            mime = f"image/{img.file_type}"
                            parts.append({"type": "text", "text": f"[图片: {img.filename}]"})
                            parts.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64_data}"},
                            })
                    except Exception as e:
                        self.logger.warning("图片下载失败", filename=img.filename, error=str(e))
                        parts.append({"type": "text", "text": f"[图片: {img.filename}（加载失败）]"})
            elif img_records and not is_vlm:
                for img in img_records:
                    parts.append({"type": "text", "text": f"[图片: {img.filename}（当前模型不支持视觉）]"})

            if parts:
                parts.append({"type": "text", "text": f"\n\n用户问题：{original_content}"})
                item["content"] = parts
            elif doc_records:
                xml = self._format_attachments_prompt(doc_records)
                item["content"] = f"{xml}\n\n用户问题：{original_content}"
            injected += 1

        if injected:
            self.logger.info("附件文本已注入上下文", session_id=session_id, injected_count=injected)

        return context

    async def _is_vlm_model(self, model_name: str, user_id: int) -> bool:
        """判断模型是否为 VLM 视觉模型"""
        if not self.model_config_service or not model_name:
            return False
        try:
            vlm_models = await self.model_config_service.list_available_models(user_id, "vlm")
            return model_name in vlm_models
        except Exception:
            return False

    async def _download_attachment_as_base64(self, attachment) -> Optional[str]:
        """从 MinIO 下载附件并转为 base64"""
        if not self.minio_client:
            return None
        try:
            bucket = self.minio_client.default_bucket
            data = await self.minio_client.download_document(bucket, attachment.storage_path)
            return base64.b64encode(data).decode()
        except Exception as e:
            self.logger.warning("MinIO 下载失败", path=attachment.storage_path, error=str(e))
            return None

    # ========== SSE 格式化 ==========

    def _format_sse(self, data: Dict[str, Any]) -> str:
        """
        格式化为SSE（Server-Sent Events）格式

        Args:
            data: 要发送的数据字典

        Returns:
            str: SSE格式的字符串
        """
        return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
