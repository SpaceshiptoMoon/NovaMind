"""OpenAI 兼容视频 LLM 客户端：帧序列伪视频与视频 URL 直输两种视频输入。

继承 OpenAICompatibleLLM（文本/图片消息完全兼容），额外提供两个视频输入方法：
- ``generate_text_from_frames``：帧 data URL 列表按 ``{"type":"video","video":[...],"fps":N}``
  伪视频格式喂入（DashScope 帧列表模式，4-512 张硬限）
- ``generate_text_from_video_url``：``{"type":"video_url","video_url":{"url":...}}``
  直输公网可达的视频 URL

服务商标明拒绝视频输入类请求时抛 :class:`VideoInputNotSupportedError`，
供编排层做 frame_seq 降级决策；其余异常原样上抛（fail fast）。
"""
import re
from collections.abc import Awaitable, Callable
from typing import Any

from novamind.shared.ai_models.llm.openai_compatible import OpenAICompatibleLLM
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# DashScope 帧列表模式硬限：4-512 张。
MAX_VIDEO_FRAMES = 512
MIN_VIDEO_FRAMES = 4

# 服务商拒绝视频输入的错误特征（4xx + 这些关键词组合），命中即转 VideoInputNotSupportedError。
_VIDEO_REJECT_PATTERNS = re.compile(
    r"(not[\s_]*support|unsupported|invalid[\s_]*type|video.*(invalid|not|unsupported)"
    r"|(invalid|unknown|unexpected).*video)",
    re.IGNORECASE,
)


class VideoInputNotSupportedError(Exception):
    """服务商明确拒绝视频类输入（不支持该请求形态）。

    由 :meth:`OpenAICompatibleVideoLLM.generate_text_from_frames` /
    :meth:`generate_text_from_video_url` 在响应错误命中视频拒绝特征时抛出，
    是 video_native → frame_seq 降级链的唯一判据；其余异常不触发降级。
    """


def build_video_frames_messages(
    frame_data_urls: list[str],
    text_prompt: str,
    *,
    fps: float,
) -> list[dict[str, Any]]:
    """构建帧序列伪视频消息（DashScope 帧列表模式）。

    Args:
        frame_data_urls: 帧 data URL 列表（4-512 张，升序时间）。
        text_prompt: 随视频发送的文本指令。
        fps: 相邻帧间隔的倒数，告知模型帧时序。

    Returns:
        单条 user 消息的列表（content 为 video 帧列表项 + text 项）。
    """
    return [{
        "role": "user",
        "content": [
            {"type": "video", "video": list(frame_data_urls), "fps": fps},
            {"type": "text", "text": text_prompt},
        ],
    }]


def build_video_url_messages(video_url: str, text_prompt: str) -> list[dict[str, Any]]:
    """构建视频 URL 直输消息。

    Args:
        video_url: 公网可达的视频 URL（如 MinIO 预签名公网 URL）。
        text_prompt: 随视频发送的文本指令。

    Returns:
        单条 user 消息的列表（content 为 video_url 项 + text 项）。
    """
    return [{
        "role": "user",
        "content": [
            {"type": "video_url", "video_url": {"url": video_url}},
            {"type": "text", "text": text_prompt},
        ],
    }]


def is_video_input_rejected(exc: BaseException) -> bool:
    """判断异常是否属服务商明确拒绝视频输入。

    Args:
        exc: generate_text* 抛出的异常。

    Returns:
        4xx 状态且错误信息命中视频拒绝特征时 True。
    """
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status is None or not (400 <= int(status) < 500):
        return False
    return bool(_VIDEO_REJECT_PATTERNS.search(str(exc)))


class OpenAICompatibleVideoLLM(OpenAICompatibleLLM):
    """OpenAI 兼容视频 LLM 客户端（protocol=openai_video）。

    在 OpenAICompatibleLLM 基础上扩展两种视频输入；文本与图片消息路径
    继承不变（同一模型配置可服务 S1-S4 全部策略）。
    """

    def _validate_frame_count(self, frame_data_urls: list[str]) -> None:
        """校验帧数在服务商机架允许区间，越界提前失败（省一次 API 往返）。"""
        n = len(frame_data_urls)
        if n > MAX_VIDEO_FRAMES:
            raise ValueError(
                f"帧序列超出单次请求上限：{n} > {MAX_VIDEO_FRAMES}，请减小分段帧数"
            )
        if n < MIN_VIDEO_FRAMES:
            raise ValueError(
                f"帧序列不足单次请求下限：{n} < {MIN_VIDEO_FRAMES}"
            )

    async def _generate_video_text(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
        log_label: str,
        on_reject: Callable[[BaseException], Awaitable[None]] | None = None,
    ) -> str:
        """视频消息的生成内核：复用父类 generate_text（list 透传 + semaphore/重试/日志）。

        Args:
            messages: 视频多模态消息列表。
            max_tokens: 生成 token 上限。
            temperature: 采样温度。
            log_label: 日志场景标签。
            on_reject: 检出视频拒绝特征异常后的异步回调（默认转译为
                VideoInputNotSupportedError 再抛）。

        Returns:
            模型生成文本。

        Raises:
            VideoInputNotSupportedError: 服务商明确拒绝视频输入时。
        """
        try:
            return await self.generate_text(
                prompt=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            if is_video_input_rejected(exc):
                logger.warning(
                    "视频输入被服务商拒绝",
                    model=self.model, input_kind=log_label,
                    error_type=type(exc).__name__, error=str(exc)[:200],
                )
                if on_reject is not None:
                    await on_reject(exc)
                raise VideoInputNotSupportedError(
                    f"服务商拒绝视频输入（{self.model}）: {str(exc)[:200]}"
                ) from exc
            raise

    async def generate_text_from_frames(
        self,
        frame_data_urls: list[str],
        text_prompt: str,
        *,
        fps: float,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        """帧序列伪视频生成（DashScope 帧列表模式，模型感知时序）。

        Args:
            frame_data_urls: 帧 data URL 列表（4-512 张，升序时间）。
            text_prompt: 文本指令（建议含帧时刻表以校准时间定位）。
            fps: 相邻帧间隔的倒数。
            max_tokens: 生成 token 上限。
            temperature: 采样温度。

        Returns:
            模型生成文本。

        Raises:
            ValueError: 帧数越界（>512 或 <4）。
            VideoInputNotSupportedError: 服务商明确拒绝视频输入。
        """
        self._validate_frame_count(frame_data_urls)
        messages = build_video_frames_messages(
            frame_data_urls, text_prompt, fps=fps
        )
        return await self._generate_video_text(
            messages,
            max_tokens=max_tokens, temperature=temperature,
            log_label="frames",
        )

    async def generate_text_from_video_url(
        self,
        video_url: str,
        text_prompt: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        """视频 URL 直输生成（服务商侧解码，不受 base64 体积限制）。

        Args:
            video_url: 公网可达的视频 URL。
            text_prompt: 文本指令（建议注入片起始绝对时间做双重时间校正）。
            max_tokens: 生成 token 上限。
            temperature: 采样温度。

        Returns:
            模型生成文本。

        Raises:
            VideoInputNotSupportedError: 服务商明确拒绝视频输入。
        """
        messages = build_video_url_messages(video_url, text_prompt)
        return await self._generate_video_text(
            messages,
            max_tokens=max_tokens, temperature=temperature,
            log_label="video_url",
        )
