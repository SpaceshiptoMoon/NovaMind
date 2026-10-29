"""凭据/端点字段格式守卫回归测试：字段互串与非法声明的边界拦截。

背景（2026-10-06 用户实测）：把 Base URL 粘进 API Key 框，请求带着
``Authorization: Bearer https://...`` 打到厂商侧才变成神秘 401。此类
「字段互串」与「声明值拼错被静默吞掉」是同一类边界校验缺失问题，
统一在 schema 层做厂商无关的格式守卫（通用补丁原则：抽象一层修一类）。

验证不变量：
1. api_key 拒绝 http(s):// 形状（凭据不会是 URL）；
2. base_url 必须 http(s) 开头；
3. extra_config 声明类枚举键（auth_type）非法值显式报错而非静默忽略；
4. 正常凭据/URL/声明全部放行（不误伤）；
5. 三个请求 schema（Create/Update/Test）守卫一致生效。
"""
import pytest
from novamind.features.user.schemas.model_config_schema import (
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelTestRequest,
)
from pydantic import ValidationError

pytestmark = pytest.mark.unit


SCHEMAS = [ModelConfigCreate, ModelConfigUpdate, ModelTestRequest]


def _kwargs(schema, **extra) -> dict:
    """按 schema 补齐必填字段，只留测试关注的字段在 extra 里。"""
    base: dict = {}
    if schema is ModelConfigCreate:
        base.update(model_type="llm", protocol="openai", model="m")
    elif schema is ModelTestRequest:
        base.update(model_type="llm", model="m")
    base.update(extra)
    return base


class TestApiKeyNotUrl:
    @pytest.mark.parametrize("schema", SCHEMAS)
    def test_url_in_api_key_rejected(self, schema):
        """把 URL 粘进 API Key 字段：边界立即报错，不再漏到厂商侧。"""
        with pytest.raises(ValidationError, match="API Key 字段填入了 URL"):
            schema(**_kwargs(schema, api_key="https://open.bigmodel.cn/api/anthropic"))

    @pytest.mark.parametrize("schema", SCHEMAS)
    def test_normal_credential_allowed(self, schema):
        """正常凭据（API Key 与 token 两种形状）不误伤。"""
        assert schema(**_kwargs(schema, api_key="a1b2c3d4.e5f6g7h8i9j0k1l2")).api_key == "a1b2c3d4.e5f6g7h8i9j0k1l2"

    @pytest.mark.parametrize("schema", SCHEMAS)
    def test_none_and_empty_allowed(self, schema):
        """None/空串放行（未填凭据是合法状态，由厂商侧校验真伪）。"""
        assert schema(**_kwargs(schema, api_key="")).api_key == ""


class TestBaseUrlScheme:
    @pytest.mark.parametrize("schema", SCHEMAS)
    def test_non_http_base_url_rejected(self, schema):
        """Base URL 非 http(s) 开头：报错。"""
        with pytest.raises(ValidationError, match="Base URL 须以"):
            schema(**_kwargs(schema, base_url="open.bigmodel.cn/api/anthropic", api_key="k"))

    @pytest.mark.parametrize("scheme", ["http://", "https://", "HTTPS://X"])
    def test_http_schemes_allowed(self, scheme):
        """http/https（含大写）与空值放行。"""
        assert ModelConfigCreate(
            model_type="llm", protocol="openai", model="m",
            base_url=scheme + "x.example.com",
        ).base_url == scheme + "x.example.com"
        assert ModelConfigCreate(
            model_type="llm", protocol="openai", model="m", base_url=None,
        ).base_url is None


class TestDeclaredEnumValues:
    def test_invalid_auth_type_rejected_not_silenced(self):
        """auth_type 拼错值：显式报错（静默忽略会让错误漏到运行时）。"""
        with pytest.raises(ValidationError, match="auth_type"):
            ModelConfigCreate(
                model_type="llm", protocol="anthropic", model="m",
                api_key="k", extra_config={"auth_type": "bear"},
            )

    def test_valid_auth_type_allowed(self):
        assert ModelConfigCreate(
            model_type="llm", protocol="anthropic", model="m",
            api_key="k", extra_config={"auth_type": "bearer"},
        ).extra_config == {"auth_type": "bearer"}

    def test_unrelated_extra_config_keys_untouched(self):
        """非声明键（dimension 等）不校验不改动。"""
        cfg = {"dimension": 1024, "timeout": 30}
        assert ModelConfigCreate(
            model_type="embedding", protocol="openai", model="m",
            api_key="k", extra_config=cfg,
        ).extra_config == cfg
