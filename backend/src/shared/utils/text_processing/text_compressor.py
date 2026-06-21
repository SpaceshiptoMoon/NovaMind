"""
文本压缩器

使用 LLM 将旧消息压缩为摘要，保留上下文关键信息
支持多种压缩策略：摘要、滑动窗口、保留最近、截断
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

from src.core.middleware.structured_logging import get_logger
from src.shared.ai_models.base_model import BaseLLM
from src.shared.prompts.templates import PromptTemplate, PromptManager

from .token_counter import TokenCounter


class CompressionStrategy(str, Enum):
    """压缩策略枚举"""
    SUMMARY = "summary"  # 摘要压缩（使用 LLM）
    SLIDING_WINDOW = "sliding_window"  # 滑动窗口
    KEEP_RECENT = "keep_recent"  # 保留最近
    TRUNCATE = "truncate"  # 截断


@dataclass
class CompressionResult:
    """压缩结果"""
    summary: str
    compressed_tokens: int
    original_tokens: int
    kept_messages: List[Dict[str, Any]]
    compression_ratio: float


class TextCompressor:
    """文本压缩器，支持多种压缩策略"""

    def __init__(
        self,
        llm_client: Optional[BaseLLM] = None,
        custom_prompt: Optional[str] = None,
    ):
        """
        初始化压缩器

        Args:
            llm_client: LLM 客户端（SUMMARY 策略需要）
            custom_prompt: 自定义的摘要生成提示词（可选）
        """
        self.llm_client = llm_client
        self.custom_prompt = custom_prompt
        self.token_counter = TokenCounter()
        self.logger = get_logger(__name__)

    @property
    def summary_prompt(self) -> str:
        """获取摘要提示词（优先使用自定义提示词）"""
        return self.custom_prompt or PromptManager.get_template(
            PromptTemplate.QA_COMPRESSION_SUMMARY.value
        )

    async def compress_with_base_summary(
        self,
        base_summary: str,
        new_messages: List[Dict[str, Any]],
        target_tokens: int = 500,
    ) -> CompressionResult:
        """
        增量压缩：基于已有摘要 + 新消息，生成更新后的摘要。

        相比 compress_messages（把全部历史重新压缩），增量压缩只把「旧摘要 + 自上次
        压缩边界之后的新消息」喂给 LLM，避免重复压缩已摘要的内容，省 LLM 调用、
        且基于旧摘要融合，信息保留更连贯。

        Args:
            base_summary: 已有的对话摘要（覆盖较早的消息）
            new_messages: 自上次摘要边界之后的新消息
            target_tokens: 更新后摘要的目标 token 数
        """
        if not new_messages:
            return CompressionResult(
                summary=base_summary,
                compressed_tokens=self.token_counter.count_tokens(base_summary),
                original_tokens=0,
                kept_messages=[],
                compression_ratio=1.0,
            )

        if not self.llm_client:
            self.logger.warning("LLM 客户端未初始化，增量压缩退化为保留旧摘要")
            return CompressionResult(
                summary=base_summary,
                compressed_tokens=self.token_counter.count_tokens(base_summary),
                original_tokens=self.token_counter.count_messages_tokens(new_messages),
                kept_messages=[],
                compression_ratio=1.0,
            )

        new_messages_text = "\n".join(
            f"[{msg.get('role', 'user')}]: {msg.get('content', '')}"
            for msg in new_messages
        )
        original_tokens = self.token_counter.count_messages_tokens(new_messages)

        prompt = f"""{self.summary_prompt}

以下是对话已有的摘要，覆盖了较早的对话内容：
---
{base_summary}
---

以下是自上次摘要之后产生的新对话消息，请将其并入已有摘要：
---
{new_messages_text}
---

请综合以上两部分，生成一份更新后的、约 {target_tokens} 个 token 的摘要（保留关键信息，去掉冗余）：

摘要:"""

        try:
            summary = await self.llm_client.generate_text(
                prompt=prompt,
                max_tokens=800,
                temperature=0.3,
            )
            summary = self._clean_summary(summary)
        except Exception as e:
            self.logger.warning("增量压缩失败，退化为保留旧摘要", error=str(e))
            return CompressionResult(
                summary=base_summary,
                compressed_tokens=self.token_counter.count_tokens(base_summary),
                original_tokens=original_tokens,
                kept_messages=[],
                compression_ratio=1.0,
            )

        compressed_tokens = self.token_counter.count_tokens(summary)
        return CompressionResult(
            summary=summary,
            compressed_tokens=compressed_tokens,
            original_tokens=original_tokens,
            kept_messages=[],
            compression_ratio=round(original_tokens / compressed_tokens, 2) if compressed_tokens else 1.0,
        )

    async def compress_with_strategy(
        self,
        messages: List[Dict[str, Any]],
        strategy: str,
        target_tokens: int = 500,
        keep_recent: int = 2,
    ) -> CompressionResult:
        """
        根据策略执行压缩

        Args:
            messages: 消息列表
            strategy: 压缩策略 (summary/sliding_window/keep_recent/truncate)
            target_tokens: 目标 token 数（用于 summary 和 truncate）
            keep_recent: 保留的最近消息数

        Returns:
            CompressionResult: 压缩结果
        """
        if strategy == CompressionStrategy.SUMMARY or strategy == "summary":
            return await self._compress_summary(messages, target_tokens, keep_recent)
        elif strategy == CompressionStrategy.SLIDING_WINDOW or strategy == "sliding_window":
            return self._compress_sliding_window(messages, keep_recent)
        elif strategy == CompressionStrategy.KEEP_RECENT or strategy == "keep_recent":
            return self._compress_keep_recent(messages, keep_recent)
        elif strategy == CompressionStrategy.TRUNCATE or strategy == "truncate":
            return self._compress_truncate(messages, target_tokens)
        else:
            # 默认使用摘要压缩
            self.logger.warning(
                "未知的压缩策略，使用默认 SUMMARY",
                strategy=strategy,
            )
            return await self._compress_summary(messages, target_tokens, keep_recent)

    async def compress_messages(
        self,
        messages: List[Dict[str, Any]],
        target_tokens: int = 500,
        keep_recent: int = 2,
    ) -> CompressionResult:
        """
        压缩消息列表为摘要（向后兼容，默认使用 SUMMARY 策略）

        Args:
            messages: 消息列表
            target_tokens: 目标 token 数
            keep_recent: 保留的最近消息数

        Returns:
            CompressionResult: 压缩结果
        """
        return await self._compress_summary(messages, target_tokens, keep_recent)

    # ========== 策略实现 ==========

    async def _compress_summary(
        self,
        messages: List[Dict[str, Any]],
        target_tokens: int,
        keep_recent: int,
    ) -> CompressionResult:
        """
        SUMMARY 策略：使用 LLM 生成摘要

        保留最近 N 条消息，将旧消息压缩为摘要
        """
        if not messages:
            return CompressionResult(
                summary="",
                compressed_tokens=0,
                original_tokens=0,
                kept_messages=[],
                compression_ratio=1.0,
            )

        # 计算原始 token 数
        original_tokens = self.token_counter.count_messages_tokens(messages)
        self.logger.debug(
            "开始 SUMMARY 压缩",
            message_count=len(messages),
            original_tokens=original_tokens,
            target_tokens=target_tokens,
            use_custom_prompt=self.custom_prompt is not None,
        )

        # 保留最近的消息
        if len(messages) >= keep_recent:
            recent_messages = messages[-keep_recent:]
            old_messages = messages[:-keep_recent]
        else:
            recent_messages = messages
            old_messages = []

        if not old_messages:
            return CompressionResult(
                summary="",
                compressed_tokens=0,
                original_tokens=original_tokens,
                kept_messages=recent_messages,
                compression_ratio=1.0,
            )

        # 检查 LLM 客户端
        if not self.llm_client:
            self.logger.warning("LLM 客户端未初始化，降级为 KEEP_RECENT 策略")
            return self._compress_keep_recent(messages, keep_recent)

        # 构建压缩提示
        compression_prompt = self._build_compression_prompt(old_messages, target_tokens)

        # 调用 LLM 生成摘要
        try:
            summary = await self.llm_client.generate_text(
                prompt=compression_prompt,
                max_tokens=800,
                temperature=0.3,
            )

            # 清理摘要（移除可能的 markdown 代码块标记）
            summary = self._clean_summary(summary)

            # 计算摘要 token 数
            summary_tokens = self.token_counter.count_tokens(summary)

            # 计算压缩比率
            compression_ratio = summary_tokens / original_tokens if original_tokens > 0 else 1.0

            self.logger.info(
                "SUMMARY 压缩完成",
                original_tokens=original_tokens,
                compressed_tokens=summary_tokens,
                kept_message_count=len(recent_messages),
                compression_ratio=round(compression_ratio, 2),
            )

            return CompressionResult(
                summary=summary,
                compressed_tokens=summary_tokens,
                original_tokens=original_tokens,
                kept_messages=recent_messages,
                compression_ratio=compression_ratio,
            )

        except Exception as e:
            self.logger.error("SUMMARY 压缩失败，降级为 KEEP_RECENT", error=str(e))
            return self._compress_keep_recent(messages, keep_recent)

    def _compress_sliding_window(
        self,
        messages: List[Dict[str, Any]],
        keep_recent: int,
    ) -> CompressionResult:
        """
        SLIDING_WINDOW 策略：滑动窗口

        只保留最近 N 条消息，丢弃更早的消息
        不生成摘要，无需 LLM
        """
        if not messages:
            return CompressionResult(
                summary="",
                compressed_tokens=0,
                original_tokens=0,
                kept_messages=[],
                compression_ratio=1.0,
            )

        original_tokens = self.token_counter.count_messages_tokens(messages)

        # 只保留最近 N 条
        kept_messages = messages[-keep_recent:] if len(messages) > keep_recent else messages
        kept_tokens = self.token_counter.count_messages_tokens(kept_messages)

        compression_ratio = kept_tokens / original_tokens if original_tokens > 0 else 1.0

        self.logger.info(
            "SLIDING_WINDOW 压缩完成",
            original_count=len(messages),
            kept_count=len(kept_messages),
            original_tokens=original_tokens,
            kept_tokens=kept_tokens,
            compression_ratio=round(compression_ratio, 2),
        )

        return CompressionResult(
            summary="",  # 无摘要
            compressed_tokens=kept_tokens,
            original_tokens=original_tokens,
            kept_messages=kept_messages,
            compression_ratio=compression_ratio,
        )

    def _compress_keep_recent(
        self,
        messages: List[Dict[str, Any]],
        keep_recent: int,
    ) -> CompressionResult:
        """
        KEEP_RECENT 策略：仅保留最近消息

        与 SLIDING_WINDOW 类似，但语义更明确：
        严格只保留最近 N 条，完全丢弃历史
        """
        if not messages:
            return CompressionResult(
                summary="",
                compressed_tokens=0,
                original_tokens=0,
                kept_messages=[],
                compression_ratio=1.0,
            )

        original_tokens = self.token_counter.count_messages_tokens(messages)

        # 严格只保留最近 N 条
        kept_messages = messages[-keep_recent:] if len(messages) > keep_recent else messages
        kept_tokens = self.token_counter.count_messages_tokens(kept_messages)

        compression_ratio = kept_tokens / original_tokens if original_tokens > 0 else 1.0

        self.logger.info(
            "KEEP_RECENT 压缩完成",
            original_count=len(messages),
            kept_count=len(kept_messages),
            original_tokens=original_tokens,
            kept_tokens=kept_tokens,
            compression_ratio=round(compression_ratio, 2),
        )

        return CompressionResult(
            summary="",  # 无摘要
            compressed_tokens=kept_tokens,
            original_tokens=original_tokens,
            kept_messages=kept_messages,
            compression_ratio=compression_ratio,
        )

    def _compress_truncate(
        self,
        messages: List[Dict[str, Any]],
        target_tokens: int,
    ) -> CompressionResult:
        """
        TRUNCATE 策略：按 token 数截断

        从最新的消息开始保留，直到达到目标 token 数
        """
        if not messages:
            return CompressionResult(
                summary="",
                compressed_tokens=0,
                original_tokens=0,
                kept_messages=[],
                compression_ratio=1.0,
            )

        original_tokens = self.token_counter.count_messages_tokens(messages)

        # 从最新消息开始，逐条添加直到达到目标
        kept_messages = []
        current_tokens = 0

        for msg in reversed(messages):
            msg_tokens = self.token_counter.count_tokens(msg.get("content", ""))
            if current_tokens + msg_tokens <= target_tokens:
                kept_messages.insert(0, msg)
                current_tokens += msg_tokens
            else:
                break

        compression_ratio = current_tokens / original_tokens if original_tokens > 0 else 1.0

        self.logger.info(
            "TRUNCATE 压缩完成",
            original_count=len(messages),
            kept_count=len(kept_messages),
            original_tokens=original_tokens,
            kept_tokens=current_tokens,
            target_tokens=target_tokens,
            compression_ratio=round(compression_ratio, 2),
        )

        return CompressionResult(
            summary="",  # 无摘要
            compressed_tokens=current_tokens,
            original_tokens=original_tokens,
            kept_messages=kept_messages,
            compression_ratio=compression_ratio,
        )

    # ========== 辅助方法 ==========

    def _build_compression_prompt(
        self, messages: List[Dict[str, Any]], target_tokens: int
    ) -> str:
        """
        构建压缩提示词

        Args:
            messages: 要压缩的消息列表
            target_tokens: 目标 token 数

        Returns:
            完整的提示词
        """
        # 格式化消息
        messages_text = "\n".join(
            f"[{msg.get('role', 'user')}]: {msg.get('content', '')}"
            for msg in messages
        )

        # 构建完整提示词
        prompt = f"""{self.summary_prompt}

请将以下对话压缩为约 {target_tokens} 个 token 的摘要:

---
{messages_text}
---

摘要:"""

        return prompt

    def _clean_summary(self, summary: str) -> str:
        """
        清理摘要内容

        Args:
            summary: 原始摘要

        Returns:
            清理后的摘要
        """
        # 移除可能的 markdown 代码块标记
        summary = summary.strip()

        # 移除 ``` 开头和结尾
        if summary.startswith("```"):
            lines = summary.split("\n")
            if len(lines) > 1:
                # 移除第一行（```language）
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            summary = "\n".join(lines)

        # 移除 "摘要:" 前缀
        if summary.startswith("摘要:"):
            summary = summary[3:].strip()
        elif summary.startswith("摘要："):
            summary = summary[3:].strip()

        return summary.strip()
