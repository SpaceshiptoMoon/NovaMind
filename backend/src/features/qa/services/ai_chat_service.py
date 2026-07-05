"""
AI对话服务层
使用结构化日志记录
支持用户配置的 LLM 模型
支持文档附件上传和分析
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, AsyncGenerator, Tuple, TYPE_CHECKING
from uuid import uuid4
import base64
import json
import tempfile

from src.shared.utils.text_processing.token_counter import TokenCounter
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
from src.shared.storage.minio_client import IMAGE_FILE_TYPES
from src.features.qa.services.qa_service import QAService
from src.features.qa.schemas.qa import QARequest
from src.features.qa.repository.chat_attachment_repository import ChatAttachmentRepository
from src.features.qa.api.exceptions import (
    QAError,
    LLMServiceError,
    InvalidMessageContentError,
    SessionManagementError,
)


# 分级拒答：检索为空时的固定兜底文案（跳过 LLM 调用）
REFUSAL_ANSWER_TEXT = (
    "抱歉，未在所绑定的知识库中找到与该问题相关的资料，无法给出可靠回答。"
    "请尝试更换问题表述、绑定其他知识库，或关闭拒答开关。"
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
    sources: list = field(default_factory=list)  # 检索来源引用（与正文 [1][2] 角标对齐）
    answer_status: str = "answered"  # answered / refused / low_confidence
    confidence: Optional[float] = None
    refused: bool = False  # 检索为空时短路跳过 LLM
    # 生效的生成参数（请求 > 会话表 llm_config > 默认，由 _prepare_chat 合并）
    max_tokens: int = 2048
    temperature: float = 0.7
    top_p: float = 0.8
    traces: list = field(default_factory=list)


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
        self._token_counter = TokenCounter()

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
            # 如果没有指定模型，获取用户配置的默认
            if not llm_model:
                llm_model = await self.model_config_service.get_user_default_model_name(user_id, "llm")

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
        attachment_ids: Optional[List[int]] = None,
        enable_web_search: bool = False,
    ) -> ChatPreparation:
        """
        流式/非流式对话共享的预处理逻辑

        Args:
            user_id: 用户ID
            session_id: 会话ID
            content: 用户消息内容
            llm_model: LLM 模型名称

        Returns:
            ChatPreparation: 预处理结果
        """
        # 验证输入
        if not content or not content.strip():
            raise InvalidMessageContentError("消息内容不能为空")

        # 创建或获取会话ID
        session_id = session_id or str(uuid4())

        # 确保会话配置存在（返回值用于会话级自动 RAG 绑定兜底）
        session_config = await self.qa_service.ensure_session_config(session_id, user_id)

        # 生成参数：全部从会话表 llm_config 读（property 已兜底 null/缺失 → 默认值）
        eff_max_tokens = session_config.llm_max_tokens if session_config else 2048
        eff_temperature = session_config.llm_temperature if session_config else 0.7
        eff_top_p = session_config.llm_top_p if session_config else 0.8
        # system_prompt：会话表 llm_config > QA 模板
        system_prompt = (session_config.llm_system_prompt if session_config else None) or PromptManager.get_template(PromptTemplate.QA_AI_CHAT_SYSTEM.value)

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

        # ===== 检索增强 + 会话级自动 RAG + 分级拒答 =====
        # 联网：请求开关（前端主输入区）；RAG：完全由会话表 auto_rag 决定（无请求开关）
        do_web = enable_web_search
        do_rag = bool(session_config and getattr(session_config, "auto_rag", False))

        # RAG 细节（空间/库/拒答/阈值/模式/top_k）统一从会话表读；
        # 前端不再传 space_id/kb_id/kb_ids/enable_refusal，避免请求与会话表两套配置源冲突
        rag_space = session_config.rag_space_id if session_config else None
        rag_kb_ids = session_config.rag_kb_ids if session_config else []
        refusal_on = session_config.rag_refusal_enabled if session_config else False
        score_threshold = session_config.rag_score_threshold if session_config else 0.3
        search_mode = session_config.rag_search_mode if session_config else "content_hybrid"
        top_k = session_config.rag_top_k if session_config else 5

        prep_sources: List[dict] = []
        prep_refused = False
        prep_status = "answered"
        prep_confidence: Optional[float] = None
        prep_raw_count = 0             # 过滤前原始检索数量（trace 区分“无结果”vs“被阈值过滤”）
        grade_traces: List[dict] = []  # grade→retry 每轮打分记录

        # ===== Query Rewriting（可插拔组件） =====
        search_queries = [content]
        rewrite_strategy = getattr(session_config, "rag_query_rewriting", "none") if session_config else "none"
        rewrite_degraded = False  # 用户开了改写但实际降级（LLM 失败/不可用）→ 透传到 trace
        if rewrite_strategy != "none" and (do_web or do_rag):
            from src.features.qa.services.query_rewriter import QueryRewriter, RewriteStrategy
            llm_for_rewrite = await self.qa_service._get_compression_llm_client(user_id) if self.qa_service else None
            if llm_for_rewrite:
                rewriter = QueryRewriter(llm_for_rewrite)
                ctx_history = [
                    {"role": m.get("role"), "content": m.get("content")}
                    for m in context if m.get("role") in ("user", "assistant")
                ]
                result = await rewriter.rewrite(
                    query=content, strategy=RewriteStrategy(rewrite_strategy),
                    history=ctx_history,
                )
                if result.queries:
                    search_queries = result.queries
                rewrite_degraded = result.degraded
            else:
                # 用户配置了改写策略，但拿不到改写 LLM → 实际未执行，标记降级
                rewrite_degraded = True

        if do_web or do_rag:
            # refusal_on 启用阈值过滤
            effective_threshold = score_threshold if refusal_on else None

            if len(search_queries) == 1:
                grade_retry = getattr(session_config, "rag_grade_retry_enabled", False) if session_config else False
                if grade_retry:
                    from src.features.qa.services.grade_retrier import GradeRetrier
                    llm_for_grade = await self.qa_service._get_compression_llm_client(user_id) if self.qa_service else None
                    if llm_for_grade:
                        retrier = GradeRetrier(llm_for_grade)
                        passing = getattr(session_config, "rag_grade_retry_passing_score", 5)

                        last_raw_count = 0  # 闭包捕获最近一次过滤前数量，供 trace 区分成因

                        async def _search_fn(q, mode, threshold):
                            nonlocal last_raw_count
                            sp, srcs, rc = await self._augment_system_prompt_with_retrieval(
                                system_prompt=system_prompt, query=q, user_id=user_id,
                                enable_web_search=do_web, enable_rag=do_rag,
                                space_id=rag_space, kb_ids=rag_kb_ids,
                                top_k=top_k, search_mode=mode,
                                score_threshold=threshold,
                            )
                            last_raw_count = rc
                            return srcs, sp

                        prep_sources, system_prompt, grade_traces = await retrier.search_with_retry(
                            query=search_queries[0], search_fn=_search_fn,
                            initial_mode=search_mode,
                            score_threshold=effective_threshold,
                            passing_score=passing,
                        )
                        prep_raw_count = last_raw_count
                    else:
                        system_prompt, prep_sources, prep_raw_count = await self._augment_system_prompt_with_retrieval(
                            system_prompt=system_prompt, query=search_queries[0], user_id=user_id,
                            enable_web_search=do_web, enable_rag=do_rag,
                            space_id=rag_space, kb_ids=rag_kb_ids,
                            top_k=top_k, search_mode=search_mode,
                            score_threshold=effective_threshold,
                        )
                else:
                    system_prompt, prep_sources, prep_raw_count = await self._augment_system_prompt_with_retrieval(
                        system_prompt=system_prompt, query=search_queries[0], user_id=user_id,
                        enable_web_search=do_web, enable_rag=do_rag,
                        space_id=rag_space, kb_ids=rag_kb_ids,
                        top_k=top_k, search_mode=search_mode,
                        score_threshold=effective_threshold,
                    )
            else:
                # DECOMPOSE：多子查询并发检索 + 合并去重；开启 grade 时整体打分 + 重试（设计A）
                grade_retry = getattr(session_config, "rag_grade_retry_enabled", False) if session_config else False
                llm_for_grade = (await self.qa_service._get_compression_llm_client(user_id) if self.qa_service else None) if grade_retry else None

                if grade_retry and llm_for_grade:
                    # grade 开 + 有 grade LLM：循环「检索所有子查询→合并→用原问题整体打分」，不通过则切 mode + 降阈值重检索
                    from src.features.qa.services.grade_retrier import GradeRetrier
                    retrier = GradeRetrier(llm_for_grade)
                    passing = getattr(session_config, "rag_grade_retry_passing_score", 5)
                    # mode 序列：用户配的 search_mode 首轮优先（复用单查询 search_with_retry 的语义）
                    default_modes = ["content_hybrid", "content_bm25", "all_hybrid"]
                    modes = [search_mode] + [m for m in default_modes if m != search_mode]
                    max_retries = 2
                    last_deduped: List[dict] = []
                    last_raw_count = 0
                    for attempt in range(max_retries + 1):
                        mode = modes[min(attempt, len(modes) - 1)]
                        threshold = effective_threshold * (0.7 ** attempt) if effective_threshold is not None else None
                        deduped, rc = await self._decompose_retrieve(
                            search_queries, system_prompt, user_id, do_web, do_rag,
                            rag_space, rag_kb_ids, top_k, mode, threshold,
                        )
                        if not deduped:
                            grade_traces.append({
                                "type": "grade", "attempt": attempt, "mode": mode,
                                "threshold": round(threshold, 4) if threshold is not None else None,
                                "score": 0, "passed": False, "reason": "无检索结果",
                            })
                            last_deduped, last_raw_count = deduped, rc
                            continue
                        grade_result = await retrier.grade(content, deduped, passing)
                        grade_traces.append({
                            "type": "grade", "attempt": attempt, "mode": mode,
                            "threshold": round(threshold, 4) if threshold is not None else None,
                            "score": grade_result.score, "passed": grade_result.passed,
                            "reason": grade_result.reason,
                        })
                        last_deduped, last_raw_count = deduped, rc
                        if grade_result.passed:
                            break
                    prep_sources = last_deduped
                    prep_raw_count = last_raw_count
                    if prep_sources:
                        system_prompt = self._build_augmented_prompt(system_prompt, prep_sources)
                else:
                    # grade 关闭或无 grade LLM：单次 DECOMPOSE 检索（行为同改造前）
                    deduped, rc = await self._decompose_retrieve(
                        search_queries, system_prompt, user_id, do_web, do_rag,
                        rag_space, rag_kb_ids, top_k, search_mode, effective_threshold,
                    )
                    prep_sources = deduped
                    prep_raw_count = rc
                    if prep_sources:
                        system_prompt = self._build_augmented_prompt(system_prompt, prep_sources)

            # 分级拒答：仅 RAG 模式且过滤后无来源 → 拒答（联网搜索时放行，LLM 可基于自身知识回答）
            if refusal_on and not prep_sources and not do_web:
                prep_refused = True
                prep_status = "refused"
            # 低分来源已被阈值过滤，留下的均合格，不再有 low_confidence 分支

        # 组建对话历史 = 系统提示词 + 压缩内容(摘要) + 新消息，三者独立。
        # 系统提示词不参与压缩（恒定，从不进 get_conversation_context）；
        # get_conversation_context 已完成「摘要+新消息」的阈值判断与压缩，
        # 返回的 context 形如 [{system: 摘要}, 最近消息...]，此处只在外层拼上系统提示词。
        conversation_history = [
            {"role": "system", "content": system_prompt}
        ] + context

        # 获取 LLM 客户端
        llm_client = await self._get_llm_client(user_id, llm_model)

        # 构建检索链路 trace（Rewrite → Search → Grade）
        traces = []
        if search_queries and (search_queries[0] != content or rewrite_degraded):
            traces.append({
                "type": "rewrite", "original": content,
                "rewritten": search_queries[0], "strategy": rewrite_strategy,
                "degraded": rewrite_degraded,
            })
        if prep_sources:
            web_count = sum(1 for s in prep_sources if s.get("kind") == "web")
            kb_count = len(prep_sources) - web_count
            mode_label = "web" if do_web and not do_rag else search_mode
            traces.append({"type": "search", "mode": mode_label, "sources_count": len(prep_sources), "web_count": web_count, "kb_count": kb_count})
        elif do_rag:
            # 区分成因：raw_count==0 表示真无结果；>0 表示检索到了但全被阈值过滤
            note = "无匹配结果" if prep_raw_count == 0 else f"检索到 {prep_raw_count} 条但均低于阈值被过滤"
            traces.append({"type": "search", "mode": search_mode, "sources_count": 0, "note": note})
        # grade→retry 每轮打分（开启自评估时才有）
        if grade_traces:
            traces.extend(grade_traces)

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
            sources=prep_sources,
            answer_status=prep_status,
            confidence=prep_confidence,
            refused=prep_refused,
            max_tokens=eff_max_tokens,
            temperature=eff_temperature,
            top_p=eff_top_p,
            traces=traces,
        )

    def _build_augmented_prompt(self, system_prompt: str, sources: List[dict]) -> str:
        """将已编号的来源列表拼接进 system_prompt，生成增强 prompt。

        角标 [i] 与 source["index"] 对齐；web/kb 分组渲染。
        单查询路径与 DECOMPOSE（合并去重、统一重新编号后）共用此方法。
        """
        web_items = [s for s in sources if s.get("kind") == "web"]
        kb_items = [s for s in sources if s.get("kind") == "kb"]
        ref_lines: List[str] = []
        if web_items:
            ref_lines.append("<web-search-results>")
            for s in web_items:
                ref_lines.append(
                    f"[{s['index']}] {s.get('document_name') or ''}\n"
                    f"URL: {s.get('url', '')}\n{s.get('snippet', '')}"
                )
            ref_lines.append("</web-search-results>")
        if kb_items:
            ref_lines.append("<knowledge-base-context>")
            for s in kb_items:
                header = f"[{s['index']}]" + (f" {s.get('document_name')}" if s.get("document_name") else "")
                ref_lines.append(f"{header}\n{s.get('snippet', '')}")
            ref_lines.append("</knowledge-base-context>")

        reference = "\n".join(ref_lines)
        return (
            f"{system_prompt}\n\n"
            "以下是为回答用户问题检索到的参考资料，请严格基于这些资料作答：\n"
            "1. 使用参考资料中的信息时，在对应句子末尾标注来源序号，如 [1]、[2]，序号与下方参考资料列表一致；\n"
            "2. 优先使用参考资料，资料不足时可结合自身知识补充，但不要编造资料中不存在的事实；\n"
            "3. 若参考资料完全不足以回答，请直接说明无法从现有资料中找到答案。\n\n"
            f"{reference}"
        )

    async def _augment_system_prompt_with_retrieval(
        self,
        system_prompt: str,
        query: str,
        user_id: int,
        enable_web_search: bool,
        enable_rag: bool,
        space_id: Optional[int],
        kb_ids: Optional[List[int]] = None,
        top_k: int = 5,
        search_mode: str = "content_hybrid",
        score_threshold: Optional[float] = None,
    ) -> Tuple[str, List[dict], int]:
        """执行联网/知识库检索，返回 (增强后的 system_prompt, 统一编号的来源列表)。

        来源列表 index 与 prompt 内 [1][2] 角标对齐；任一检索失败均降级跳过，不阻塞对话。

        score_threshold 非空时（refusal_on 启用阈值过滤），丢弃得分低于阈值的 KB 来源——
        低相关噪声不注入上下文，LLM 只看高质量结果。
        """
        raw_sources: List[dict] = []

        if enable_web_search:
            try:
                res = await self._retrieve_web(query=query, max_results=5)
                if res:
                    raw_sources.extend(res[1])
                    self.logger.info("联网搜索完成", count=len(res[1]))
                else:
                    self.logger.warning("联网搜索无结果（DuckDuckGo 可能限流或不可用）")
            except Exception as e:
                self.logger.warning("联网搜索失败，跳过", error=str(e))

        if enable_rag:
            try:
                res = await self._retrieve_knowledge(
                    query=query, user_id=user_id, space_id=space_id,
                    kb_ids=kb_ids, top_k=top_k, search_mode=search_mode,
                )
                if res:
                    raw_sources.extend(res[1])
            except Exception as e:
                self.logger.warning("知识库检索失败，跳过", error=str(e))

        web_src = sum(1 for s in raw_sources if s.get("kind") == "web")
        kb_src = sum(1 for s in raw_sources if s.get("kind") == "kb")
        self.logger.info("检索原始结果（过滤前）", web_count=web_src, kb_count=kb_src)
        raw_count = len(raw_sources)  # 过滤前数量，透传给 trace 区分“无结果”与“被阈值过滤”

        # 阈值过滤：丢弃低分 KB 来源（web 来源无阈值语义，保留）
        if score_threshold is not None:
            raw_sources = [
                s for s in raw_sources
                if s.get("kind") != "kb" or (s.get("score") or 0) >= score_threshold
            ]

        if not raw_sources:
            return system_prompt, [], raw_count

        # 统一重新编号（web + kb 合并后 index 连续，与正文角标一致）
        sources: List[dict] = []
        for i, s in enumerate(raw_sources, start=1):
            s["index"] = i
            sources.append(s)

        return self._build_augmented_prompt(system_prompt, sources), sources, raw_count

    async def _decompose_retrieve(
        self,
        search_queries: List[str],
        system_prompt: str,
        user_id: int,
        enable_web_search: bool,
        enable_rag: bool,
        space_id: Optional[int],
        kb_ids: Optional[List[int]],
        top_k: int,
        search_mode: str,
        score_threshold: Optional[float],
    ) -> Tuple[List[dict], int]:
        """DECOMPOSE：并发检索所有子查询，合并去重 + 全局重编号。

        返回 (去重重编号后的 sources, 各子查询过滤前数量之和)。
        任一子查询失败仅 warning 跳过，不阻塞整体。
        """
        import asyncio
        tasks = [
            self._augment_system_prompt_with_retrieval(
                system_prompt=system_prompt, query=sq, user_id=user_id,
                enable_web_search=enable_web_search, enable_rag=enable_rag,
                space_id=space_id, kb_ids=kb_ids,
                top_k=top_k, search_mode=search_mode,
                score_threshold=score_threshold,
            )
            for sq in search_queries
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_sources: List[dict] = []
        raw_count = 0
        for r in results:
            if isinstance(r, Exception):
                self.logger.warning("DECOMPOSE 子检索失败", error=str(r))
            else:
                all_sources.extend(r[1])
                raw_count += r[2]  # 各子查询过滤前数量之和
        # 跨子查询去重（web 按 url、kb 按 chunk_id），避免同一资料被重复编号/注入
        seen: set = set()
        deduped: List[dict] = []
        for s in all_sources:
            key = s.get("url") if s.get("kind") == "web" else s.get("chunk_id")
            if key is not None and key in seen:
                continue
            if key is not None:
                seen.add(key)
            deduped.append(s)
        # 全局统一重新编号：子查询各自从 1 编号，合并后需重排以保证角标连续唯一
        for i, s in enumerate(deduped, start=1):
            s["index"] = i
        return deduped, raw_count

    async def _retrieve_web(self, query: str, max_results: int = 5) -> Optional[Tuple[str, List[dict]]]:
        """联网搜索，返回 (参考资料块文本, 结构化来源列表)。复用 deep_research 的 DuckDuckGo 服务"""
        from src.features.deep_research.services.duckduckgo_service import (
            DuckDuckGoSearchService,
        )

        service = DuckDuckGoSearchService()
        results = await service.search(query=query, max_results=max_results)
        self.logger.info("联网搜索原始返回", count=len(results) if results else 0, query=query[:50])
        if not results:
            return None

        sources: List[dict] = []
        lines: List[str] = ["<web-search-results>"]
        for i, r in enumerate(results, start=1):
            title = self._sanitize(getattr(r, "title", ""))
            url = getattr(r, "url", "")
            snippet = self._sanitize(getattr(r, "content", ""))
            sources.append({
                "index": i,
                "kind": "web",
                "document_name": title or None,
                "url": url,
                "snippet": snippet,
            })
            lines.append(f"[{i}] {title}\nURL: {url}\n{snippet}")
        lines.append("</web-search-results>")
        return "\n".join(lines), sources

    async def _retrieve_knowledge(
        self,
        query: str,
        user_id: int,
        space_id: Optional[int],
        kb_ids: Optional[List[int]] = None,
        top_k: int = 5,
        search_mode: str = "content_hybrid",
    ) -> Optional[Tuple[str, List[dict]]]:
        """知识库检索，返回 (参考资料块文本, 结构化来源列表)。复用 knowledge_space 的 SearchService"""
        if not space_id:
            self.logger.warning("RAG 开关已开但未指定 space_id，跳过知识库检索")
            return None

        from src.features.knowledge_space.services.search_service import SearchService
        from src.features.knowledge_space.schemas.search_schema import SearchRequest
        from src.shared.clients import get_elasticsearch_client

        search_request = SearchRequest(query=query, search_mode=search_mode, top_k=top_k)
        es_client = await get_elasticsearch_client()
        model_config_service = self.model_config_service
        if model_config_service is None:
            from src.features.user.services.model_config_service import ModelConfigService
            model_config_service = ModelConfigService(self.db)
        search_service = SearchService(self.db, es_client, model_config_service)

        # 确定检索的知识库列表：kb_ids > 空间下全部（前 3 个）
        if kb_ids:
            target_kb_ids: List[int] = list(kb_ids)
        else:
            from src.features.knowledge_space.repository.knowledge_base_repository import (
                KnowledgeBaseRepository,
            )
            kb_repo = KnowledgeBaseRepository(self.db)
            kbs = await kb_repo.get_by_space(space_id)
            target_kb_ids = [kb.id for kb in kbs[:3]]

        if not target_kb_ids:
            return None

        all_results: List[Dict[str, Any]] = []
        for tid in target_kb_ids:
            try:
                r = await search_service.search(
                    space_id=space_id, kb_id=tid, user_id=user_id, request=search_request
                )
                all_results.extend(r.get("results", []))
            except Exception as e:
                self.logger.warning("知识库检索失败，跳过", kb_id=tid, error=str(e))

        if not all_results:
            return None

        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        results = all_results[:top_k]

        sources: List[dict] = []
        lines: List[str] = ["<knowledge-base-context>"]
        for i, r in enumerate(results, start=1):
            file_info = r.get("file_info") or {}
            metadata = r.get("metadata") or {}
            filename = file_info.get("filename", "")
            snippet = self._sanitize(r.get("content", ""))[:800]
            sources.append({
                "index": i,
                "kind": "kb",
                "document_id": r.get("document_id"),
                "document_name": filename or None,
                "kb_id": r.get("kb_id"),
                "chunk_id": r.get("chunk_id"),
                "score": r.get("score"),
                "snippet": snippet,
                "page": metadata.get("page"),
            })
            header = f"[{i}]" + (f" {filename}" if filename else "")
            lines.append(f"{header}\n{snippet}")
        lines.append("</knowledge-base-context>")
        return "\n".join(lines), sources

    @staticmethod
    def _sanitize(text: Any) -> str:
        """清理检索文本，剥离 XML 分隔标记以防 prompt 注入"""
        if not text:
            return ""
        if not isinstance(text, str):
            text = str(text)
        for tag in (
            "<web-search-results>", "</web-search-results>",
            "<knowledge-base-context>", "</knowledge-base-context>",
        ):
            text = text.replace(tag, "")
        return text.strip()

    async def chat(self,
                   user_id: int,
                   session_id: Optional[str] = None,
                   content: Optional[str] = None,
                   llm_model: Optional[str] = None,
                   enable_thinking: bool = False,
                   attachment_ids: Optional[List[int]] = None,
                   enable_web_search: bool = False) -> Dict[str, Any]:
        """
        执行AI对话

        Args:
            user_id: 用户ID
            session_id: 会话ID，如果为None则创建新会话
            content: 用户输入的消息
            llm_model: LLM 模型名称（可选）

        Returns:
            包含用户消息、AI回复和会话信息的字典
        """
        user_message = None
        try:
            # 共享预处理
            prep = await self._prepare_chat(
                user_id, session_id, content, llm_model, attachment_ids,
                enable_web_search=enable_web_search,
            )
            user_message = prep.user_message

            # 在 LLM 调用前提交预处理数据，释放数据库锁
            # 避免 LLM API 卡住时事务锁阻塞其他请求
            await self.qa_service.commit()
            self.logger.info("预处理数据已提交，数据库锁已释放", session_id=prep.session_id)

            # 分级拒答：检索完全为空时短路跳过 LLM，直接返回固定文案
            if prep.refused:
                async with self.db.begin_nested():
                    ai_response_content = REFUSAL_ANSWER_TEXT
                    ai_message = await self.qa_service.add_message(
                        QARequest(
                            content=ai_response_content,
                            role="assistant",
                            session_id=prep.session_id,
                            extra=self._build_ai_extra(prep),
                        ),
                        user_id,
                    )
            else:
                # 使用 savepoint 保护 LLM 调用和 AI 消息保存
                # LLM 失败时 savepoint 自动回滚，避免部分写入
                async with self.db.begin_nested():
                    # 生成AI回复
                    self.logger.debug("[调试] 开始调用 LLM generate_text", session_id=prep.session_id)
                    ai_response_content = await prep.llm_client.generate_text(
                        prompt=prep.conversation_history,
                        max_tokens=prep.max_tokens,
                        temperature=prep.temperature,
                        top_p=prep.top_p,
                        enable_thinking=enable_thinking,
                    )
                    self.logger.debug(
                        "[调试] LLM 返回内容",
                        session_id=prep.session_id,
                        content_len=len(ai_response_content) if ai_response_content else 0,
                        content_preview=(ai_response_content or "")[:100],
                    )

                    # 添加AI回复到会话（落库 sources/answer_status 到 extra）
                    self.logger.debug("[调试] 开始 add_message 保存 AI 回复", session_id=prep.session_id)
                    _ai_extra = self._build_ai_extra(prep)
                    ai_message = await self.qa_service.add_message(
                        QARequest(
                            content=ai_response_content,
                            role="assistant",
                            session_id=prep.session_id,
                            extra=_ai_extra,
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
                    "created_at": ai_message.created_at,
                    "sources": prep.sources,
                    "answer_status": prep.answer_status,
                    "confidence": prep.confidence,
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
        enable_thinking: bool = False,
        attachment_ids: Optional[List[int]] = None,
        enable_web_search: bool = False,
    ) -> AsyncGenerator[str, None]:
        """
        流式执行AI对话

        Args:
            user_id: 用户ID
            session_id: 会话ID，如果为None则创建新会话
            content: 用户输入的消息
            llm_model: LLM 模型名称（可选）

        Yields:
            str: SSE格式的流式数据
        """
        user_message = None
        try:
            # 共享预处理
            prep = await self._prepare_chat(
                user_id, session_id, content, llm_model, attachment_ids,
                enable_web_search=enable_web_search,
            )
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

            # 检索来源事件（在正文流式前下发，供前端渲染引用卡片）
            if prep.sources:
                yield self._format_sse({
                    "type": "sources",
                    "data": {
                        "sources": prep.sources,
                        "answer_status": prep.answer_status,
                        "confidence": prep.confidence,
                        "session_id": session_id,
                    }
                })

            # 检索链路 Trace 事件（Rewrite → Search → Grade）
            if prep.traces:
                for t in prep.traces:
                    yield self._format_sse({
                        "type": "trace",
                        "data": {**t, "session_id": session_id},
                    })

            # 分级拒答：检索完全为空时短路跳过 LLM
            if prep.refused:
                full_response = REFUSAL_ANSWER_TEXT
                ai_message = await self.qa_service.add_message(
                    QARequest(
                        content=full_response,
                        role="assistant",
                        session_id=session_id,
                        extra=self._build_ai_extra(prep),
                    ),
                    user_id,
                )
                await self.qa_service.commit()
            else:
                # 收集完整的AI回复
                full_response = ""

                # 流式生成AI回复（带心跳机制 + thinking 模式适配）
                raw_stream = prep.llm_client.generate_text_stream_structured(
                    prompt=prep.conversation_history,
                    max_tokens=prep.max_tokens,
                    temperature=prep.temperature,
                    top_p=prep.top_p,
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

                # 保存完整的AI回复到数据库（落库 sources/answer_status 到 extra）
                _ai_extra = self._build_ai_extra(prep)
                ai_message = await self.qa_service.add_message(
                    QARequest(
                        content=full_response,
                        role="assistant",
                        session_id=session_id,
                        extra=_ai_extra,
                    ),
                    user_id,
                )
                await self.qa_service.commit()

            # 发送完成消息（含来源与回答状态，前端兜底渲染）
            yield self._format_sse({
                "type": "done",
                "data": {
                    "id": ai_message.id,
                    "content": full_response,
                    "role": ai_message.role,
                    "created_at": ai_message.created_at,
                    "session_id": session_id,
                    "llm_model": llm_model,
                    "sources": prep.sources,
                    "answer_status": prep.answer_status,
                    "confidence": prep.confidence,
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

    def _build_ai_extra(self, prep: ChatPreparation) -> Optional[dict]:
        """构造 AI 消息 extra（sources/answer_status/confidence）。

        拒答/低置信/有检索来源时落库；正常回答且无来源时返回 None（不写 extra）。
        chat() 与 chat_stream() 的拒答/正常分支共用，避免 4 处重复构造。
        """
        if prep.sources or prep.answer_status != "answered":
            return {
                "sources": prep.sources,
                "answer_status": prep.answer_status,
                "confidence": prep.confidence,
            }
        return None

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
    IMAGE_FILE_TYPES = IMAGE_FILE_TYPES  # 收敛到 minio_client 唯一定义
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
    MAX_EXTRACTED_TEXT_LENGTH = 50000  # 50000 字符
    # 附件注入 token 预算：所有文档附件合计不超此值，避免撑爆上下文
    ATTACHMENT_TOKEN_BUDGET = 20000   # 总预算
    ATTACHMENT_MIN_KEEP = 2000        # 剩余 ≥ 此值才截断到剩余（否则走头部保留）
    ATTACHMENT_HEAD_KEEP = 800        # 预算耗尽后，每个老附件至少保留的头部 token

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

        # 验证文件内容（魔术字节校验，防止文件伪装攻击）
        from src.shared.utils.file_validator import validate_file
        file_info = validate_file(
            content=file_data,
            filename=filename,
            allowed_extensions=self.ALLOWED_FILE_TYPES,
        )
        if not file_info.is_valid:
            raise InvalidMessageContentError(f"文件内容与类型不匹配: {file_info.validation_message}")

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

    def _format_attachments_prompt(
        self, attachments: list, max_tokens: Optional[int] = None,
    ) -> str:
        """将附件文本格式化为 XML 结构的 LLM 提示。

        max_tokens 非空时，所有附件合计不超过该 token 数：
        按顺序累计，超出预算的附件截断到剩余预算或标记省略。
        """
        docs = []
        used = 0
        for att in attachments:
            text = att.extracted_text or "(无法提取文档文本)"
            if max_tokens is not None:
                remaining = max_tokens - used
                text_tokens = self._token_counter.count_tokens(text)
                if remaining <= 0:
                    text = "[...内容因附件预算省略...]"
                elif text_tokens > remaining:
                    # 截断到剩余预算（token→char 粗估，中文偏保守）
                    char_limit = max(100, int(remaining * 2.5))
                    text = text[:char_limit] + "\n[...内容已截断...]"
                    used = max_tokens
                else:
                    used += text_tokens
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
        # 收集 context 里带附件的 user 消息（保持 context 顺序：旧→新）
        items_with_att = [
            item for item in context
            if item.get("role") == "user" and item.get("id") in msg_att_map
        ]
        if not items_with_att:
            return context

        # 预留制：先统计文档附件总数，每个预分配 HEAD_KEEP 作为必保阅读量
        reserved = 0
        for item in reversed(items_with_att):
            msg_id = item.get("id")
            records = [att_by_id[aid] for aid in msg_att_map.get(msg_id, []) if aid in att_by_id]
            if not records:
                continue
            doc_records = [r for r in records if r.file_type not in IMAGE_TYPES]
            if doc_records:
                reserved += len(doc_records) * self.ATTACHMENT_HEAD_KEEP
        remaining_budget = max(0, self.ATTACHMENT_TOKEN_BUDGET - reserved)

        injected = 0
        # 反向遍历：最近的消息优先占用剩余预算（全量），老的逐级截断 / 头部保底
        for item in reversed(items_with_att):
            msg_id = item.get("id")
            records = [att_by_id[aid] for aid in msg_att_map.get(msg_id, []) if aid in att_by_id]
            if not records:
                continue

            doc_records = [r for r in records if r.file_type not in IMAGE_TYPES]
            img_records = [r for r in records if r.file_type in IMAGE_TYPES]

            parts: list = []
            original_content = item.get("content", "")

            # 文档附件：每个至少 HEAD_KEEP 保底（已预留），剩余预算从最近开始按全量/截断分配
            if doc_records:
                full_xml = self._format_attachments_prompt(doc_records)
                full_tokens = self._token_counter.count_tokens(full_xml)
                head_xml = self._format_attachments_prompt(doc_records, max_tokens=self.ATTACHMENT_HEAD_KEEP)

                if remaining_budget >= full_tokens:
                    # 剩余预算够 → 全量注入
                    doc_xml = full_xml
                    remaining_budget -= full_tokens
                elif remaining_budget >= self.ATTACHMENT_MIN_KEEP:
                    # 不够全量但够截断 → 截断到剩余
                    doc_xml = self._format_attachments_prompt(doc_records, max_tokens=remaining_budget)
                    remaining_budget = 0
                else:
                    # 预算用完 → 用必保头部（已预留，不占 remaining_budget）
                    doc_xml = head_xml
                parts.append({"type": "text", "text": doc_xml})

            # 图片附件 → multimodal（仅 VLM；图片不占文本预算）
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
            injected += 1

        if injected:
            self.logger.info(
                "附件文本已注入上下文（按 token 预算）",
                session_id=session_id, injected_count=injected,
                budget=self.ATTACHMENT_TOKEN_BUDGET, remaining=remaining_budget,
            )

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
