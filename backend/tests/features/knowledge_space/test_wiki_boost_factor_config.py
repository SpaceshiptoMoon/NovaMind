"""回归：WikiGenerationConfig.boost_factor 声明进 schema，配置经 API 校验不再被静默丢弃。

背景（2026-10-03 文档审计发现）：search_service 以裸 dict ``kb_cfg["wiki"]["boost_factor"]``
读取 wiki 检索加权，但 WikiGenerationConfig 未声明该字段——pydantic extra=ignore
令任何经 KnowledgeBaseConfig 校验回写的配置都丢掉 boost_factor，唯一生效途径只剩直改 DB。
正用例：合法值经全量 KB config 校验 round-trip 后仍存在（修复前被丢弃）。
反用例：默认 None 不进 exclude_none 载荷（存量配置负载不变）；越界值（<0.1 / >10）被拒。
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    KnowledgeBaseConfig,
    WikiGenerationConfig,
)

pytestmark = pytest.mark.unit


def test_boost_factor_roundtrip_survives_config_validation():
    """正用例：boost_factor 经 KnowledgeBaseConfig 校验 round-trip 后保留。"""
    raw = {"wiki": {"enabled": True, "boost_factor": 1.8}}
    dumped = KnowledgeBaseConfig.model_validate(raw).model_dump(exclude_none=True)
    assert dumped["wiki"]["boost_factor"] == 1.8


def test_boost_factor_default_none_excluded_from_payload():
    """反用例：未设置时不出现在 exclude_none 载荷，存量配置负载不变。"""
    dumped = WikiGenerationConfig().model_dump(exclude_none=True)
    assert "boost_factor" not in dumped


@pytest.mark.parametrize("bad", [0.05, 10.5, -1.0])
def test_boost_factor_out_of_range_rejected(bad):
    """反用例：越界值（<0.1 / >10）在 schema 层被拒，不会流入裸 dict 消费端。"""
    with pytest.raises(ValueError):
        WikiGenerationConfig(enabled=True, boost_factor=bad)
