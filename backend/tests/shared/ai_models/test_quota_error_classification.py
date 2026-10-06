"""额度类错误分类测试：欠费/免费额度耗尽归 ModelQuotaError，普通参数错不误判。"""
import pytest

from novamind.shared.ai_models.errors import (
    ModelProviderError,
    ModelQuotaError,
    ModelRateLimitError,
    translate_provider_error,
)


class _FakeSDKError(Exception):
    """模拟 OpenAI SDK 异常形态：status_code 属性 + "Error code: NNN" 文本。"""

    def __init__(self, status_code: int, body: str):
        super().__init__(f"Error code: {status_code} - {body}")
        self.status_code = status_code


@pytest.mark.parametrize(
    "status_code, body",
    [
        # DashScope 欠费（实测样例，验证判据覆盖）
        (400, "{'error': {'message': 'Access denied... Arrearage', 'code': 'Arrearage'}}"),
        # DashScope 免费额度耗尽
        (403, "{'error': {'message': 'Free quota exhausted.', "
              "'code': 'AllocationQuota.FreeTierOnly'}}"),
        # 通用英文措辞
        (400, "insufficient balance"),
        (402, "out of credit, please top up"),
        # 中文措辞
        (400, "账户已欠费，请充值后重试"),
    ],
)
def test_quota_errors_classified(status_code: int, body: str):
    """额度类词面 + 4xx → ModelQuotaError，文案含行动指引不误导为参数错误。"""
    exc = translate_provider_error(_FakeSDKError(status_code, body), model="m1")
    assert isinstance(exc, ModelQuotaError)
    assert isinstance(exc, ModelProviderError)
    assert exc.status_code == status_code
    assert exc.model == "m1"
    assert "额度不可用" in exc.message
    assert "充值" in exc.message


@pytest.mark.parametrize(
    "status_code, body",
    [
        # 普通 400 参数错：词面不含额度语义
        (400, "{'error': {'message': 'Invalid parameter: temperature must be in [0, 2]'}}"),
        # 404 模型不存在：即使文本含 balance 也不算额度错（非 4xx 计费语境的反例）
        (404, "model not found, please check balance of model name"),
        # 5xx 服务端错误
        (500, "internal server error"),
    ],
)
def test_non_quota_errors_not_misclassified(status_code: int, body: str):
    """非额度类错误不得误判为 ModelQuotaError。"""
    exc = translate_provider_error(_FakeSDKError(status_code, body))
    assert not isinstance(exc, ModelQuotaError)
    assert type(exc) is ModelProviderError or isinstance(exc, ModelRateLimitError)


def test_quota_error_word_outside_4xx_ignored():
    """额度词面出现在非 4xx（如 500）不归类额度错误。"""
    exc = translate_provider_error(_FakeSDKError(500, "quota service unavailable"))
    assert not isinstance(exc, ModelQuotaError)


def test_existing_model_provider_error_passthrough():
    """已是 ModelProviderError 的异常原样透传，不被二次分类改写类型。"""
    original = ModelProviderError("原始错误", status_code=400, model="m1")
    exc = translate_provider_error(original)
    assert exc is original
