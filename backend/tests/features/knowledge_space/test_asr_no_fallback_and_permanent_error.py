"""ASR no-fallback 收敛 + 永久错误不重试 + cancel TTL（审计 P1#8/P2 回归）。

P1#8：音频路径的「whisper-1 硬编码 → 取第一个 ASR 配置 → local 失败回退云端」
三级静默兜底违反「没选不兜底」决策（图片/视频路径都是留空即抛错）。修复：
asr_model 未显式配置即抛 PermanentProcessingError；凭证按模型名精确匹配，
找不到即抛错；local 失败不再自动回退云端（烧用户未授权费用且不可追踪）。

P2 永久错误：PermanentProcessingError 子类化的确定性失败（配置缺失/文件损坏/
模型输出无效）在 worker 侧直接终判，不再 raise Retry 白烧 N 次。

P2 TTL：取消标记 TTL 从 1h 提到 4h（≥ job_timeout 7200s 的一半以上），
防长任务处理途中标记过期、取消静默失效。
"""
import ast
from pathlib import Path

import pytest

from novamind.features.knowledge_space.exceptions import (
    DocumentProcessingError,
    PermanentProcessingError,
)

SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
MEDIA_MODULE = SRC_ROOT / "features" / "knowledge_space" / "services" / "media_processing.py"
TASKS_MODULE = SRC_ROOT / "features" / "knowledge_space" / "tasks" / "document_tasks.py"
TRACKER_MODULE = SRC_ROOT / "shared" / "mq" / "task_tracker.py"


# ========== P1#8 ASR no-fallback 门禁 ==========


def test_audio_path_has_no_whisper1_hardcode():
    """音频路径不得硬编码 whisper-1 默认模型。"""
    src = MEDIA_MODULE.read_text(encoding="utf-8")
    assert '"whisper-1"' not in src and "'whisper-1'" not in src, (
        "音频路径仍硬编码 whisper-1 默认模型（no-fallback 违规）"
    )


def test_audio_path_has_no_first_config_fallback():
    """音频路径不得「取该用户第一个 ASR 配置」兜底（asr_configs[0]）。"""
    src = MEDIA_MODULE.read_text(encoding="utf-8")
    assert "asr_configs[0]" not in src, (
        "音频路径仍存在「取第一个 ASR 配置」兜底——用户选了 A 模型可能被静默换成 B"
    )
    assert "_find_cloud_asr_credentials" not in src, (
        "音频路径仍存在云端凭证回退查找（local 失败自动烧云端费用）"
    )


def test_audio_unconfigured_model_defaults_to_local(monkeypatch):
    """未配置 asr_model 时默认本地 faster-whisper-tiny（用户裁定 2026-09-23）。

    本地模型不查凭证、协议恒为 local（部署期预装模型，本地推理免费无未授权
    费用风险）；显式配云端模型但凭证缺失仍抛错（test_…_below）。
    这里验证：走到转写时 protocol=local、模型名为默认值。
    """
    import asyncio
    from types import SimpleNamespace

    import novamind.features.knowledge_space.services.media_processing as mp

    monkeypatch.setattr(
        "novamind.setting.yaml_config.get_config",
        lambda: SimpleNamespace(
            knowledge_base=SimpleNamespace(
                parsing=SimpleNamespace(
                    local_whisper_model_dir="", local_whisper_cpu_threads=1,
                )
            )
        ),
    )

    async def _fake_load_ctx(session, document, task=None):
        return SimpleNamespace(
            pipeline_config={"parsing": {"audio": {}}},  # 未配 asr_model → 默认本地
            space=SimpleNamespace(config={}),
        )

    monkeypatch.setattr(mp, "load_pipeline_context", _fake_load_ctx)

    async def _no_cancel(doc_id):
        return None

    monkeypatch.setattr(mp, "check_document_cancelled", _no_cancel)

    # 记录实际路由到 _run_asr 的协议：local 协议走 transcribe_audio_local
    captured: dict = {}

    async def _fake_local(*a, **kw):
        captured["called"] = "local"
        from novamind.engines.document.media.audio import AudioFileInvalidError
        raise AudioFileInvalidError("（测试探针）停止在转写入口")

    monkeypatch.setattr(mp, "transcribe_audio_local", _fake_local)

    # 凭证查找不应被触达（本地模型不查凭证）
    async def _creds_should_not_be_called(*a, **kw):
        raise AssertionError("本地默认模型不应查 ASR 凭证")

    def _noop(*a, **k):
        pass

    document = SimpleNamespace(id=1, space_id=1, kb_id=1, uploader_id=1,
                               filename="a.mp3", file_type="mp3")
    mcs = SimpleNamespace(get_credentials_by_model=_creds_should_not_be_called)

    with pytest.raises(Exception, match="测试探针"):
        asyncio.run(mp.process_audio_document(
            document=document, file_content=b"x" * 2048, session=None,
            logger=SimpleNamespace(info=_noop, warning=_noop, error=_noop, debug=_noop),
            task=None, model_config_port=mcs,
        ))
    assert captured.get("called") == "local", "未配置时未走本地 ASR 协议"


def test_cloud_model_missing_credentials_still_raises_permanent(monkeypatch):
    """显式配云端模型但凭证缺失仍抛 PermanentProcessingError（不串用其它配置）。"""
    import asyncio
    from types import SimpleNamespace

    import novamind.features.knowledge_space.services.media_processing as mp

    monkeypatch.setattr(
        "novamind.setting.yaml_config.get_config",
        lambda: SimpleNamespace(
            knowledge_base=SimpleNamespace(
                parsing=SimpleNamespace(
                    local_whisper_model_dir="", local_whisper_cpu_threads=1,
                )
            )
        ),
    )

    async def _fake_load_ctx(session, document, task=None):
        return SimpleNamespace(
            pipeline_config={"parsing": {"audio": {"asr_model": "whisper-1-cloud"}}},
            space=SimpleNamespace(config={}),
        )

    monkeypatch.setattr(mp, "load_pipeline_context", _fake_load_ctx)

    async def _no_cancel(doc_id):
        return None

    monkeypatch.setattr(mp, "check_document_cancelled", _no_cancel)

    async def _missing_creds(uploader_id, model_type, model):
        return None

    def _noop(*a, **k):
        pass

    document = SimpleNamespace(id=1, space_id=1, kb_id=1, uploader_id=1,
                               filename="a.mp3", file_type="mp3")
    mcs = SimpleNamespace(get_credentials_by_model=_missing_creds)

    with pytest.raises(PermanentProcessingError, match="凭证"):
        asyncio.run(mp.process_audio_document(
            document=document, file_content=b"x" * 2048, session=None,
            logger=SimpleNamespace(info=_noop, warning=_noop, error=_noop, debug=_noop),
            task=None, model_config_port=mcs,
        ))


# ========== P2 永久错误不重试 ==========


def test_worker_branches_permanent_error_before_retry():
    """worker 异常处理必须在 Retry 判定前分流 PermanentProcessingError。"""
    src = TASKS_MODULE.read_text(encoding="utf-8")
    assert "PermanentProcessingError" in src, "worker 未分流永久性错误"
    # 分流点必须在 job_try 判定之前
    perm_pos = src.find("isinstance(e, PermanentProcessingError)")
    retry_pos = src.find("if job_try >= max_tries")
    assert 0 < perm_pos < retry_pos, "永久错误分流未置于重试判定之前"


def test_permanent_error_is_subclass_of_document_processing_error():
    """PermanentProcessingError 是 DocumentProcessingError 子类（API 异常处理兼容）。"""
    assert issubclass(PermanentProcessingError, DocumentProcessingError)


# ========== P2 cancel TTL ==========


def test_cancel_key_ttl_exceeds_half_job_timeout():
    """取消标记 TTL 必须 > job_timeout（7200s）的一半，防长任务取消静默失效。"""
    import novamind.shared.mq.task_tracker as tt

    assert tt.CANCEL_KEY_TTL >= 3600 * 2, (
        f"CANCEL_KEY_TTL={tt.CANCEL_KEY_TTL}s 过短，长任务处理途中标记会过期"
    )
