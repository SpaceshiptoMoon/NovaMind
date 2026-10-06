"""OllamaLLM 工具调用测试：非流式工具解析、dict arguments 归一化、错误翻译。"""
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from novamind.shared.ai_models.llm.ollama_llm import OllamaLLM


def _make_llm() -> OllamaLLM:
    llm = OllamaLLM.__new__(OllamaLLM)
    llm.api_key = ""
    llm.base_url = "http://localhost:11434"
    llm.model = "llama3"
    llm.timeout = 30
    llm.max_retries = 1
    llm._semaphore = None
    llm._max_concurrent = 5
    llm.default_system_prompt = "You are a helpful assistant."
    llm._http_client = None
    llm._http_client_lock = None
    return llm


def _mock_response(payload: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=payload)
    resp.text = json.dumps(payload, ensure_ascii=False)
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            f"Error code: {status_code}",
            request=MagicMock(),
            response=MagicMock(status_code=status_code),
        )
        if status_code >= 400
        else None
    )
    return resp


@pytest.mark.asyncio
async def test_generate_with_tools_parses_dict_arguments():
    """Ollama tool_calls[].function.arguments 是 dict → 归一为 JSON 字符串。"""
    llm = _make_llm()
    llm._get_http_client = AsyncMock(return_value=MagicMock(
        post=AsyncMock(return_value=_mock_response({
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "abc",
                    "function": {"name": "get_weather", "arguments": {"city": "北京"}},
                }],
            },
            "prompt_eval_count": 10,
            "eval_count": 20,
        }))
    ))

    resp = await llm.generate_with_tools(
        prompt="hi",
        tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {}}}],
    )
    assert resp.finish_reason == "tool_calls"
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.name == "get_weather"
    import json
    assert json.loads(tc.arguments) == {"city": "北京"}
    assert resp.usage == {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

    # OpenAI function 外壳被剥掉，直接发 Ollama 格式 tools
    payload = llm._get_http_client.return_value.post.call_args.kwargs["json"]
    assert payload["tools"] == [{"name": "get_weather", "parameters": {}}]


@pytest.mark.asyncio
async def test_generate_with_tools_no_tools_returns_content():
    """无 tool_calls 时 finish_reason=stop、tool_calls=None。"""
    llm = _make_llm()
    llm._get_http_client = AsyncMock(return_value=MagicMock(
        post=AsyncMock(return_value=_mock_response({
            "message": {"content": "直接回答"},
            "prompt_eval_count": 5,
            "eval_count": 7,
        }))
    ))

    resp = await llm.generate_with_tools(prompt="hi", tools=None)
    assert resp.content == "直接回答"
    assert resp.tool_calls is None
    assert resp.finish_reason == "stop"


@pytest.mark.asyncio
async def test_http_error_translated_to_provider_error():
    """HTTP 状态错误经 translate_provider_error 统一翻译；带计费词面归额度类。"""
    from novamind.shared.ai_models.errors import ModelProviderError, ModelQuotaError

    llm = _make_llm()
    # 额度词面（quota）+ 4xx → ModelQuotaError
    llm._get_http_client = AsyncMock(return_value=MagicMock(
        post=AsyncMock(return_value=_mock_response(
            {"error": "insufficient quota for model"}, status_code=403,
        ))
    ))
    with pytest.raises(ModelQuotaError):
        await llm.generate_with_tools(prompt="hi", tools=None)

    # 无计费词面的普通 4xx → ModelProviderError（不误判）
    llm._get_http_client = AsyncMock(return_value=MagicMock(
        post=AsyncMock(return_value=_mock_response(
            {"error": "model requires newer ollama version"}, status_code=400,
        ))
    ))
    with pytest.raises(ModelProviderError) as exc_info:
        await llm.generate_with_tools(prompt="hi", tools=None)
    assert type(exc_info.value) is ModelProviderError


@pytest.mark.asyncio
async def test_stream_text_error_translated():
    """流式路径的错误翻译同覆盖（raise_for_status 处）。"""
    llm = _make_llm()
    client = MagicMock()

    class _FakeStreamCtx:
        async def __aenter__(self):
            return _mock_response({"error": "arrearage"}, status_code=400)

        async def __aexit__(self, *args):
            return None

    client.stream = MagicMock(return_value=_FakeStreamCtx())
    llm._get_http_client = AsyncMock(return_value=client)

    with pytest.raises(Exception) as exc_info:
        async for _ in llm.generate_text_stream(prompt="hi"):
            pass
    from novamind.shared.ai_models.errors import ModelProviderError
    assert isinstance(exc_info.value, ModelProviderError)
