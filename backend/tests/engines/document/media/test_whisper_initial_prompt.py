"""whisper 解码引导 prompt（initial_prompt）三态解析回归测试。

背景：faster-whisper 的 zh 不分简繁，解码文字体系强烈跟随 initial_prompt——
本地转写中文输出繁体是用户可感知缺陷（audio_utils 无 initial_prompt、全链路
无简繁转换）。修复：注入简体引导句抑制繁体输出，三态语义：

1. 配置 None（默认）+ language="zh" → 注入简体引导句；
2. 配置 None + language=None（auto）→ 不注入（语言未知，中文 prompt 会污染
   其他语种）；
3. 配置非空字符串 → 完全覆盖（任何语言）；配置 "" → 显式禁用。

约束：解析后的实际注入值必须进 ASR 快照指纹（配置/规则/language 任一变化
→ 快照失效 → RETRY 重转写，不复用繁体旧产物）。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.audio import (
    DEFAULT_ZH_INITIAL_PROMPT,
    resolve_initial_prompt,
)

pytestmark = pytest.mark.unit


def _cfg(prompt) -> SimpleNamespace:
    return SimpleNamespace(local_whisper_initial_prompt=prompt)


def test_default_zh_language_injects_prompt():
    """配置未设 + 显式 zh → 注入简体引导句（抑制繁体输出主手段）。"""
    assert resolve_initial_prompt(_cfg(None), "zh") == DEFAULT_ZH_INITIAL_PROMPT


def test_default_auto_language_no_injection():
    """配置未设 + auto 检测 → 不注入（避免中文 prompt 污染其他语种）。"""
    assert resolve_initial_prompt(_cfg(None), None) is None
    assert resolve_initial_prompt(_cfg(None), "en") is None


def test_explicit_config_overrides_default():
    """配置非空字符串 → 完全覆盖默认值（任何语言都注入）。"""
    assert resolve_initial_prompt(_cfg("请用简体中文输出。"), None) == "请用简体中文输出。"
    assert resolve_initial_prompt(_cfg("custom prompt"), "en") == "custom prompt"


def test_empty_string_explicitly_disables():
    """配置空字符串 → 显式禁用（zh 也不注入，回退上游默认行为）。"""
    assert resolve_initial_prompt(_cfg(""), "zh") is None


def test_none_audio_config_falls_back_to_language_rule():
    """audio_config 缺省（None）等价配置 None，按语言规则走。"""
    assert resolve_initial_prompt(None, "zh") == DEFAULT_ZH_INITIAL_PROMPT
    assert resolve_initial_prompt(None, None) is None


def test_initial_prompt_in_fingerprint_block():
    """指纹块必须含 initial_prompt 键（防快照复用繁体旧产物的硬约束）。"""
    from novamind.features.knowledge_space.services.media_processing import (
        _audio_asr_fingerprint_params,
    )

    params = _audio_asr_fingerprint_params(
        "local", "large-v3", SimpleNamespace(), [], initial_prompt="以下是普通话的句子。"
    )
    assert params["initial_prompt"] == "以下是普通话的句子。"
