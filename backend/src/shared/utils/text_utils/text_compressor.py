"""
文本压缩器

使用 LLM 将旧消息压缩为摘要，保留上下文关键信息。
支持摘要、滑动窗口、保留最近、截断四种策略。
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.ai_models.base_model import BaseLLM
from novamind.shared.prompts.templates import PromptManager, PromptTemplate

from .token_counter import TokenCounter


class CompressionStrategy(str, Enum):
    SUMMARY = "summary"
    SLIDING_WINDOW = "sliding_window"
    KEEP_RECENT = "keep_recent"
    TRUNCATE = "truncate"


@dataclass
class CompressionResult:
    summary: str
    compressed_tokens: int
    original_tokens: int
    kept_messages: List[Dict[str, Any]]
    compression_ratio: float


class TextCompressor:
    def __init__(
        self,
        llm_client: Optional[BaseLLM] = None,
        custom_prompt: Optional[str] = None,
    ):
        self.llm_client = llm_client
        self.custom_prompt = custom_prompt
        self.token_counter = TokenCounter()
        self.logger = get_logger(__name__)

    @property
    def summary_prompt(self) -> str:
        return self.custom_prompt or PromptManager.get_template(
            PromptTemplate.QA_COMPRESSION_SUMMARY.value
        )

    def _message_text(self, message: Dict[str, Any]) -> str:
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(content)

    def _messages_tokens(self, messages: List[Dict[str, Any]]) -> int:
        return self.token_counter.count_messages_tokens(messages)

    async def compress_messages(
        self,
        messages: List[Dict[str, Any]],
        *,
        target_tokens: int = 500,
        keep_recent: int = 4,
    ) -> CompressionResult:
        return await self.compress_with_strategy(
            messages,
            strategy=CompressionStrategy.SUMMARY.value,
            target_tokens=target_tokens,
            keep_recent=keep_recent,
        )

    async def compress_with_base_summary(
        self,
        base_summary: str,
        new_messages: List[Dict[str, Any]],
        target_tokens: int = 500,
    ) -> CompressionResult:
        existing = base_summary.strip()
        summary = existing
        if new_messages:
            added_text = "\n".join(self._message_text(msg) for msg in new_messages)
            summary = f"{existing}\n{added_text}".strip() if existing else added_text
        compressed_tokens = self.token_counter.count_tokens(summary)
        original_tokens = self._messages_tokens(new_messages)
        return CompressionResult(
            summary=summary,
            compressed_tokens=compressed_tokens,
            original_tokens=original_tokens,
            kept_messages=list(new_messages),
            compression_ratio=(compressed_tokens / max(original_tokens, 1)),
        )

    async def compress_with_strategy(
        self,
        messages: List[Dict[str, Any]],
        *,
        strategy: str = "summary",
        target_tokens: int = 500,
        keep_recent: int = 4,
    ) -> CompressionResult:
        original_tokens = self._messages_tokens(messages)
        if not messages:
            return CompressionResult("", 0, 0, [], 0.0)

        if strategy == CompressionStrategy.TRUNCATE.value:
            kept = self._truncate_to_target(messages, target_tokens)
            summary = "\n".join(self._message_text(msg) for msg in kept)
        elif strategy in (CompressionStrategy.SLIDING_WINDOW.value, CompressionStrategy.KEEP_RECENT.value):
            kept = list(messages[-keep_recent:]) if keep_recent > 0 else []
            summary = "\n".join(self._message_text(msg) for msg in kept)
        else:
            kept = list(messages[-keep_recent:]) if keep_recent > 0 else []
            summary = await self._build_summary(messages[:-keep_recent] if keep_recent > 0 else messages)
            if kept:
                suffix = "\n".join(self._message_text(msg) for msg in kept)
                summary = f"{summary}\n{suffix}".strip() if summary else suffix

        compressed_tokens = self.token_counter.count_tokens(summary)
        return CompressionResult(
            summary=summary,
            compressed_tokens=compressed_tokens,
            original_tokens=original_tokens,
            kept_messages=kept,
            compression_ratio=(compressed_tokens / max(original_tokens, 1)),
        )

    def _truncate_to_target(self, messages: List[Dict[str, Any]], target_tokens: int) -> List[Dict[str, Any]]:
        kept: List[Dict[str, Any]] = []
        total = 0
        for msg in reversed(messages):
            msg_tokens = self.token_counter.count_tokens(self._message_text(msg))
            if kept and total + msg_tokens > target_tokens:
                break
            kept.append(msg)
            total += msg_tokens
            if total >= target_tokens:
                break
        return list(reversed(kept))

    async def _build_summary(self, messages: List[Dict[str, Any]]) -> str:
        if not messages:
            return ""
        if self.llm_client is None:
            return "\n".join(self._message_text(msg) for msg in messages)
        prompt = self.summary_prompt
        input_text = "\n".join(self._message_text(msg) for msg in messages)
        return await self.llm_client.generate_text(
            prompt=f"{prompt}\n\n{input_text}",
            max_tokens=512,
        )
