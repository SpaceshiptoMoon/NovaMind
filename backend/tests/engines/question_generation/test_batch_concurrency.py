"""假设问题批间并发回归测试（2026-11-20 离线优化批次）。

generate_questions_batch 从串行批循环改为有界并发（max_concurrent_batches
信号量）。回归面：
1. 正确性：乱序完成批次按 chunk 索引回填，results 位置不串；
2. 有界性：在飞批次峰值 ≤ max_concurrent_batches；
3. 降级语义：批全空 → 逐块降级，stats 计数保持。
"""
import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.engines.question_generation.service import (
    QuestionGenConfig,
    QuestionGenerationService,
)

pytestmark = pytest.mark.unit


class _FakeLLM:
    pass


def _make_service() -> QuestionGenerationService:
    return QuestionGenerationService(llm_client=_FakeLLM(), config=QuestionGenConfig())


def _mock_batch_generation(service, *, batch_delay_s: float = 0.0, delay_probe=None):
    """mock _generate_batch_questions：按 chunk 内容标记回填问题，记录完成序与在飞峰值。

    chunk 内容约定 "chunk-{i}"——从批次首 chunk 解析批次号（batch_start）。
    delay_probe(idx, in_flight) 供调用方观测并发行为。
    """
    in_flight = {"n": 0, "peak": 0}
    finished_order: list[int] = []

    async def fake_generate_batch_questions(llm_client, batch, temperature, top_p, max_tokens):
        first_content = batch[0][0]
        batch_idx = int(first_content.split("-")[1])
        in_flight["n"] += 1
        in_flight["peak"] = max(in_flight["peak"], in_flight["n"])
        if callable(delay_probe):
            delay_probe(batch_idx, in_flight["n"])
        if batch_delay_s:
            await asyncio.sleep(batch_delay_s * (batch_idx % 3))  # 乱序延迟
        finished_order.append(batch_idx)
        in_flight["n"] -= 1
        # 适配 _generate_batch_questions 的返回契约：(每 chunk 的问题列表, signals)
        # 问题编码 = 所属 chunk 内容标记（chunk-{n} → q-{n}），断言可对全局序号
        return [
            [
                type("GQ", (), {"index": 0, "question": f"q-{content.split('-')[1]}", "category": None})
            ]
            for (content, _) in batch
        ], {}

    service._generate_batch_questions = fake_generate_batch_questions
    return in_flight, finished_order


def _chunks(n: int) -> list[tuple[str, None]]:
    return [(f"chunk-{i}", None) for i in range(n)]


@pytest.mark.asyncio
async def test_batch_concurrency_results_filled_by_index():
    """乱序完成批次必须按 chunk 索引回填（30 chunk / 10 批，乱序延迟）。"""
    service = _make_service()
    _mock_batch_generation(service, batch_delay_s=0.03)

    chunks = _chunks(30)
    results, stats = await service.generate_questions_batch(
        chunks, batch_size=3, max_concurrent_batches=4,
    )

    assert len(results) == 30
    for i, qs in enumerate(results):
        assert len(qs) == 1, f"chunk-{i} 的问题不得缺失或串位"
        assert qs[0].question == f"q-{i}", (
            f"chunk-{i} 的问题必须来自其所属批次，实际: {qs[0].question}"
        )
    assert stats.batches_total == 10
    assert stats.batches_failed == 0


@pytest.mark.asyncio
async def test_batch_concurrency_bounded_by_semaphore():
    """在飞批次峰值不得超过 max_concurrent_batches。"""
    service = _make_service()
    in_flight, _finished = _mock_batch_generation(service, batch_delay_s=0.05)

    chunks = _chunks(36)  # batch_size=3 → 12 批
    await service.generate_questions_batch(
        chunks, batch_size=3, max_concurrent_batches=4,
    )
    assert in_flight["peak"] <= 4, f"在飞批次峰值 {in_flight['peak']} 超过并发上限 4"
    assert in_flight["peak"] >= 2, f"在飞峰值 {in_flight['peak']} 说明批间根本没有并发"


@pytest.mark.asyncio
async def test_degrade_semantics_preserved_under_concurrency():
    """并发下降级语义保持：全空批逐块降级、stats 计数不串。"""
    service = _make_service()

    async def fake_generate_batch_questions(llm_client, batch, temperature, top_p, max_tokens):
        # 全部返回空 → 触发逐块降级
        return [[] for _ in batch], {}

    async def fake_degrade(llm_client, batch, temperature, top_p, max_tokens):
        # 降级按 chunk 内容标记回填，前 3 块救回、其余留空
        out = []
        for i, (content, _) in enumerate(batch):
            idx = int(content.split("-")[1])
            if idx % 2 == 0:
                from novamind.engines.question_generation.service import GeneratedQuestion

                out.append([GeneratedQuestion(index=0, question=f"degraded-{idx}")])
            else:
                out.append([])
        return out

    service._generate_batch_questions = fake_generate_batch_questions
    service._degrade_to_single_chunks = fake_degrade

    chunks = _chunks(9)  # 3 批 × 3
    results, stats = await service.generate_questions_batch(
        chunks, batch_size=3, max_concurrent_batches=2,
    )
    assert len(results) == 9
    for i, qs in enumerate(results):
        if i % 2 == 0:
            assert len(qs) == 1 and qs[0].question == f"degraded-{i}"
        else:
            assert qs == []
    assert stats.degraded_batches == 3


def test_batch_prompt_truncation_aligned_with_single_path():
    """批量 prompt 的单 chunk 截断与单块降级路径同上限（3000）——
    超长 chunk 尾部信息点也能进批量生成（1000 上限曾造成批量覆盖面
    反而比逐块降级更窄的质量倒挂）。"""
    service = _make_service()
    long_content = "长" * 5000
    prompt = service._build_batch_prompt([(long_content, None)])
    assert "长" * 3000 in prompt
    assert "长" * 3001 not in prompt, "批量路径截断上限应为 3000（对齐单块路径）"
