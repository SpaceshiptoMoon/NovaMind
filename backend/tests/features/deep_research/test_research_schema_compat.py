"""ResearchRequest schema 兼容测试（可插拽数据源扩展段）。

守护归并规则与旧契约：

  - 旧形状请求（仅 search_source + 平铺字段，无 sources）解析结果与历史一致
  - ``sources.internal``/``sources.external`` 非空时覆盖同名平铺字段
  - ``sources.enabled``/``sources.extra`` 透传
  - 已删除的死字段 time_range/region 不再被接受
  - service ``_extract_research_params`` 归并行为（含无 sources 默认路径）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.deep_research.schemas.research_schema import (
    ExternalSearchConfig,
    InternalSearchConfig,
    ResearchRequest,
    SourcesConfig,
)
from novamind.features.deep_research.services.deep_research_service import (
    _extract_research_params,
)

pytestmark = pytest.mark.unit


def test_legacy_request_shape_parses_unchanged():
    """旧形状请求（无 sources）解析结果与历史契约逐字段一致。"""
    req = ResearchRequest(
        query="什么是 RAG 技术？有哪些最佳实践？",
        research_mode="standard",
        search_source="hybrid",
        internal_search={"kb_ids": [1, 2], "top_k": 10},
        external_search={"provider": "duckduckgo", "max_results": 10},
    )
    assert req.search_source.value == "hybrid"
    assert req.internal_search.kb_ids == [1, 2]
    assert req.internal_search.top_k == 10
    assert req.external_search.provider.value == "duckduckgo"
    assert req.external_search.max_results == 10
    assert req.sources is None


def test_default_request_unchanged():
    """全默认请求（仅 query）与历史默认一致。"""
    req = ResearchRequest(query="最小请求示例查询内容")
    assert req.search_source.value == "hybrid"
    assert req.internal_search.search_mode == "content_hybrid"
    assert req.internal_search.top_k == 10
    assert req.external_search.provider.value == "duckduckgo"
    assert req.sources is None


def test_sources_internal_overrides_flat():
    """sources.internal 非空覆盖平铺 internal_search。"""
    req = ResearchRequest(
        query="覆盖测试查询内容示例",
        internal_search={"top_k": 10},
        sources={"internal": {"top_k": 33, "kb_ids": [7]}},
    )
    assert req.internal_search.top_k == 10  # 平铺不变
    assert req.sources.internal.top_k == 33
    # 归并发生在 _extract_research_params
    params = _extract_research_params(req)
    assert params.internal_config.top_k == 33
    assert params.internal_config.kb_ids == [7]


def test_sources_external_overrides_flat():
    """sources.external 非空覆盖平铺 external_search。"""
    req = ResearchRequest(
        query="覆盖测试查询内容示例",
        sources={"external": {"provider": "tavily", "max_results": 22}},
    )
    params = _extract_research_params(req)
    assert params.external_config.provider.value == "tavily"
    assert params.external_config.max_results == 22


def test_sources_enabled_and_extra_passthrough():
    """sources.enabled/extra 透传至 ResearchParams。"""
    req = ResearchRequest(
        query="扩展源测试查询内容示例",
        sources={
            "enabled": ["internal", "confluence"],
            "extra": {"confluence": {"space": "ENG", "top_k": 5}},
        },
    )
    params = _extract_research_params(req)
    assert params.enabled_sources == ["internal", "confluence"]
    assert params.extra_source_configs == {"confluence": {"space": "ENG", "top_k": 5}}


def test_no_sources_defaults_none():
    """无 sources 时 enabled/extra 为 None（等价平铺路径）。"""
    req = ResearchRequest(query="默认路径验证查询内容")
    params = _extract_research_params(req)
    assert params.enabled_sources is None
    assert params.extra_source_configs is None
    assert params.internal_config.top_k == req.internal_search.top_k


def test_dead_fields_time_range_region_removed():
    """死字段 time_range/region 已从 schema 删除（字段不存在）。"""
    assert "time_range" not in ExternalSearchConfig.model_fields
    assert "region" not in ExternalSearchConfig.model_fields


def test_search_depth_accepted():
    """search_depth 保留且接通（请求级可覆盖 YAML）。"""
    cfg = ExternalSearchConfig(provider="tavily", search_depth="advanced")
    assert cfg.search_depth == "advanced"


def test_sources_config_defaults():
    """SourcesConfig 全默认：enabled=None、internal/external=None、extra={}。"""
    s = SourcesConfig()
    assert s.enabled is None
    assert s.internal is None
    assert s.external is None
    assert s.extra == {}
