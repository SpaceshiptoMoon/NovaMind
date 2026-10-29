"""媒体模态解析配置节读取回归测试。

历史 bug：kb 配置经 PATCH 局部更新后序列化保留 "audio"/"video": null 显式
null 键，``dict.get(key, {})`` 的默认值只对键缺失生效、对显式 null 不生效，
未配置音视频的知识库上传音频/视频时在 ``audio_config.get("asr_model")`` 上
AttributeError（端到端实测暴露；与 _space_asr_cfg 的 "asr": null 先例同根因，
该先例修复未同步到媒体解析配置取用处）。
"""
import pytest
from novamind.features.knowledge_space.services.media_processing import (
    _parsing_media_section,
)

pytestmark = pytest.mark.unit


def test_explicit_null_section_normalized_to_empty_dict():
    """反例（bug 场景）：显式 null 配置节必须归一为空 dict 而非 None。"""
    cfg = {"parsing": {"audio": None, "video": None}}
    assert _parsing_media_section(cfg, "audio") == {}
    assert _parsing_media_section(cfg, "video") == {}


def test_missing_keys_and_none_pipeline_config_are_safe():
    """键缺失与 pipeline_config 为 None 均安全返回空 dict。"""
    assert _parsing_media_section({}, "audio") == {}
    assert _parsing_media_section({"parsing": {}}, "video") == {}
    assert _parsing_media_section(None, "audio") == {}


def test_configured_section_passthrough():
    """正例：正常配置节原样透传，供 asr_model/vlm_model 等字段读取。"""
    cfg = {"parsing": {"audio": {"asr_model": "faster-whisper-tiny"}}}
    assert _parsing_media_section(cfg, "audio") == {"asr_model": "faster-whisper-tiny"}
