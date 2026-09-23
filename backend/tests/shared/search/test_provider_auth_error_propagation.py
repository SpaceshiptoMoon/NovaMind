# -*- coding: utf-8 -*-
"""搜索 provider 凭证错误传播测试。

背景（2026-09-23 接口全量测试发现）：三个 provider 的 search() 曾把
HTTPStatusError（含 401/403 凭证拒绝）吞成空列表，导致「搜索配置 → 测试连接」
对假 api_key 返回 success=true（results_count=0），配置验证形同虚设。

修复语义：
- 401/403 → 抛 WebSearchProviderAuthError（确定性配置错误，必须传播）
- 5xx/超时 → 仍降级返回 []（可用性问题，不中断搜索流，消费方单源降级逻辑不受影响）
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


def _service_with_response(provider_module: str, status_code: int):
    """构造指定 provider 的 service，其 HTTP client 返回给定状态码响应。"""
    from novamind.shared.search.duckduckgo_service import DuckDuckGoSearchService
    from novamind.shared.search.serpapi_service import SerpAPISearchService
    from novamind.shared.search.tavily_service import TavilySearchService
    from novamind.shared.config import (
        DuckDuckGoSearchConfig,
        SerpApiSearchConfig,
        TavilySearchConfig,
    )

    spec = {
        "tavily_service": (TavilySearchService, TavilySearchConfig),
        "serpapi_service": (SerpAPISearchService, SerpApiSearchConfig),
        "duckduckgo_service": (DuckDuckGoSearchService, DuckDuckGoSearchConfig),
    }[provider_module]
    cls, cfg_cls = spec
    cfg = cfg_cls()
    if hasattr(cfg, "api_key"):
        cfg.api_key = "test-key"
    svc = cls(cfg)

    response = MagicMock()
    response.status_code = status_code
    request = MagicMock()
    error = httpx.HTTPStatusError(
        f"HTTP {status_code}", request=request, response=response
    )
    client = MagicMock()
    client.is_closed = False
    client.post = AsyncMock(side_effect=error)
    client.get = AsyncMock(side_effect=error)
    svc._client = client
    return svc


@pytest.mark.parametrize("provider_module", ["tavily_service", "serpapi_service", "duckduckgo_service"])
@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_auth_rejected_raises_auth_error(provider_module, status):
    """401/403 必须抛 WebSearchProviderAuthError，不得吞成空列表。"""
    from novamind.engines.search.errors import WebSearchProviderAuthError

    svc = _service_with_response(provider_module, status)
    with pytest.raises(WebSearchProviderAuthError) as exc:
        await svc.search("test query")
    assert exc.value.status_code == status
    assert exc.value.provider in ("tavily", "serpapi", "duckduckgo")


@pytest.mark.parametrize("provider_module", ["tavily_service", "serpapi_service", "duckduckgo_service"])
@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 503])
async def test_server_error_still_degrades_to_empty(provider_module, status):
    """5xx 保持降级语义：返回空列表，不抛异常（消费方单源降级不受影响）。"""
    svc = _service_with_response(provider_module, status)
    results = await svc.search("test query")
    assert results == []


@pytest.mark.asyncio
async def test_test_connection_reports_invalid_key_as_failure():
    """搜索配置「测试连接」对无效凭证应报失败（不再 success=true）。"""
    from unittest.mock import patch

    from novamind.features.user.services.search_config_service import (
        SearchConfigService,
    )
    from novamind.features.user.schemas.search_config_schema import SearchTestRequest
    from novamind.engines.search.errors import WebSearchProviderAuthError
    from novamind.shared.search.web_search_factory import build_web_search_port_from_provider

    svc = SearchConfigService(db=None)
    fake_port = build_web_search_port_from_provider("duckduckgo", None, {})

    async def _raise_auth(query, max_results=5):
        raise WebSearchProviderAuthError("duckduckgo", 403)

    fake_port.search = _raise_auth
    with patch(
        "novamind.features.user.services.search_config_service.build_web_search_port_from_provider",
        return_value=fake_port,
    ):
        with pytest.raises(Exception) as exc:
            await svc.test_connection(1, SearchTestRequest(provider="duckduckgo", api_key=""))
    # SearchConfigTestFailedError 继承 SearchConfigError（http_status_code=400）
    assert "凭证无效" in str(exc.value) or "拒绝" in str(exc.value)
