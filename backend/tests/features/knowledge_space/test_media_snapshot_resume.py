"""媒体快照 resume 接线 + parse 快照 payload 增强（2026-09 链路审计 P1#2/P1#3 回归）。

P1#2：音视频 parse 快照此前只写不读——load_parse_snapshot 唯一调用点在文本
分支，restore_time_alignment 死代码是铁证。RETRY 时 VLM/ASR 全量白烧。
门禁：音/视频入口必须有快照命中检查；快照还原必须经 restore_time_alignment /
restore_frame_paths（int 键还原），不得传 raw dict（JSON 序列化后 int 键变 str，
时间线全 miss）。

P1#3：文本切分发生在 parse 阶段内而 parse 指纹不含切分配置——改切分配置+RETRY
静默复用旧分块。修复：快照记录 splitting_config，resume 比对漂移则放弃旧分块
改走 full_text 重切（贵解析仍复用）。

附带：payload_fingerprint_matches 防双 worker 交错写同名对象后指针/内容错配。
"""
import ast
from pathlib import Path

import pytest

from novamind.features.knowledge_space.services.pipeline_snapshots import (
    build_parse_snapshot_payload,
    canonical_json,
    payload_fingerprint_matches,
    restore_frame_paths,
    restore_time_alignment,
)

SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
MEDIA_MODULE = SRC_ROOT / "features" / "knowledge_space" / "services" / "media_processing.py"
PIPELINE_MODULE = SRC_ROOT / "features" / "knowledge_space" / "services" / "document_pipeline.py"


# ========== P1#2 门禁：媒体分支 resume 接线 ==========


def test_video_branch_has_snapshot_resume():
    """视频入口：抽帧前必须有快照命中检查 + resume 尾。"""
    src = MEDIA_MODULE.read_text(encoding="utf-8")
    fn_pos = src.find("async def process_video_document")
    fn_end = src.find("\nasync def ", fn_pos + 10)
    body = src[fn_pos:fn_end]
    assert "load_parse_snapshot" in body, "视频分支未接 load_parse_snapshot（快照只写不读）"
    assert "snapshot_fingerprint" in body, "视频分支未做指纹命中检查"
    assert "_video_resume_tail" in body, "视频分支缺少 resume 尾接线"


def test_audio_branch_has_snapshot_resume():
    """音频入口：ASR 前必须有快照命中检查 + resume 尾。"""
    src = MEDIA_MODULE.read_text(encoding="utf-8")
    fn_pos = src.find("async def process_audio_document")
    fn_end = src.find("\nasync def ", fn_pos + 10)
    body = src[fn_pos:fn_end]
    assert "load_parse_snapshot" in body, "音频分支未接 load_parse_snapshot（快照只写不读）"
    assert "snapshot_fingerprint" in body, "音频分支未做指纹命中检查"
    assert "_audio_resume_tail" in body, "音频分支缺少 resume 尾接线"


def test_resume_tails_restore_time_alignment():
    """resume 尾必须经 restore_time_alignment 还原（raw dict 的 int 键经 JSON 变 str）。"""
    src = MEDIA_MODULE.read_text(encoding="utf-8")
    for fn_name in ("_video_resume_tail", "_audio_resume_tail"):
        fn_pos = src.find(f"async def {fn_name}")
        fn_end = src.find("\nasync def ", fn_pos + 10)
        body = src[fn_pos:fn_end]
        assert "restore_time_alignment" in body, f"{fn_name} 未还原时间线 int 键"
    # 视频 resume 尾还要还原帧路径
    fn_pos = src.find("async def _video_resume_tail")
    fn_end = src.find("\nasync def ", fn_pos + 10)
    assert "restore_frame_paths" in src[fn_pos:fn_end], "视频 resume 尾未还原帧路径"


# ========== P1#3 splitting_config 漂移检测 ==========


def test_text_resume_compares_splitting_config():
    """文本 resume 分支必须比对快照 splitting_config 与当前配置。"""
    src = PIPELINE_MODULE.read_text(encoding="utf-8")
    assert "split_config_drifted" in src, "文本 resume 未做切分配置漂移检测"
    assert "splitting_config=splitting_config" in src or "splitting_config" in src
    # 快照保存侧必须带 splitting_config
    assert "splitting_config=splitting_config or {}" in src.replace(" ", "") or (
        "splitting_config=splitting_config or {}" in src
    ), "快照保存未记录 splitting_config"


def test_build_payload_records_splitting_config():
    """build_parse_snapshot_payload 支持 splitting_config 入 payload。"""
    payload = build_parse_snapshot_payload(
        parse_fingerprint="fp",
        full_text="text",
        splitting_config={"strategy": "recursive", "chunk_size": 500},
    )
    assert payload["splitting_config"] == {"strategy": "recursive", "chunk_size": 500}
    # 不传时不写键（兼容旧调用方与历史快照）
    payload2 = build_parse_snapshot_payload(parse_fingerprint="fp", full_text="text")
    assert "splitting_config" not in payload2


# ========== payload 指纹校验 + 还原函数语义 ==========


def test_payload_fingerprint_matches():
    assert payload_fingerprint_matches({"parse_fingerprint": "a"}, "parse_fingerprint", "a")
    assert not payload_fingerprint_matches({"parse_fingerprint": "b"}, "parse_fingerprint", "a")
    assert not payload_fingerprint_matches({}, "parse_fingerprint", "a")
    # expected 为空（未启用比对）时放行——与历史行为一致
    assert payload_fingerprint_matches({}, "parse_fingerprint", "")


def test_restore_time_alignment_restores_int_keys():
    """JSON 序列化把 timeline_map int 键变 str——还原后必须能按 int 查。"""
    raw = {
        "timeline_map": {"3": [1.0, 2.0], "7": [2.0, None]},
        "is_video": True,
        "frame_groups": {"3": [3, 4, 5]},
    }
    restored = restore_time_alignment(raw)
    assert restored["timeline_map"][3] == [1.0, 2.0]
    assert restored["timeline_map"][7] == [2.0, None]
    assert restored["is_video"] is True
    assert restored["frame_groups"][3] == [3, 4, 5]
    assert restore_time_alignment(None) is None
    assert restore_time_alignment({}) is None


def test_restore_frame_paths_restores_int_keys():
    restored = restore_frame_paths({"0": "a.jpg", "12": "b.jpg", "x": "skip.jpg"})
    assert restored == {0: "a.jpg", 12: "b.jpg"}


def test_canonical_json_order_insensitive():
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})
    assert canonical_json({"a": [1, {"c": 2, "b": 3}]}) == canonical_json({'a': [1, {"b": 3, "c": 2}]})
