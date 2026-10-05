"""回归测试：模型/搜索配置测试链路六项修复（2026-10 浏览器实测揪出）。

覆盖（正反两用例）：
1. update_config 空串 api_key 不覆盖原密文（P0 编辑洗 key），显式传值仍加密覆盖
2. ASRConnectionTester._test_local 按 model 字段解析目录（不再硬编码 tiny）
3. _test_llm 空 content 判失败（thinking 吃满预算不再假成功）
4. CompatibleRerankClient 对 compatible-mode URL 选 /reranks（不再拼 404 端点）
5. _check_delete_impact 用 self.db 查空间绑定，查询失败补 warning 项（不谎报无影响）
6. SearchConfigService.test_connection 空结果判失败且异常不被双包

沿用 fake-repo / 桩客户端模式，不走真实 DB 与网络。
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


@pytest.fixture(scope="session", autouse=True)
def _configure_crypto():
    """注入测试用加密密钥（update_config 加密路径需要）。"""
    from novamind.shared.utils.crypto import configure_encryption_key

    configure_encryption_key("test-encryption-key-for-model-config-tests")


# ========== 1. update_config 空串 api_key 不洗掉原密文 ==========


class _UpdateFakeRepo:
    """最小仓储桩：get_by_id / get_by_user_and_model / update。"""

    def __init__(self, config):
        self._config = config

    async def get_by_id(self, config_id):
        return self._config if self._config.id == config_id else None

    async def get_by_user_and_model(self, user_id, model_type, model):
        return None

    async def update(self, config, data):
        # 对齐真实仓储语义：exclude_unset 只落显式传入的字段
        for f, v in data.model_dump(exclude_unset=True).items():
            setattr(config, f, v)
        return config


def _make_llm_config():
    """构造 LLM 配置行（api_key 为已加密密文占位）。"""
    from novamind.features.user.models.user_model_config import UserModelConfig

    cfg = UserModelConfig(
        id=7,
        user_id=10,
        model_type=1,  # llm
        protocol="openai",
        model="glm-5.3",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="ENC-ORIGINAL-CIPHERTEXT",
    )
    cfg.created_at = datetime(2026, 1, 1)
    cfg.updated_at = datetime(2026, 1, 1)
    return cfg


def _make_update_service(config, monkeypatch):
    """构造 update_config 不触发连接重验的服务（_connection_fields_changed 恒 False）。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    svc = ModelConfigService(db=None)
    svc.repo = _UpdateFakeRepo(config)
    # 只测 api_key 留空行为，绕开连接重验（该路径由连接测试用例覆盖）
    monkeypatch.setattr(
        "novamind.features.user.services.model_config_service.ModelConfigService._connection_fields_changed",
        staticmethod(lambda data, config: False),
    )
    return svc


@pytest.mark.asyncio
async def test_update_config_empty_api_key_keeps_original(monkeypatch):
    """反例：编辑态回传空串 api_key 不得覆盖原密文（P0 洗 key 回归）。"""
    from novamind.features.user.schemas.model_config_schema import ModelConfigUpdate

    config = _make_llm_config()
    svc = _make_update_service(config, monkeypatch)

    await svc.update_config(
        user_id=10,
        config_id=7,
        data=ModelConfigUpdate(api_key=""),  # 前端编辑态原样回传的空串
    )

    assert config.api_key == "ENC-ORIGINAL-CIPHERTEXT"  # 原密文保留


@pytest.mark.asyncio
async def test_update_config_explicit_api_key_overwrites_encrypted(monkeypatch):
    """正例：显式传入新 api_key 应加密覆盖原密文。"""
    from novamind.features.user.schemas.model_config_schema import ModelConfigUpdate
    from novamind.shared.utils.crypto import decrypt_api_key_async

    config = _make_llm_config()
    svc = _make_update_service(config, monkeypatch)

    await svc.update_config(
        user_id=10,
        config_id=7,
        data=ModelConfigUpdate(api_key="sk-brand-new-key"),
    )

    assert config.api_key != "sk-brand-new-key"  # 落库是密文
    assert config.api_key != "ENC-ORIGINAL-CIPHERTEXT"  # 原密文已被覆盖
    assert await decrypt_api_key_async(config.api_key) == "sk-brand-new-key"


# ========== 2. ASR local 测试按 model 字段解析 ==========


def _tester():
    from novamind.shared.ai_models.connection_testers.asr import ASRConnectionTester

    return ASRConnectionTester()


@pytest.mark.asyncio
async def test_asr_local_unsupported_tier_raises(monkeypatch):
    """反例：faster-whisper-<不支持档位> 应报错，绝不忽略 model 字段假成功。"""
    with pytest.raises(ValueError, match="不支持的本地 ASR 模型档位"):
        await _tester()._test_local(model="faster-whisper-nonexistent-tier")


@pytest.mark.asyncio
async def test_asr_local_missing_dir_reports_model_specific_path(monkeypatch):
    """目录缺失时报错信息携带按 model 解析的档位目录（而非硬编码 tiny）。"""
    import novamind.shared.ai_models.connection_testers.asr as asr_mod

    def _raise_no_dir(slug):
        return Path("/nonexistent/cache/dir") / slug

    import novamind.engines.document.media.audio.audio_utils as audio_utils

    monkeypatch.setattr(audio_utils, "default_faster_whisper_cache_dir", _raise_no_dir)
    monkeypatch.setattr(
        asr_mod, "default_faster_whisper_cache_dir", _raise_no_dir, raising=False
    )

    with pytest.raises(ValueError, match="large-v3"):
        await _tester()._test_local(model="faster-whisper-large-v3")


@pytest.mark.asyncio
async def test_asr_local_bare_tier_resolves(monkeypatch):
    """正例边界：裸档位名（无 faster-whisper- 前缀）按宽容解析走同一目录约定。"""
    import novamind.engines.document.media.audio.audio_utils as audio_utils
    import novamind.shared.ai_models.connection_testers.asr as asr_mod

    captured = {}

    def _capture_dir(slug):
        captured["slug"] = slug
        return Path("/nonexistent/cache/dir") / slug

    monkeypatch.setattr(audio_utils, "default_faster_whisper_cache_dir", _capture_dir)
    monkeypatch.setattr(asr_mod, "default_faster_whisper_cache_dir", _capture_dir, raising=False)

    with pytest.raises(ValueError):
        await _tester()._test_local(model="small")

    assert captured["slug"] == "small"  # 裸档位直接作为 slug


# ========== 3. _test_llm 空 content 判失败 ==========


class _EmptyContentLLM:
    """桩客户端：非流式返回空串（thinking 吃满预算的假成功形态）。"""

    async def generate_text(self, **kwargs):
        return "   "


@pytest.mark.asyncio
async def test_test_llm_empty_content_raises(monkeypatch):
    """反例：连通但正文为空应判失败（thinking 耗尽输出预算）。"""
    from novamind.features.user.schemas.model_config_schema import ModelTestRequest
    from novamind.features.user.services.model_config_service import ModelConfigService

    monkeypatch.setattr(
        "novamind.features.user.services.model_config_service.create_llm_client",
        lambda **kwargs: _EmptyContentLLM(),
    )
    svc = ModelConfigService(db=None)
    request = ModelTestRequest(
        model_type="llm", protocol="openai", model="qwen3.8-27b", api_key="sk-x"
    )

    with pytest.raises(ValueError, match="空内容"):
        await svc._test_llm(request)


@pytest.mark.asyncio
async def test_test_llm_nonempty_content_passes(monkeypatch):
    """正例：正常返回内容不误伤。"""
    from novamind.features.user.schemas.model_config_schema import ModelTestRequest
    from novamind.features.user.services.model_config_service import ModelConfigService

    class _OkLLM:
        async def generate_text(self, **kwargs):
            return "Hi"

    monkeypatch.setattr(
        "novamind.features.user.services.model_config_service.create_llm_client",
        lambda **kwargs: _OkLLM(),
    )
    svc = ModelConfigService(db=None)
    request = ModelTestRequest(
        model_type="llm", protocol="openai", model="gpt-4o", api_key="sk-x"
    )

    await svc._test_llm(request)  # 不抛即通过


# ========== 4. rerank compatible-mode 端点选择 ==========


def test_rerank_compatible_mode_uses_reranks_endpoint():
    """反例：用户误抄 compatible-mode 的 rerank 配置应走 /reranks，非原生 404 端点。"""
    from novamind.shared.ai_models.rerank.openai_rerank import CompatibleRerankClient

    c = CompatibleRerankClient(
        api_key="sk-test",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="gte-rerank",
    )
    assert c._is_dashscope_native is False
    assert c.endpoint == "/reranks"


def test_rerank_native_still_detected():
    """正例边界：真原生 URL（services，无 compatible 路径）仍走嵌套端点。"""
    from novamind.shared.ai_models.rerank.openai_rerank import CompatibleRerankClient

    c = CompatibleRerankClient(
        api_key="sk-test",
        base_url="https://dashscope.aliyuncs.com/api/v1/services",
        model_name="qwen3-vl-rerank",
    )
    assert c._is_dashscope_native is True
    assert c.endpoint == "/rerank/text-rerank/text-rerank"


# ========== 5. 删除影响检查：self.db 生效 + 失败补 warning ==========


@pytest.mark.asyncio
async def test_delete_impact_uses_self_db(monkeypatch):
    """反例回归：查询走 self.db（原 self.session AttributeError 被吞成恒空）。"""
    from novamind.features.user.models.user_model_config import UserModelConfig
    from novamind.features.user.services.model_config_service import ModelConfigService

    cfg = UserModelConfig(
        id=3, user_id=10, model_type=2, protocol="openai", model="text-embedding-v4"
    )

    captured = {}

    class _FakeSpaceRepo:
        def __init__(self, db):
            captured["db"] = db

        async def find_spaces_using_embedding(self, model):
            captured["model"] = model
            return [{"space_id": 1, "space_name": "项目文档库"}]

    import novamind.features.knowledge_space.repository.space_repository as space_repo_mod

    monkeypatch.setattr(space_repo_mod, "SpaceRepository", _FakeSpaceRepo)

    svc = ModelConfigService(db="SENTINEL-DB")
    impacts = await svc._check_delete_impact(cfg)

    assert captured["db"] == "SENTINEL-DB"  # 传的是 self.db（原代码传 self.session 直接炸）
    assert captured["model"] == "text-embedding-v4"
    assert impacts == [{
        "type": "space",
        "id": 1,
        "name": "项目文档库",
        "reason": "空间 '项目文档库' 正在使用此 Embedding 模型",
    }]


@pytest.mark.asyncio
async def test_delete_impact_query_failure_appends_warning(monkeypatch):
    """正例：空间绑定查询失败应补 warning 项，不谎报「无影响」。"""
    from novamind.features.user.models.user_model_config import UserModelConfig
    from novamind.features.user.services.model_config_service import ModelConfigService

    cfg = UserModelConfig(
        id=3, user_id=10, model_type=2, protocol="openai", model="text-embedding-v4"
    )

    class _BoomRepo:
        def __init__(self, db):
            raise RuntimeError("db unavailable")

    import novamind.features.knowledge_space.repository.space_repository as space_repo_mod

    monkeypatch.setattr(space_repo_mod, "SpaceRepository", _BoomRepo)

    svc = ModelConfigService(db=None)
    impacts = await svc._check_delete_impact(cfg)

    assert len(impacts) == 1
    assert impacts[0]["type"] == "warning"
    assert "检查失败" in impacts[0]["reason"]


# ========== 6. search test_connection 空结果判失败 ==========


class _EmptyResultsPort:
    """search 返回空列表（DuckDuckGo 超时降级形态），close 可观察。"""

    def __init__(self):
        self.closed = False

    async def search(self, query, max_results=5):
        return []

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_search_test_connection_empty_results_fails(monkeypatch):
    """反例：请求完成但零结果应判失败（超时被吞成空列表不再假成功）。"""
    import novamind.features.user.services.search_config_service as svc_mod
    from novamind.features.user.exceptions import SearchConfigTestFailedError
    from novamind.features.user.schemas.search_config_schema import SearchTestRequest

    port = _EmptyResultsPort()
    monkeypatch.setattr(
        svc_mod,
        "build_web_search_port_from_provider",
        lambda provider, api_key, extra_config: port,
    )

    svc = svc_mod.SearchConfigService(db=None)
    with pytest.raises(SearchConfigTestFailedError, match="未返回任何结果"):
        await svc.test_connection(
            user_id=10,
            request=SearchTestRequest(provider="duckduckgo"),
        )
    assert port.closed is True  # 端口仍被正确关闭


@pytest.mark.asyncio
async def test_search_test_connection_nonempty_passes(monkeypatch):
    """正例：有结果不误伤，异常透传分支不改变成功路径。"""
    import novamind.features.user.services.search_config_service as svc_mod
    from novamind.engines.search.ports import WebSearchResult
    from novamind.features.user.schemas.search_config_schema import SearchTestRequest

    class _Port:
        async def search(self, query, max_results=5):
            return [WebSearchResult(title="t", url="u", snippet="s")]

        async def close(self):
            pass

    monkeypatch.setattr(
        svc_mod,
        "build_web_search_port_from_provider",
        lambda provider, api_key, extra_config: _Port(),
    )

    svc = svc_mod.SearchConfigService(db=None)
    resp = await svc.test_connection(
        user_id=10,
        request=SearchTestRequest(provider="tavily", api_key="tvly-x"),
    )
    assert resp.success is True
    assert resp.results_count == 1
