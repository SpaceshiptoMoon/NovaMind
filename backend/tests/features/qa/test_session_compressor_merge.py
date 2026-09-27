"""增量摘要 LLM 融合回归测试（评审 P1-5）。

compress_with_base_summary 历史实现是纯字符串拼接——strategy 配置为 summary
但增量路径从不调 LLM，长会话反复超阈值后"摘要"退化为全量历史拼接，token
预算控制失效。修复后：有 LLM 时走 qa_compression_merge 融合摘要（长度受
target_tokens 约束）；LLM 缺席/调用失败时降级拼接（宁长勿丢）。

正反用例：
- 正例：有 LLM → 调用融合模板，摘要为 LLM 产物且长度有界；
- 反例 1：无 LLM → 降级拼接（历史行为保留，供无模型环境兜底）；
- 反例 2：LLM 抛错 → 降级拼接不抛异常。
"""
from __future__ import annotations

import pytest

from novamind.features.qa.services.session_compressor import TextCompressor
from novamind.shared.ai_models.base_model import BaseLLM

pytestmark = pytest.mark.unit


class _MergeLLM(BaseLLM):
    """融合桩：返回固定长度受控摘要，记录收到的 prompt。

    仅压缩路径会被调用，embedding/rerank 等抽象方法给空实现。
    """

    def __init__(self, reply: str = "融合后的简短摘要"):
        self.received_prompt = ""
        self.received_max_tokens = None
        self._reply = reply
        self.raise_error = False

    async def generate_text(self, prompt: str, max_tokens: int = 2048, **kwargs) -> str:
        self.received_prompt = prompt
        self.received_max_tokens = max_tokens
        if self.raise_error:
            raise RuntimeError("LLM down")
        return self._reply

    async def generate_text_stream(self, *args, **kwargs):
        yield ""
        return

    async def generate_embedding(self, text: str) -> list[float]:
        return []

    async def generate_embeddings_batch(self, texts, batch_size=None):
        return [[] for _ in texts]

    async def rerank(self, query, documents, top_k=3):
        return []


def _msgs(n: int) -> list[dict]:
    return [{"role": "user", "content": f"消息{i}：一些需要被融合的上下文"} for i in range(n)]


@pytest.mark.asyncio
async def test_merge_uses_llm_and_bounds_length():
    """正例：有 LLM → 走融合模板（含 EXISTING SUMMARY 与 NEW MESSAGES 段）。"""
    llm = _MergeLLM(reply="更新后的紧凑摘要")
    compressor = TextCompressor(llm_client=llm)

    result = await compressor.compress_with_base_summary(
        base_summary="旧摘要：用户在调研 RAG 方案",
        new_messages=_msgs(4),
        target_tokens=800,
    )

    assert result.summary == "更新后的紧凑摘要"
    assert "EXISTING SUMMARY" in llm.received_prompt
    assert "NEW MESSAGES" in llm.received_prompt
    assert "旧摘要：用户在调研 RAG 方案" in llm.received_prompt
    # 融合产物 token 远小于拼接（证明不是降级路径）
    assert result.compressed_tokens < 50


@pytest.mark.asyncio
async def test_no_llm_degrades_to_concat():
    """反例：LLM 缺席 → 保持历史拼接行为（无模型环境的兜底语义不变）。"""
    compressor = TextCompressor(llm_client=None)

    result = await compressor.compress_with_base_summary(
        base_summary="旧摘要",
        new_messages=_msgs(2),
    )

    assert "旧摘要" in result.summary
    assert "消息0" in result.summary


@pytest.mark.asyncio
async def test_llm_failure_degrades_to_concat_not_raise():
    """反例：LLM 调用失败 → 降级拼接，不向调用方抛异常。"""
    llm = _MergeLLM()
    llm.raise_error = True
    compressor = TextCompressor(llm_client=llm)

    result = await compressor.compress_with_base_summary(
        base_summary="旧摘要",
        new_messages=_msgs(2),
    )

    assert "旧摘要" in result.summary
    assert "消息0" in result.summary
