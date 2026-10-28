"""问题生成批次重试策略与 metrics 透出的回归测试。

背景（doc787 实例）：thinking 模型（qwen3 强制 enable_thinking=True）思考 token
计入 max_completion_tokens，空响应（content 空 + completion 撞满 2048）触发
批内重试；旧实现整批固定 120s 超时导致 4/6 批次静默丢弃（12/16 分块无问题），
节点 metrics 只报 total_questions=20 掩盖了缺口。

本文件锁定三层重试语义：
1. 批内重试：空响应缩短 max_tokens 重试，单次调用超时不放弃整批；
2. 逐块降级：批内耗尽后逐 chunk 独立调用，成功一块救一块；
3. 留空 + 计数：全部失败的批次留空并计入 batches_failed，metrics 可见。
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    QuestionGenerationConfig,
)
from novamind.engines.question_generation.service import (
    QuestionGenConfig,
    MAX_BATCH_ATTEMPTS,
    PER_CALL_TIMEOUT_SECONDS,
    QuestionGenerationService,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeLLM:
    """可编程 LLM 桩：批量调用按 "batch" 键取序列，单块调用按 chunk 标记取序列。

    Attributes:
        script: 键 → 响应序列；元素为 str（正常响应）/
            Exception（抛出）/ None（模拟超过单次调用超时的挂起）。
            批量 prompt 含 "### 分块 2"（≥2 块时）；单块 prompt 含 chunk
            原文，因此用 chunk 内容本身作键即可区分不同 chunk 的调用。
    """

    def __init__(self, script: dict[str, list]):
        self.script = script
        self.calls: list[tuple[str, int, int]] = []  # (key, attempt, max_tokens)

    def _resolve_key(self, prompt: str) -> str:
        if "### 分块 2" in prompt:
            return "batch"
        for key in self.script:
            if key != "batch" and key in prompt:
                return key
        return "batch"

    async def generate_text(self, prompt: str, max_tokens: int = 1024, **kwargs):
        key = self._resolve_key(prompt)
        seq = self.script.setdefault(key, [])
        attempt = len([c for c in self.calls if c[0] == key])
        self.calls.append((key, attempt, max_tokens))
        if attempt >= len(seq):
            # 序列耗尽：默认成功响应（验证"重试后恢复"路径的终止态）。
            # 单块路径的输出契约是顶层数组（与 _build_prompt 示例一致）。
            return '[{"question": "q-ok", "category": "factual"}]'
        item = seq[attempt]
        if isinstance(item, Exception):
            raise item
        if item is None:
            # 模拟超时：挂起超过单次调用超时（测试中把 PER_CALL_TIMEOUT 调小）
            import asyncio

            await asyncio.sleep(PER_CALL_TIMEOUT_SECONDS + 5)
        return item


def _service() -> QuestionGenerationService:
    from unittest.mock import AsyncMock

    llm = SimpleNamespace(generate_text=AsyncMock(return_value='{"chunks": []}'))
    return QuestionGenerationService(
        llm_client=llm,
        config=QuestionGenConfig(max_questions_per_chunk=5),
    )


@pytest.mark.anyio("asyncio")
async def test_empty_response_retries_with_shrunk_max_tokens(monkeypatch):
    """空响应触发批内重试，且重试轮次携带缩短后的 max_tokens。"""
    svc = _service()
    llm = FakeLLM({"batch": ["", '{"chunks":[{"questions":[{"question":"q1"}]}]}']})
    monkeypatch.setattr(svc, "llm_client", llm)

    results, stats = await svc.generate_questions_batch(
        chunks=[("内容A", None), ("内容B", None), ("内容C", None)]
    )

    batch_calls = [c for c in llm.calls if c[0] == "batch"]
    assert len(batch_calls) == 2
    # 首轮用原始 max_tokens（默认配置 2048 上限），空响应轮次缩短
    assert batch_calls[0][2] == 2048
    assert batch_calls[1][2] == int(2048 * 0.5)
    assert results[0][0].question == "q1"
    assert stats.batches_total == 1
    assert stats.batches_failed == 0


@pytest.mark.anyio("asyncio")
async def test_batch_timeout_does_not_abort_batch_triggers_degrade(monkeypatch):
    """单次调用超时后批内继续重试；全部轮次耗尽触发逐块降级恢复。"""
    svc = _service()
    # 批量调用：超时 → 空响应 → 空响应（耗尽 3 轮）；单块调用全部成功
    llm = FakeLLM({
        "batch": [None, "", ""],
        "块0": ['[{"question": "s1"}]'],
        "块1": ['[{"question": "s2"}]'],
        "块2": ['[{"question": "s3"}]'],
    })
    monkeypatch.setattr(svc, "llm_client", llm)
    # 把单次调用超时调小，避免测试真的挂 90s
    monkeypatch.setattr(
        "novamind.engines.question_generation.service."
        "PER_CALL_TIMEOUT_SECONDS",
        0.2,
    )

    results, stats = await svc.generate_questions_batch(
        chunks=[("块0", None), ("块1", None), ("块2", None)]
    )

    # 逐块降级后每个 chunk 都恢复出问题
    assert [qs[0].question for qs in results] == ["s1", "s2", "s3"]
    assert stats.timeout_batches == 1
    assert stats.degraded_batches == 1
    assert stats.batches_failed == 0
    assert stats.batches_total == 1


@pytest.mark.anyio("asyncio")
async def test_degrade_partial_recovery_leaves_failed_chunks_empty(monkeypatch):
    """逐块降级部分恢复：成功的块有题，失败的块留空并计入失败批次。"""
    svc = _service()
    llm = FakeLLM({
        "batch": ["", "", ""],  # 批内 3 轮全空
        "块0": ['[{"question": "only-0"}]'],
        "块1": ["", "", ""],  # 单块 3 次尝试全空 → 留空
        "块2": [Exception("llm down"), "", ""],  # 异常后重试仍空
    })
    monkeypatch.setattr(svc, "llm_client", llm)

    results, stats = await svc.generate_questions_batch(
        chunks=[("块0", None), ("块1", None), ("块2", None)]
    )

    assert results[0][0].question == "only-0"
    assert results[1] == []
    assert results[2] == []
    # 有恢复 → degraded；同时仍有空块 → 整批计失败
    assert stats.degraded_batches == 1
    assert stats.batches_failed == 1


@pytest.mark.anyio("asyncio")
async def test_llm_client_exception_degrades_to_single_chunks(monkeypatch):
    """LLM 客户端持续异常（raise 路径）也走逐块降级，而非整批丢弃。"""
    svc = _service()
    llm = FakeLLM({
        "batch": [Exception("gateway 502"), Exception("gateway 502"), Exception("gateway 502")],
        "块0": ['[{"question": "recovered"}]'],
        "块1": ['[{"question": "recovered"}]'],
        "块2": ['[{"question": "recovered"}]'],
    })
    monkeypatch.setattr(svc, "llm_client", llm)

    results, stats = await svc.generate_questions_batch(
        chunks=[("块0", None), ("块1", None), ("块2", None)]
    )

    assert all(qs and qs[0].question == "recovered" for qs in results)
    assert stats.batches_failed == 0
    assert stats.degraded_batches == 1


@pytest.mark.anyio("asyncio")
async def test_single_chunk_timeout_uses_per_call_budget(monkeypatch):
    """单块生成路径的超时按单次调用计，不随批大小/重试次数放大预算。"""
    svc = _service()
    # None 表示挂起超时；3 个元素覆盖单块路径 MAX_PARSE_RETRY+1 次尝试
    llm = FakeLLM({"块X": [None, None, None]})
    monkeypatch.setattr(svc, "llm_client", llm)
    monkeypatch.setattr(
        "novamind.engines.question_generation.service."
        "PER_CALL_TIMEOUT_SECONDS",
        0.2,
    )

    questions = await svc._generate_single_with_retry(llm, "块X 内容", 0.3, 0.9, 1024)

    assert questions == []
    # MAX_PARSE_RETRY + 1 次尝试全部发生
    assert len(llm.calls) == 3


@pytest.mark.anyio("asyncio")
async def test_metrics_constants_contract():
    """超时/重试常量契约：防后续调参时无感知漂移（改值应同步改测试意图）。"""
    assert PER_CALL_TIMEOUT_SECONDS == 90
    assert MAX_BATCH_ATTEMPTS == 3


@pytest.mark.anyio("asyncio")
async def test_generate_questions_for_chunks_metrics_passthrough(monkeypatch):
    """generate_questions_for_chunks 返回三元组，stats 原样透传供节点 metrics。"""
    from novamind.features.knowledge_space.services import pipeline_steps
    from novamind.engines.question_generation.service import (
        BatchGenerationStats,
    )

    fake_stats = BatchGenerationStats(
        batches_total=2, batches_failed=1, degraded_batches=1, timeout_batches=1
    )

    class FakeQGService:
        def __init__(self, llm_client=None, config=None):
            pass

        async def generate_questions_batch(self, chunks):
            from novamind.engines.question_generation.service import (
                GeneratedQuestion,
            )

            return [
                [GeneratedQuestion(index=1, question="q1")],
                [],
            ], fake_stats

    async def fake_generate_embeddings(texts, embedding_config, session=None, user_id=None, model_config_port=None):
        return [[0.1] for _ in texts]

    class FakeMCS:
        async def get_user_default_model_name(self, user_id, model_type):
            return "default-llm"

        async def get_llm_client_by_model(self, user_id, model):
            return SimpleNamespace(model=model)

    monkeypatch.setattr(
        "novamind.engines.question_generation.service."
        "QuestionGenerationService",
        FakeQGService,
    )
    monkeypatch.setattr(
        pipeline_steps, "generate_embeddings", fake_generate_embeddings
    )

    questions_list, embeddings_list, stats = await pipeline_steps.generate_questions_for_chunks(
        chunks=["块A", "块B"],
        document_title="Demo",
        kb_config={"question_generation": {"enabled": True}},
        embedding_config={"model": "emb"},
        user_id=7,
        session=SimpleNamespace(),
        model_config_port=FakeMCS(),
    )

    assert questions_list == [["q1"], []]
    # 空问题块对应空向量组
    assert embeddings_list == [[[0.1]], []]
    assert stats.batches_total == 2
    assert stats.batches_failed == 1
    assert stats.to_metrics() == {
        "batches_total": 2,
        "batches_failed": 1,
        "batches_degraded": 1,
        "batches_timeout": 1,
    }
