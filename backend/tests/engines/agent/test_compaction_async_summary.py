"""压缩摘要任务化回归测试（arq 后台任务，借鉴 pi compaction 思想）。

覆盖：
- compaction_async 开关关（默认）：走同步 _generate_summary，不触 arq 入队
- 开关开 + 入队成功：enqueue_job 收到 asdict 后的 turns，同步摘要不执行，
  compress 结果用静态占位降级
- 开关开 + 入队返回 None（任务被拒）/抛异常（Redis 不可达）：退回同步摘要
- generate_compaction_summary_task：LLM 摘要生成后 save_summary 落库、
  LLM 失败不落库、DB 异常不外抛
"""
import contextlib
import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _turn(role="user", content="内容"):
    from novamind.engines.agent.memory.interfaces import MemoryMessage

    return MemoryMessage(role=role, content=content)


def _compressor(summary_text, *, compaction_async=False):
    """惯例桩：注入 stub LLM 工厂与摘要存储的 ContextCompressor（真实逻辑）。

    开关经构造参数注入（生产为宿主从 agent.memory 配置节读值传入）。
    """
    from novamind.engines.agent.memory.context_compressor import ContextCompressor

    llm = SimpleNamespace(
        generate_text=AsyncMock(return_value=summary_text),
    )
    factory = AsyncMock(return_value=llm)
    store = SimpleNamespace(
        get_latest_summary=AsyncMock(return_value=None),
        save_summary=AsyncMock(),
    )
    c = ContextCompressor(
        llm_client_factory=factory,
        summary_store=store,
        conversation_id=55,
        agent_id=7,
        user_id=1,
        model="gpt-4o-mini",
        compaction_async=compaction_async,
    )
    return c, llm, store


def _budget():
    from novamind.engines.agent.memory.token_budget import TokenBudget

    return TokenBudget("gpt-4")


def _oversized_messages(n=30):
    """构造超出预算、必然触发压缩的消息序列。"""
    return [
        _turn("user" if i % 2 == 0 else "assistant", f"消息 {i} " + "x" * 400)
        for i in range(n)
    ]


def _pool(enqueue_return):
    pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=enqueue_return))
    return patch("novamind.shared.mq.get_arq_pool", AsyncMock(return_value=pool))


def _join(compressed):
    return "\n".join(m.content for m in compressed if isinstance(m.content, str))


# ==================== compress 集成：开关与降级 ====================


@pytest.mark.asyncio
async def test_switch_off_uses_sync_summary():
    """开关关（默认）：走同步 _generate_summary，不触 arq 入队。"""
    c, llm, _ = _compressor("同步摘要正文")
    msgs = _oversized_messages()

    with patch("novamind.shared.mq.get_arq_pool") as mock_pool:
        compressed, triggered, _ = await c.compress(
            msgs, available_tokens=100, token_budget=_budget(),
        )

    assert triggered is True
    assert "同步摘要正文" in _join(compressed)
    mock_pool.assert_not_called()
    llm.generate_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_switch_on_enqueues_and_skips_sync_summary():
    """开关开 + 入队成功：同步摘要 LLM 不执行，主循环走静态占位降级。"""
    c, llm, _ = _compressor("同步摘要正文", compaction_async=True)
    msgs = _oversized_messages()

    with _pool(MagicMock()):
        compressed, triggered, _ = await c.compress(
            msgs, available_tokens=100, token_budget=_budget(),
        )

    assert triggered is True
    llm.generate_text.assert_not_awaited()
    joined = _join(compressed)
    assert "摘要生成不可用" in joined
    # 降级占位不带资源清单段（该段仅摘要成功时携带）
    assert "Resources consulted" not in joined


@pytest.mark.asyncio
async def test_switch_on_enqueue_payload():
    """入队参数契约：turns 序列化为 asdict、previous_summary/身份字段逐项核对。"""
    c, _, _ = _compressor("s", compaction_async=True)
    c._previous_summary = "上一代摘要"
    msgs = _oversized_messages()

    pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=MagicMock()))
    with patch(
        "novamind.shared.mq.get_arq_pool", AsyncMock(return_value=pool)
    ):
        await c.compress(msgs, available_tokens=100, token_budget=_budget())

    kwargs = dict(pool.enqueue_job.await_args.kwargs)
    assert pool.enqueue_job.await_args.args == ("generate_compaction_summary_task",)
    turns = kwargs.pop("turns")
    assert turns == [dataclasses.asdict(t) for t in msgs[: len(turns)]]
    assert len(turns) < len(msgs)  # 只压缩前段，尾部保护区不进任务
    assert kwargs["previous_summary"] == "上一代摘要"
    assert kwargs["conversation_id"] == 55
    assert kwargs["agent_id"] == 7
    assert kwargs["user_id"] == 1
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["compressed_count"] == len(turns)
    assert 0 < kwargs["compression_ratio"] < 1.0


@pytest.mark.asyncio
async def test_enqueue_rejected_falls_back_to_sync():
    """开关开 + enqueue_job 返回 None（任务被拒）：退回同步摘要。"""
    c, llm, _ = _compressor("同步摘要正文")
    msgs = _oversized_messages()

    with _pool(None):
        compressed, _, _ = await c.compress(
            msgs, available_tokens=100, token_budget=_budget(),
        )

    llm.generate_text.assert_awaited_once()
    assert "同步摘要正文" in _join(compressed)


@pytest.mark.asyncio
async def test_enqueue_error_falls_back_to_sync():
    """开关开 + 入队抛异常（Redis 不可达）：退回同步摘要。"""
    c, llm, _ = _compressor("同步摘要正文")
    pool = SimpleNamespace(
        enqueue_job=AsyncMock(side_effect=RuntimeError("redis down"))
    )
    msgs = _oversized_messages()

    with patch(
        "novamind.shared.mq.get_arq_pool", AsyncMock(return_value=pool)
    ):
        compressed, _, _ = await c.compress(
            msgs, available_tokens=100, token_budget=_budget(),
        )

    llm.generate_text.assert_awaited_once()
    assert "同步摘要正文" in _join(compressed)


@pytest.mark.asyncio
async def test_enqueue_skipped_without_conversation_id():
    """无会话 ID（任务侧无处落库）：不投递，直接退回同步摘要。"""
    from novamind.engines.agent.memory.context_compressor import ContextCompressor

    llm = SimpleNamespace(generate_text=AsyncMock(return_value="同步摘要"))
    c = ContextCompressor(
        llm_client_factory=AsyncMock(return_value=llm),
        summary_store=None,
        conversation_id=None,
        agent_id=None, user_id=None,
        model="gpt-4o-mini",
    )
    msgs = _oversized_messages()

    with _pool(MagicMock()) as pool_mock:
        await c.compress(msgs, available_tokens=100, token_budget=_budget())

    pool_mock.assert_not_called()
    llm.generate_text.assert_awaited_once()


# ==================== generate_compaction_summary_task 任务函数 ====================


class _TaskEnv:
    """任务函数装配桩：只替换外部依赖（session 工厂/模型服务/摘要存储），
    ContextCompressor 真实构造——私有方法全真跑，LLM 由注入桩返回。"""

    def __init__(self, llm_summary="异步摘要正文"):
        self.session = SimpleNamespace(close=AsyncMock())
        self.llm = SimpleNamespace(generate_text=AsyncMock(return_value=llm_summary))
        self.store = SimpleNamespace(save_summary=AsyncMock())

    def patches(self):
        import novamind.core.database.database as db_mod
        import novamind.features.agent.services.host_memory_store as hms_mod
        import novamind.features.user.services.model_config_service as mcs_mod

        def factory():
            return lambda: self.session

        mcs = SimpleNamespace(
            get_llm_client_by_model=AsyncMock(return_value=self.llm),
            get_vlm_client_by_model=AsyncMock(),
        )
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(db_mod, "get_session_factory", factory))
        stack.enter_context(
            patch.object(mcs_mod, "ModelConfigService", MagicMock(return_value=mcs))
        )
        stack.enter_context(
            patch.object(
                hms_mod, "HostMemoryStorePort", MagicMock(return_value=self.store)
            )
        )
        return stack


@pytest.mark.asyncio
async def test_task_generates_and_saves_summary():
    """任务正路：LLM 生成摘要后 save_summary 落库（含元数据）。"""
    env = _TaskEnv()
    with env.patches():
        from novamind.features.agent.tasks.compaction_tasks import (
            generate_compaction_summary_task,
        )

        turns = [dataclasses.asdict(_turn("user", "查询一下 x"))]
        await generate_compaction_summary_task(
            ctx={}, conversation_id=55, turns=turns,
            previous_summary=None, compressed_count=1,
            compression_ratio=0.4, agent_id=7, user_id=1, model="gpt-4o-mini",
        )

    env.store.save_summary.assert_awaited_once()
    kwargs = env.store.save_summary.await_args.kwargs
    assert kwargs["conversation_id"] == 55
    assert "异步摘要正文" in kwargs["summary_text"]
    assert kwargs["summary_text"].startswith("<system-compaction>")
    assert kwargs["compressed_count"] == 1
    assert kwargs["compression_ratio"] == 0.4
    assert kwargs["token_count"] > 0


@pytest.mark.asyncio
async def test_task_merge_prompt_carries_previous_summary():
    """增量融合：有 previous_summary 时走 merge prompt（旧摘要进上下文）。"""
    env = _TaskEnv()
    with env.patches():
        from novamind.features.agent.tasks.compaction_tasks import (
            generate_compaction_summary_task,
        )

        await generate_compaction_summary_task(
            ctx={}, conversation_id=55,
            turns=[dataclasses.asdict(_turn("user", "新内容"))],
            previous_summary="<system-compaction>\n旧摘要要点",
            compressed_count=1, compression_ratio=0.4,
            agent_id=7, user_id=1, model="gpt-4o-mini",
        )

    env.store.save_summary.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_llm_failure_does_not_save():
    """任务降级：LLM 失败（返回 None）不落库、不外抛。"""
    env = _TaskEnv(llm_summary=None)
    with env.patches():
        from novamind.features.agent.tasks.compaction_tasks import (
            generate_compaction_summary_task,
        )

        await generate_compaction_summary_task(
            ctx={}, conversation_id=55,
            turns=[dataclasses.asdict(_turn())],
            previous_summary=None, compressed_count=1,
            compression_ratio=0.4, agent_id=7, user_id=1, model="gpt-4o-mini",
        )

    env.store.save_summary.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_db_error_does_not_raise():
    """任务异常：save_summary 抛 DB 错误不外抛（arq 重试兜底）。"""
    env = _TaskEnv()
    env.store.save_summary = AsyncMock(side_effect=RuntimeError("db down"))
    with env.patches():
        from novamind.features.agent.tasks.compaction_tasks import (
            generate_compaction_summary_task,
        )

        await generate_compaction_summary_task(
            ctx={}, conversation_id=55,
            turns=[dataclasses.asdict(_turn())],
            previous_summary=None, compressed_count=1,
            compression_ratio=0.4, agent_id=7, user_id=1, model="gpt-4o-mini",
        )

    env.store.save_summary.assert_awaited_once()
