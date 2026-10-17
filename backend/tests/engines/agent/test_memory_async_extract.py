"""压缩时记忆提取异步化回归测试（arq 后台任务，方案 A）。

覆盖：
- on_turn_done 开关关（默认）：走同步 consolidate，不触 arq 入队
- 开关开 + 入队成功：enqueue_job 收到 asdict 后的 turns，同步路径不执行
- 开关开 + 入队返回 None（任务被拒）：退回同步
- 开关开 + 入队抛异常（Redis 不可达等）：退回同步
- consolidate_memory_task：MemoryMessage 反序列化与 consolidate 参数、
  ES 装配失败降级、mem0 装配失败降级 builtin、异常不外抛
"""
import contextlib
import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _turn(role="user", content="内容"):
    """惯例桩：构造一条 MemoryMessage。"""
    from novamind.engines.agent.memory.interfaces import MemoryMessage

    return MemoryMessage(role=role, content=content)


def _compressor(long_term):
    """惯例桩：构造注入 stub 依赖的 ContextCompressor。"""
    from novamind.engines.agent.memory.context_compressor import ContextCompressor

    c = ContextCompressor.__new__(ContextCompressor)
    c._long_term = long_term
    c._agent_id = 7
    c._user_id = 1
    c._model = "gpt-4o-mini"
    return c


def _long_term():
    """惯例桩：LongTermMemory stub（consolidate 计数）。"""
    lt = SimpleNamespace()
    lt.consolidate = AsyncMock(return_value=2)
    return lt


def _cfg(on_turn_done):
    """惯例桩：get_config 返回值（agent.memory 全部被读取的字段）。"""
    return SimpleNamespace(
        agent=SimpleNamespace(
            memory=SimpleNamespace(on_turn_done=on_turn_done, backend="builtin")
        )
    )


def _cfg_patch(on_turn_done):
    """patch get_config 的目标路径（生产代码内 `from novamind.setting.yaml_config
    import get_config` 为调用期懒 import，每次调用从包属性重新解析）。"""
    return patch(
        "novamind.setting.yaml_config.get_config",
        return_value=_cfg(on_turn_done),
    )


@pytest.mark.asyncio
async def test_switch_off_uses_sync_path():
    """开关关（默认）：直接同步 consolidate，不触 get_arq_pool。"""
    lt = _long_term()
    c = _compressor(lt)
    turns = [_turn(), _turn("assistant")]

    with _cfg_patch(False), patch("novamind.shared.mq.get_arq_pool") as mock_pool:
        await c._extract_memories(turns, 55)

    lt.consolidate.assert_awaited_once()
    kwargs = lt.consolidate.await_args.kwargs
    assert kwargs["agent_id"] == 7
    assert kwargs["conversation_id"] == 55
    assert kwargs["messages"] == turns
    assert kwargs["min_turns"] == 2
    assert kwargs["max_recent_turns"] == 2
    mock_pool.assert_not_called()


@pytest.mark.asyncio
async def test_switch_on_enqueues_and_skips_sync():
    """开关开 + 入队成功：enqueue_job 收到 asdict turns 与 model，同步不执行。"""
    lt = _long_term()
    c = _compressor(lt)
    turns = [_turn(), _turn("assistant", "答复")]

    job = MagicMock()
    pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=job))
    with _cfg_patch(True), patch(
        "novamind.shared.mq.get_arq_pool", AsyncMock(return_value=pool)
    ):
        await c._extract_memories(turns, 55)

    pool.enqueue_job.assert_awaited_once()
    kwargs = pool.enqueue_job.await_args.kwargs
    assert kwargs["agent_id"] == 7
    assert kwargs["user_id"] == 1
    assert kwargs["conversation_id"] == 55
    assert kwargs["turns"] == [dataclasses.asdict(t) for t in turns]
    assert kwargs["model"] == "gpt-4o-mini"
    lt.consolidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_enqueue_rejected_falls_back_to_sync():
    """开关开 + enqueue_job 返回 None（任务被拒）：退回同步提取。"""
    lt = _long_term()
    c = _compressor(lt)
    pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=None))
    with _cfg_patch(True), patch(
        "novamind.shared.mq.get_arq_pool", AsyncMock(return_value=pool)
    ):
        await c._extract_memories([_turn(), _turn()], 55)

    lt.consolidate.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_error_falls_back_to_sync():
    """开关开 + 入队抛异常（Redis 不可达）：退回同步提取。"""
    lt = _long_term()
    c = _compressor(lt)
    pool = SimpleNamespace(enqueue_job=AsyncMock(side_effect=RuntimeError("redis down")))
    with _cfg_patch(True), patch(
        "novamind.shared.mq.get_arq_pool", AsyncMock(return_value=pool)
    ):
        await c._extract_memories([_turn(), _turn()], 55)

    lt.consolidate.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_scope_returns_early():
    """缺 long_term/agent_id 任一：直接返回，零调用。"""
    c = _compressor(None)
    with _cfg_patch(True), patch("novamind.shared.mq.get_arq_pool") as mock_pool:
        await c._extract_memories([_turn()], 55)
    mock_pool.assert_not_called()

    lt = _long_term()
    c2 = _compressor(lt)
    c2._agent_id = None
    with _cfg_patch(True):
        await c2._extract_memories([_turn()], 55)
    lt.consolidate.assert_not_awaited()


# ==================== consolidate_memory_task 任务函数 ====================


class _TaskEnv:
    """任务函数装配桩集合：捕获 LongTermMemory 构造参数与 consolidate 调用。"""

    def __init__(self):
        self.lt_instance = SimpleNamespace(consolidate=AsyncMock(return_value=3))
        self.lt_cls = MagicMock(return_value=self.lt_instance)
        self.session = SimpleNamespace(close=AsyncMock())
        self.mcs = SimpleNamespace(
            get_llm_client_by_model=AsyncMock(),
            get_vlm_client_by_model=AsyncMock(),
            get_user_default_model_name=AsyncMock(return_value="text-embedding-3"),
            get_embedding_client_by_model=AsyncMock(),
        )
        self.search_repo = MagicMock()
        self.es_client_error: Exception | None = None
        self.reconciler_error: Exception | None = None
        self.reconciler = None

    def patches(self):
        """全部依赖的真实模块属性 patch（任务函数内 import 在调用期解析）。"""
        es_factory = AsyncMock(side_effect=self.es_client_error) if self.es_client_error else AsyncMock()
        es_factory.return_value = SimpleNamespace(es_client=MagicMock())

        reconciler_builder = AsyncMock(side_effect=self.reconciler_error) if self.reconciler_error else AsyncMock(return_value=self.reconciler)

        import novamind.core.database.database as db_mod
        import novamind.engines.agent.memory.long_term as lt_mod
        import novamind.features.agent.repository.memory_search_repository as msr_mod
        import novamind.features.agent.services.chat_service as cs_mod
        import novamind.features.agent.services.host_memory_store as hms_mod
        import novamind.features.user.services.model_config_service as mcs_mod
        import novamind.shared.prompts.prompt_manager as pm_mod
        import novamind.shared.storage.client_factory as cf_mod

        def factory():
            # 与真实签名一致：get_session_factory() 返回会话工厂，再调用得 session
            return lambda: self.session

        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(db_mod, "get_session_factory", factory))
        stack.enter_context(patch.object(lt_mod, "LongTermMemory", self.lt_cls))
        stack.enter_context(patch.object(mcs_mod, "ModelConfigService", MagicMock(return_value=self.mcs)))
        stack.enter_context(patch.object(hms_mod, "HostMemoryStorePort", MagicMock()))
        stack.enter_context(patch.object(msr_mod, "MemorySearchRepository", MagicMock(return_value=self.search_repo)))
        stack.enter_context(patch.object(cf_mod, "get_elasticsearch_client", es_factory))
        stack.enter_context(patch.object(pm_mod, "PromptManager", MagicMock()))
        stack.enter_context(patch.object(cs_mod.AgentChatService, "_build_memory_reconciler", reconciler_builder))
        stack.enter_context(_cfg_patch(True))
        return stack


@pytest.mark.asyncio
async def test_task_consolidates_deserialized_turns():
    """任务函数：反序列化 turns 后调 consolidate，参数语义与同步路径一致。"""
    from novamind.features.agent.tasks import memory_tasks

    env = _TaskEnv()
    with env.patches():
        await memory_tasks.consolidate_memory_task(
            {}, agent_id=7, user_id=1, conversation_id=55,
            turns=[{"role": "user", "content": "问题"}, {"role": "assistant", "content": "答复"}],
            model="gpt-4o-mini",
        )

    env.lt_cls.assert_called_once()
    kwargs = env.lt_cls.call_args.kwargs
    assert kwargs["memory_search"] is env.search_repo
    assert kwargs["embedding_factory"] is not None
    assert kwargs["reconciler"] is None  # backend 默认 builtin

    env.lt_instance.consolidate.assert_awaited_once()
    ck = env.lt_instance.consolidate.await_args.kwargs
    assert ck["agent_id"] == 7
    assert ck["conversation_id"] == 55
    assert [m.role for m in ck["messages"]] == ["user", "assistant"]
    assert ck["min_turns"] == 2
    assert ck["max_recent_turns"] == 2
    env.session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_es_failure_degrades():
    """任务函数：ES 装配抛错 → memory_search/embedding_factory 置空，不阻断提取。"""
    from novamind.features.agent.tasks import memory_tasks

    env = _TaskEnv()
    env.es_client_error = RuntimeError("es down")
    with env.patches():
        await memory_tasks.consolidate_memory_task(
            {}, agent_id=7, user_id=1, conversation_id=55,
            turns=[{"role": "user", "content": "q"}], model="m",
        )

    assert env.lt_cls.call_args.kwargs["memory_search"] is None
    assert env.lt_cls.call_args.kwargs["embedding_factory"] is None
    env.lt_instance.consolidate.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_mem0_reconciler_assembly_failure_degrades_builtin():
    """任务函数：mem0 模式下 reconciler 装配失败 → 降级 builtin（reconciler=None）。"""
    from novamind.features.agent.tasks import memory_tasks

    env = _TaskEnv()
    env.reconciler_error = RuntimeError("mem0 missing")
    with env.patches(), patch(
        "novamind.setting.yaml_config.get_config",
        return_value=SimpleNamespace(
            agent=SimpleNamespace(
                memory=SimpleNamespace(on_turn_done=True, backend="mem0")
            )
        ),
    ):
        await memory_tasks.consolidate_memory_task(
            {}, agent_id=7, user_id=1, conversation_id=55,
            turns=[{"role": "user", "content": "q"}], model="m",
        )

    assert env.lt_cls.call_args.kwargs["reconciler"] is None
    env.lt_instance.consolidate.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_failure_does_not_raise():
    """任务函数：consolidate 抛错不外抛（仅告警日志，session 仍关闭）。"""
    from novamind.features.agent.tasks import memory_tasks

    env = _TaskEnv()
    env.lt_instance.consolidate = AsyncMock(side_effect=RuntimeError("llm down"))
    with env.patches():
        await memory_tasks.consolidate_memory_task(
            {}, agent_id=7, user_id=1, conversation_id=55,
            turns=[{"role": "user", "content": "q"}], model="m",
        )
    env.session.close.assert_awaited_once()


# ==================== reconciler staticmethod 回归 ====================


def test_build_reconciler_is_staticmethod():
    """_build_memory_reconciler 转 staticmethod 后可经类直接调用（任务侧复用面）。"""
    from novamind.features.agent.services.chat_service import AgentChatService

    # staticmethod：类 __dict__ 里是描述符，getattr 后为普通函数
    fn = AgentChatService._build_memory_reconciler
    assert callable(fn)
    assert not hasattr(fn, "__func__"), "应为 staticmethod 而非 bound method"
    assert "model_config_service" in fn.__code__.co_varnames
