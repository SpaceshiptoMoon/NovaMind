"""空间 config 显式 null 段兼容回归（2026-10 配置矩阵真测暴露）。

历史空间行（旧创建序列化未 exclude_none）的 config JSON 存显式 null 段
（"asr": null / "limits": null 等），而 dict.get(key, default) 的默认值只对
键缺失生效——读侧拿到 None 后下游属性访问直接 AttributeError，音频文档
对未配置 ASR 的新空间解析必崩（'NoneType' object has no attribute 'get'）。

三层防线各覆盖正反用例：
- 写侧：SpaceConfig.model_dump(exclude_none=True) 不再持久化 null 段；
- 模型读侧：KnowledgeSpace 各段 getter 对显式 null 返回空默认；
- 消费读侧：media_processing._space_asr_cfg 对 null/缺失/正常三态归一。
"""
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
from novamind.features.knowledge_space.schemas.space_schema import SpaceConfig
from novamind.features.knowledge_space.services.media_processing import _space_asr_cfg

pytestmark = pytest.mark.unit


# ---------- 写侧：新空间不再落 null 段 ----------

def test_space_config_dump_excludes_unset_sections():
    """只填 embedding 时，未配置段不得出现在持久化 dict 里（null 段源头）。"""
    cfg = SpaceConfig(embedding={"model": "m"})
    dumped = cfg.model_dump(exclude_none=True)
    assert dumped["embedding"]["model"] == "m"
    for section in ("asr", "llm", "vlm", "limits", "storage", "defaults", "ui"):
        assert section not in dumped, f"未配置段 {section} 不应被序列化"


def test_space_config_dump_keeps_explicit_values():
    """反例不误伤：显式配置的段与空集合默认值正常保留。"""
    cfg = SpaceConfig(asr={"model": "whisper-1"}, description="d", tags=["t"])
    dumped = cfg.model_dump(exclude_none=True)
    assert dumped["asr"] == {"model": "whisper-1"}
    assert dumped["description"] == "d"
    assert dumped["tags"] == ["t"]


# ---------- 模型读侧：存量 null 行不崩 ----------

def _space_with_raw_config(config: dict) -> KnowledgeSpace:
    """不经 API 序列化，直接构造携带历史 config 的模型实例（模拟存量行）。"""
    return KnowledgeSpace(name="s", config=config)


def test_space_getters_tolerate_explicit_null_sections():
    """config 各段为显式 null 时，getter 返回空默认而非 None。"""
    space = _space_with_raw_config({
        "asr": None, "llm": None, "vlm": None,
        "limits": None, "storage": None, "defaults": None,
        "embedding": {"model": "m", "dimension": 1024},
    })
    assert space.get_limits_config() == {}
    assert space.get_defaults_config() == {}
    assert space.get_storage_config() == {}
    assert space.get_description() == ""
    assert space.embedding_config == {"model": "m", "dimension": 1024}


def test_space_getters_normal_config_unaffected():
    """反例不误伤：正常配置段原样读出。"""
    space = _space_with_raw_config({
        "limits": {"max_file_size_mb": 50},
        "defaults": {"splitting": {"strategy": "fixed_size"}},
        "storage": {"quota_gb": 10},
        "description": "desc",
    })
    assert space.get_limits_config() == {"max_file_size_mb": 50}
    assert space.get_defaults_config()["splitting"]["strategy"] == "fixed_size"
    assert space.get_storage_config() == {"quota_gb": 10}
    assert space.get_description() == "desc"


# ---------- 消费读侧：ASR 配置节三态归一 ----------

def test_space_asr_cfg_null_becomes_empty():
    """显式 null（历史行）与键缺失同归 {}——音频管道崩溃点。"""
    assert _space_asr_cfg({"asr": None}) == {}
    assert _space_asr_cfg({}) == {}
    assert _space_asr_cfg(None) == {}


def test_space_asr_cfg_passthrough_configured():
    """反例不误伤：已配置的 ASR 节原样透传。"""
    assert _space_asr_cfg({"asr": {"model": "paraformer-v2"}}) == {"model": "paraformer-v2"}
