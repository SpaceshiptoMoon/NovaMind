"""
假设问题生成服务

使用 LLM 为文档分块生成假设性问题，提升检索召回率
"""

import json
import re
from typing import List, Optional, Tuple, Any
from dataclasses import dataclass

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.ai_models.llm import BaseLLM
from src.shared.prompts import PromptTemplate, PromptManager
from src.features.user.services.model_config_service import ModelConfigService
from src.features.knowledge_space.schemas.knowledge_base_schema import (
    QuestionGenerationConfig,
    QuestionLLMConfig,
)
from src.core.middleware.structured_logging import get_logger
from src.features.knowledge_space.api.exceptions import (
    EmbeddingError,
    InvalidParameterError,
    QuestionGenerationError,
)


logger = get_logger(__name__)

# 解析结果为空时的最大重试次数
MAX_PARSE_RETRY = 2


@dataclass
class GeneratedQuestion:
    """生成的问题"""
    index: int
    question: str
    category: Optional[str] = None  # 问题类别: factual, conceptual, procedural


class QuestionGenerationService:
    """
    假设问题生成服务

    为每个文档分块生成若干假设性问题，用于提升检索召回率。

    工作原理:
    1. 用户查询可能与原始文档内容不匹配
    2. 但用户查询很可能与"针对该内容提出的问题"匹配
    3. 通过生成假设问题,建立用户查询 -> 问题 -> 原始内容的桥梁

    示例:
    - 文档内容: "FastAPI 是一个现代、快速的 Web 框架..."
    - 假设问题: "什么是 FastAPI？", "如何使用 FastAPI 构建 API?"
    - 用户查询: "fastapi 是什么" -> 匹配假设问题 -> 返回原始内容
    """

    def __init__(
        self,
        session: Optional[AsyncSession] = None,
        model_config_service: Optional[ModelConfigService] = None,
        config: Optional[QuestionGenerationConfig] = None,
    ):
        """
        初始化问题生成服务

        Args:
            session: 数据库会话（用于获取用户模型配置）
            model_config_service: 模型配置服务（可选）
            config: 问题生成配置（可选，默认使用全局配置）
        """
        self.session = session
        self.config = config or QuestionGenerationConfig()
        self.logger = logger

        # 模型配置服务
        if model_config_service:
            self.model_config_service = model_config_service
        elif session:
            self.model_config_service = ModelConfigService(session)
        else:
            self.model_config_service = None

        # LLM 客户端缓存
        self._llm_client: Optional[BaseLLM] = None

    async def _get_llm_client(self, user_id: Optional[int] = None) -> BaseLLM:
        """
        获取 LLM 客户端

        通过 ModelConfigService 从数据库解析凭证，无配置时抛异常

        Args:
            user_id: 用户 ID（可选，用于获取用户私有模型配置）

        Returns:
            LLM 客户端

        Raises:
            QuestionGenerationError: 未找到模型配置
        """
        if self._llm_client:
            return self._llm_client

        llm_config = self.config.llm
        model_name = llm_config.model if llm_config else None

        if self.model_config_service:
            # 如果没有指定模型，获取系统默认
            if not model_name:
                model_name = await self.model_config_service.get_default_model_name("llm")

            if model_name:
                effective_user_id = user_id or 0
                self._llm_client = await self.model_config_service.get_llm_client_by_model(
                    user_id=effective_user_id,
                    model=model_name,
                )
                self.logger.debug(
                    "使用 ModelConfigService 获取的 LLM 客户端",
                    model=model_name,
                    user_id=effective_user_id,
                )
                return self._llm_client

        raise QuestionGenerationError("未配置 LLM 模型，请在模型配置中添加")

    async def generate_questions(
        self,
        chunk_content: str,
        document_title: Optional[str] = None,
        user_id: Optional[int] = None,
        raise_on_error: bool = False,
    ) -> List[GeneratedQuestion]:
        """
        为单个分块生成假设问题

        Args:
            chunk_content: 分块内容
            document_title: 文档标题（可选，用于提供上下文）
            user_id: 用户 ID（可选，用于获取用户模型配置）
            raise_on_error: 是否在错误时抛出异常

        Returns:
            生成的问题列表

        Raises:
            InvalidParameterError: 分块内容为空
            QuestionGenerationError: LLM 调用失败
        """
        # 参数校验
        if not chunk_content or not chunk_content.strip():
            raise InvalidParameterError("分块内容不能为空", field="chunk_content")

        # 检查是否启用
        if not self.config.enabled:
            self.logger.debug("假设问题生成未启用，跳过")
            return []

        try:
            # 获取 LLM 客户端
            llm_client = await self._get_llm_client(user_id)

            # 构建提示词
            prompt = self._build_prompt(chunk_content, document_title)

            # 获取 LLM 配置参数，约束上限确保输出稳定
            llm_config = self.config.llm or QuestionLLMConfig()
            temperature = min(llm_config.temperature, 0.5)
            top_p = min(llm_config.top_p, 0.9)
            max_tokens = min(llm_config.max_tokens, 2048)

            # 调用 LLM 生成问题，解析为空时重试
            questions = []
            for attempt in range(MAX_PARSE_RETRY + 1):
                response = await llm_client.generate_text(
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    response_format={"type": "json_object"},
                )

                questions = self._parse_response(response)
                if questions:
                    break

                if attempt < MAX_PARSE_RETRY:
                    self.logger.warning(
                        "问题解析结果为空，准备重试",
                        attempt=attempt + 1,
                        max_retry=MAX_PARSE_RETRY,
                        response_preview=response[:100],
                    )

            self.logger.debug(
                "生成假设问题完成",
                question_count=len(questions),
                content_length=len(chunk_content),
                document_title=document_title,
            )

            return questions

        except (InvalidParameterError, QuestionGenerationError):
            raise
        except Exception as e:
            self.logger.error(
                "生成假设问题失败",
                error=str(e),
                chunk_preview=chunk_content[:100] if chunk_content else None,
                document_title=document_title,
            )
            if raise_on_error:
                raise QuestionGenerationError(f"生成假设问题失败: {str(e)}")
            # 降级：返回空列表，允许调用方决定如何处理
            return []

    async def generate_questions_batch(
        self,
        chunks: List[Tuple[str, Optional[str]]],
        user_id: Optional[int] = None,
        raise_on_error: bool = False,
        batch_size: int = 3,
    ) -> List[List[GeneratedQuestion]]:
        """
        批量为多个分块生成假设问题

        将多个 chunk 打包进一次 LLM 调用，减少 API 调用次数。
        N 个 chunk → ceil(N/batch_size) 次 LLM 调用。

        Args:
            chunks: 分块列表，每个元素是 (content, title) 元组
            user_id: 用户 ID（可选）
            raise_on_error: 是否在错误时抛出异常
            batch_size: 每次 LLM 调用包含的 chunk 数量

        Returns:
            每个分块对应的问题列表
        """
        if not chunks:
            return []

        llm_client = await self._get_llm_client(user_id)
        llm_config = self.config.llm or QuestionLLMConfig()
        temperature = min(llm_config.temperature, 0.5)
        top_p = min(llm_config.top_p, 0.9)
        # 批量场景输出为简洁 JSON，不需要过多 token
        max_tokens = min(llm_config.max_tokens, 2048)

        results: List[List[GeneratedQuestion]] = [[] for _ in chunks]
        import time as _time
        total_start = _time.monotonic()

        for batch_start in range(0, len(chunks), batch_size):
            batch = chunks[batch_start:batch_start + batch_size]
            batch_start_time = _time.monotonic()
            try:
                batch_questions = await asyncio.wait_for(
                    self._generate_batch_questions(
                        llm_client, batch, temperature, top_p, max_tokens,
                    ),
                    timeout=120,
                )
                batch_elapsed = _time.monotonic() - batch_start_time
                self.logger.info(
                    "批量问题生成：批次成功",
                    batch_start=batch_start,
                    batch_size=len(batch),
                    elapsed_s=round(batch_elapsed, 1),
                )
                for i, questions in enumerate(batch_questions):
                    results[batch_start + i] = questions
            except asyncio.TimeoutError:
                batch_elapsed = _time.monotonic() - batch_start_time
                self.logger.warning(
                    "批量问题生成超时，跳过",
                    batch_start=batch_start,
                    batch_size=len(batch),
                    elapsed_s=round(batch_elapsed, 1),
                    total_elapsed_s=round(_time.monotonic() - total_start, 1),
                )
            except Exception as e:
                self.logger.error(
                    "批量问题生成失败",
                    error=str(e),
                    batch_start=batch_start,
                )
                if raise_on_error:
                    raise

        return results

    async def _generate_batch_questions(
        self,
        llm_client: BaseLLM,
        batch: List[Tuple[str, Optional[str]]],
        temperature: float,
        top_p: float,
        max_tokens: int,
    ) -> List[List[GeneratedQuestion]]:
        """单次 LLM 调用为多个 chunk 生成问题"""
        import time as _time
        prompt = self._build_batch_prompt(batch)
        self.logger.info(
            "批量问题生成：开始调用 LLM",
            batch_size=len(batch),
            prompt_length=len(prompt),
            max_tokens=max_tokens,
        )

        for attempt in range(MAX_PARSE_RETRY + 1):
            call_start = _time.monotonic()
            try:
                response = await llm_client.generate_text(
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    response_format={"type": "json_object"},
                )
                call_elapsed = _time.monotonic() - call_start
                self.logger.info(
                    "批量问题生成：LLM 响应收到",
                    attempt=attempt,
                    response_length=len(response),
                    elapsed_s=round(call_elapsed, 1),
                    response_preview=response[:200],
                )
            except Exception as e:
                call_elapsed = _time.monotonic() - call_start
                self.logger.warning(
                    "批量问题生成：LLM 调用异常",
                    attempt=attempt,
                    error_type=type(e).__name__,
                    error=str(e)[:200],
                    elapsed_s=round(call_elapsed, 1),
                )
                raise

            batch_questions = self._parse_batch_response(response, len(batch))
            if batch_questions:
                self.logger.debug(
                    "批量问题生成完成",
                    batch_size=len(batch),
                    total_questions=sum(len(q) for q in batch_questions),
                )
                return batch_questions

            if attempt < MAX_PARSE_RETRY:
                self.logger.warning(
                    "批量解析结果为空，准备重试",
                    attempt=attempt + 1,
                    response_preview=response[:100],
                )

        return [[] for _ in batch]

    def _build_batch_prompt(
        self,
        batch: List[Tuple[str, Optional[str]]],
    ) -> str:
        """为多个 chunk 构建合并的提示词"""
        count = self.config.max_questions_per_chunk
        sections = []
        for i, (content, _) in enumerate(batch):
            # 截取前 1000 字符，足够提取核心信息点
            sections.append(f"### 分块 {i + 1}\n{content[:1000]}")

        chunks_text = "\n\n".join(sections)

        return f"""请严格根据以下文档内容，为每个分块各生成 {count} 个用户可能会问的问题。

要求：
1. 问题必须且只能基于对应分块中实际出现的文字信息，禁止使用分块内容之外的信息
2. 问题应该覆盖分块的核心信息点
3. 问题应该是用户真实可能提出的查询
4. 问题表述要清晰、简洁
5. 只输出 JSON，不要输出任何其他文字

输出格式：
{{"chunks": [{{"questions": [{{"question": "问题内容", "category": "factual"}}]}}]}}

category 可选值: factual(事实性), conceptual(概念性), procedural(操作性)

{chunks_text}

请为每个分块各生成 {count} 个问题："""

    def _parse_batch_response(
        self,
        response: str,
        expected_count: int,
    ) -> Optional[List[List[GeneratedQuestion]]]:
        """解析批量 LLM 响应为每个 chunk 的问题列表"""
        try:
            data = json.loads(response)
            chunks_data = data.get("chunks", [])

            results = []
            for i, chunk_data in enumerate(chunks_data):
                if i >= expected_count:
                    break

                questions = []
                question_items = (
                    chunk_data.get("questions", [])
                    if isinstance(chunk_data, dict)
                    else (chunk_data if isinstance(chunk_data, list) else [])
                )
                for item in question_items:
                    if isinstance(item, dict) and "question" in item:
                        questions.append(GeneratedQuestion(
                            index=len(questions) + 1,
                            question=item["question"].strip(),
                            category=item.get("category"),
                        ))
                    elif isinstance(item, str):
                        questions.append(GeneratedQuestion(
                            index=len(questions) + 1,
                            question=item.strip(),
                        ))
                results.append(questions[:self.config.max_questions_per_chunk])

            while len(results) < expected_count:
                results.append([])

            return results
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def _build_prompt(
        self,
        chunk_content: str,
        document_title: Optional[str] = None,
    ) -> str:
        """
        构建提示词

        优先使用配置的自定义模板，否则使用默认模板

        Args:
            chunk_content: 分块内容
            document_title: 文档标题

        Returns:
            构建好的提示词
        """
        # 获取模板（用户自定义模板使用 .format()，默认模板使用 PromptManager）
        if self.config.prompt_template:
            template = self.config.prompt_template
            prompt = template.replace("{{content}}", chunk_content[:3000])
            prompt = prompt.replace("{{count}}", str(self.config.max_questions_per_chunk))
        else:
            prompt = PromptManager.format_prompt(
                PromptTemplate.KB_DEFAULT_QUESTION.value,
                content=chunk_content[:3000],
                count=str(self.config.max_questions_per_chunk),
            )

        # 注意：不再注入文档标题到提示词中
        # 原因：文档标题可能包含人名等实体信息（如"刘琳辉_简历"），
        # 会导致 LLM 在生成问题时引入 chunk 内容中不存在的实体，产生幻觉

        return prompt

    def _parse_response(self, response: str) -> List[GeneratedQuestion]:
        """
        解析 LLM 响应

        Args:
            response: LLM 返回的原始响应

        Returns:
            解析后的问题列表
        """
        questions = []
        max_count = self.config.max_questions_per_chunk

        # 第一步：尝试直接解析整个响应为 JSON
        json_text = None
        try:
            data = json.loads(response)
            if isinstance(data, list):
                json_text = data
        except json.JSONDecodeError:
            pass

        # 第二步：从 ```json 代码块中提取
        if json_text is None:
            json_block_match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', response)
            if json_block_match:
                try:
                    json_text = json.loads(json_block_match.group(1))
                except json.JSONDecodeError:
                    pass

        # 第三步：全文中找 JSON 数组
        if json_text is None:
            json_match = re.search(r'\[[\s\S]*\]', response)
            if json_match:
                try:
                    json_text = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

        # 从 JSON 数据中提取问题
        if json_text:
            for item in json_text:
                if isinstance(item, dict) and "question" in item:
                    questions.append(GeneratedQuestion(
                        index=item.get("index", len(questions) + 1),
                        question=item["question"].strip(),
                        category=item.get("category"),
                    ))
                elif isinstance(item, str):
                    questions.append(GeneratedQuestion(
                        index=len(questions) + 1,
                        question=item.strip(),
                    ))

        # 第四步：所有 JSON 解析均失败，按行解析
        if not questions:
            lines = response.strip().split("\n")
            for i, line in enumerate(lines, start=1):
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("[") or line.startswith("]"):
                    continue
                # 移除序号前缀和 markdown 标记
                cleaned = re.sub(r'^[\d]+[.、)\]}\s]*', '', line)
                cleaned = re.sub(r'^[-*]\s*', '', cleaned)
                cleaned = cleaned.strip('"\',，。')
                if cleaned and len(cleaned) > 2:
                    questions.append(GeneratedQuestion(
                        index=i,
                        question=cleaned,
                    ))

        # 限制数量
        return questions[:max_count]

    async def generate_questions_simple(
        self,
        chunk_content: str,
        user_id: Optional[int] = None,
        raise_on_error: bool = False,
    ) -> List[str]:
        """
        生成问题（简化版，仅返回问题文本列表）

        Args:
            chunk_content: 分块内容
            user_id: 用户 ID（可选）
            raise_on_error: 是否在错误时抛出异常

        Returns:
            问题文本列表
        """
        questions = await self.generate_questions(
            chunk_content,
            user_id=user_id,
            raise_on_error=raise_on_error,
        )
        return [q.question for q in questions]


# 便捷函数
async def generate_hypothetical_questions(
    chunk_content: str,
    document_title: Optional[str] = None,
    max_questions: int = 5,
    user_id: Optional[int] = None,
    config: Optional[QuestionGenerationConfig] = None,
) -> List[str]:
    """
    为分块生成假设问题（便捷函数）

    Args:
        chunk_content: 分块内容
        document_title: 文档标题
        max_questions: 最大问题数量
        user_id: 用户 ID（可选）
        config: 问题生成配置（可选）

    Returns:
        问题文本列表
    """
    if config is None:
        config = QuestionGenerationConfig(
            enabled=True,
            max_questions_per_chunk=max_questions,
        )

    service = QuestionGenerationService(config=config)
    return await service.generate_questions_simple(
        chunk_content,
        user_id=user_id,
    )
