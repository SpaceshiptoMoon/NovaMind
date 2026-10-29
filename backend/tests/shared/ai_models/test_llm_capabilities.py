"""LLM 能力解析测试：类默认 ← quirks 用户声明覆盖 ← 兜底全 False。"""

from novamind.shared.ai_models.base_model import LLMCapabilities, resolve_capabilities
from novamind.shared.ai_models.llm.quirks import LLMQuirks, resolve_quirks


class _FullCapLLM:
    """模拟 OpenAI 兼容类：全能力协议默认。"""

    capabilities = LLMCapabilities(tools=True, thinking=True)
    quirks = LLMQuirks()


class _NoCapLLM:
    """模拟 Transformers 类：全 False 协议默认。"""

    capabilities = LLMCapabilities(tools=False, thinking=False)
    quirks = LLMQuirks()


class _PlainStub:
    """无 capabilities/quirks 属性的裸桩（duck-typing 兜底路径）。"""


def test_class_defaults_pass_through():
    """未声明时（quirks 两键 None）原样返回类默认能力。"""
    assert resolve_capabilities(_FullCapLLM()) == LLMCapabilities(tools=True, thinking=True)
    assert resolve_capabilities(_NoCapLLM()) == LLMCapabilities(tools=False, thinking=False)


def test_quirks_override_disable():
    """用户声明 supports_tools=False 覆盖类默认 True——声明 False 是实测语义，优先。"""

    class _LLM(_FullCapLLM):
        quirks = LLMQuirks(supports_tools=False)

    assert resolve_capabilities(_LLM()) == LLMCapabilities(tools=False, thinking=True)


def test_quirks_override_enable():
    """用户声明 supports_thinking=True 覆盖类默认 False（如某 Ollama 模型实测可思考）。"""

    class _LLM(_NoCapLLM):
        quirks = LLMQuirks(supports_thinking=True)

    assert resolve_capabilities(_LLM()) == LLMCapabilities(tools=False, thinking=True)


def test_both_overrides():
    """两键同时声明均生效。"""

    class _LLM(_FullCapLLM):
        quirks = LLMQuirks(supports_tools=False, supports_thinking=False)

    assert resolve_capabilities(_LLM()) == LLMCapabilities(tools=False, thinking=False)


def test_plain_stub_falls_back_to_all_false():
    """裸桩缺属性落全 False 兜底（保守声明，调用侧按不支持协商）。"""
    assert resolve_capabilities(_PlainStub()) == LLMCapabilities(tools=False, thinking=False)


def test_resolve_quirks_extra_config_override_keys():
    """extra_config 白名单已扩展两能力键：supports_tools/supports_thinking 可经覆盖生效。"""
    quirks = resolve_quirks("https://x", "m", {"supports_tools": False, "supports_thinking": True})
    assert quirks.supports_tools is False
    assert quirks.supports_thinking is True
