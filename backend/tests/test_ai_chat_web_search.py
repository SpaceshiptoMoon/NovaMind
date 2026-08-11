"""单元测试：AIChatService._retrieve_web 接 SearchConfigPort 后的行为。

覆盖：
- 用户级配置命中 → 用对应 provider 的 port 搜
- 用户级未命中 / 无 port → 回退 YAML 兜底
- port.search 失败 → 降级返回 None，不抛
- web source 含 score 字段
- 用户级构造端口失败（WebSearchError / 其他异常）→ 回退 YAML

不真实实例化 AIChatService 全链路（牵涉太多端口/DB），仅构造最小桩覆盖 _retrieve_web 路径。
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


class _FakePort:
    """WebSearchPort 桩：search 返回固定 WebSearchResult，close 无操作。"""

    def __init__(self, results=None, raise_exc=None):
        self._results = results or []
        self._raise = raise_exc
        self.closed = False
        self.search_called_with = None

    async def search(self, query, max_results=5):
        self.search_called_with = (query, max_results)
        if self._raise:
            raise self._raise
        return self._results

    async def close(self):
        self.closed = True


class _FakeSearchConfigPort:
    """SearchConfigPort 桩：返回预设 SearchCredentials 或 None。"""

    def __init__(self, creds=None, raise_exc=None):
        self._creds = creds
        self._raise = raise_exc
        self.call_count = 0

    async def get_primary_search_config(self, user_id):
        self.call_count += 1
        if self._raise:
            raise self._raise
        return self._creds


def _make_chat_service(search_config_port=None):
    """构造仅装好 _retrieve_web 依赖的 AIChatService 实例（跳过完整 __init__）。"""
    from novamind.features.qa.services.ai_chat_service import AIChatService

    svc = AIChatService.__new__(AIChatService)
    # 仅设 _retrieve_web 需要的属性；logger 用结构化日志
    from novamind.core.middleware.structured_logging import get_logger

    svc.logger = get_logger("test.ai_chat_web_search")
    svc._search_config_port = search_config_port
    return svc


# ========== 用户级配置命中 ==========

@pytest.mark.asyncio
async def test_retrieve_web_user_config_hit(monkeypatch):
    """用户级配置命中 → 用对应 provider port 搜，结果含 score。"""
    from novamind.engines.search_ports import WebSearchResult
    from novamind.shared.search_config_ports import SearchCredentials
    import novamind.features.qa.services.ai_chat_service as chat_mod

    creds = SearchCredentials(provider="tavily", api_key="tvly-x", extra_config=None)
    scp = _FakeSearchConfigPort(creds=creds)
    svc = _make_chat_service(search_config_port=scp)

    fake_port = _FakePort(
        results=[WebSearchResult(title="T", url="https://e.com", snippet="s", score=0.9)]
    )
    monkeypatch.setattr(
        chat_mod, "build_web_search_port_from_provider",
        lambda provider, api_key, extra_config: fake_port,
    )

    res = await svc._retrieve_web(query="q", user_id=10, max_results=3)
    assert res is not None
    text, sources = res
    assert "<web-search-results>" in text
    assert len(sources) == 1
    assert sources[0]["kind"] == "web"
    assert sources[0]["score"] == 0.9
    assert sources[0]["document_name"] == "T"
    assert fake_port.closed is True
    assert scp.call_count == 1


@pytest.mark.asyncio
async def test_retrieve_web_user_config_hit_uses_provider_and_key(monkeypatch):
    """构造端口时应透传用户级 provider / api_key / extra_config。"""
    from novamind.shared.search_config_ports import SearchCredentials
    import novamind.features.qa.services.ai_chat_service as chat_mod

    creds = SearchCredentials(provider="serpapi", api_key="serp-key", extra_config={"num": 7})
    scp = _FakeSearchConfigPort(creds=creds)
    svc = _make_chat_service(search_config_port=scp)

    captured = {}

    def _build(provider, api_key, extra_config):
        captured["provider"] = provider
        captured["api_key"] = api_key
        captured["extra_config"] = extra_config
        return _FakePort(results=[])

    monkeypatch.setattr(chat_mod, "build_web_search_port_from_provider", _build)

    await svc._retrieve_web(query="q", user_id=10, max_results=3)
    assert captured["provider"] == "serpapi"
    assert captured["api_key"] == "serp-key"
    assert captured["extra_config"] == {"num": 7}


# ========== 用户级未命中 / 无 port → YAML 兜底 ==========

@pytest.mark.asyncio
async def test_retrieve_web_no_user_config_falls_back_yaml(monkeypatch):
    """用户级返回 None → 回退 YAML 兜底构造端口。"""
    from novamind.engines.search_ports import WebSearchResult
    import novamind.features.qa.services.ai_chat_service as chat_mod

    scp = _FakeSearchConfigPort(creds=None)  # 无用户级配置
    svc = _make_chat_service(search_config_port=scp)

    fake_port = _FakePort(results=[WebSearchResult(title="Y", url="https://y.com", snippet="")])
    monkeypatch.setattr(
        chat_mod, "build_web_search_port_from_provider",
        lambda provider, api_key, extra_config: fake_port,
    )

    res = await svc._retrieve_web(query="q", user_id=10)
    assert res is not None
    assert res[1][0]["document_name"] == "Y"


@pytest.mark.asyncio
async def test_retrieve_web_no_search_config_port_falls_back_yaml(monkeypatch):
    """SearchConfigPort 未注入（None）→ 直接走 YAML 兜底。"""
    from novamind.engines.search_ports import WebSearchResult
    import novamind.features.qa.services.ai_chat_service as chat_mod

    svc = _make_chat_service(search_config_port=None)

    fake_port = _FakePort(results=[WebSearchResult(title="F", url="https://f.com", snippet="")])
    monkeypatch.setattr(
        chat_mod, "build_web_search_port_from_provider",
        lambda provider, api_key, extra_config: fake_port,
    )

    res = await svc._retrieve_web(query="q", user_id=10)
    assert res is not None
    assert res[1][0]["document_name"] == "F"


# ========== port.search 失败 → 降级 ==========

@pytest.mark.asyncio
async def test_retrieve_web_search_failure_returns_none(monkeypatch):
    """port.search 抛异常 → 降级返回 None，不向上抛。"""
    from novamind.shared.search_config_ports import SearchCredentials
    import novamind.features.qa.services.ai_chat_service as chat_mod

    creds = SearchCredentials(provider="tavily", api_key="k", extra_config=None)
    scp = _FakeSearchConfigPort(creds=creds)
    svc = _make_chat_service(search_config_port=scp)

    fake_port = _FakePort(raise_exc=RuntimeError("network down"))
    monkeypatch.setattr(
        chat_mod, "build_web_search_port_from_provider",
        lambda provider, api_key, extra_config: fake_port,
    )

    res = await svc._retrieve_web(query="q", user_id=10)
    assert res is None
    # port 仍被关闭
    assert fake_port.closed is True


@pytest.mark.asyncio
async def test_retrieve_web_no_results_returns_none(monkeypatch):
    """port.search 返回空列表 → 返回 None。"""
    from novamind.shared.search_config_ports import SearchCredentials
    import novamind.features.qa.services.ai_chat_service as chat_mod

    creds = SearchCredentials(provider="tavily", api_key="k", extra_config=None)
    scp = _FakeSearchConfigPort(creds=creds)
    svc = _make_chat_service(search_config_port=scp)

    fake_port = _FakePort(results=[])
    monkeypatch.setattr(
        chat_mod, "build_web_search_port_from_provider",
        lambda provider, api_key, extra_config: fake_port,
    )

    res = await svc._retrieve_web(query="q", user_id=10)
    assert res is None


# ========== 用户级构造端口失败 → 回退 YAML ==========

@pytest.mark.asyncio
async def test_retrieve_web_user_build_fails_falls_back_yaml(monkeypatch):
    """用户级 build_web_search_port_from_provider 抛 WebSearchError → 回退 YAML 兜底。"""
    from novamind.engines.search_errors import WebSearchError
    from novamind.engines.search_ports import WebSearchResult
    from novamind.shared.search_config_ports import SearchCredentials
    import novamind.features.qa.services.ai_chat_service as chat_mod

    creds = SearchCredentials(provider="tavily", api_key="bad-key", extra_config=None)
    scp = _FakeSearchConfigPort(creds=creds)
    svc = _make_chat_service(search_config_port=scp)

    yaml_port = _FakePort(results=[WebSearchResult(title="YAML", url="https://y.com", snippet="")])
    call_count = {"n": 0}

    def _build(provider, api_key, extra_config):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # 第一次（用户级 tavily bad-key）抛错
            raise WebSearchError("invalid key")
        # 第二次（YAML 兜底）成功
        return yaml_port

    monkeypatch.setattr(chat_mod, "build_web_search_port_from_provider", _build)

    res = await svc._retrieve_web(query="q", user_id=10)
    assert res is not None
    assert res[1][0]["document_name"] == "YAML"
    assert call_count["n"] == 2  # 用户级失败 + YAML 兜底各一次


@pytest.mark.asyncio
async def test_retrieve_web_search_config_port_exception_falls_back_yaml(monkeypatch):
    """SearchConfigPort.get_primary_search_config 抛异常 → 回退 YAML 兜底。"""
    from novamind.engines.search_ports import WebSearchResult
    import novamind.features.qa.services.ai_chat_service as chat_mod

    scp = _FakeSearchConfigPort(raise_exc=RuntimeError("db down"))
    svc = _make_chat_service(search_config_port=scp)

    yaml_port = _FakePort(results=[WebSearchResult(title="Y", url="https://y.com", snippet="")])
    monkeypatch.setattr(
        chat_mod, "build_web_search_port_from_provider",
        lambda provider, api_key, extra_config: yaml_port,
    )

    res = await svc._retrieve_web(query="q", user_id=10)
    assert res is not None
    assert res[1][0]["document_name"] == "Y"


# ========== 均失败 → None ==========

@pytest.mark.asyncio
async def test_retrieve_web_all_fail_returns_none(monkeypatch):
    """用户级 + YAML 兜底都失败 → 返回 None。"""
    from novamind.engines.search_errors import WebSearchError
    from novamind.shared.search_config_ports import SearchCredentials
    import novamind.features.qa.services.ai_chat_service as chat_mod

    creds = SearchCredentials(provider="tavily", api_key="bad", extra_config=None)
    scp = _FakeSearchConfigPort(creds=creds)
    svc = _make_chat_service(search_config_port=scp)

    def _build(provider, api_key, extra_config):
        raise WebSearchError("no provider available")

    monkeypatch.setattr(chat_mod, "build_web_search_port_from_provider", _build)

    res = await svc._retrieve_web(query="q", user_id=10)
    assert res is None


# ========== web source score 默认 0 ==========

@pytest.mark.asyncio
async def test_retrieve_web_score_defaults_to_zero(monkeypatch):
    """WebSearchResult 无 score 时，source score 默认 0.0。"""
    from novamind.engines.search_ports import WebSearchResult
    import novamind.features.qa.services.ai_chat_service as chat_mod

    svc = _make_chat_service(search_config_port=None)

    # WebSearchResult score 默认 0.0
    fake_port = _FakePort(results=[WebSearchResult(title="T", url="https://e.com", snippet="s")])
    monkeypatch.setattr(
        chat_mod, "build_web_search_port_from_provider",
        lambda provider, api_key, extra_config: fake_port,
    )

    res = await svc._retrieve_web(query="q", user_id=10)
    assert res is not None
    assert res[1][0]["score"] == 0.0