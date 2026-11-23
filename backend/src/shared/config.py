"""
引擎自用配置 dataclass，存放引擎运行所需的纯数据配置（AudioConfig、搜索配置等）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AudioConfig:
    """音频处理引擎配置。

    宿主从 `setting.yaml_config.ParsingConfig` 构造注入。引擎侧 ``audio_utils``
    据此解析本地 faster-whisper 模型目录与推理参数，不再 import
    `novamind.setting`。

    模型解析优先级（见 ``audio_utils._resolve_local_whisper_model_dir``）：
      1. ``local_whisper_model_dir``（显式目录，对应 YAML
         ``knowledge_base.parsing.local_whisper_model_dir``——存量部署兼容通道）
      2. ``local_whisper_model``（档位名，对应 YAML
         ``knowledge_base.parsing.local_whisper_model``）→
         ``backend/.cache/faster-whisper/{档位}``
         档位名缺省时按推理设备选默认档：有 CUDA → ``DEFAULT_LOCAL_WHISPER_MODEL``
         （生产 large-v3），仅 CPU → ``DEFAULT_LOCAL_WHISPER_CPU_MODEL``（small，
         无 GPU 自动降级，见 ``audio_utils.resolve_local_whisper_model_slug``）
    """

    local_whisper_model_dir: str | None = None
    # 本地 faster-whisper 模型档位（tiny/base/small/medium/large-v2/large-v3）。
    # None 时按推理设备自动选默认档（有 CUDA → large-v3，仅 CPU → small）；
    # 显式配置的档位不随设备改写。
    # 仅在 local_whisper_model_dir 为空时生效（显式目录优先）。
    local_whisper_model: str | None = None
    # 本地 faster-whisper 转写使用的 CPU 线程数。None 时按物理核数自动取保守值
    # （见 audio_utils._resolve_cpu_threads），保留至少一个物理核给 asyncio
    # 事件循环。ASR 推理在独立子进程跑（ProcessPoolExecutor），OS 级 CPU/GIL
    # 隔离；cpu_threads 仅约束子进程 CPU。GPU 推理（device=cuda）时此值无效果。
    local_whisper_cpu_threads: int | None = None
    # 推理设备：auto（CTranslate2 自动探测 CUDA，生产 GPU 服务器自动用卡）/
    # cpu / cuda。None 时 auto。
    local_whisper_device: str | None = None
    # 量化类型：auto（CPU→int8 / CUDA→int8_float16，由引擎按设备选择）/ int8 / int8_float16 / float16 /
    # float32。None 时 auto。
    local_whisper_compute_type: str | None = None
    # 束搜索宽度，默认 5（Whisper 官方默认）。加大精度略升、速度线性下降。
    local_whisper_beam_size: int | None = None
    # silero VAD 前置过滤（切静音/噪声段，省算力且抑制幻觉），默认开。
    local_whisper_vad_enabled: bool = True
    # 段级声学能量下限（RMS dBFS）。低于该值的段视为非语音（底噪/静音残留），
    # 仅当段文本 ≤15 字符时丢弃（长短语可能是真实轻声内容，能量判据只做交叉
    # 验证）。None = 禁用该过滤。正常语音约 -30~-20 dBFS，底噪约 -45~-40，
    # 默认 -40 取两者分界；阈值越低越宽松。调 None 关闭校验。
    local_whisper_min_speech_dbfs: float | None = -40.0
    # 转写结果为空且首跑语言置信度低时的重试语言。None = 不重试（默认，行为
    # 与上游 faster-whisper 一致）；典型配置 "zh"——tiny/small 档对短中文音频
    # 常误判语言导致空结果，按此语言重试一次。
    local_whisper_empty_result_retry_language: str | None = None
    # 解码引导 prompt（faster-whisper initial_prompt，每个解码窗口重放）。None =
    # 注入引擎默认值（见 audio_utils._resolve_initial_prompt：zh 显式指定时注入
    # 简体中文引导句，抑制繁体输出；auto 检测不注入以免污染其他语种）；配置为
    # 非空字符串时完全覆盖默认值；空字符串"" 显式表示不注入。
    local_whisper_initial_prompt: str | None = None


# ==================== 外部搜索（联网搜索）====================


@dataclass
class DuckDuckGoSearchConfig:
    """DuckDuckGo 搜索引擎配置（无需 API Key）。

    宿主从 `setting.yaml_config.DuckDuckGoConfig` 构造注入；引擎侧搜索服务
    不再 import `novamind.setting`。
    """

    max_results: int = 10
    timeout: int = 15


@dataclass
class SerpApiSearchConfig:
    """SerpAPI 搜索引擎配置（Google 结果 API）。

    宿主从 `setting.yaml_config.SerpAPIConfig` 构造注入。
    """

    api_key: str = ""
    max_results: int = 10
    timeout: int = 30
    engine: str = "google"


@dataclass
class TavilySearchConfig:
    """Tavily 搜索引擎配置（AI 优化搜索 API）。

    宿主从 `setting.yaml_config.TavilyConfig` 构造注入。
    """

    api_key: str = ""
    max_results: int = 10
    search_depth: str = "basic"
    timeout: int = 30


__all__ = [
    "AudioConfig",
    "DuckDuckGoSearchConfig",
    "SerpApiSearchConfig",
    "TavilySearchConfig",
]