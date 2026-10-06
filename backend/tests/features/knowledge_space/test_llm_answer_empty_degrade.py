"""
LLM 回答生成的空答案降级与 max_tokens 透传回归测试

背景：思考型模型（如 glm-5.3-flash 经 Anthropic 端点，思考不可关）可能把
max_tokens 预算全部花在思考上，generate_text 返回空串。此前空串被当"成功"
记录（answer=""、无 answer_error），MCP/API 消费方拿到假成功。修复后空答案
按失败降级（answer=None + answer_error），且 max_tokens 从 SearchLLMConfig
透传（默认 1024→4096，给思考 token 留余量）。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from novamind.features.knowledge_space.schemas.search_schema import SearchLLMConfig
from novamind.features.knowledge_space.services.search_service import SearchService


def _make_service(llm_answer: str):
    """构造最小 SearchService：只注入 _get_llm_client 的返回。"""
    service = SearchService.__new__(SearchService)
    service.logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
    llm_client = SimpleNamespace(generate_text=AsyncMock(return_value=llm_answer))
    service._get_llm_client = AsyncMock(return_value=llm_client)
    return service, llm_client


def _run_generate(service, llm_config):
    return asyncio.run(service._generate_llm_answer(
        query="测试问题",
        results=[{"content": "片段内容"}],
        llm_config=llm_config,
        user_id=1,
    ))


def test_empty_answer_degrades_to_error_not_fake_success():
    """反例：LLM 返回空串（思考吃满预算）时必须降级为 answer_error，不得假成功。"""
    service, _ = _make_service(llm_answer="")
    result = _run_generate(service, SearchLLMConfig(enabled=True, temperature=0.3))

    assert result["answer"] is None
    assert result.get("answer_error")
    assert result.get("error")


def test_non_empty_answer_succeeds_with_content():
    """正例：正常文本回答时 answer 原样返回、无 error，相邻场景不误伤。"""
    service, _ = _make_service(llm_answer="这是基于检索片段生成的回答。")
    result = _run_generate(service, SearchLLMConfig(enabled=True, temperature=0.3))

    assert result["answer"] == "这是基于检索片段生成的回答。"
    assert "answer_error" not in result
    assert "error" not in result
    assert result["model"] is None  # 未显式指定模型，走用户默认


def test_max_tokens_passed_through_from_config_not_hardcoded():
    """max_tokens 必须从 SearchLLMConfig 透传到 LLM 客户端，不得硬编码。"""
    service, llm_client = _make_service(llm_answer="ok")
    _run_generate(service, SearchLLMConfig(enabled=True, max_tokens=8192))

    kwargs = llm_client.generate_text.await_args.kwargs
    assert kwargs["max_tokens"] == 8192


def test_default_max_tokens_is_4096():
    """schema 默认值 4096：给思考型模型的思考 token 留余量（旧值 1024 易被吃满）。"""
    assert SearchLLMConfig(enabled=True).max_tokens == 4096
