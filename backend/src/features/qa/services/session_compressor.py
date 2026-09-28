"""qa 会话压缩器（批次 5.1 从 shared/utils/text_utils 迁入 qa 域）。

会话压缩是 qa 业务能力（消费 qa 的 LLM 客户端与配置），不属于通用工具层。
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any

from novamind.shared.ai_models.base_model import BaseLLM
from novamind.shared.logging import get_logger
from novamind.shared.prompts.templates import PromptManager
from novamind.shared.utils.text_utils.token_counter import TokenCounter


class CompressionStrategy(str, Enum):
    """会话压缩策略枚举：摘要/滑动窗口/保留最近/截断。"""
    SUMMARY = "summary"
    SLIDING_WINDOW = "sliding_window"
    KEEP_RECENT = "keep_recent"
    TRUNCATE = "truncate"


@dataclass
class CompressionResult:
    """压缩结果：摘要文本、前后 token 数、保留消息与压缩比。"""
    summary: str
    compressed_tokens: int
    original_tokens: int
    kept_messages: list[dict[str, Any]]
    compression_ratio: float


class TextCompressor:
    """会话上下文压缩器：按策略把超限消息压成摘要或截断窗口。"""
    def __init__(
        self,
        llm_client: BaseLLM | None = None,
        custom_prompt: str | None = None,
    ):
        """注入可选 LLM 客户端与自定义摘要提示词（LLM 缺席时降级为拼接）。"""
        self.llm_client = llm_client
        self.custom_prompt = custom_prompt
        self.token_counter = TokenCounter()
        self.logger = get_logger(__name__)

    @property
    def summary_prompt(self) -> str:
        """摘要提示词：自定义优先，否则取注册模板。"""
        return self.custom_prompt or PromptManager.get_template(
            "qa_compression_summary"
        )

    def _message_text(self, message: dict[str, Any]) -> str:
        """提取消息文本，兼容纯字符串与多模态分段列表两种 content 形态。"""
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

    def _messages_tokens(self, messages: list[dict[str, Any]]) -> int:
        """统计整组消息的 token 总数。"""
        return self.token_counter.count_messages_tokens(messages)

    async def compress_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        target_tokens: int = 500,
        keep_recent: int = 4,
    ) -> CompressionResult:
        """按摘要策略压缩消息列表（默认入口，参数透传给通用策略接口）。

        Args:
            messages: 消息字典列表（role/content），按时间序排列。
            target_tokens: 压缩后摘要的 token 预算，默认 500。
            keep_recent: 保留原文的最近消息条数，默认 4；其余进入摘要。

        Returns:
            压缩结果（摘要文本/前后 token 数/保留消息/压缩比）。
        """
        return await self.compress_with_strategy(
            messages,
            strategy=CompressionStrategy.SUMMARY.value,
            target_tokens=target_tokens,
            keep_recent=keep_recent,
        )

    async def compress_with_base_summary(
        self,
        base_summary: str,
        new_messages: list[dict[str, Any]],
        target_tokens: int = 500,
    ) -> CompressionResult:
        """增量压缩：把新消息融合进旧摘要。

        有 LLM 时走 ``qa_compression_merge`` 模板做融合摘要（摘要长度有界，
        不会随轮次无界膨胀）；LLM 缺席（纯本地降级）时退回字符串拼接，此时
        调用方应注意拼接结果的 token 会随新消息增长。
        """
        existing = base_summary.strip()
        summary = existing
        if new_messages:
            added_text = "\n".join(self._message_text(msg) for msg in new_messages)
            if existing and self.llm_client is not None:
                summary = await self._merge_summary(
                    existing, added_text, target_tokens=target_tokens,
                )
            else:
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

    async def _merge_summary(
        self, existing_summary: str, new_text: str, *, target_tokens: int = 500,
    ) -> str:
        """LLM 融合摘要：新消息并入旧摘要，输出长度受 target_tokens 约束。

        LLM 调用失败时降级为拼接（宁可摘要偏长也不丢上下文），由调用方的
        超阈值重压路径兜底收敛。
        """
        try:
            prompt = PromptManager.format_prompt(
                "qa_compression_merge",
                target_tokens=target_tokens,
            )
            merged = await self.llm_client.generate_text(
                prompt=(
                    f"{prompt}\n\n"
                    f"## EXISTING SUMMARY\n{existing_summary}\n\n"
                    f"## NEW MESSAGES\n{new_text}"
                ),
                max_tokens=max(256, min(target_tokens, 1024)),
            )
            if merged and merged.strip():
                return merged.strip()
        except Exception as merge_err:
            self.logger.warning(
                "增量摘要 LLM 融合失败，降级为拼接",
                error=str(merge_err),
            )
        return f"{existing_summary}\n{new_text}".strip()

    async def compress_with_strategy(
        self,
        messages: list[dict[str, Any]],
        *,
        strategy: str = "summary",
        target_tokens: int = 500,
        keep_recent: int = 4,
    ) -> CompressionResult:
        """按指定策略压缩：截断/滑窗只保留消息，摘要策略另调 LLM 生成摘要。

        Args:
            messages: 消息字典列表（role/content），按时间序排列。
            strategy: 压缩策略（summary/sliding_window/keep_recent/truncate），未知值按 summary 处理。
            target_tokens: token 预算：truncate 下为保留上限，summary 下为摘要长度目标，默认 500。
            keep_recent: 滑窗/摘要策略保留的最近消息条数，默认 4；0 表示不留原文。

        Returns:
            压缩结果（摘要文本/前后 token 数/保留消息/压缩比）；空入参返回全零结果。
        """
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

    def _truncate_to_target(self, messages: list[dict[str, Any]], target_tokens: int) -> list[dict[str, Any]]:
        """从最新消息倒序保留至 token 预算用尽，至少保留一条，按时间序返回。"""
        kept: list[dict[str, Any]] = []
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

    async def _build_summary(self, messages: list[dict[str, Any]]) -> str:
        """对被压缩的消息生成摘要：无 LLM 时降级为原文拼接。"""
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
