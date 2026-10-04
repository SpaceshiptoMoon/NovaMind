"""OpenAI 兼容视频客户端测试（纯 mock，不打真实 API）。

覆盖：
- 消息构造：帧序列（video 项含帧列表+fps）/ URL 直输（video_url 项）；
- R5 注册表：protocol=openai_video 经 create_llm_client 构造本类实例；
- 继承兼容：父类文本 generate_text 照常工作（S1/S2 不受影响）；
- 帧数硬限前置校验：>512 / <4 直接 ValueError；
- VideoInputNotSupportedError：4xx+视频拒绝特征 → 转译；其余异常原样上抛。
"""
import pytest

from novamind.shared.ai_models.llm import (
    OpenAICompatibleVideoLLM,
    VideoInputNotSupportedError,
    create_llm_client,
)
from novamind.shared.ai_models.llm.openai_compatible_video import (
    MAX_VIDEO_FRAMES,
    MIN_VIDEO_FRAMES,
    build_video_frames_messages,
    build_video_url_messages,
    is_video_input_rejected,
)

pytestmark = pytest.mark.unit


# ==================== 消息构造 ====================

def test_build_video_frames_messages_structure() -> None:
    """帧序列消息：单条 user，content = video 项（帧列表+fps）+ text 项。"""
    urls = [f"data:image/jpeg;base64,A{i}" for i in range(4)]
    msgs = build_video_frames_messages(urls, "描述这段画面", fps=0.2)
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    content = msgs[0]["content"]
    assert content[0] == {"type": "video", "video": urls, "fps": 0.2}
    assert content[1] == {"type": "text", "text": "描述这段画面"}


def test_build_video_url_messages_structure() -> None:
    """URL 直输消息：content = video_url 项（含 url）+ text 项。"""
    msgs = build_video_url_messages("https://example.com/v.mp4", "描述")
    content = msgs[0]["content"]
    assert content[0] == {"type": "video_url", "video_url": {"url": "https://example.com/v.mp4"}}
    assert content[1] == {"type": "text", "text": "描述"}


# ==================== R5 注册表 ====================

def test_factory_registry_creates_video_client() -> None:
    """protocol=openai_video 经工厂查表构造本类实例。"""
    client = create_llm_client(
        protocol="openai_video", api_key="k",
        base_url="https://dashscope.example/v1", model_name="qwen-vl",
    )
    assert isinstance(client, OpenAICompatibleVideoLLM)
    # 继承链：也是 OpenAICompatibleLLM（文本/图片路径可用）
    from novamind.shared.ai_models.llm.openai_compatible import OpenAICompatibleLLM

    assert isinstance(client, OpenAICompatibleLLM)


def test_factory_protocol_attribute() -> None:
    """_FACTORY_PROTOCOL 挂载正确（R5 自注册契约）。"""
    assert OpenAICompatibleVideoLLM._FACTORY_PROTOCOL == "openai_video"


# ==================== 帧数硬限前置校验 ====================

def _make_client() -> OpenAICompatibleVideoLLM:
    return OpenAICompatibleVideoLLM(
        api_key="k", base_url="http://x", model_name="m",
    )


@pytest.mark.asyncio
async def test_frames_over_limit_rejected_before_api() -> None:
    """超 512 帧直接 ValueError，不发起 API 调用（省一次往返）。"""
    client = _make_client()
    urls = ["data:image/jpeg;base64,A"] * (MAX_VIDEO_FRAMES + 1)
    with pytest.raises(ValueError, match="512"):
        await client.generate_text_from_frames(urls, "p", fps=1.0)


@pytest.mark.asyncio
async def test_frames_under_minimum_rejected() -> None:
    """少于 4 帧直接 ValueError（DashScope 帧列表下限）。"""
    client = _make_client()
    urls = ["data:image/jpeg;base64,A"] * (MIN_VIDEO_FRAMES - 1)
    with pytest.raises(ValueError, match="下限"):
        await client.generate_text_from_frames(urls, "p", fps=1.0)


# ==================== 视频拒绝特征判定与转译 ====================

class _FakeApiError(Exception):
    """带 status_code 的假 API 异常（模拟 openai SDK 错误形态）。"""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def test_is_video_input_rejected_match() -> None:
    """4xx + 视频拒绝特征关键词 → True。"""
    assert is_video_input_rejected(
        _FakeApiError("This model does not support video input", 400)
    )
    assert is_video_input_rejected(
        _FakeApiError("Invalid type: 'video' is unsupported", 422)
    )


def test_is_video_input_rejected_non_match() -> None:
    """5xx / 4xx 无视频特征 / 4xx 语义不属视频拒绝 → False。"""
    assert not is_video_input_rejected(
        _FakeApiError("This model does not support video input", 500)
    )
    assert not is_video_input_rejected(
        _FakeApiError("rate limit exceeded", 429)
    )
    assert not is_video_input_rejected(RuntimeError("video broken on our side"))
    assert not is_video_input_rejected(_FakeApiError("quota exceeded", 403))


@pytest.mark.asyncio
async def test_generate_from_frames_translates_rejection(monkeypatch) -> None:
    """帧序列请求被 4xx 拒绝 → 转译 VideoInputNotSupportedError。"""

    async def _fail(prompt, **kwargs):
        raise _FakeApiError("does not support video input", 400)

    client = _make_client()
    monkeypatch.setattr(client, "generate_text", _fail)
    urls = ["data:image/jpeg;base64,A"] * 4
    with pytest.raises(VideoInputNotSupportedError):
        await client.generate_text_from_frames(urls, "p", fps=1.0)


@pytest.mark.asyncio
async def test_generate_from_url_translates_rejection(monkeypatch) -> None:
    """URL 直输请求被 4xx 拒绝 → 转译 VideoInputNotSupportedError。"""

    async def _fail(prompt, **kwargs):
        raise _FakeApiError("unsupported content type video", 415)

    client = _make_client()
    monkeypatch.setattr(client, "generate_text", _fail)
    with pytest.raises(VideoInputNotSupportedError):
        await client.generate_text_from_video_url("https://x/v.mp4", "p")


@pytest.mark.asyncio
async def test_non_rejection_error_passthrough(monkeypatch) -> None:
    """非拒绝类异常（超时/5xx/配额）原样上抛，不触发降级判据。"""

    async def _fail(prompt, **kwargs):
        raise TimeoutError("upstream timeout")

    client = _make_client()
    monkeypatch.setattr(client, "generate_text", _fail)
    with pytest.raises(TimeoutError):
        await client.generate_text_from_video_url("https://x/v.mp4", "p")


@pytest.mark.asyncio
async def test_inherited_text_generate_still_works(monkeypatch) -> None:
    """继承兼容：父类文本 generate_text(str) 路径不受视频扩展影响。"""

    async def _ok(prompt, **kwargs):
        assert isinstance(prompt, str)
        return "ok"

    client = _make_client()
    monkeypatch.setattr(client, "generate_text", _ok)
    # 直接调用父类路径（str prompt）
    assert await client.generate_text("hello") == "ok"


@pytest.mark.asyncio
async def test_frames_request_reaches_parent_with_messages(monkeypatch) -> None:
    """帧序列请求构造正确的消息列表后透传父类 generate_text。"""
    captured: dict = {}

    async def _capture(prompt, **kwargs):
        captured["prompt"] = prompt
        return "desc"

    client = _make_client()
    monkeypatch.setattr(client, "generate_text", _capture)
    urls = [f"data:image/jpeg;base64,A{i}" for i in range(4)]
    out = await client.generate_text_from_frames(
        urls, "prompt-text", fps=0.5, temperature=0.1,
    )
    assert out == "desc"
    msgs = captured["prompt"]
    assert msgs[0]["content"][0]["fps"] == 0.5
    assert msgs[0]["content"][0]["video"] == urls
