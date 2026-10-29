"""图片解析链路一致性回归测试（2026-10 图片配置审计修复）。

三个真 bug：
1. 图片解析快照「只写不读」：``_process_image_document_static`` 算指纹、存快照，
   但从不做命中检查 → RETRY 永远重跑 VLM/OCR（与音频 asr_clean 形状漂移同型的
   P1#2 缺口，但根因不同：音频是两侧指纹形状漂移，图片是根本没有命中侧）。
2. ``vlm_model`` 扁平键跨模态覆盖：``build_runtime_parsing_config`` 把
   ``image.vlm_model`` 与 ``video.vlm_model`` 共写同一扁平 ``result["vlm_model"]``，
   video 后写覆盖 image——KB 同时配了图片 VLM 与视频 VLM 时，图片解析静默串用
   视频的 VLM（视频路径 B10 已修同款问题，图片路径漏了）。
3. 前端 placeholder「留空时继承空间默认模型」与后端「留空即抛错」相悖（不兜底
   原则），前端文案修正为「必选：留空解析时将报错要求显式选择」。

门禁：命中检查与保存侧共用同一次指纹计算；消费侧与指纹侧同读嵌套 image.vlm_model。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

PIPELINE_MODULE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "features"
    / "knowledge_space"
    / "services"
    / "document_pipeline.py"
)
FRONTEND_VUE = (
    Path(__file__).resolve().parents[4]
    / "frontend"
    / "src"
    / "components"
    / "knowledge"
    / "KbMultimodalParsingSection.vue"
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Bug 1：图片解析快照必须有命中侧（与保存侧共用同一次指纹计算）
# ---------------------------------------------------------------------------


def _extract_process_image_body() -> str:
    src = PIPELINE_MODULE.read_text(encoding="utf-8")
    fn_pos = src.find("async def _process_image_document_static")
    fn_end = src.find("\nasync def ", fn_pos + 10)
    return src[fn_pos:fn_end]


def test_image_parse_snapshot_has_hit_check():
    """``_process_image_document_static`` 内必须调用 load_parse_snapshot 做命中检查。

    历史缺口：只有 save_parse_snapshot 没有命中侧 → 快照只写不读，RETRY 永远
    重跑 VLM/OCR。命中侧缺失或负载指纹校验缺失均判失败。
    """
    body = _extract_process_image_body()
    assert "load_parse_snapshot" in body, (
        "图片解析路径没有快照命中检查：快照只写不读，RETRY 永远重跑 VLM/OCR"
    )
    assert "payload_fingerprint_matches" in body, (
        "快照命中判定缺少 payload 内嵌指纹校验（防双 worker 交错写错配）"
    )
    # 命中检查与保存必须共用同一次指纹计算：函数内 compute_parse_fingerprint
    # 只允许出现一次（在命中检查之前），保存侧直接复用其结果
    assert body.count("compute_parse_fingerprint") == 1, (
        "指纹计算不满足单一事实源：命中检查与保存侧必须共用同一次 compute_parse_fingerprint"
    )
    # 保存侧必须复用命中侧的指纹变量，不允许保存前重算
    save_pos = body.find("save_parse_snapshot")
    assert save_pos > 0, "图片解析路径缺少快照保存"
    between = body[body.find("compute_parse_fingerprint"):save_pos]
    assert "load_parse_snapshot" in between, (
        "快照保存不在命中检查之后：结构异常，疑似保存侧与命中侧分离计算"
    )


def test_image_parse_snapshot_skips_expensive_call_on_hit():
    """快照命中时必须跳过 VLM/OCR 调用（resumed 短路），不允许命中后又调用。"""
    body = _extract_process_image_body()
    resumed_pos = body.find("resumed = bool(resumed_description)")
    assert resumed_pos > 0, "缺少快照命中短路标志"
    resumed_branch_end = body.find("elif image_strategy", resumed_pos)
    resumed_branch = body[resumed_pos:resumed_branch_end]
    assert "if resumed:" in resumed_branch, "快照命中分支缺失（应直接 pass 跳过昂贵调用）"


# ---------------------------------------------------------------------------
# Bug 2：消费侧与指纹侧同读嵌套 image.vlm_model（不读被 video 覆盖的扁平键）
# ---------------------------------------------------------------------------


def test_image_vlm_model_reads_nested_config_not_flat_key():
    """消费侧（VLM 路径）与指纹侧都必须读嵌套 image.vlm_model。

    扁平 result["vlm_model"] 被 build_runtime_parsing_config 的 video 段后写
    覆盖——图片文档解析串用视频 VLM（跨模态污染）。视频路径 B10 同款修复先例。
    """
    body = _extract_process_image_body()
    flat_reads = body.count('parsing_config.get("vlm_model"')
    flat_reads += body.count("parsing_config.get('vlm_model'")
    assert flat_reads == 0, (
        "图片解析路径仍在读扁平 parsing_config['vlm_model']："
        "该键被 video.vlm_model 后写覆盖，图片会串用视频的 VLM（跨模态污染）。"
        "必须读嵌套 parsing.image.vlm_model（与视频 B10 修复同款）"
    )
    assert 'image_nested_cfg.get("vlm_model")' in body, (
        "消费侧未读嵌套 image.vlm_model"
    )
    # 指纹侧与消费侧必须同源：指纹注入的模型名（主+备）与 VLM 调用用的是同一变量
    assert 'f"image:{image_strategy}:{image_vlm_model}:{image_vlm_fallback_model or \'\'}"' in body, (
        "指纹注入的 VLM 模型与消费侧不同源（指纹侧读扁平键会把指纹带偏）"
    )


# ---------------------------------------------------------------------------
# Bug 2 的根因侧：build_runtime_parsing_config 扁平键共写行为（存量契约，只锁定
# 现状防回归，不修复——改键名会导致全部存量解析快照指纹漂移、大规模重解析）
# ---------------------------------------------------------------------------


def test_flat_vlm_model_key_still_written_by_both_sections():
    """扁平 vlm_model 键共写现状锁定：image 写、video 覆盖。

    这是已知的历史契约（视频路径已绕开它读嵌套键，图片路径本修复后同样绕开）。
    若未来有人改动该行为（例如删掉 video 段的写入），此测试会失败提醒同步检查
    全部媒体路径的读取方。
    """
    src = PIPELINE_MODULE.parent.parent.joinpath(
        "schemas", "knowledge_base_schema.py"
    ).read_text(encoding="utf-8")
    fn_pos = src.find("def build_runtime_parsing_config")
    fn_end = src.find("\ndef ", fn_pos + 10)
    body = src[fn_pos:fn_end]
    assert 'result["vlm_model"] = parsed.image.vlm_model' in body, (
        "build_runtime_parsing_config 的 image 段扁平 vlm_model 写入行为变了，"
        "检查媒体路径是否仍安全绕开扁平键"
    )
    assert 'result["vlm_model"] = parsed.video.vlm_model' in body, (
        "build_runtime_parsing_config 的 video 段扁平 vlm_model 写入行为变了，"
        "检查媒体路径是否仍安全绕开扁平键"
    )


# ---------------------------------------------------------------------------
# Bug 3：前端 placeholder 与后端不兜底行为一致
# ---------------------------------------------------------------------------


def test_frontend_image_vlm_placeholder_matches_no_fallback_semantics():
    """图片 VLM select 的 placeholder 不得声称「留空时继承空间默认模型」。

    后端行为：留空即抛 DocumentProcessingError（不兜底原则，P1-3 修复）。
    前端若声称有默认回退，用户留空保存后解析必然失败，且错误信息自相矛盾。
    """
    content = FRONTEND_VUE.read_text(encoding="utf-8")
    assert "留空时继承空间默认模型" not in content, (
        "图片 VLM placeholder 仍声称「留空时继承空间默认模型」："
        "后端留空即抛错不兜底，前端文案自相矛盾，会误导用户"
    )
    assert "必选：留空解析时将报错要求显式选择" in content, (
        "图片 VLM placeholder 未更新为不兜底语义"
    )


# ---------------------------------------------------------------------------
# 功能级：快照命中端到端（不走真 VLM/OCR，验证复用与跳过）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_parse_snapshot_hit_end_to_end(monkeypatch):
    """快照命中端到端：重算指纹与 DB 指针一致 + payload 内嵌指纹一致 → 复用文本、
    VLM/OCR 均不被调用；保存侧也不应重复保存。"""
    from novamind.features.knowledge_space.services import document_pipeline, pipeline_steps
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        build_parse_snapshot_payload,
        canonical_json,
    )

    doc = SimpleNamespace(
        id=91,
        space_id=1,
        kb_id=1,
        file_hash="hh",
        file_type="png",
        filename="a.png",
        storage={"minio_object_name": "obj", "pipeline_snapshots": {
            "parse_fingerprint": "FP",
            "parse_meta_object": "snapshots/parse_meta.json",
        }},
        uploader_id=1,
    )

    # 固定指纹函数输出，让「重算指纹 == DB 指针」成立
    monkeypatch.setattr(
        document_pipeline, "build_runtime_parsing_config",
        lambda parsing, ft: {"image_strategy": "vlm"},
    )
    import novamind.features.knowledge_space.services.pipeline_snapshots as snap_mod

    monkeypatch.setattr(snap_mod, "compute_parse_fingerprint", lambda d, c: "FP")

    snap_payload = build_parse_snapshot_payload(
        parse_fingerprint="FP",
        full_text="快照描述文本",
        parse_metadata={"strategy": "vlm"},
    )
    assert canonical_json(snap_payload)  # payload 构造健全性

    class _FakeMinio:
        async def upload_file(self, *a, **k): ...
        async def download_file(self, *a, **k):
            import json as _json
            return _json.dumps(snap_payload, ensure_ascii=False).encode("utf-8")

    # 函数内 import 的是真实 ClientFactory 类，必须 patch 类上的静态方法
    # （此前只定义了 _FakeCF 未接线，测试环境连不上 MinIO → 指纹计算被吞 →
    # 无快照命中 → 误入 VLM 路径，端到端测试假红根因）。
    import novamind.shared.storage.client_factory as cf_mod

    async def _fake_get_minio():
        return _FakeMinio()

    monkeypatch.setattr(cf_mod.ClientFactory, "get_minio_client", staticmethod(_fake_get_minio))

    # document_pipeline 内部是函数内 import pipeline_snapshots，patch 模块属性即可生效
    async def _fake_load_snap(d, m, lang):
        return snap_payload

    monkeypatch.setattr(snap_mod, "load_parse_snapshot", _fake_load_snap)
    monkeypatch.setattr(snap_mod, "save_parse_snapshot", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("快照命中时不应再保存快照")
    ))
    # _download_json 失败时 fail-open，这里直接给 load 成功，无需 _FakeMinio.download_file 生效

    ctx = pipeline_steps.PipelineContext(
        space=SimpleNamespace(owner_id=1),
        kb=None,
        pipeline_config={
            "parsing": {"image": {"strategy": "vlm", "vlm_model": "img-vlm"}},
            "splitting": {},
        },
        embedding_config={"model": "emb", "dimension": 8},
    )

    async def _fake_load_ctx(session, document, task):
        return ctx

    async def _no_cancel(doc_id):
        return None

    monkeypatch.setattr(document_pipeline, "load_pipeline_context", _fake_load_ctx)
    monkeypatch.setattr(document_pipeline, "check_document_cancelled", _no_cancel)

    # persist/tail 全部 mock：本测试只看解析阶段行为
    async def _fake_persist(*a, **k):
        return None

    monkeypatch.setattr(document_pipeline, "persist_parsed_text", _fake_persist)

    tail_called = {"n": 0}

    async def _fake_tail(inputs=None, **kwargs):
        tail_called["n"] += 1
        return {"chunk_count": 1, "total_questions": 0}

    monkeypatch.setattr(document_pipeline, "run_post_parse_tail", _fake_tail)

    # VLM/OCR 调用一旦发生即失败：快照命中必须短路跳过
    async def _fail_vlm(**kwargs):
        raise AssertionError("快照命中时不应调用 VLM")

    async def _fail_ocr(**kwargs):
        raise AssertionError("快照命中时不应调用 OCR")

    monkeypatch.setattr(document_pipeline, "_generate_image_description", _fail_vlm)
    monkeypatch.setattr(document_pipeline, "_process_image_ocr_static", _fail_ocr)

    class _FakeSession:
        async def commit(self):
            return None

    await document_pipeline._process_image_document_static(
        document=doc,
        file_content=b"\x89PNG fake",
        session=_FakeSession(),
        _logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None,
                                error=lambda *a, **k: None),
        task=None,
        model_config_port=None,
    )

    assert tail_called["n"] == 1, "快照命中后仍应走切分/嵌入/索引尾段（只有解析被跳过）"
