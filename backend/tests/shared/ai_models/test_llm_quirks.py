"""LLMQuirks 声明层测试：注册表匹配、覆盖优先级、未知模型全默认兜底。"""
from novamind.shared.ai_models.llm.quirks import (
    LLMQuirks,
    is_stream_only_error,
    resolve_quirks,
)


# ========== 注册表匹配 ==========


def test_dashscope_glm45_resolves_stream_only():
    """DashScope + glm-4.5 命中 stream_only（2026-10-05 实测 stream-only 400）。"""
    quirks = resolve_quirks("https://dashscope.aliyuncs.com/compatible-mode/v1", "glm-4.5")
    assert quirks.stream_only is True
    assert quirks.force_thinking is False


def test_dashscope_qwen3_resolves_force_thinking():
    """DashScope + qwen3* 命中 force_thinking（服务商强制 enable_thinking=True）。"""
    quirks = resolve_quirks("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3-max")
    assert quirks.force_thinking is True
    assert quirks.stream_only is False


def test_non_dashscope_same_model_no_quirks():
    """同模型名非 DashScope 端点不命中（怪癖绑定端点，不绑定模型名）。"""
    quirks = resolve_quirks("https://api.openai.com/v1", "glm-4.5")
    assert quirks == LLMQuirks()


def test_dashscope_unrelated_model_no_quirks():
    """DashScope + 无怪癖模型（qwen-max）落全默认。"""
    quirks = resolve_quirks("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-max")
    assert quirks == LLMQuirks()


def test_unknown_provider_and_model_falls_back_to_default():
    """未知端点+未知模型落全默认，resolve 永不抛错（baseProvider 兜底语义）。"""
    quirks = resolve_quirks("", "")
    assert quirks == LLMQuirks()
    assert quirks.thinking_budget_ratio == 0.5


def test_match_is_case_insensitive():
    """端点与模型名匹配大小写不敏感。"""
    quirks = resolve_quirks("https://DASHSCOPE.ALIYUNCS.COM/compatible-mode/v1", "GLM-4.5")
    assert quirks.stream_only is True


# ========== overrides 覆盖 ==========


def test_user_override_enables_stream_only_for_any_model():
    """用户经 extra_config 声明 stream_only 对任意模型生效（长尾兜底）。"""
    quirks = resolve_quirks(
        "https://my-gateway.example.com/v1", "custom-model", {"stream_only": True}
    )
    assert quirks.stream_only is True


def test_user_override_takes_precedence_over_registry():
    """用户声明优先级最高：可关闭注册表命中的 stream_only。"""
    quirks = resolve_quirks(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "glm-4.5",
        {"stream_only": False},
    )
    assert quirks.stream_only is False


def test_invalid_override_values_silently_ignored():
    """非布尔声明值静默忽略（视为未声明），不抛错。"""
    quirks = resolve_quirks(
        "https://my-gateway.example.com/v1",
        "custom-model",
        {"stream_only": "yes", "force_thinking": 1, "unknown_key": True},
    )
    assert quirks == LLMQuirks()


# ========== is_stream_only_error 判据 ==========


def testis_stream_only_error_matches_dashscope_wording():
    assert is_stream_only_error(
        "Error code: 400 - This model only support stream mode, "
        "please enable the stream parameter to access the model."
    )


def testis_stream_only_error_rejects_auth_and_timeout():
    assert not is_stream_only_error("Error code: 403 - Access denied")
    assert not is_stream_only_error("Request timed out")


# ========== auth_type 鉴权头语义 ==========


def test_zhipu_anthropic_endpoint_resolves_bearer():
    """智谱 Anthropic 兼容端点命中 bearer（coding-plan token 语义）。"""
    quirks = resolve_quirks("https://open.bigmodel.cn/api/anthropic", "glm-5.3-flash")
    assert quirks.auth_type == "bearer"


def test_official_anthropic_stays_api_key():
    """官方 Anthropic 端点不命中，保持 x-api-key 语义。"""
    quirks = resolve_quirks("https://api.anthropic.com", "claude-sonnet-4-5")
    assert quirks.auth_type == "api_key"


def test_user_override_auth_type_for_any_endpoint():
    """用户经 extra_config 声明 auth_type 对任意端点生效。"""
    quirks = resolve_quirks(
        "https://my-gateway.example.com", "any-model", {"auth_type": "bearer"}
    )
    assert quirks.auth_type == "bearer"


def test_invalid_auth_type_override_silently_ignored():
    """非法 auth_type 值静默忽略，不抛错不落怪癖。"""
    quirks = resolve_quirks(
        "https://my-gateway.example.com", "any-model", {"auth_type": "digest"}
    )
    assert quirks == LLMQuirks()
