"""单元测试：engines 层 build_web_search_port_from_provider 契约。

验证：
- duckduckgo 无 key 可构造（免费兜底）
- tavily / serpapi 无 key 抛 WebSearchProviderNotConfiguredError
- 未知 provider 抛 WebSearchProviderNotConfiguredError
- 构造出的端口满足 WebSearchPort Protocol，search 归一化结果
- 不读 YAML / 不 import features/setting（由 test_unidirectional_dependency_gate 守护）
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


def test_duckduckgo_no_key_constructs():
    """duckduckgo 无 api_key 应构造成功（免费、无需 key）。"""
    from novamind.engines.search_ports import (
        WebSearchPort,
        build_web_search_port_from_provider,
    )

    port = build_web_search_port_from_provider("duckduckgo", None, {"max_results": 3})
    assert isinstance(port, WebSearchPort)


def test_tavily_no_key_raises_not_configured():
    """tavily 无 api_key 应抛 WebSearchProviderNotConfiguredError。"""
    from novamind.engines.search_ports import build_web_search_port_from_provider
    from novamind.engines.search_errors import WebSearchProviderNotConfiguredError

    with pytest.raises(WebSearchProviderNotConfiguredError) as exc:
        build_web_search_port_from_provider("tavily", None, None)
    assert exc.value.provider == "tavily"


def test_serpapi_no_key_raises_not_configured():
    """serpapi 无 api_key 应抛 WebSearchProviderNotConfiguredError。"""
    from novamind.engines.search_ports import build_web_search_port_from_provider
    from novamind.engines.search_errors import WebSearchProviderNotConfiguredError

    with pytest.raises(WebSearchProviderNotConfiguredError):
        build_web_search_port_from_provider("serpapi", None, None)


def test_unknown_provider_raises_not_configured():
    """未知 provider 应抛 WebSearchProviderNotConfiguredError。"""
    from novamind.engines.search_ports import build_web_search_port_from_provider
    from novamind.engines.search_errors import WebSearchProviderNotConfiguredError

    with pytest.raises(WebSearchProviderNotConfiguredError):
        build_web_search_port_from_provider("bogus", "k", None)


def test_tavily_with_key_constructs():
    """tavily 带 api_key 应构造成功（service.is_available() 为 True）。"""
    from novamind.engines.search_ports import (
        WebSearchPort,
        build_web_search_port_from_provider,
    )

    port = build_web_search_port_from_provider("tavily", "tvly-real-key", None)
    assert isinstance(port, WebSearchPort)


@pytest.mark.asyncio
async def test_provider_port_search_normalizes_results():
    """ProviderWebSearchPort.search 应把 ExternalSearchResult 归一化为 WebSearchResult。

    用 duckduckgo（实搜可能因沙箱网络失败返回 []），故直接用 ProviderWebSearchPort
    包一个桩 service 验证归一化逻辑。
    """
    from novamind.engines.search_ports import ProviderWebSearchPort, WebSearchResult

    class _StubService:
        async def search(self, query, max_results=5, **kwargs):
            # 模拟 ExternalSearchResult（dataclass）字段
            class _R:
                title = "T"
                url = "https://example.com"
                content = "snippet text"
                score = 0.8

            return [_R()]

        async def close(self):
            pass

    port = ProviderWebSearchPort(service=_StubService())
    results = await port.search("q", max_results=2)
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, WebSearchResult)
    assert r.title == "T"
    assert r.url == "https://example.com"
    assert r.snippet == "snippet text"
    assert r.content == "snippet text"
    assert r.score == 0.8


@pytest.mark.asyncio
async def test_provider_port_no_service_raises():
    """ProviderWebSearchPort 无 service 时 search 应抛 WebSearchError。"""
    from novamind.engines.search_ports import ProviderWebSearchPort
    from novamind.engines.search_errors import WebSearchError

    port = ProviderWebSearchPort(service=None)
    with pytest.raises(WebSearchError):
        await port.search("q")