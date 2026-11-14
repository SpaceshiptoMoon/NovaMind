"""查询向量缓存回归测试（retrieval_engine._embed_cached）。

验证不变量：
1. 有效性：同配置同文本不重复调用远程 embedding；
2. 键隔离：配置签名（提供商/模型/归一化）或文本任一不同即换键——同名模型
   在不同提供商下向量完全不同，签名不隔离会静默串键（维度恰好相同时是
   错误结果而非报错）；
3. 失败方向：embedding 异常原样上抛，失败结果不缓存。
"""
import pytest
from novamind.engines.rag import RetrievalEngine
from novamind.engines.rag.errors import EmbeddingError
from novamind.shared.ai_models.base_model import client_cache_signature

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class FakeEmbeddingClient:
    """鸭子桩：cache_signature 与生产实现同构（base_url/model/normalize 指纹）。"""

    def __init__(self, model: str, base_url: str = "https://api.example.com",
                 normalize: bool = True, fail: bool = False):
        self.model = model
        self.base_url = base_url
        self.normalize = normalize
        self.fail = fail
        self.calls: list[str] = []
        self._cache_sig_extra = {"normalize": normalize}

    def cache_signature(self) -> str:
        return client_cache_signature(self.base_url, self.model, self._cache_sig_extra)

    async def generate_embedding(self, text: str) -> list[float]:
        self.calls.append(text)
        if self.fail:
            raise EmbeddingError("embedding upstream down")
        return [0.1, 0.2, 0.3]


@pytest.fixture
def engine(fake_redis):
    return RetrievalEngine.__new__(RetrievalEngine)


async def test_same_config_same_text_embedded_once(engine, fake_redis):
    client = FakeEmbeddingClient("text-embedding-v3")

    v1 = await engine._embed_cached(client, "如何配置知识库")
    v2 = await engine._embed_cached(client, "如何配置知识库")

    assert v1 == v2 == [0.1, 0.2, 0.3]
    assert client.calls == ["如何配置知识库"], "同配置同文本应只调一次远程 embedding"


async def test_same_model_name_different_provider_different_key(engine, fake_redis):
    """同名模型、不同提供商：键必须隔离（维度恰好相同时串键 = 静默错误向量）。"""
    a = FakeEmbeddingClient("text-embedding-v3", base_url="https://dashscope.example")
    b = FakeEmbeddingClient("text-embedding-v3", base_url="http://vllm.local:8000")

    await engine._embed_cached(a, "同一段文本")
    await engine._embed_cached(b, "同一段文本")

    assert a.calls and b.calls, "不同提供商的签名必须隔离，不得共用向量"


async def test_normalize_flag_changes_key(engine, fake_redis):
    """归一化开关改变输出：开关不同的两个客户端不得共用缓存。"""
    a = FakeEmbeddingClient("m", normalize=True)
    b = FakeEmbeddingClient("m", normalize=False)

    await engine._embed_cached(a, "同一段文本")
    await engine._embed_cached(b, "同一段文本")

    assert a.calls and b.calls, "归一化开关必须参与缓存签名"


async def test_different_model_different_key(engine, fake_redis):
    a = FakeEmbeddingClient("text-embedding-v3")
    b = FakeEmbeddingClient("bge-large-zh")

    await engine._embed_cached(a, "同一段文本")
    await engine._embed_cached(b, "同一段文本")

    assert a.calls and b.calls


async def test_different_text_different_key(engine, fake_redis):
    client = FakeEmbeddingClient("m")

    await engine._embed_cached(client, "查询一")
    await engine._embed_cached(client, "查询二")

    assert client.calls == ["查询一", "查询二"]


async def test_embedding_error_propagates_not_cached(engine, fake_redis):
    client = FakeEmbeddingClient("m", fail=True)

    with pytest.raises(EmbeddingError):
        await engine._embed_cached(client, "会失败的查询")
    assert len(client.calls) == 1

    client.fail = False
    await engine._embed_cached(client, "会失败的查询")  # 失败不缓存，恢复后重试
    assert len(client.calls) == 2
