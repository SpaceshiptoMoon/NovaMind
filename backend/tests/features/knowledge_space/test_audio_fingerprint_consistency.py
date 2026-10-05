"""音频解析快照指纹一致性回归（2026-10 表单-管道对齐审计修复）。

历史 bug：批次②给保存侧指纹加了 ``asr_clean`` 块，命中检查侧没加——两侧
指纹形状漂移，音频解析快照**永不命中**，RETRY 全量重跑 ASR（正是 P1#2
修掉的问题被批次②重新引入）。门禁：命中检查与保存侧的指纹构造必须共用
同一组构造函数（单一事实源），不得各自手拼 dict。
"""
import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

MEDIA_MODULE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "features"
    / "knowledge_space"
    / "services"
    / "media_processing.py"
)
PIPELINE_MODULE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "features"
    / "knowledge_space"
    / "services"
    / "pipeline_steps.py"
)


def _load_clean_fingerprint_fn():
    """从源码 AST 抽出 _audio_clean_fingerprint_params 单函数执行（避免拉起整个依赖图）。"""
    from typing import Any  # noqa: F401  # 函数签名注解的执行环境

    ns: dict = {"Any": Any}
    src = MEDIA_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_audio_clean_fingerprint_params":
            exec(compile(ast.Module([node], []), str(MEDIA_MODULE), "exec"), ns)
    return ns["_audio_clean_fingerprint_params"]


def test_clean_fingerprint_block_is_single_source_of_truth():
    """命中检查侧与保存侧都必须调用 _audio_clean_fingerprint_params 构造 asr_clean。

    两侧任一侧手拼 dict（键漂移）即指纹形状不一致 → 快照永不命中。
    """
    src = MEDIA_MODULE.read_text(encoding="utf-8")
    fn_pos = src.find("async def process_audio_document")
    fn_end = src.find("\nasync def ", fn_pos + 10)
    body = src[fn_pos:fn_end]
    calls = body.count('_audio_clean_fingerprint_params(')
    assert calls >= 2, (
        f"process_audio_document 内 _audio_clean_fingerprint_params 调用数 {calls} < 2："
        "命中检查侧与保存侧必须共用同一指纹构造（单一事实源）"
    )
    # 不允许任何一侧手拼 asr_clean 字面量（键漂移即两侧形状漂移）
    assert '"clean_enabled":' not in body, (
        "asr_clean 块存在手拼字面量：指纹形状漂移会令快照永不命中，"
        "必须经 _audio_clean_fingerprint_params 构造"
    )


def test_clean_fingerprint_params_semantics():
    """构造语义：开关取 bool、模型留空归一空串（与保存侧原实现等价）。"""
    fn = _load_clean_fingerprint_fn()
    assert fn({"clean_enabled": True, "clean_llm_model": "gpt"}) == {
        "clean_enabled": True,
        "clean_llm_model": "gpt",
    }
    assert fn({}) == {
        "clean_enabled": False,
        "clean_llm_model": "",
    }
    # clean_enabled 非零真值归一 True；模型 None 归一空串
    assert fn({"clean_enabled": 1, "clean_llm_model": None}) == {
        "clean_enabled": True,
        "clean_llm_model": "",
    }


def test_pause_topic_split_fingerprint_includes_effective_gap():
    """切分指纹的 split_mode 必须并入 pause_topic 的有效停顿阈值。

    pause_gap_seconds 决定切分边界却不在顶层 splitting_config——不进指纹则
    改阈值后 RETRY 命中旧分块（参数静默失效）。
    """
    src = PIPELINE_MODULE.read_text(encoding="utf-8")
    fn_pos = src.find("async def run_post_parse_tail")
    fn_end = src.find("\nasync def ", fn_pos + 10)
    body = src[fn_pos:fn_end]
    assert "pause_topic" in body, (
        "run_post_parse_tail 切分指纹未并入 pause_topic 有效阈值："
        "改 pause_gap_seconds 后切分快照不会失效"
    )
    assert "pause_gap_seconds" in body, "切分指纹块未读取 pause_gap_seconds"
