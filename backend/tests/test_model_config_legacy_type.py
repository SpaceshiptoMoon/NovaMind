"""回归测试：user_model_configs 残留已废弃 model_type 编号不应让接口 500。

背景：``ModelType`` 枚举移除了编号 5（原 MULTIMODAL_EMBEDDING），但 DB 里可能仍有
``model_type=5`` 的旧行。修复前 ``_build_response`` 等处直接 ``ModelType(config.model_type)``
对 5 抛 ``ValueError: 5 is not a valid ModelType``，导致 ``GET /user/model-configs`` 整体 500。

本测试复现该失败模式，验证安全降级 helper 与 ``_build_response`` 对废弃编号不再崩溃。
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


def test_model_type_int_to_str_deprecated_value_safe():
    """编号 5（已废弃）应返回 default，不抛 ValueError。"""
    from novamind.features.user.repository.model_config_repository import (
        model_type_int_to_str,
    )

    assert model_type_int_to_str(5, "unknown") == "unknown"
    assert model_type_int_to_str(5) == "unknown"  # 默认 default
    # 已知编号仍正常解析
    assert model_type_int_to_str(1) == "llm"
    assert model_type_int_to_str(2) == "embedding"
    assert model_type_int_to_str(6) == "asr"


def test_model_type_int_to_enum_deprecated_value_none():
    """编号 5 应返回 None，使后续 == ModelType.X 比较自然不命中。"""
    from novamind.features.user.repository.model_config_repository import (
        model_type_int_to_enum,
    )
    from novamind.features.user.models.user_model_config import ModelType

    assert model_type_int_to_enum(5) is None
    assert model_type_int_to_enum(2) == ModelType.EMBEDDING


def _make_config(model_type: int):
    """构造一个不依赖 DB 的 UserModelConfig 实例。"""
    from novamind.features.user.models.user_model_config import UserModelConfig

    cfg = UserModelConfig(
        id=1,
        user_id=10,
        model_type=model_type,
        protocol="openai",
        model="some-model",
        base_url=None,
        api_key="enc-key",
        extra_config=None,
    )
    # created_at/updated_at 由 BaseModel 默认提供，但响应 schema 要求非空，显式赋值稳妥
    cfg.created_at = datetime(2026, 1, 1)
    cfg.updated_at = datetime(2026, 1, 1)
    return cfg


def test_build_response_deprecated_type_does_not_crash():
    """_build_response 对 model_type=5 的脏行应返回 model_type='unknown'，不抛异常。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    # _build_response 不访问 db / port，传 None 即可
    svc = ModelConfigService(db=None, knowledge_space_info_port=None)
    resp = svc._build_response(_make_config(5))

    assert resp.model_type == "unknown"
    assert resp.id == 1
    assert resp.api_key == "****"  # 脱敏，不泄露原值


def test_build_response_known_type_still_resolves():
    """正常编号不受影响，避免回归。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    svc = ModelConfigService(db=None, knowledge_space_info_port=None)
    assert svc._build_response(_make_config(2)).model_type == "embedding"
    assert svc._build_response(_make_config(6)).model_type == "asr"


class _FakeRepo:
    """最小仓储桩：list_by_user / count_by_user 返回含脏行的列表。"""

    def __init__(self, configs):
        self._configs = configs

    async def list_by_user(self, user_id, model_type=None):
        return self._configs

    async def count_by_user(self, user_id, model_type=None):
        return len(self._configs)


@pytest.mark.asyncio
async def test_list_configs_with_deprecated_type_does_not_500():
    """list_configs 在结果集中含 model_type=5 脏行时应正常返回，不抛 ValueError。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    svc = ModelConfigService(db=None, knowledge_space_info_port=None)
    svc.repo = _FakeRepo([_make_config(5), _make_config(2)])

    result = await svc.list_configs(user_id=10, model_type=None)

    assert result.total == 2
    types = {item.model_type for item in result.items}
    assert types == {"unknown", "embedding"}