"""AudioParsingConfig.asr_model 默认值陷阱修复回归。

历史 bug：schema 默认值 "whisper-1" 与运行时空值默认（本地 faster-whisper）
语义不一致——KB 配置里存了 audio 子节但用户未显式选模型时，会拿 "whisper-1"
去查不存在的云端凭证并抛 PermanentProcessingError。现统一为 None = 本地默认。
"""

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    AudioParsingConfig,
    VideoParsingConfig,
)

pytestmark = pytest.mark.unit


def test_audio_asr_model_default_is_none_not_whisper_cloud():
    """默认 None = 本地默认档（修复 "whisper-1" 陷阱）。"""
    cfg = AudioParsingConfig()
    assert cfg.asr_model is None


def test_audio_hotwords_default_and_validation():
    """hotwords 默认 None；接受词表；超 100 条拒绝。"""
    assert AudioParsingConfig().hotwords is None
    cfg = AudioParsingConfig(hotwords=["NovaMind", "RAG"])
    assert cfg.hotwords == ["NovaMind", "RAG"]
    with pytest.raises(Exception):
        AudioParsingConfig(hotwords=[f"w{i}" for i in range(101)])


def test_video_hotwords_field_exists():
    """视频音轨配置同样支持 hotwords（语义与音频一致）。"""
    cfg = VideoParsingConfig()
    assert cfg.hotwords is None
    assert VideoParsingConfig(hotwords=["术语"]).hotwords == ["术语"]
