"""假设问题生成引擎：LLM 为文本分块生成假设性问题，提升检索召回率。

通用模块（engines 层）：纯"文本进、问题出"能力——LLM 客户端 duck 注入，
配置为纯 dataclass，零 features/ORM/setting 依赖。业务编排（KB 配置解析、
问题向量生成、ES 写入、enabled 开关）在 features/knowledge_space。
"""

import asyncio
import json
import re
import time as _time
from dataclasses import dataclass
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.ai_models.llm import BaseLLM
from novamind.shared.prompts import PromptManager
from novamind.shared.utils.llm_response import extract_json_obj

logger = get_logger(__name__)


class QuestionGenerationError(Exception):
    """问题生成失败（LLM 调用/配置缺失）。引擎自持异常，与业务 HTTP 异常族无关。"""


@dataclass
class QuestionGenConfig:
    """问题生成的引擎侧纯数据配置。

    业务 KB 配置（QuestionGenerationConfig Pydantic 模型）由业务层转换为本
    结构传入；enabled 业务开关不进引擎（调用方决定是否调用）。
    """

    model: str | None = None
    temperature: float = 0.3
    top_p: float = 0.9
    max_tokens: int = 2048
    max_questions_per_chunk: int = 5
    prompt_template: str | None = None


# 解析结果为空时的最大重试次数
MAX_PARSE_RETRY = 2

# 单次 LLM 调用超时基数（秒）。超时按调用计而非按批次计：旧实现把整批
# （含全部解析重试）包进固定 120s，thinking 模型单次 50-60s 的耗时下
# 「一次空响应 + 一次重试」即耗尽预算，超时批次整批静默丢弃。
PER_CALL_TIMEOUT_SECONDS = 90

# 批次整体降级前，批内单次调用失败的最大重试轮数（首轮 + 2 轮重试）
MAX_BATCH_ATTEMPTS = 3

# 空响应重试时压缩 max_tokens 的比例。thinking 模型（如 qwen3 强制
# enable_thinking=True）会把思考 token 计入 max_completion_tokens：预算
# 被思考耗尽后 content 为空（completion_tokens 恰好撞满上限）。缩短预算
# 不能减少思考 token，但对"接近上限才溢出"的场景有效；真正的恢复手段
# 是逐块降级（prompt 更短、思考更少、更易在预算内产出）。
EMPTY_RESPONSE_MAX_TOKENS_SCALE = 0.5


@dataclass
class BatchGenerationStats:
    """批量生成的批次级统计，供节点 metrics 透出降级覆盖信息。

    Attributes:
        batches_total: 批次总数。
        batches_failed: 整批留空的批次数（含批内重试与逐块降级均失败）。
        degraded_batches: 经逐块降级部分恢复的批次数。
        timeout_batches: 触发过单次调用超时的批次数。
    """

    batches_total: int = 0
    batches_failed: int = 0
    degraded_batches: int = 0
    timeout_batches: int = 0

    def to_metrics(self) -> dict[str, int]:
        """转成节点 metrics 字典（仅保留有信息量的键）。"""
        return {
            "batches_total": self.batches_total,
            "batches_failed": self.batches_failed,
            "batches_degraded": self.degraded_batches,
            "batches_timeout": self.timeout_batches,
        }


@dataclass
class GeneratedQuestion:
    """生成的问题"""
    index: int
    question: str
    category: str | None = None  # 问题类别: factual, conceptual, procedural


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
        model_config_service: Any | None = None,
        config: QuestionGenConfig | None = None,
    ):
        """
        初始化问题生成服务

        Args:
            model_config_service: LLM 客户端解析器（duck 注入，引擎不 import
                业务类型）：需提供 ``async get_user_default_model_name(
                user_id, "llm")`` 与 ``async get_llm_client_by_model(
                user_id, model)`` 两方法。
            config: 引擎侧生成配置（可选，默认值见 QuestionGenConfig）。
        """
        self.config = config or QuestionGenConfig()
        self.logger = logger

        self.model_config_service = model_config_service

        # LLM 客户端缓存
        self._llm_client: BaseLLM | None = None

    async def _get_llm_client(self, user_id: int | None = None) -> BaseLLM:
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

        model_name = self.config.model

        if self.model_config_service:
            # 如果没有指定模型，获取用户默认
            if not model_name:
                model_name = await self.model_config_service.get_user_default_model_name(user_id or 0, "llm")

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
        document_title: str | None = None,
        user_id: int | None = None,
        raise_on_error: bool = False,
    ) -> list[GeneratedQuestion]:
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
            ValueError: 分块内容为空
            QuestionGenerationError: LLM 调用失败
        """
        # 参数校验
        if not chunk_content or not chunk_content.strip():
            raise ValueError("分块内容不能为空")

        try:
            # 获取 LLM 客户端
            llm_client = await self._get_llm_client(user_id)

            # 构建提示词
            prompt = self._build_prompt(chunk_content, document_title)

            # 获取 LLM 配置参数，约束上限确保输出稳定。
            # 上限 8192（schema 允许的最大值）：thinking 模型（qwen3.8 系列）的
            # 思考 token 计入输出预算，2048 会被 reasoning 吃满导致 content 为空
            #（2026-10-05 实测 119/119 空响应全部 completion_tokens=2048）。
            # 服务端 thinking_budget 注入后思考有界，此处提高预算兜底存量配置。
            llm_config = self.config
            temperature = min(llm_config.temperature, 0.5)
            top_p = min(llm_config.top_p, 0.9)
            max_tokens = min(llm_config.max_tokens, 8192)

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

        except (ValueError, QuestionGenerationError):
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
        chunks: list[tuple[str, str | None]],
        user_id: int | None = None,
        raise_on_error: bool = False,
        batch_size: int = 3,
    ) -> tuple[list[list[GeneratedQuestion]], BatchGenerationStats]:
        """
        批量为多个分块生成假设问题

        将多个 chunk 打包进一次 LLM 调用，减少 API 调用次数。
        N 个 chunk → ceil(N/batch_size) 次 LLM 调用。

        重试策略分层（失败方向安全：能力缺失而非错误结果）：
        1. 批内重试：单次调用超时/解析为空 → 最多 MAX_BATCH_ATTEMPTS 轮，
           空响应轮次缩短 max_tokens 再试；
        2. 逐块降级：批内重试耗尽 → 该批 chunk 逐个独立调用，成功一块救一块；
        3. 留空：逐块降级也失败的 chunk 保持空列表，由 metrics 记录批次失败数。

        Args:
            chunks: 分块列表，每个元素是 (content, title) 元组
            user_id: 用户 ID（可选）
            raise_on_error: 是否在错误时抛出异常
            batch_size: 每次 LLM 调用包含的 chunk 数量

        Returns:
            (每个分块对应的问题列表, 批次级统计) — 统计供节点 metrics 透出
        """
        if not chunks:
            return [], BatchGenerationStats()

        llm_client = await self._get_llm_client(user_id)
        llm_config = self.config
        temperature = min(llm_config.temperature, 0.5)
        top_p = min(llm_config.top_p, 0.9)
        # 上限 8192 同 generate_questions：thinking 模型 reasoning 计入预算，
        # 2048 会被思考吃满致 content 为空（见 generate_questions 内注释）
        max_tokens = min(llm_config.max_tokens, 8192)

        results: list[list[GeneratedQuestion]] = [[] for _ in chunks]
        stats = BatchGenerationStats(batches_total=(len(chunks) + batch_size - 1) // batch_size)
        total_start = _time.monotonic()

        for batch_start in range(0, len(chunks), batch_size):
            batch = chunks[batch_start:batch_start + batch_size]
            batch_start_time = _time.monotonic()
            try:
                batch_questions, batch_signals = await self._generate_batch_questions(
                    llm_client, batch, temperature, top_p, max_tokens,
                )
                if batch_signals.get("timed_out"):
                    stats.timeout_batches += 1
                for i, questions in enumerate(batch_questions):
                    results[batch_start + i] = questions
                batch_elapsed = _time.monotonic() - batch_start_time

                if all(len(qs) == 0 for qs in batch_questions):
                    # 批内重试全失败 → 逐块降级：prompt 更短、成功率高，成功一块救一块
                    recovered = await self._degrade_to_single_chunks(
                        llm_client, batch, temperature, top_p, max_tokens,
                    )
                    any_recovered = any(len(qs) > 0 for qs in recovered)
                    stats.degraded_batches += 1 if any_recovered else 0
                    # 降级后仍有空块即计失败批次（部分恢复的缺口比全失败更隐蔽，
                    # 必须在 metrics 可见——doc787 教训：total=20 掩盖 12 块为空）
                    stats.batches_failed += 1 if any(len(qs) == 0 for qs in recovered) else 0
                    for i, questions in enumerate(recovered):
                        results[batch_start + i] = questions
                    self.logger.warning(
                        "批量问题生成：批内重试耗尽，逐块降级完成",
                        batch_start=batch_start,
                        batch_size=len(batch),
                        recovered_chunks=sum(1 for qs in recovered if qs),
                        elapsed_s=round(_time.monotonic() - batch_start_time, 1),
                    )
                else:
                    self.logger.info(
                        "批量问题生成：批次成功",
                        batch_start=batch_start,
                        batch_size=len(batch),
                        elapsed_s=round(batch_elapsed, 1),
                    )
            except Exception as e:
                # _generate_batch_questions 只在 raise 场景（LLM 客户端持续异常）到达这里；
                # 逐块降级兜一次底，把影响面从整批缩小到单块
                self.logger.error(
                    "批量问题生成失败，尝试逐块降级",
                    error=str(e),
                    batch_start=batch_start,
                )
                try:
                    recovered = await self._degrade_to_single_chunks(
                        llm_client, batch, temperature, top_p, max_tokens,
                    )
                    any_recovered = any(len(qs) > 0 for qs in recovered)
                    stats.degraded_batches += 1 if any_recovered else 0
                    stats.batches_failed += 1 if any(len(qs) == 0 for qs in recovered) else 0
                    for i, questions in enumerate(recovered):
                        results[batch_start + i] = questions
                except Exception as degrade_err:
                    stats.batches_failed += 1
                    self.logger.error(
                        "逐块降级也失败，该批留空",
                        batch_start=batch_start,
                        error=str(degrade_err),
                    )
                    if raise_on_error:
                        raise

        self.logger.info(
            "批量问题生成完成",
            chunks=len(chunks),
            chunks_with_questions=sum(1 for qs in results if qs),
            total_questions=sum(len(qs) for qs in results),
            **stats.to_metrics(),
            total_elapsed_s=round(_time.monotonic() - total_start, 1),
        )
        return results, stats

    async def _degrade_to_single_chunks(
        self,
        llm_client: BaseLLM,
        batch: list[tuple[str, str | None]],
        temperature: float,
        top_p: float,
        max_tokens: int,
    ) -> list[list[GeneratedQuestion]]:
        """逐块降级：批内每个 chunk 独立调用生成问题。

        单块 prompt 短、结构简单，thinking 模型的思考开销与撞预算概率都更低；
        单块失败只丢一块，不影响批内其他 chunk。

        Args:
            llm_client: LLM 客户端。
            batch: 该批的 (content, title) 元组列表。
            temperature/top_p/max_tokens: 生成参数（沿用批内配置）。

        Returns:
            与 batch 等长的问题列表；失败的 chunk 为空列表。
        """
        results: list[list[GeneratedQuestion]] = []
        for content, _title in batch:
            questions = await self._generate_single_with_retry(
                llm_client, content, temperature, top_p, max_tokens,
            )
            results.append(questions)
        return results

    async def _generate_single_with_retry(
        self,
        llm_client: BaseLLM,
        chunk_content: str,
        temperature: float,
        top_p: float,
        max_tokens: int,
    ) -> list[GeneratedQuestion]:
        """单 chunk 生成 + 解析重试；全部失败返回空列表（不抛异常）。

        Args:
            llm_client: LLM 客户端。
            chunk_content: 分块内容。
            temperature/top_p/max_tokens: 生成参数。

        Returns:
            问题列表；持续失败为空列表。
        """
        for attempt in range(MAX_PARSE_RETRY + 1):
            try:
                response = await asyncio.wait_for(
                    llm_client.generate_text(
                        prompt=self._build_prompt(chunk_content),
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        response_format={"type": "json_object"},
                    ),
                    timeout=PER_CALL_TIMEOUT_SECONDS,
                )
                questions = self._parse_response(response)
                if questions:
                    return questions
                # 空响应：缩短预算重试（thinking 预算耗尽场景可能恢复）
                max_tokens = max(int(max_tokens * EMPTY_RESPONSE_MAX_TOKENS_SCALE), 512)
            except (TimeoutError, asyncio.TimeoutError):
                self.logger.warning(
                    "单块问题生成超时",
                    attempt=attempt,
                    content_length=len(chunk_content),
                    timeout_s=PER_CALL_TIMEOUT_SECONDS,
                )
            except Exception as e:
                self.logger.warning(
                    "单块问题生成异常",
                    attempt=attempt,
                    error_type=type(e).__name__,
                    error=str(e)[:200],
                )
        return []

    async def _generate_batch_questions(
        self,
        llm_client: BaseLLM,
        batch: list[tuple[str, str | None]],
        temperature: float,
        top_p: float,
        max_tokens: int,
    ) -> tuple[list[list[GeneratedQuestion]], dict[str, bool]]:
        """单次 LLM 调用为多个 chunk 生成问题（含批内解析重试）。

        超时按单次调用计（PER_CALL_TIMEOUT_SECONDS × 轮内串行调用数），
        不再把整批含重试的总时长卡死在一个固定值里。

        Returns:
            (每 chunk 的问题列表, 批次信号 dict)；全部轮次解析为空时返回
            空 placeholder 列表（非 None），由调用方触发逐块降级。
        """
        prompt = self._build_batch_prompt(batch)
        self.logger.info(
            "批量问题生成：开始调用 LLM",
            batch_size=len(batch),
            prompt_length=len(prompt),
            max_tokens=max_tokens,
        )

        # 单轮 = 1 次 LLM 调用；批内最多 MAX_BATCH_ATTEMPTS 轮。
        # 超时预算 = 单次超时 × 轮数上限，覆盖"每轮都接近超时"的最坏串行路径。
        batch_timeout = PER_CALL_TIMEOUT_SECONDS * MAX_BATCH_ATTEMPTS
        batch_stats = {"timed_out": False}

        for attempt in range(MAX_BATCH_ATTEMPTS):
            call_start = _time.monotonic()
            try:
                response = await asyncio.wait_for(
                    llm_client.generate_text(
                        prompt=prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        response_format={"type": "json_object"},
                    ),
                    timeout=PER_CALL_TIMEOUT_SECONDS,
                )
                call_elapsed = _time.monotonic() - call_start
                self.logger.info(
                    "批量问题生成：LLM 响应收到",
                    attempt=attempt,
                    response_length=len(response),
                    elapsed_s=round(call_elapsed, 1),
                    response_preview=response[:200],
                )
            except (TimeoutError, asyncio.TimeoutError):
                call_elapsed = _time.monotonic() - call_start
                batch_stats["timed_out"] = True
                self.logger.warning(
                    "批量问题生成：单次调用超时",
                    attempt=attempt,
                    batch_size=len(batch),
                    elapsed_s=round(call_elapsed, 1),
                    timeout_s=PER_CALL_TIMEOUT_SECONDS,
                )
                continue

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
            if batch_questions and any(len(qs) > 0 for qs in batch_questions):
                self.logger.debug(
                    "批量问题生成完成",
                    batch_size=len(batch),
                    total_questions=sum(len(q) for q in batch_questions),
                )
                return batch_questions, batch_stats

            if attempt < MAX_BATCH_ATTEMPTS - 1:
                self.logger.warning(
                    "批量解析结果为空，缩短 max_tokens 后重试",
                    attempt=attempt + 1,
                    response_preview=response[:100],
                )
                max_tokens = max(int(max_tokens * EMPTY_RESPONSE_MAX_TOKENS_SCALE), 512)

        # 全部轮次耗尽：返回空 placeholder（触发调用方逐块降级）
        return [[] for _ in batch], batch_stats

    def _build_batch_prompt(
        self,
        batch: list[tuple[str, str | None]],
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
    ) -> list[list[GeneratedQuestion]] | None:
        """解析批量 LLM 响应为每个 chunk 的问题列表"""
        try:
            # 提取容错：围栏/前导噪声可解析（裸 loads 遇 ```json 包裹会把
            # 本可解析的响应判 None，触发无谓的整批重试与逐块降级）
            data = extract_json_obj(response)
            if data is None:
                return None
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
        document_title: str | None = None,
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
                "kb_default_question",
                content=chunk_content[:3000],
                count=str(self.config.max_questions_per_chunk),
            )

        # 注意：不再注入文档标题到提示词中
        # 原因：文档标题可能包含人名等实体信息（如"张三_简历"），
        # 会导致 LLM 在生成问题时引入 chunk 内容中不存在的实体，产生幻觉

        return prompt

    def _parse_response(self, response: str) -> list[GeneratedQuestion]:
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
        user_id: int | None = None,
        raise_on_error: bool = False,
    ) -> list[str]:
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
    document_title: str | None = None,
    max_questions: int = 5,
    user_id: int | None = None,
    config: QuestionGenConfig | None = None,
) -> list[str]:
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
        config = QuestionGenConfig(max_questions_per_chunk=max_questions)

    service = QuestionGenerationService(config=config)
    return await service.generate_questions_simple(
        chunk_content,
        user_id=user_id,
    )
