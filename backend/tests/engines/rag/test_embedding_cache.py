"""查询向量缓存回归测试（retrieval_engine._embed_cached）。

验证不变量：
1. 有效性：同模型同文本不重复调用远程 embedding；
2. 键隔离：模型名或文本任一不同即换键——模型名入键是硬约束（不同模型
   向量维度不同，串键会让 kNN 直接报错）；
3. 失败方向：embedding 异常原样上抛，失败结果不缓存。
"""
import pytest
from novamind.engines.rag import RetrievalEngine
from novamind.engines.rag.errors import EmbeddingError

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class FakeEmbeddingClient:
    def __init__(self, model: str, fail: bool = False):
        self.model = model
        self.fail = fail
        self.calls: list[str] = []

    async def generate_embedding(self, text: str) -> list[float]:
        self.calls.append(text)
        if self.fail:
            raise EmbeddingError("embedding upstream down")
        return [0.1, 0.2, 0.3]


@pytest.fixture
def engine(fake_redis):
    return RetrievalEngine.__new__(RetrievalEngine)


async def test_same_model_same_text_embedded_once(engine, fake_redis):
    client = FakeEmbeddingClient("text-embedding-v3")

    v1 = await engine._embed_cached(client, "如何配置知识库")
    v2 = await engine._embed_cached(client, "如何配置知识库")

    assert v1 == v2 == [0.1, 0.2, 0.3]
    assert client.calls == ["如何配置知识库"], "同模型同文本应只调一次远程 embedding"


async def test_different_model_different_key(engine, fake_redis):
    a = FakeEmbeddingClient("text-embedding-v3")
    b = FakeEmbeddingClient("bge-large-zh")

    await engine._embed_cached(a, "同一段文本")
    await engine._embed_cached(b, "同一段文本")

    assert a.calls and b.calls, "不同模型的键必须隔离，不得共用向量"


async def test_different_text_different_key(engine, fake_redis):
    client = FakeEmbeddingClient("m")

    await engine._embed_cached(client, "查询一")
    await engine._embed_cached(client, "查询二")

    assert client.calls == ["查询一", "查询二"]


async def test_embedding_error_propagates_not_cached(engine, fake_redis):
    client = FakeEmbeddingClient("m", fail=True)

    with pytest.raises(EmbeddingError):
        await engine._embed_cached(client, "会失败的查询")
    assert not client.calls or len(client.calls) == 1

    client.fail = False
    await engine._embed_cached(client, "会失败的查询")  # 失败不缓存，恢复后重试
    assert len(client.calls) == 2
