"""Embedding / LLM 客户端容错测试。

验证（2026-09-04 DashScope ReadTimeout 故障的回归测试）：
  - openai SDK 包装的异常（APITimeoutError / APIConnectionError / RateLimitError）
    会命中 tenacity 重试名单——修复前 tenacity 名单只有 httpx 异常，
    openai 包装类型直接穿透，超时后外层重试从不触发。
  - generate_embeddings_batch 的双层 batch_size 语义：不传 batch_size 时
    使用构造器的 self.batch_size（而非方法硬编码默认值）。
"""

import asyncio
import inspect
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


def _make_client(**kwargs) -> "OpenAICompatibleEmbedding":  # noqa: F821 懒 import 字符串注解
    """构造绕过真实 AsyncOpenAI 初始化的客户端实例。"""
    from novamind.shared.ai_models.embedding.openai_compatible import (
        OpenAICompatibleEmbedding,
    )

    with patch("novamind.shared.ai_models.embedding.openai_compatible.AsyncOpenAI"):
        client = OpenAICompatibleEmbedding(
            api_key="test-key",
            base_url="https://example.com/v1",
            model_name="test-embedding",
            **kwargs,
        )
    return client


# ---- openai 包装异常命中 tenacity 重试 ----

def test_retry_list_contains_openai_wrapped_exceptions():
    """tenacity 重试名单必须包含 openai SDK 包装异常类型。"""
    from novamind.shared.ai_models.embedding import openai_compatible as emb_mod
    from novamind.shared.ai_models.llm import openai_compatible as llm_mod

    openai_exc = emb_mod.OPENAI_RETRY_EXCEPTIONS
    assert openai_exc, "OPENAI_RETRY_EXCEPTIONS 不应为空（openai 已安装）"

    from openai import APIConnectionError, APITimeoutError, RateLimitError

    assert APIConnectionError in openai_exc
    assert APITimeoutError in openai_exc
    assert RateLimitError in openai_exc

    # LLM 客户端复用同一异常元组（同 bug 类，同修复）
    assert llm_mod.OPENAI_RETRY_EXCEPTIONS is openai_exc or llm_mod.OPENAI_RETRY_EXCEPTIONS == openai_exc


def test_embedding_batch_timeout_is_retried():
    """模拟 DashScope ReadTimeout：_generate_batch 抛 APITimeoutError 两次后成功，
    tenacity 应重试并最终返回结果（修复前直接穿透抛出）。"""
    import httpx
    from openai import APITimeoutError

    # 构造真实的 APITimeoutError（需要 message 参数和 request 属性）
    request = httpx.Request("POST", "https://example.com/v1/embeddings")
    exc = APITimeoutError(request=request)

    client = _make_client(batch_size=32)

    calls = {"n": 0}
    fake_response = MagicMock()
    fake_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

    async def flaky_create(**kwargs):
        if calls["n"] < 2:
            calls["n"] += 1
            raise exc
        return fake_response

    client.client = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=flaky_create)

    result = asyncio.run(client._generate_batch(["文本1", "文本2"]))

    assert calls["n"] == 2, "应重试 2 次后成功"
    assert result == [[0.1, 0.2, 0.3]]


def test_embedding_batch_timeout_exhausts_retries_and_reraises():
    """连续超时 3 次后，tenacity 应停止重试并原样抛出（reraise=True 不包 RetryError）。"""
    import httpx
    from openai import APITimeoutError

    request = httpx.Request("POST", "https://example.com/v1/embeddings")
    exc = APITimeoutError(request=request)

    client = _make_client()
    calls = {"n": 0}

    async def always_timeout(**kwargs):
        calls["n"] += 1
        raise exc

    client.client = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=always_timeout)

    with pytest.raises(APITimeoutError):
        asyncio.run(client._generate_batch(["文本"]))

    assert calls["n"] == 3, "stop_after_attempt(3) 应恰好尝试 3 次"


# ---- 双层 batch_size 语义 ----

def test_generate_embeddings_batch_uses_constructor_batch_size_by_default():
    """不传 batch_size 时使用构造器的 self.batch_size，而非方法硬编码默认值。"""
    client = _make_client(batch_size=32)

    inner_batches = []

    async def fake_generate_batch(batch_texts):
        inner_batches.append(len(batch_texts))
        return [[0.0]] * len(batch_texts)

    client._generate_batch = fake_generate_batch

    texts = [f"文本{i}" for i in range(35)]
    result = asyncio.run(client.generate_embeddings_batch(texts))

    assert inner_batches == [32, 3], (
        f"35 条文本应按构造器 batch_size=32 切成 [32, 3]，实际: {inner_batches}"
    )
    assert len(result) == 35


def test_generate_embeddings_batch_explicit_batch_size_wins():
    """显式传 batch_size 时优先于构造器配置（调用方显式覆盖语义保留）。"""
    client = _make_client(batch_size=32)

    inner_batches = []

    async def fake_generate_batch(batch_texts):
        inner_batches.append(len(batch_texts))
        return [[0.0]] * len(batch_texts)

    client._generate_batch = fake_generate_batch

    texts = [f"文本{i}" for i in range(15)]
    asyncio.run(client.generate_embeddings_batch(texts, batch_size=10))

    assert inner_batches == [10, 5], f"显式 batch_size=10 应切成 [10, 5]，实际: {inner_batches}"


def test_base_embedding_abstract_signature_allows_none_batch_size():
    """BaseEmbedding 抽象签名 batch_size 默认值应为 None（None → 客户端自配批次）。"""
    from novamind.shared.ai_models.base_model import BaseEmbedding

    params = inspect.signature(BaseEmbedding.generate_embeddings_batch).parameters
    assert params["batch_size"].default is None


# ---- 服务商批量条数上限自适应（2026-09-04 DashScope batch_size>20 400 故障回归）----

def _make_batch_limit_error(limit: int = 20):
    """构造 DashScope 风格的批量超限 400（真实报错文本）。"""
    import httpx
    import openai

    request = httpx.Request("POST", "https://example.com/v1/embeddings")
    response = httpx.Response(400, request=request)
    message = (
        "Error code: 400 - {'error': {'message': '<400> InternalError.Algo.InvalidParameter: "
        f"Value error, batch size is invalid, it should not be larger than {limit}.: input.contents'"
        ", 'type': 'InvalidParameter', 'param': None, 'code': 'InvalidParameter'}}"
    )
    return openai.BadRequestError(message, response=response, body=None)


def test_batch_limit_400_shrinks_batch_and_recovers():
    """批量超限 400 → 缩小到服务商上限重发，后续批次直接用新上限。"""
    client = _make_client(batch_size=32)

    batch_sizes = []

    async def fake_create(**kwargs):
        batch_sizes.append(len(kwargs["input"]))
        if len(batch_sizes) == 1:
            raise _make_batch_limit_error(20)  # 首批 32 条被拒
        return MagicMock(
            data=[MagicMock(embedding=[0.1]) for _ in kwargs["input"]]
        )

    client.client = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=fake_create)

    texts = [f"文本{i}" for i in range(35)]
    result = asyncio.run(client.generate_embeddings_batch(texts))

    # 首批 [0:32] 被拒 → 从 0 处按 20 重发，剩 15 条 → [32(拒), 20, 15]
    assert batch_sizes == [32, 20, 15], f"应按 [32→拒, 20, 15] 重发，实际: {batch_sizes}"
    assert len(result) == 35


def test_batch_limit_400_remembered_for_subsequent_batches():
    """首个批次触发缩批后，后续批次不再触发 400（批大小已记住）。"""
    client = _make_client(batch_size=32)

    batch_sizes = []

    async def fake_create(**kwargs):
        batch_sizes.append(len(kwargs["input"]))
        if len(batch_sizes) == 1:
            raise _make_batch_limit_error(20)
        return MagicMock(
            data=[MagicMock(embedding=[0.1]) for _ in kwargs["input"]]
        )

    client.client = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=fake_create)

    texts = [f"文本{i}" for i in range(100)]
    asyncio.run(client.generate_embeddings_batch(texts))

    # 100 条 = 32(拒) + 20 + 20 + 20 + 12 + ... 首批之后全部 ≤ 20
    assert all(s <= 20 for s in batch_sizes[1:]), batch_sizes
    assert sum(batch_sizes[1:]) == 100


def test_non_batch_400_reraises_immediately():
    """非批量条数类 400（如鉴权失败）→ 原样抛出，不尝试缩批。"""
    import httpx
    import openai

    client = _make_client(batch_size=32)

    request = httpx.Request("POST", "https://example.com/v1/embeddings")
    response = httpx.Response(400, request=request)
    auth_err = openai.BadRequestError(
        "Error code: 400 - Invalid API key", response=response, body=None
    )

    calls = {"n": 0}

    async def always_auth_error(**kwargs):
        calls["n"] += 1
        raise auth_err

    client.client = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=always_auth_error)

    with pytest.raises(openai.BadRequestError):
        asyncio.run(client.generate_embeddings_batch(["文本"]))

    assert calls["n"] == 1, "非批量错误不应重发"


def test_batch_limit_without_parseable_number_reraises():
    """批量超限但解析不出具体上限数字 → 原样抛出（避免无限缩批循环）。"""
    import httpx
    import openai

    client = _make_client(batch_size=32)

    request = httpx.Request("POST", "https://example.com/v1/embeddings")
    response = httpx.Response(400, request=request)
    vague_err = openai.BadRequestError(
        "Error code: 400 - batch size is too large", response=response, body=None
    )

    calls = {"n": 0}

    async def always_vague(**kwargs):
        calls["n"] += 1
        raise vague_err

    client.client = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=always_vague)

    with pytest.raises(openai.BadRequestError):
        asyncio.run(client.generate_embeddings_batch(["文本"]))

    assert calls["n"] == 1


def test_batch_limit_ge_current_reraises():
    """解析出的上限 ≥ 当前批大小（异常情形）→ 原样抛出而非空转。"""
    import httpx
    import openai

    client = _make_client(batch_size=10)

    request = httpx.Request("POST", "https://example.com/v1/embeddings")
    response = httpx.Response(400, request=request)
    weird_err = openai.BadRequestError(
        "Error code: 400 - batch size is invalid, it should not be larger than 20",
        response=response, body=None,
    )

    calls = {"n": 0}

    async def always_weird(**kwargs):
        calls["n"] += 1
        raise weird_err

    client.client = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=always_weird)

    with pytest.raises(openai.BadRequestError):
        asyncio.run(client.generate_embeddings_batch(["文本"]))

    assert calls["n"] == 1


def test_async_openai_receives_zero_internal_retries():
    """SDK 内部重试必须为 0：外层 tenacity 已重试，双层相乘会让单批挂 12 分钟
    （doc 574 实测 3×4 次 HTTP × 60s timeout）。与 LLM 客户端语义对齐。"""
    import httpx
    from novamind.shared.ai_models.embedding import openai_compatible as emb_mod

    captured = {}
    real_async_openai = emb_mod.AsyncOpenAI

    def capturing_async_openai(**kwargs):
        captured.update(kwargs)
        http_client = httpx.AsyncClient(trust_env=False)
        captured["_http_client_created"] = True
        return real_async_openai(**{**kwargs, "http_client": http_client})

    with patch(
        "novamind.shared.ai_models.embedding.openai_compatible.AsyncOpenAI",
        capturing_async_openai,
    ), patch(
        "novamind.shared.ai_models.embedding.openai_compatible.build_openai_http_client"
    ):
        from novamind.shared.ai_models.embedding.openai_compatible import (
            OpenAICompatibleEmbedding,
        )

        OpenAICompatibleEmbedding(
            api_key="k",
            base_url="https://example.com/v1",
            model_name="m",
        )

    assert captured.get("max_retries") == 0, (
        f"AsyncOpenAI(max_retries=...) 应为 0，实际: {captured.get('max_retries')}"
    )


def test_learned_batch_limit_reused_across_calls():
    """学到的上限跨调用复用：第二个文档不再触发 400，直接按 20 切批。"""
    client = _make_client(batch_size=32)

    batch_sizes = []

    async def fake_create(**kwargs):
        batch_sizes.append(len(kwargs["input"]))
        if len(kwargs["input"]) > 20:
            raise _make_batch_limit_error(20)
        return MagicMock(
            data=[MagicMock(embedding=[0.1]) for _ in kwargs["input"]]
        )

    client.client = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=fake_create)

    # 第一个文档：撞一次 400 后学得 20
    asyncio.run(client.generate_embeddings_batch([f"a{i}" for i in range(35)]))
    first_call_warnings = batch_sizes.copy()
    assert 32 in first_call_warnings, "首个文档应先以 32 条撞上限"

    batch_sizes.clear()
    # 第二个文档：直接按 20 切批，零次 400
    result = asyncio.run(client.generate_embeddings_batch([f"b{i}" for i in range(45)]))

    assert batch_sizes == [20, 20, 5], f"第二个文档应直接按 20 切批，实际: {batch_sizes}"
    assert len(result) == 45


def test_learned_batch_limit_takes_historical_minimum():
    """多轮学习取历史最小值（服务商上限随 token 数浮动：先报 25 后报 20 → 稳定用 20）。"""
    client = _make_client(batch_size=32)

    batch_sizes = []

    async def fake_create(**kwargs):
        batch_sizes.append(len(kwargs["input"]))
        # 上限随请求浮动：32 条时拒（报 25），25 条时再拒（报 20）
        if len(kwargs["input"]) > 25:
            raise _make_batch_limit_error(25)
        if len(kwargs["input"]) > 20:
            raise _make_batch_limit_error(20)
        return MagicMock(
            data=[MagicMock(embedding=[0.1]) for _ in kwargs["input"]]
        )

    client.client = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=fake_create)

    asyncio.run(client.generate_embeddings_batch([f"a{i}" for i in range(60)]))

    # 60 条：32(拒→25) 25(拒→20) 20 20 20（从 0 处重发）→ 学习值取历史最小 20
    assert batch_sizes == [32, 25, 20, 20, 20], batch_sizes
    assert client._learned_batch_limit == 20

    batch_sizes.clear()
    # 后续调用直接从 20 开始
    asyncio.run(client.generate_embeddings_batch([f"b{i}" for i in range(40)]))
    assert batch_sizes == [20, 20], batch_sizes


# ---- 乱码/控制字符清洗（2026-09-07 doc 574 DashScope 挂起故障回归）----
#
# DeepDoc 解析 PDF 数学公式会把方程组大括号等排版符号编码到 PUA 私用区
# （如 U+F8F1-F8F4），并在分块残留 NUL、C0 控制字符、孤立 \r。DashScope 对
# 含 PUA 的请求不报错也不返回（无限挂起直到读超时）。doc 574 首批 20 块中
# chunk#16 含 5 个 PUA 即触发 3×60s 超时 → 任务 FAILED。431 块中 75 块含异类
# 字符（PUA=27 / NUL=90 / C0=89）。sanitize 范围须对齐 DeepDoc _is_garbled_char
# （pdf.py:158-174）乱码标准，覆盖 PUA / U+FFFD / C1，仅处理 C0+NUL 不足。

def test_sanitize_normalizes_control_chars():
    """\\r\\n/孤立\\r 归一为 \\n；NUL/DEL/C0/C1 控制字符替换为空格；\\t 保留。"""
    from novamind.shared.ai_models.embedding.openai_compatible import (
        sanitize_text_for_embedding,
    )

    assert sanitize_text_for_embedding("a\r\nb") == "a\nb"
    assert sanitize_text_for_embedding("a\rb") == "a\nb"
    assert sanitize_text_for_embedding("a\x00b") == "a b"
    assert sanitize_text_for_embedding("a\x7fb") == "a b"
    assert sanitize_text_for_embedding("a\x03b") == "a b"  # ETX（doc 574 chunk#0）
    assert sanitize_text_for_embedding("a\x0cb") == "a b"  # FF（doc 574 chunk#3）
    assert sanitize_text_for_embedding("a\x9bb") == "a b"  # C1 (CSI)
    assert sanitize_text_for_embedding("a\tb") == "a\tb"
    assert sanitize_text_for_embedding("") == ""
    assert sanitize_text_for_embedding("正常中文") == "正常中文"


def test_sanitize_strips_pua_fffd_aligns_deepdoc_garbled_standard():
    """PUA（DeepDoc 公式排版符号）/ U+FFFD 替换符替换为空格——doc 574 真凶。

    doc 574 chunk#16 含 U+F8F1/F8F2/F8F3/F8F4（方程组左大括号），sanitize
    旧版只处理 C0+NUL+DEL，漏 PUA → 原样发 DashScope 触发 60s 挂起。
    此测试钉死 sanitize 范围对齐 DeepDoc _is_garbled_char（pdf.py:158-174）。
    """
    from novamind.shared.ai_models.embedding.openai_compatible import (
        sanitize_text_for_embedding,
    )

    # doc 574 chunk#16 的真实 PUA 序列（方程组大括号）
    formula = "x = 1y = 2"
    cleaned = sanitize_text_for_embedding(formula)
    assert "" not in cleaned and "" not in cleaned
    assert "" not in cleaned and "" not in cleaned
    # PUA 替换为空格，正文保留
    assert "x = 1" in cleaned and "y = 2" in cleaned

    # U+FFFD 替换符
    assert sanitize_text_for_embedding("a�b") == "a b"
    # PUA 平面15-16
    assert sanitize_text_for_embedding("a\U000f0000b") == "a b"
    assert sanitize_text_for_embedding("a\U0010ffffb") == "a b"
    # 干净的数学符号（≤ ≥ ∇ ∆）须保留——这些不是乱码
    clean_math = "∇f(Xk) ≤ L 且 ||∆k|| ≥ 0"
    assert sanitize_text_for_embedding(clean_math) == clean_math


def test_sanitize_preserves_clean_text_and_newline_semantics():
    """干净文本零改动；多行公式的换行结构保留（向量语义损失最小化）。"""
    from novamind.shared.ai_models.embedding.openai_compatible import (
        sanitize_text_for_embedding,
    )

    text = "第一段\n第二段\n1. 变量 x = 1"
    assert sanitize_text_for_embedding(text) == text


def test_generate_batch_sanitizes_input_before_request():
    """_generate_batch 发送给服务商的 input 已清洗（mock 捕获请求参数断言）。"""

    client = _make_client(batch_size=20)
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return MagicMock(
            data=[MagicMock(embedding=[0.1]) for _ in kwargs["input"]]
        )

    client.client = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=fake_create)

    dirty = ["公式 ||∆k|| ≤ L\r\r∇f(Xk)\x00 归纳"]
    asyncio.run(client._generate_batch(dirty))

    sent = captured["input"]
    assert sent != dirty, "发送的 input 不应包含未清洗文本"
    assert "\r" not in sent[0] and "\x00" not in sent[0]
    assert "" not in sent[0] and "" not in sent[0] and "" not in sent[0]
    # \r\r 折叠为 \n、NUL 变空格、PUA 变空格，正文保留
    assert "∇f(Xk)" in sent[0]
    assert "\n" in sent[0]


def test_generate_embedding_sanitizes_single_text():
    """单条 generate_embedding 路径同样清洗。"""
    client = _make_client()
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return MagicMock(data=[MagicMock(embedding=[0.1, 0.2])])

    client.client = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=fake_create)

    asyncio.run(client.generate_embedding("残留\x00文本\r\n第二行"))
    sent = captured["input"]
    assert "\x00" not in sent and "\r" not in sent
    assert sent == "残留 文本\n第二行"
