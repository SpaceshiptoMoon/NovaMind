"""单元测试：用户搜索配置服务（SearchConfigService）。

覆盖：
- CRUD + 加密入库 / 解密读取（AES-256-GCM 真实往返）
- 多租户隔离（user_id 过滤）
- set_primary 唯一性（原子清旧 + 设新）
- provider 白名单（schema 校验）
- test_connection（mock engines builder，验证中立异常映射）

沿用 ``test_model_config_legacy_type.py`` 的 fake-repo 模式，不走真实 DB，
避免 SQLite create_all 全量建表陷阱（见 memory
``backend-test-sqlite-create-all-gotcha.md``）。
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


@pytest.fixture(scope="session", autouse=True)
def _configure_crypto():
    """注入测试用加密密钥（生产由 startup_manager 注入，测试环境需自行配置）。

    crypto 模块未配置密钥时 encrypt/decrypt 抛 ValueError，故 session 级注入一次。
    """
    from novamind.shared.utils.crypto import configure_encryption_key

    configure_encryption_key("test-encryption-key-for-search-config-tests")


# ========== fake repo ==========

class _FakeRepo:
    """内存仓储桩：模拟 SearchConfigRepository 行为，存 UserSearchConfig 列表。"""

    def __init__(self):
        self._rows: list = []
        self._next_id = 1
        self.clear_primary_calls: list = []
        self.set_primary_calls: list = []

    def _make(self, user_id, data):
        from novamind.features.user.models.user_search_config import UserSearchConfig

        cfg = UserSearchConfig(
            id=self._next_id,
            user_id=user_id,
            provider=data.provider,
            api_key=data.api_key,
            extra_config=data.extra_config,
            is_primary=data.is_primary,
        )
        cfg.created_at = datetime(2026, 1, 1)
        cfg.updated_at = datetime(2026, 1, 1)
        return cfg

    async def get_by_id(self, config_id):
        for r in self._rows:
            if r.id == config_id:
                return r
        return None

    async def get_by_user_and_provider(self, user_id, provider):
        for r in self._rows:
            if r.user_id == user_id and r.provider == provider.lower():
                return r
        return None

    async def get_primary(self, user_id):
        for r in self._rows:
            if r.user_id == user_id and r.is_primary:
                return r
        return None

    async def list_by_user(self, user_id):
        return [r for r in self._rows if r.user_id == user_id]

    async def count_by_user(self, user_id):
        return sum(1 for r in self._rows if r.user_id == user_id)

    async def create(self, user_id, data):
        cfg = self._make(user_id, data)
        self._rows.append(cfg)
        self._next_id += 1
        return cfg

    async def update(self, config, data):
        update_data = data.model_dump(exclude_unset=True)
        for f, v in update_data.items():
            setattr(config, f, v)
        return config

    async def delete(self, config_id):
        before = len(self._rows)
        self._rows = [r for r in self._rows if r.id != config_id]
        return len(self._rows) < before

    async def clear_primary(self, user_id):
        count = 0
        for r in self._rows:
            if r.user_id == user_id and r.is_primary:
                r.is_primary = False
                count += 1
        self.clear_primary_calls.append((user_id, count))
        return count

    async def set_primary(self, user_id, config_id):
        # 清旧
        for r in self._rows:
            if r.user_id == user_id and r.is_primary:
                r.is_primary = False
        # 设新
        for r in self._rows:
            if r.id == config_id and r.user_id == user_id:
                r.is_primary = True
                self.set_primary_calls.append((user_id, config_id))
                return r
        return None


def _make_service():
    """构造绑定 fake repo 的 SearchConfigService。"""
    from novamind.features.user.services.search_config_service import SearchConfigService

    svc = SearchConfigService(db=None)
    svc.repo = _FakeRepo()
    return svc


# ========== schema 白名单 ==========

def test_provider_whitelist_rejects_unknown():
    """未知 provider 应在 schema 层被拒。"""
    from pydantic import ValidationError

    from novamind.features.user.schemas.search_config_schema import SearchConfigCreate

    with pytest.raises(ValidationError):
        SearchConfigCreate(provider="bogus", api_key="k")


def test_provider_whitelist_normalizes_case():
    """provider 大小写应归一化为小写。"""
    from novamind.features.user.schemas.search_config_schema import SearchConfigCreate

    data = SearchConfigCreate(provider="TAVILY", api_key="k")
    assert data.provider == "tavily"


# ========== create + 加密 ==========

@pytest.mark.asyncio
async def test_create_config_encrypts_api_key():
    """创建后入库的 api_key 应为密文（不等于明文），响应脱敏为 ****。"""
    from novamind.features.user.schemas.search_config_schema import SearchConfigCreate

    svc = _make_service()
    data = SearchConfigCreate(provider="tavily", api_key="tvly-secret-123")
    resp = await svc.create_config(data, user_id=10)

    assert resp.api_key == "****"  # 脱敏
    # 入库的应是密文
    stored = svc.repo._rows[0]
    assert stored.api_key != "tvly-secret-123"
    assert stored.api_key  # 非空
    assert stored.provider == "tavily"


@pytest.mark.asyncio
async def test_create_config_dedup_same_provider():
    """同 user 同 provider 重复创建应抛 SearchConfigAlreadyExistsError。"""
    from novamind.features.user.schemas.search_config_schema import SearchConfigCreate
    from novamind.features.user.exceptions import SearchConfigAlreadyExistsError

    svc = _make_service()
    await svc.create_config(
        SearchConfigCreate(provider="tavily", api_key="k1"), user_id=10
    )
    with pytest.raises(SearchConfigAlreadyExistsError):
        await svc.create_config(
            SearchConfigCreate(provider="tavily", api_key="k2"), user_id=10
        )


@pytest.mark.asyncio
async def test_create_config_is_primary_clears_old_primary():
    """创建新 primary 时应先清除该用户其他 primary，保证唯一。"""
    from novamind.features.user.schemas.search_config_schema import SearchConfigCreate

    svc = _make_service()
    # 先建一个 primary（tavily）
    await svc.create_config(
        SearchConfigCreate(provider="tavily", api_key="k1", is_primary=True),
        user_id=10,
    )
    # 再建一个 primary（serpapi）—— 应清掉 tavily 的 primary
    await svc.create_config(
        SearchConfigCreate(provider="serpapi", api_key="k2", is_primary=True),
        user_id=10,
    )

    primaries = [r for r in svc.repo._rows if r.user_id == 10 and r.is_primary]
    assert len(primaries) == 1
    assert primaries[0].provider == "serpapi"
    # clear_primary 应被调用过
    assert len(svc.repo.clear_primary_calls) >= 1


@pytest.mark.asyncio
async def test_create_config_multi_tenant_same_provider_allowed():
    """不同用户可以配同一 provider（多租户隔离）。"""
    from novamind.features.user.schemas.search_config_schema import SearchConfigCreate

    svc = _make_service()
    await svc.create_config(SearchConfigCreate(provider="tavily", api_key="k1"), user_id=10)
    # user 11 配同样的 tavily 不应冲突
    resp = await svc.create_config(SearchConfigCreate(provider="tavily", api_key="k2"), user_id=11)
    assert resp.user_id == 11


# ========== get / 多租户隔离 ==========

@pytest.mark.asyncio
async def test_get_config_isolation_other_user_not_found():
    """用户 A 不能读取用户 B 的配置（应抛 NotFound）。"""
    from novamind.features.user.schemas.search_config_schema import SearchConfigCreate
    from novamind.features.user.exceptions import SearchConfigNotFoundError

    svc = _make_service()
    resp = await svc.create_config(
        SearchConfigCreate(provider="tavily", api_key="k1"), user_id=10
    )
    # user 11 读 user 10 的配置 → NotFound
    with pytest.raises(SearchConfigNotFoundError):
        await svc.get_config(user_id=11, config_id=resp.id)
    # user 10 自己能读
    own = await svc.get_config(user_id=10, config_id=resp.id)
    assert own.id == resp.id


# ========== update ==========

@pytest.mark.asyncio
async def test_update_config_api_key_none_keeps_original():
    """更新时 api_key 留空（None）应保留原密文，不擦除。"""
    from novamind.features.user.schemas.search_config_schema import (
        SearchConfigCreate,
        SearchConfigUpdate,
    )

    svc = _make_service()
    created = await svc.create_config(
        SearchConfigCreate(provider="tavily", api_key="tvly-original"), user_id=10
    )
    original_cipher = svc.repo._rows[0].api_key

    # 更新 extra_config，不传 api_key
    updated = await svc.update_config(
        user_id=10,
        config_id=created.id,
        data=SearchConfigUpdate(extra_config={"max_results": 5}),
    )
    assert updated.extra_config == {"max_results": 5}
    # 原密文保留
    assert svc.repo._rows[0].api_key == original_cipher


@pytest.mark.asyncio
async def test_update_config_api_key_value_replaces():
    """更新时传 api_key 应加密覆盖原密文。"""
    from novamind.features.user.schemas.search_config_schema import (
        SearchConfigCreate,
        SearchConfigUpdate,
    )

    svc = _make_service()
    created = await svc.create_config(
        SearchConfigCreate(provider="tavily", api_key="tvly-old"), user_id=10
    )
    original_cipher = svc.repo._rows[0].api_key

    await svc.update_config(
        user_id=10,
        config_id=created.id,
        data=SearchConfigUpdate(api_key="tvly-new"),
    )
    new_cipher = svc.repo._rows[0].api_key
    assert new_cipher != original_cipher
    assert new_cipher != "tvly-new"  # 仍是密文


@pytest.mark.asyncio
async def test_update_config_is_primary_clears_old():
    """更新时把非 primary 配置设为 primary，应清除旧 primary。"""
    from novamind.features.user.schemas.search_config_schema import (
        SearchConfigCreate,
        SearchConfigUpdate,
    )

    svc = _make_service()
    a = await svc.create_config(
        SearchConfigCreate(provider="tavily", api_key="k1", is_primary=True), user_id=10
    )
    b = await svc.create_config(
        SearchConfigCreate(provider="serpapi", api_key="k2"), user_id=10
    )
    await svc.update_config(
        user_id=10, config_id=b.id, data=SearchConfigUpdate(is_primary=True)
    )
    primaries = [r for r in svc.repo._rows if r.user_id == 10 and r.is_primary]
    assert len(primaries) == 1
    assert primaries[0].id == b.id


# ========== set_primary ==========

@pytest.mark.asyncio
async def test_set_primary_atomic_switch():
    """set_primary 应原子清旧 + 设新，最终仅一条 primary。"""
    from novamind.features.user.schemas.search_config_schema import SearchConfigCreate

    svc = _make_service()
    a = await svc.create_config(
        SearchConfigCreate(provider="tavily", api_key="k1", is_primary=True), user_id=10
    )
    b = await svc.create_config(
        SearchConfigCreate(provider="serpapi", api_key="k2"), user_id=10
    )
    resp = await svc.set_primary(user_id=10, config_id=b.id)
    assert resp.is_primary is True
    # a 不再是 primary
    a_row = await svc.repo.get_by_id(a.id)
    assert a_row.is_primary is False
    assert len(svc.repo.set_primary_calls) == 1


@pytest.mark.asyncio
async def test_set_primary_other_user_not_found():
    """set_primary 跨用户应抛 NotFound（不能设别人的配置为 primary）。"""
    from novamind.features.user.schemas.search_config_schema import SearchConfigCreate
    from novamind.features.user.exceptions import SearchConfigNotFoundError

    svc = _make_service()
    created = await svc.create_config(
        SearchConfigCreate(provider="tavily", api_key="k1"), user_id=10
    )
    with pytest.raises(SearchConfigNotFoundError):
        await svc.set_primary(user_id=99, config_id=created.id)


# ========== delete ==========

@pytest.mark.asyncio
async def test_delete_config_ownership():
    """删除跨用户配置应抛 NotFound。"""
    from novamind.features.user.schemas.search_config_schema import SearchConfigCreate
    from novamind.features.user.exceptions import SearchConfigNotFoundError

    svc = _make_service()
    created = await svc.create_config(
        SearchConfigCreate(provider="tavily", api_key="k1"), user_id=10
    )
    with pytest.raises(SearchConfigNotFoundError):
        await svc.delete_config(user_id=99, config_id=created.id)
    # 自己能删
    await svc.delete_config(user_id=10, config_id=created.id)
    assert await svc.repo.get_by_id(created.id) is None


# ========== get_primary_search_config（解密） ==========

@pytest.mark.asyncio
async def test_get_primary_search_config_decrypts():
    """get_primary_search_config 应返回解密后的明文 api_key。"""
    from novamind.features.user.schemas.search_config_schema import SearchConfigCreate

    svc = _make_service()
    await svc.create_config(
        SearchConfigCreate(provider="tavily", api_key="tvly-plaintext", is_primary=True),
        user_id=10,
    )
    creds = await svc.get_primary_search_config(user_id=10)
    assert creds is not None
    assert creds.provider == "tavily"
    assert creds.api_key == "tvly-plaintext"  # 解密回明文


@pytest.mark.asyncio
async def test_get_primary_search_config_none_when_no_primary():
    """无 primary 配置应返回 None（宿主降级 YAML）。"""
    svc = _make_service()
    creds = await svc.get_primary_search_config(user_id=10)
    assert creds is None


@pytest.mark.asyncio
async def test_get_primary_search_config_duckduckgo_null_key():
    """duckduckgo 配置 api_key 为空时，凭证 api_key 应为 None（不抛错）。"""
    from novamind.features.user.schemas.search_config_schema import SearchConfigCreate

    svc = _make_service()
    await svc.create_config(
        SearchConfigCreate(provider="duckduckgo", api_key=None, is_primary=True),
        user_id=10,
    )
    creds = await svc.get_primary_search_config(user_id=10)
    assert creds is not None
    assert creds.provider == "duckduckgo"
    assert creds.api_key is None


# ========== test_connection（mock engines builder） ==========

class _FakePort:
    """WebSearchPort 桩：search 返回固定结果，close 无操作。"""

    def __init__(self, results=None, raise_exc=None):
        self._results = results or []
        self._raise = raise_exc
        self.closed = False

    async def search(self, query, max_results=5):
        if self._raise:
            raise self._raise
        return self._results

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_test_connection_success(monkeypatch):
    """test_connection 成功应返回 success=True + 结果数。"""
    from novamind.engines.search_ports import WebSearchResult
    from novamind.features.user.schemas.search_config_schema import SearchTestRequest
    import novamind.features.user.services.search_config_service as svc_mod

    fake_port = _FakePort(results=[WebSearchResult(title="t", url="u", snippet="s")])
    monkeypatch.setattr(
        svc_mod, "build_web_search_port_from_provider",
        lambda provider, api_key, extra_config: fake_port,
    )

    svc = _make_service()
    resp = await svc.test_connection(
        user_id=10,
        request=SearchTestRequest(provider="tavily", api_key="tvly-x"),
    )
    assert resp.success is True
    assert resp.results_count == 1
    assert fake_port.closed is True


@pytest.mark.asyncio
async def test_test_connection_provider_not_configured(monkeypatch):
    """engines 抛 WebSearchProviderNotConfiguredError 应映射为 SearchConfigTestFailedError。"""
    from novamind.engines.search_errors import WebSearchProviderNotConfiguredError
    from novamind.features.user.schemas.search_config_schema import SearchTestRequest
    from novamind.features.user.exceptions import SearchConfigTestFailedError
    import novamind.features.user.services.search_config_service as svc_mod

    def _raise(provider, api_key, extra_config):
        raise WebSearchProviderNotConfiguredError(provider)

    monkeypatch.setattr(svc_mod, "build_web_search_port_from_provider", _raise)

    svc = _make_service()
    with pytest.raises(SearchConfigTestFailedError):
        await svc.test_connection(
            user_id=10,
            request=SearchTestRequest(provider="tavily", api_key=None),
        )


@pytest.mark.asyncio
async def test_test_connection_search_failure_mapped(monkeypatch):
    """port.search 抛中立 WebSearchError 应映射为 SearchConfigTestFailedError。"""
    from novamind.engines.search_errors import WebSearchError
    from novamind.features.user.schemas.search_config_schema import SearchTestRequest
    from novamind.features.user.exceptions import SearchConfigTestFailedError
    import novamind.features.user.services.search_config_service as svc_mod

    fake_port = _FakePort(raise_exc=WebSearchError("boom"))
    monkeypatch.setattr(
        svc_mod, "build_web_search_port_from_provider",
        lambda provider, api_key, extra_config: fake_port,
    )

    svc = _make_service()
    with pytest.raises(SearchConfigTestFailedError):
        await svc.test_connection(
            user_id=10,
            request=SearchTestRequest(provider="duckduckgo"),
        )