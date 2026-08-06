"""引擎自用配置 dataclass。

存放引擎运行所需、不依赖 ``novamind.setting`` 的纯数据配置。宿主装配时从
``setting`` 构造并注入引擎，切断引擎→setting 导入边。dataclass 不持有 ORM/客户端/session。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class AudioConfig:
    """音频处理引擎配置。

    宿主从 `setting.yaml_config.ParsingConfig.local_whisper_model_dir` 构造注入。
    引擎侧 ``audio_utils`` 据此解析本地 faster-whisper 模型目录，不再 import
    `novamind.setting`。

    解析优先级（见 ``audio_utils._resolve_local_whisper_model_dir``）：
      1. ``local_whisper_model_dir``（本字段，对应 YAML
         ``knowledge_base.parsing.local_whisper_model_dir``）
      2. 环境变量 ``NOVAMIND_LOCAL_WHISPER_MODEL_DIR``
      3. 默认 ``~/.cache/faster-whisper/tiny``
    """

    local_whisper_model_dir: Optional[str] = None


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