"""prompt_cache_key 构造链回归测试（OpenAI prompt caching 路由键 opt-in）。

覆盖三态解析与客户端注入：
- extra_config.prompt_cache_key 缺失/None/false → 不启用（None）；
- 布尔 true → 按模型名生成稳定键 "novamind:{model}"；
- 非空字符串 → 字面量键（strip）；空串视为未启用；
- 客户端配置了 key → extra_body 注入；未配置 → extra_body 原样。
"""
import pytest

from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.ai_models.llm.openai_compatible import OpenAICompatibleLLM

pytestmark = pytest.mark.unit


def test_resolve_missing_and_falsy() -> None:
    """缺失/None/false/空串 → None（请求不带该字段）。"""
    resolve = ModelConfigService._resolve_prompt_cache_key
    assert resolve(None, "m") is None
    assert resolve({}, "m") is None
    assert resolve({"prompt_cache_key": None}, "m") is None
    assert resolve({"prompt_cache_key": False}, "m") is None
    assert resolve({"prompt_cache_key": ""}, "m") is None
    assert resolve({"prompt_cache_key": "  "}, "m") is None
    # 其他类型不猜测
    assert resolve({"prompt_cache_key": 123}, "m") is None


def test_resolve_bool_true_generates_stable_key() -> None:
    """布尔 true → "novamind:{model}" 稳定键（同模型同键）。"""
    resolve = ModelConfigService._resolve_prompt_cache_key
    assert resolve({"prompt_cache_key": True}, "gpt-4o") == "novamind:gpt-4o"
    assert resolve({"prompt_cache_key": True}, "gpt-4o") == resolve(
        {"prompt_cache_key": True}, "gpt-4o"
    )


def test_resolve_string_passthrough() -> None:
    """非空字符串 → 字面量键（strip）。"""
    resolve = ModelConfigService._resolve_prompt_cache_key
    assert resolve({"prompt_cache_key": " sess-abc "}, "m") == "sess-abc"


def test_client_injects_key_into_extra_body() -> None:
    """客户端配置 key → extra_body 注入；未配置 → 原样。"""
    c1 = OpenAICompatibleLLM(
        api_key="k", base_url="http://x", model_name="m", prompt_cache_key="novamind:m",
    )
    eb = {"enable_thinking": False}
    c1._apply_prompt_cache_key(eb)
    assert eb["prompt_cache_key"] == "novamind:m"

    c2 = OpenAICompatibleLLM(api_key="k", base_url="http://x", model_name="m")
    eb2 = {"enable_thinking": False}
    c2._apply_prompt_cache_key(eb2)
    assert eb2 == {"enable_thinking": False}


def test_other_protocol_clients_accept_kwargs() -> None:
    """非 OpenAI 协议客户端构造收 prompt_cache_key 不崩（**kwargs 静默忽略，
    与 timeout/max_retries 等公共 kwargs 同策略）。"""
    from novamind.shared.ai_models.llm.ollama_llm import OllamaLLM

    client = OllamaLLM(
        api_key="k", base_url="http://localhost:11434", model_name="m",
        prompt_cache_key="novamind:m",
    )
    assert client is not None
