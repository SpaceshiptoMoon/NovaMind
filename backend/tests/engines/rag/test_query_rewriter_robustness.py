"""QueryRewriter 鲁棒性回归测试。

历史两笔（端到端实测 hyde 策略暴露）：
1. ``_call_llm`` except 分支用 stdlib logger 传 novamind 风格 kwargs
   （``warning(..., error=...)``）——stdlib logger 不接受 kwargs，TypeError
   崩掉异常处理器、掩盖真实 LLM 异常（"stdlib logging kwargs 坑"复发）。
2. ``max_tokens=512`` 对 thinking 模型（glm-5.3/qwen3.8 系列）不够——思考
   token 计入输出预算，512 被 reasoning 吃满致 text 块为空、degraded
   （与 question_generation/service.py 同根因，上限同修 8192）。
"""
from unittest.mock import AsyncMock

import pytest
from novamind.engines.rag.query_rewriter import QueryRewriter, RewriteStrategy

pytestmark = pytest.mark.unit


class _BoomLLM:
    async def generate_text(self, **kwargs):
        raise RuntimeError('simulated llm failure')


@pytest.mark.asyncio
async def test_llm_failure_degrades_without_logger_crash():
    """反例（bug 场景）：LLM 故障时必须干净回退原查询，except 块自身不得抛错。"""
    rw = QueryRewriter(_BoomLLM())
    for strat in (RewriteStrategy.SYNONYM, RewriteStrategy.DECOMPOSE, RewriteStrategy.HYDE):
        res = await rw.rewrite(query='原始查询', strategy=strat, history=[])
        assert res.queries == ['原始查询']
        assert res.degraded is True


@pytest.mark.asyncio
async def test_max_tokens_budget_for_thinking_models():
    """正例守卫：LLM 调用的输出预算必须是 thinking 模型安全的 8192 上限。"""
    llm = AsyncMock()
    llm.generate_text = AsyncMock(return_value='改写结果')
    rw = QueryRewriter(llm)
    await rw.rewrite(query='q', strategy=RewriteStrategy.SYNONYM, history=[])
    _, kwargs = llm.generate_text.call_args
    assert kwargs.get('max_tokens') == 8192
