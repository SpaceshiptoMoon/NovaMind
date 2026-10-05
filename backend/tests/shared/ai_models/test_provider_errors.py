"""统一异常族测试：状态码提取、中文翻译、非模型异常透传。"""
import httpx

from novamind.shared.ai_models.errors import (
    ModelProviderError,
    ModelRateLimitError,
    translate_provider_error,
)


# ========== 状态码提取 ==========


def test_extract_from_exception_attribute():
    """OpenAI SDK 风格：异常自带 status_code 属性。"""
    exc = type("SDKError", (Exception,), {})("boom")
    exc.status_code = 403
    translated = translate_provider_error(exc, model="glm-4.5")
    assert translated.status_code == 403
    assert translated.model == "glm-4.5"


def test_extract_from_httpx_response():
    """httpx 风格：状态码在 exc.response.status_code。"""
    request = httpx.Request("POST", "https://api.example.com/v1/chat")
    response = httpx.Response(429, request=request)
    exc = httpx.HTTPStatusError("rate limited", request=request, response=response)
    translated = translate_provider_error(exc)
    assert isinstance(translated, ModelRateLimitError)
    assert translated.status_code == 429


def test_extract_from_error_text_regex():
    """错误文本 "Error code: NNN" 正则兜底（openai SDK 字符串形态）。"""
    exc = Exception("Error code: 403 - {'error': {'message': 'Access denied.'}}")
    translated = translate_provider_error(exc)
    assert translated.status_code == 403


# ========== 中文翻译 ==========


def test_403_message_is_actionable_chinese():
    """403 消息覆盖百炼三类根因（未开通/额度耗尽/已下线），非原始 dict。"""
    exc = Exception("Error code: 403 - {'error': {'message': 'Access denied', 'code': 'access_denied'}}")
    translated = translate_provider_error(exc)
    assert "无权访问" in translated.message
    assert "开通" in translated.message
    assert "Access denied" in translated.message  # 厂商原文保留供定位


def test_400_and_5xx_map_to_human_messages():
    e400 = translate_provider_error(Exception("Error code: 400 - bad param"))
    e500 = translate_provider_error(Exception("Error code: 500 - internal"))
    assert "参数" in e400.message
    assert "暂不可用" in e500.message


def test_timeout_translated_as_network_error():
    """无状态码的连接/超时异常 → 网络错误提示。"""
    translated = translate_provider_error(TimeoutError("connection timed out"))
    assert "无法连接" in translated.message
    assert translated.status_code is None


# ========== 透传语义 ==========


def test_non_http_non_network_exception_passes_through():
    """无状态码且非网络异常原样返回（不包装、不吞类型）。"""
    class AppLogicError(Exception):
        pass

    exc = AppLogicError("prompt too long")
    assert translate_provider_error(exc) is exc


def test_existing_provider_error_passes_through():
    """已是统一异常族的实例直接透传（补 model 属性）。"""
    original = ModelProviderError("已有异常", status_code=500)
    result = translate_provider_error(original, model="qwen-max")
    assert result is original
    assert result.model == "qwen-max"
