"""LLM 连接测试的 stream-only 回退：仅支持流式的模型不再被非流式探针误判为连接失败。"""
import pytest

from novamind.features.user.services.model_config_service import (
    is_stream_only_error,
    _probe_llm_stream,
)
from novamind.features.user.schemas.model_config_schema import ModelTestRequest


# ========== is_stream_only_error 判据（正反两用） ==========


@pytest.mark.parametrize(
    "error_msg,expected",
    [
        # 正例：DashScope glm-4.5 原样报错文本
        (
            "Error code: 400 - {'error': {'message': 'This model only support stream mode, "
            "please enable the stream parameter to access the model. ', "
            "'type': 'invalid_request_error', 'code': 'invalid_parameter_error'}}",
            True,
        ),
        ("This model only supports stream mode.", True),
        # 反例：403 鉴权拒绝、超时、thinking 强制——都不能走流式回退
        (
            "Error code: 403 - {'error': {'message': 'Access denied', 'code': 'access_denied'}}",
            False,
        ),
        ("Request timed out", False),
        ("Model requires enable_thinking parameter", False),
    ],
)
def testis_stream_only_error(error_msg, expected):
    """stream 类错误命中判据；鉴权/超时/thinking 错误不命中。"""
    assert is_stream_only_error(error_msg) is expected


# ========== _test_llm 回退行为 ==========


class _StreamOnlyLLM:
    """桩客户端：非流式必抛 stream-only 400，流式返回内容块。"""

    async def generate_text(self, **kwargs):
        raise Exception(
            "Error code: 400 - This model only support stream mode, "
            "please enable the stream parameter to access the model."
        )

    async def generate_text_stream(self, **kwargs):
        yield "Hi"
        yield "!"


class _RaisingLLM:
    """桩客户端：非流式抛非 stream 错误（403），流式不应被触达。"""

    stream_called = False

    async def generate_text(self, **kwargs):
        raise Exception("Error code: 403 - Access denied")

    async def generate_text_stream(self, **kwargs):
        _RaisingLLM.stream_called = True
        yield "should not be reached"


@pytest.mark.asyncio
async def test_test_llm_falls_back_to_stream_probe(monkeypatch):
    """非流式探针遇 stream-only 400 时应回退流式并判定连接成功。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    monkeypatch.setattr(
        "novamind.features.user.services.model_config_service.create_llm_client",
        lambda **kwargs: _StreamOnlyLLM(),
    )
    svc = ModelConfigService(db=None)
    request = ModelTestRequest(
        model_type="llm", protocol="openai", model="glm-4.5", api_key="sk-x"
    )

    # 不抛异常即通过
    await svc._test_llm(request)


class _NonStreamNeverLLM:
    """桩客户端：非流式调用即失败（应永不被触达），流式正常返回。"""

    non_stream_called = False

    async def generate_text(self, **kwargs):
        _NonStreamNeverLLM.non_stream_called = True
        raise Exception("non-stream path should never be called when declared stream_only")

    async def generate_text_stream(self, **kwargs):
        yield "ok"


@pytest.mark.asyncio
async def test_test_llm_declared_stream_only_skips_non_stream_probe(monkeypatch):
    """声明 stream_only（端点注册表或 extra_config）后探针直接走流式，免付必败 400。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    captured = {}

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return _NonStreamNeverLLM()

    monkeypatch.setattr(
        "novamind.features.user.services.model_config_service.create_llm_client",
        _fake_create,
    )
    svc = ModelConfigService(db=None)

    # 路径①：DashScope + glm-4.5 端点注册表命中
    _NonStreamNeverLLM.non_stream_called = False
    request = ModelTestRequest(
        model_type="llm",
        protocol="openai",
        model="glm-4.5",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-x",
    )
    await svc._test_llm(request)
    assert _NonStreamNeverLLM.non_stream_called is False
    assert captured["quirks"].stream_only is True

    # 路径②：任意端点 + extra_config 显式声明
    _NonStreamNeverLLM.non_stream_called = False
    request = ModelTestRequest(
        model_type="llm",
        protocol="openai",
        model="custom-model",
        base_url="https://my-gateway.example.com/v1",
        api_key="sk-x",
        extra_config={"stream_only": True},
    )
    await svc._test_llm(request)
    assert _NonStreamNeverLLM.non_stream_called is False


@pytest.mark.asyncio
async def test_test_llm_non_stream_error_still_raises(monkeypatch):
    """403 等非 stream 错误不应触发流式回退，原样抛出。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    _RaisingLLM.stream_called = False
    monkeypatch.setattr(
        "novamind.features.user.services.model_config_service.create_llm_client",
        lambda **kwargs: _RaisingLLM(),
    )
    svc = ModelConfigService(db=None)
    request = ModelTestRequest(
        model_type="llm", protocol="openai", model="gpt-4o", api_key="sk-x"
    )

    with pytest.raises(Exception, match="Access denied"):
        await svc._test_llm(request)
    assert not _RaisingLLM.stream_called


@pytest.mark.asyncio
async def test_probe_llm_stream_returns_joined_content():
    """流式探针把内容块拼接为完整字符串。"""

    async def _gen():
        yield "A"
        yield "B"

    client = type("_C", (), {"generate_text_stream": staticmethod(lambda **kw: _gen())})()
    assert await _probe_llm_stream(client) == "AB"
