"""音视频文档处理管道：视频走关键帧提取加 VLM 逐帧描述，音频走 ASR 转写，之后统一文本切分、embedding 与 ES 入库。"""

import asyncio
from typing import Any

from novamind.engines.document.media.audio import (
    AudioFileInvalidError,
    transcribe_audio_local,
    transcribe_audio_with_timestamps,
    transcribe_audio_with_dashscope,
)
from novamind.engines.document.media.chunk_time_alignment import (
    build_frame_timeline_map,
    build_segment_timeline_map,
    format_time_anchor,
    merge_audio_into_frame_lines,
)
from novamind.engines.document.media.video import (
    AllFrameDescriptionsFailedError,
    dedup_frame_diff,
    describe_frame_sequence,
    describe_grouped,
    describe_rewrite,
    describe_single,
    describe_video_native,
    extract_frames_fixed,
    extract_frames_fixed_from_path,
    extract_frames_scene,
    extract_frames_scene_from_path,
)
from novamind.features.knowledge_space.exceptions import (
    DocumentProcessingError,
    LocalASRBusyError,
    PermanentProcessingError,
)
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.document_task import DocumentTask
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    build_runtime_parsing_config,
)
from novamind.features.knowledge_space.services.pipeline_snapshots import (
    SNAPSHOTS_ENABLED,
    build_parse_snapshot_payload,
    compute_parse_fingerprint,
    load_parse_snapshot,
    payload_fingerprint_matches,
    restore_frame_paths,
    restore_time_alignment,
    save_parse_snapshot,
    snapshot_fingerprint,
)
from novamind.features.knowledge_space.services.pipeline_steps import (
    begin_step,
    check_document_cancelled,
    finish_step_committed,
    load_pipeline_context,
    persist_parsed_text,
    run_post_parse_tail,
)
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.config import AudioConfig
from novamind.shared.utils.time_utils import now_china
from sqlalchemy.ext.asyncio import AsyncSession


# VLM 配额/鉴权类错误的特征串。这类错误通常不会因重试而恢复，应触发回退或跳过降级，
# 而不是让整个文档任务失败后还被 arq 重试 N 次。
_VLM_QUOTA_OR_AUTH_MARKERS = (
    "allocationquota",
    "freetieronly",
    "free quota",
    "免费额度",
    "quota",
    "exhausted",
    "403",
    "401",
    "unauthorized",
    "authentication",
    "permission denied",
)


def _is_vlm_quota_or_auth_error(exc: BaseException) -> bool:
    """判断 VLM 调用异常是否属于配额/鉴权类（可降级，无需重试）。"""
    text = str(exc).lower()
    return any(marker in text for marker in _VLM_QUOTA_OR_AUTH_MARKERS)


async def _snap_minio():
    """快照读写的 MinIO 客户端获取（懒加载，失败由调用方 fail-open）。"""
    from novamind.shared.storage.client_factory import ClientFactory

    return await ClientFactory.get_minio_client()


async def _resolve_asr_route(
    document: Document,
    model_config_port: ModelConfigService,
    asr_model: str,
) -> tuple[str, str, str | None, str | None]:
    """解析 ASR 模型名到实际路由（协议/模型/API 凭证）。

    本地默认模型（faster-whisper-tiny）不查凭证——协议恒为 local；云端模型
    凭证按名字精确匹配，找不到即抛错，不取「该用户第一个 ASR 配置」串用
    （审计 P1#8：用户选了 A 模型可能被静默换成 B 模型/他家凭证，不可追踪）。

    Args:
        document: 文档（uploader_id 用于凭证查询）。
        model_config_port: 模型配置端口。
        asr_model: 显式配置的 ASR 模型名（空串/None 由调用方归一为本地默认）。

    Returns:
        (protocol, model, api_key, base_url) 四元组。

    Raises:
        PermanentProcessingError: 云端模型凭证缺失。
    """
    if asr_model == "faster-whisper-tiny":
        return "local", asr_model, None, None

    asr_creds = await model_config_port.get_credentials_by_model(
        document.uploader_id, "asr", asr_model
    )
    if not asr_creds:
        raise PermanentProcessingError(
            document_id=document.id,
            error_message=(
                f"未找到 ASR 模型「{asr_model}」的凭证，请在模型管理中添加该模型的 "
                f"API 配置，或将知识库音频解析配置切回本地默认"
                f"（asr_model 留空 = faster-whisper-tiny 本地转写）"
            ),
        )
    protocol = asr_creds.protocol or "openai"
    model = asr_creds.model or asr_model
    return protocol, model, asr_creds.api_key, asr_creds.base_url


async def _run_asr_transcription(
    *,
    file_content: bytes,
    file_type: str,
    protocol: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
    language: str | None,
    engine_audio_config: AudioConfig,
    document: Document,
) -> list:
    """按协议分发执行一次 ASR 转写（不含本地锁/失败语义——归调用方）。

    音频文档与视频音轨共用同一路由：openai → Whisper / dashscope →
    Paraformer（MinIO 中转）/ local → faster-whisper（须持有 ASR 锁）。
    """
    if protocol == "local":
        return await transcribe_audio_local(
            file_content=file_content,
            file_type=file_type,
            language=language,
            audio_config=engine_audio_config,
        )
    if protocol == "dashscope":
        from novamind.shared.storage.client_factory import ClientFactory

        minio_client = await ClientFactory.get_minio_client()
        storage_info = document.get_storage_info()
        language_hints = [language] if language else None
        return await transcribe_audio_with_dashscope(
            file_content=file_content,
            file_type=file_type,
            model=model,
            api_key=api_key,
            base_url=base_url,
            minio_bucket=storage_info.get("minio_bucket"),
            language_hints=language_hints,
            minio_client=minio_client,
        )
    return await transcribe_audio_with_timestamps(
        file_content=file_content,
        file_type=file_type,
        model=model,
        api_key=api_key,
        base_url=base_url,
        language=language,
    )


async def _transcribe_video_audio(
    *,
    document: Document,
    file_path: str | None,
    file_content: bytes | None,
    model_config_port: ModelConfigService,
    asr_model: str,
    language: str | None,
    engine_audio_config: AudioConfig,
    logger,
) -> list[dict[str, Any]]:
    """视频音轨转写：ffmpeg 提取 + ASR 路由复用（c3 双轨融合的音侧）。

    音轨提取必须有原始文件（归一化产物带 ``-an`` 已丢音轨）：优先
    ``file_path``（worker 落盘路径），否则 ``file_content`` 写临时文件。
    两者均缺时返回空列表（能力缺失方向安全——告警跳过，文档不失败）。

    失败语义（与音频文档的致命语义不同：视频旁白是增强能力，帧描述
    独立可用，旁白获取失败不应拖死文档）：
    - 本地 ASR 忙碌（LocalASRBusyError）原样上抛：延后重入队不吞；
    - 凭证缺失 / 提取失败 / ASR 失败：告警跳过返回空列表。

    Returns:
        ASR segments（可为空列表 = 无音轨/转写失败/无可用输入）。
    """
    # 音轨源文件就位：file_path 直用；bytes 落临时盘
    audio_source: str | None = file_path
    tmp_audio_src: str | None = None
    if audio_source is None and file_content:
        import tempfile
        from pathlib import Path

        suffix = Path(document.filename or "video.mp4").suffix or ".mp4"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_content)
            tmp_audio_src = tmp.name
        audio_source = tmp_audio_src
    try:
        if audio_source is None:
            logger.warning(
                "视频音轨转写跳过：无原始文件可用（file_path/file_content 均缺）",
                document_id=document.id,
            )
            return []

        from novamind.engines.document.media.video import (
            AudioTrackExtractionError,
            extract_audio_track,
        )

        try:
            asr_protocol, asr_model, asr_api_key, asr_base_url = await _resolve_asr_route(
                document, model_config_port, asr_model
            )
        except PermanentProcessingError as exc:
            logger.warning(
                "视频音轨 ASR 凭证缺失，跳过音轨（帧描述继续）",
                document_id=document.id, error=str(exc),
            )
            return []

        # 本地 ASR：锁在音轨提取前获取——忙碌重入队时不白跑 ffmpeg 提取
        local_lock_acquired = False
        if asr_protocol == "local":
            from novamind.engines.document.media.audio import (
                acquire_asr_or_busy,
                force_release_asr_slot,
            )

            if not await acquire_asr_or_busy():
                logger.info("本地 ASR 忙碌，视频音轨延后重入队", document_id=document.id)
                raise LocalASRBusyError(document_id=document.id)
            local_lock_acquired = True
        try:
            audio_bytes = await asyncio.to_thread(extract_audio_track, audio_source)
            if not audio_bytes:
                return []
            return await _run_asr_transcription(
                file_content=audio_bytes,
                file_type="mp3",
                protocol=asr_protocol,
                model=asr_model,
                api_key=asr_api_key,
                base_url=asr_base_url,
                language=language,
                engine_audio_config=engine_audio_config,
                document=document,
            )
        except AudioTrackExtractionError as exc:
            logger.warning(
                "视频音轨提取失败，跳过音轨继续帧描述",
                document_id=document.id, error=str(exc),
            )
            return []
        except Exception as exc:
            logger.warning(
                "视频音轨 ASR 失败，跳过音轨继续帧描述（旁白信息缺失但文档不失败）",
                document_id=document.id, error=str(exc),
            )
            return []
        finally:
            if local_lock_acquired:
                from novamind.engines.document.media.audio import force_release_asr_slot

                force_release_asr_slot()
    finally:
        if tmp_audio_src is not None:
            from pathlib import Path as _P

            _P(tmp_audio_src).unlink(missing_ok=True)


def _parse_steps_json(response: str) -> list[dict[str, Any]]:
    """解析步骤综合 LLM 输出的 JSON（容忍 ```json 围栏与前后噪声）。"""
    import json
    import re as _re

    text = (response or "").strip()
    fence = _re.search(r"```(?:json)?\s*(.+?)\s*```", text, _re.DOTALL)
    if fence:
        text = fence.group(1)
    # 前后噪声兜底：截取首个 { 到末个 } 之间
    lbrace = text.find("{")
    rbrace = text.rfind("}")
    if lbrace >= 0 and rbrace > lbrace:
        text = text[lbrace : rbrace + 1]
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list):
        return []
    parsed: list[dict[str, Any]] = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or "").strip()
        body = str(s.get("body") or "").strip()
        if not title and not body:
            continue
        try:
            start_idx = int(s.get("start_frame_idx"))
            end_idx = int(s.get("end_frame_idx"))
        except (TypeError, ValueError):
            continue
        if end_idx < start_idx:
            start_idx, end_idx = end_idx, start_idx
        parsed.append({
            "no": len(parsed) + 1,
            "title": title,
            "body": body,
            "start_frame_idx": start_idx,
            "end_frame_idx": end_idx,
        })
    return parsed


def _steps_coverage_gap(
    steps: list[dict[str, Any]],
    anchor_indices: set[int],
    frame_groups: dict[int, list[int]] | None,
) -> set[int]:
    """计算双层覆盖缺口：帧层（全部帧 idx 被步骤区间覆盖）。

    grouped 策略下步骤区间端点是组首帧 idx，经 frame_groups 展开为组内全部帧。
    返回未被任何步骤区间覆盖的帧 idx 集合（空集 = 帧层全覆盖）。
    """
    def _expand(idx: int) -> list[int]:
        if frame_groups and idx in frame_groups:
            return list(frame_groups[idx])
        return [idx]

    covered: set[int] = set()
    for step in steps:
        for i in range(step["start_frame_idx"], step["end_frame_idx"] + 1):
            covered.update(_expand(i))
    return anchor_indices - covered


async def _synthesize_steps(
    *,
    document: Document,
    full_text: str,
    frame_timeline_map: dict[int, tuple[float | None, float | None]],
    frame_groups: dict[int, list[int]] | None,
    llm_client: Any,
    max_steps: int,
    logger,
    document_id: int | None = None,
) -> list[dict[str, Any]] | None:
    """步骤综合 pass：LLM 汇总双轨描述输出带帧区间的操作步骤（批2 c4）。

    双层覆盖率校验（「不遗漏」的机制保证）：
    - 帧层：全部锚点帧 idx 被 steps 的 [start, end] 区间覆盖（grouped 经
      frame_groups 展开）；
    - 旁白层：调用方在归并后保证每个含旁白的帧仍是一个锚点帧，帧层覆盖
      即蕴含旁白层（旁白不单独出现在无帧区间）。

    缺失 → 带清单重试 1 次 → 仍缺 → 返回 None（告警降级，文档不失败，
    保留帧级 chunks——失败方向安全）。

    Returns:
        步骤条目列表（已按 no 排序、idx 区间合法、条数 ≤ max_steps），
        或 None 表示综合失败/全覆盖不可达，调用方跳过步骤 chunks。
    """
    from novamind.shared.prompts.templates import PromptManager

    anchor_indices = set(frame_timeline_map.keys())
    if not anchor_indices:
        return None

    prompt_tpl = PromptManager.get_template("video_steps_synthesis")
    # 输入即双轨描述行本身（含锚点/画面/旁白），LLM 据此输出步骤 JSON
    synthesis_input = full_text
    if len(synthesis_input) > 60_000:
        logger.warning(
            "步骤综合输入过长，截断到 60000 字符（尾部帧可能不被覆盖）",
            document_id=document.id, input_len=len(synthesis_input),
        )
        synthesis_input = synthesis_input[:60_000]

    last_gap: set[int] = set()
    for attempt in range(2):
        messages = [{"role": "user", "content": f"{prompt_tpl}\n\n--- 双轨描述 ---\n{synthesis_input}"}]
        if attempt == 1 and last_gap:
            gap_list = sorted(last_gap)[:50]
            messages.append({
                "role": "user",
                "content": (
                    f"你上一轮输出的步骤未覆盖以下帧序号：{gap_list}。"
                    f"请重新输出完整 JSON，确保每个帧序号都落在某个步骤的 "
                    f"start_frame_idx..end_frame_idx 区间内。"
                ),
            })
        try:
            response = await llm_client.generate_text(
                prompt=messages,
                max_tokens=4096,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            logger.warning(
                "步骤综合 LLM 调用失败，跳过步骤 chunks（帧级 chunks 保留）",
                document_id=document.id, attempt=attempt + 1, error=str(exc),
            )
            return None

        steps = _parse_steps_json(response)
        if not steps:
            logger.warning(
                "步骤综合输出解析为空，重试或降级",
                document_id=document.id, attempt=attempt + 1,
                response_preview=(response or "")[:200],
            )
            last_gap = anchor_indices
            continue
        if len(steps) > max_steps:
            steps = steps[:max_steps]
        gap = _steps_coverage_gap(steps, anchor_indices, frame_groups)
        if not gap:
            logger.info(
                "步骤综合完成（帧层全覆盖）",
                document_id=document.id, step_count=len(steps),
            )
            return steps
        last_gap = gap
        logger.warning(
            "步骤综合帧覆盖缺口，重试",
            document_id=document.id, attempt=attempt + 1,
            gap_count=len(gap), gap_sample=sorted(gap)[:20],
        )

    logger.warning(
        "步骤综合重试后仍有帧覆盖缺口，降级跳过步骤 chunks（帧级 chunks 保留）",
        document_id=document.id, gap_count=len(last_gap),
        gap_sample=sorted(last_gap)[:20],
    )
    return None


async def _audio_resume_tail(
    *,
    document: Document,
    session: AsyncSession,
    task: DocumentTask | None,
    logger,
    model_config_port: ModelConfigService | None,
    ctx,
    splitting_config: dict,
    full_text: str,
    snap: dict,
    parse_fingerprint: str,
    pipeline_config: dict,
) -> None:
    """音频解析快照命中后的续跑尾：persist → 切分/向量化/问题生成/索引 → 完成。"""
    resumed_time_alignment = restore_time_alignment(snap.get("time_alignment"))

    await persist_parsed_text(document, full_text, session, logger)

    tail_result = await run_post_parse_tail(
        document=document,
        session=session,
        task=task,
        model_config_port=model_config_port,
        logger=logger,
        chunk_type=ChunkType.AUDIO,
        embedding_config=ctx.embedding_config,
        pipeline_config=pipeline_config,
        splitting_config=splitting_config,
        full_text=full_text,
        time_alignment=resumed_time_alignment,
        parse_fingerprint=parse_fingerprint,
        user_id=document.uploader_id,
    )
    if task:
        task.mark_completed(result={
            "chunk_count": tail_result["chunk_count"],
            "chunk_type": ChunkType.AUDIO,
            "resumed_from_snapshot": True,
            "indexed_at": now_china().isoformat(),
        })
    await session.commit()
    logger.info(
        "音频文档处理完成（断点续跑）", document_id=document.id,
        chunks=tail_result["chunk_count"],
    )


async def _video_resume_tail(
    *,
    document: Document,
    session: AsyncSession,
    task: DocumentTask | None,
    logger,
    model_config_port: ModelConfigService | None,
    ctx,
    splitting_config: dict,
    full_text: str,
    snap: dict,
    parse_fingerprint: str,
    pipeline_config: dict,
) -> None:
    """视频解析快照命中后的续跑尾：persist → 切分/向量化/问题生成/索引 → 完成。

    时间线/帧路径从快照还原（restore_time_alignment 处理 JSON 序列化把 int 键
    变 str 的问题——此前 resume 分支直接传 raw dict，int 键全 miss，对齐静默失效）。
    """
    resumed_time_alignment = restore_time_alignment(snap.get("time_alignment"))
    resumed_frame_paths = restore_frame_paths(snap.get("frame_paths"))

    await persist_parsed_text(document, full_text, session, logger)
    if task:
        await finish_step_committed(session, task, "descriptions_generated", metrics={"resumed": True})

    tail_result = await run_post_parse_tail(
        document=document,
        session=session,
        task=task,
        model_config_port=model_config_port,
        logger=logger,
        chunk_type=ChunkType.VIDEO,
        embedding_config=ctx.embedding_config,
        pipeline_config=pipeline_config,
        splitting_config=splitting_config,
        full_text=full_text,
        frame_paths=resumed_frame_paths or None,
        time_alignment=resumed_time_alignment,
        parse_fingerprint=parse_fingerprint,
        user_id=document.uploader_id,
    )
    if task:
        task.mark_completed(result={
            "chunk_count": tail_result["chunk_count"],
            "chunk_type": ChunkType.VIDEO,
            "resumed_from_snapshot": True,
            "indexed_at": now_china().isoformat(),
        })
    await session.commit()
    logger.info(
        "视频文档处理完成（断点续跑）", document_id=document.id,
        chunks=tail_result["chunk_count"],
    )



async def process_video_document(
    document: Document,
    file_content: bytes | None,
    session: AsyncSession,
    logger,
    task: DocumentTask | None = None,
    model_config_port: ModelConfigService | None = None,
    file_path: str | None = None,
) -> None:
    """
    视频文档处理管道

    1. 提取关键帧（按 pipeline 配置的间隔和最大帧数）
    2. 逐帧调 VLM 生成描述
    3. MD 拼接全文 → 上传 MinIO
    4. 统一文本切分
    5. Embedding → ES 索引

    批次 5b：model_config_port 由调用方（execute_document_pipeline）注入，
    不再内部自建 ModelConfigService。

    大文件路径：file_path 给出时抽帧直接吃文件路径（引擎 *_from_path 变体），
    file_content 仅在 file_path 缺席时使用（二者由 execute_document_pipeline
    互斥保证至少一个在场）。
    """
    ctx = await load_pipeline_context(session, document, task)
    pipeline_config = ctx.pipeline_config
    parsing_config = build_runtime_parsing_config(pipeline_config.get("parsing", {}), document.file_type)
    splitting_config = dict(pipeline_config.get("splitting", {}))
    video_config = (pipeline_config.get("parsing", {}) or {}).get("video", {})
    # strategy：6 预设映射到抽帧/去重/描述三阶段（build_runtime_parsing_config 同时扁平化到 video_strategy）
    strategy = video_config.get("strategy") or parsing_config.get("video_strategy") or "simple"
    frame_interval = video_config.get("frame_interval", 5)
    max_frames = video_config.get("max_frames", 60)
    # VLM 降级开关：主模型配额/鉴权失败时回退的备用模型；以及全帧失败时是否跳过 VLM。
    vlm_fallback_model = video_config.get("vlm_fallback_model")
    vlm_skip_on_quota_error = bool(video_config.get("vlm_skip_on_quota_error", False))
    # VLM 逐帧/逐组描述并发数：系统级性能旋钮，由 YAML 配置
    # knowledge_base.parsing.video_vlm_concurrency 控制（默认 4，范围 1~20），
    # 不放每个知识库的 VideoParsingConfig——并发是宿主调优项，非业务配置。
    from novamind.setting.yaml_config import get_config
    vlm_concurrency = max(1, min(20, int(get_config().knowledge_base.parsing.video_vlm_concurrency)))
    # 高级参数（可选，留空用引擎层默认）
    scene_threshold = video_config.get("scene_threshold")
    scene_min_interval = video_config.get("scene_min_interval")
    dedup_similarity_threshold = video_config.get("dedup_similarity_threshold")
    group_size = video_config.get("group_size") or 3
    # 帧序列伪视频每段帧数上限（strategy=frame_seq），留空用引擎默认 512。
    frame_seq_chunk_frames = video_config.get("frame_seq_chunk_frames")
    # S4 视频直输（strategy=video_native）：聚片/降级链旋钮，留空用引擎默认。
    video_native_chunk_sec = video_config.get("video_native_chunk_sec")
    video_native_min_tail_sec = video_config.get("video_native_min_tail_sec")
    video_native_concurrency = video_config.get("video_native_concurrency")
    video_native_fallback_to_frame_seq = bool(
        video_config.get("video_native_fallback_to_frame_seq", True)
    )

    # 批次 5b：用注入的 ModelConfigService
    mcs = model_config_port

    # 1. 提取帧（按 strategy 路由：scene 场景抽帧，其余固定间隔）
    logger.info(
        "视频帧提取开始", document_id=document.id,
        strategy=strategy, interval=frame_interval, max_frames=max_frames,
    )
    if task:
        await begin_step(session, task, "frames_extracted")

    # ===== 解析快照命中检查（审计 P1#2：此前音视频快照只写不读，RETRY 时
    # VLM 描述全量白烧）。指纹匹配即复用快照全文/时间线/帧路径，跳过抽帧+VLM。
    video_parse_fp = ""
    if SNAPSHOTS_ENABLED:
        try:
            video_parse_fp = compute_parse_fingerprint(document, parsing_config)
        except Exception as fp_exc:
            logger.warning("视频解析指纹计算失败，不启用快照", document_id=document.id, error=str(fp_exc))

    if video_parse_fp and snapshot_fingerprint(document, "parse") == video_parse_fp:
        snap = await load_parse_snapshot(document, await _snap_minio(), logger)
        if snap and payload_fingerprint_matches(snap, "parse_fingerprint", video_parse_fp):
            snap_text = str(snap.get("full_text") or "")
            if snap_text.strip():
                logger.info(
                    "视频解析快照命中，复用帧描述（跳过抽帧+VLM）",
                    document_id=document.id, char_count=len(snap_text),
                )
                if task:
                    await finish_step_committed(session, task, "frames_extracted", metrics={"resumed": True, "frame_count": None})
                    await begin_step(session, task, "descriptions_generated")
                return await _video_resume_tail(
                    document=document, session=session, task=task, logger=logger,
                    model_config_port=model_config_port, ctx=ctx,
                    splitting_config=splitting_config,
                    full_text=snap_text,
                    snap=snap, parse_fingerprint=video_parse_fp,
                    pipeline_config=pipeline_config,
                )
        logger.info("视频解析快照未命中/不可用，走全量抽帧+VLM", document_id=document.id)

    # ===== c3 音轨 ASR 融合（旁白）：ffmpeg 提取原始视频音轨 → ASR 转写。
    # 在 VLM 描述前执行——本地 ASR 忙碌上抛重入队时不白烧 VLM 配额；
    # 凭证缺失/提取失败/转写失败告警跳过（能力缺失方向安全，帧描述独立可用）。
    # transcribe_audio 开关与 asr_model/language 由视频解析配置给出（c4 加
    # schema 字段；此处直接读 video_config dict，配置未显式开启时零行为变化）。
    audio_segments: list[dict[str, Any]] = []
    transcribe_enabled = bool(video_config.get("transcribe_audio", False))
    if transcribe_enabled:
        from novamind.setting.yaml_config import get_config

        engine_audio_config = AudioConfig(
            local_whisper_model_dir=get_config().knowledge_base.parsing.local_whisper_model_dir,
            local_whisper_cpu_threads=get_config().knowledge_base.parsing.local_whisper_cpu_threads,
        )
        audio_asr_model = video_config.get("asr_model") or "faster-whisper-tiny"
        audio_segments = await _transcribe_video_audio(
            document=document,
            file_path=file_path,
            file_content=file_content,
            model_config_port=mcs,
            asr_model=audio_asr_model,
            language=video_config.get("language"),
            engine_audio_config=engine_audio_config,
            logger=logger,
        )

    if strategy in ("scene", "video_native"):
        scene_kwargs: dict[str, Any] = {}
        if scene_threshold is not None:
            scene_kwargs["scene_threshold"] = scene_threshold
        if scene_min_interval is not None:
            scene_kwargs["min_interval"] = scene_min_interval
        if file_path is not None:
            frames = await extract_frames_scene_from_path(file_path, max_frames, **scene_kwargs)
        else:
            frames = await extract_frames_scene(file_content, max_frames, **scene_kwargs)
    else:
        if file_path is not None:
            frames = await extract_frames_fixed_from_path(file_path, frame_interval, max_frames)
        else:
            frames = await extract_frames_fixed(file_content, frame_interval, max_frames)
    logger.info(
        "视频帧提取完成", document_id=document.id, frame_count=len(frames),
    )

    # 检查点1：帧提取完成
    await check_document_cancelled(document.id)

    if not frames:
        raise DocumentProcessingError(
            document_id=document.id,
            error_message=f"视频 {document.filename} 未能提取到任何帧",
        )

    # 1.5 去重（dedup 策略：相邻帧直方图相似度去重，frame_idx 重映射为连续序号）
    if strategy == "dedup":
        dedup_kwargs: dict[str, Any] = {}
        if dedup_similarity_threshold is not None:
            dedup_kwargs["similarity_threshold"] = dedup_similarity_threshold
        frames = dedup_frame_diff(frames, **dedup_kwargs)
        logger.info(
            "视频帧去重完成", document_id=document.id, kept_frame_count=len(frames),
        )
        if not frames:
            raise DocumentProcessingError(
                document_id=document.id,
                error_message=f"视频 {document.filename} 去重后无剩余帧",
            )

    # 1.5. 帧持久化到 MinIO（在 VLM 调用前上传，避免 VLM 失败后帧丢失）
    from novamind.shared.storage.client_factory import ClientFactory
    minio_client = await ClientFactory.get_minio_client()
    storage_info = document.storage or {}
    base_object = storage_info.get("minio_object_name", "")

    # frame_paths 用 Dict[int, str]（frame_idx → MinIO path），根治抽帧解码失败导致的
    # frame_idx 空洞：engines 抽帧在 read_frame_at 返回 None 或抛错时跳过该帧但 frame_idx
    # 仍递增（video_utils.py / frame_extraction.py 的 enumerate+continue 模式），若 frame_paths
    # 按位置 append 会与 frame_idx 错位 → ES chunk 帧图指向错误帧或丢失。dict 映射让
    # build_es_chunks 按 frame_idx 精确取帧，空洞 idx 自动跳过。dedup 策略因 dedup_frame_diff
    # 已用 len(kept) 重映射连续 idx 而天然免疫，此处 dict 同样兼容。
    frame_paths: dict[int, str] = {}
    for frame_bytes, ts, frame_idx in frames:
        object_name = f"{base_object}_frames/frame_{frame_idx:04d}.jpg"
        try:
            await minio_client.upload_file(object_name, frame_bytes, "image/jpeg")
            frame_paths[frame_idx] = object_name
            logger.debug("帧已上传 MinIO", object_name=object_name, timestamp=ts)
        except Exception as e:
            logger.error("帧上传 MinIO 失败", document_id=document.id,
                         frame_idx=frame_idx, timestamp=ts, error=str(e))
            # 上传失败占位保留 frame_idx→空映射，不丢 idx 对应关系，不阻塞整体
            frame_paths[frame_idx] = ""

    # 帧上传后立即持久化 storage["frames"]，确保后续切分/嵌入/索引（run_post_parse_tail）
    # 失败时帧仍可追踪，配合重处理/删除的 MinIO 前缀清理避免孤儿。storage["frames"] 保持
    # "按 frame_idx 升序的非空 path 列表"格式（get_document_frames 按列表 enumerate 消费）。
    document.storage = {
        **(document.storage or {}),
        "frames": [frame_paths[k] for k in sorted(frame_paths) if frame_paths[k]],
    }
    await session.commit()

    if task:
        await finish_step_committed(session, task, "frames_extracted", metrics={"frame_count": len(frames)})

    if task:
        await begin_step(session, task, "descriptions_generated")
    # 2. 装配 VLM client + prompt（features 装配点注入引擎 describe_* 函数）
    # 从视频自身嵌套配置读 vlm_model（video_config = pipeline_config["parsing"]["video"]），
    # 不读扁平 parsing_config["vlm_model"]：build_runtime_parsing_config 把 image.vlm_model
    # 与 video.vlm_model 共写同一扁平 result["vlm_model"]，video 留空时残留 image 的模型，
    # 视频会静默串用图片的 VLM（跨模态污染，且是不可追踪的兜底）。留空即抛错，不回退用户
    # 默认（守"没选不兜底"原则，与图片路径一致）。vlm_fallback_model 是用户显式配置的备用，保留。
    vlm_model_name = video_config.get("vlm_model")
    if not vlm_model_name:
        raise PermanentProcessingError(
            document_id=document.id,
            error_message=(
                f"视频 {document.filename} 解析需配置 VLM 模型，请在知识库视频解析配置中选择 VLM 模型"
            ),
        )
    vlm_client = await mcs.get_vlm_client_by_model(document.uploader_id, vlm_model_name)
    vlm_fallback_client = None
    if vlm_fallback_model:
        vlm_fallback_client = await mcs.get_vlm_client_by_model(
            document.uploader_id, vlm_fallback_model
        )

    from novamind.shared.prompts.templates import PromptManager

    def cancelled_check() -> bool:
        return check_document_cancelled(document.id)
    base_log_ctx: dict[str, Any] = {"document_id": document.id}

    # 双锚点 [HH:MM:SS#frame_idx]：时间戳给人看，#frame_idx 给切分后反查唯一映射回帧时间区间。
    # 帧时间线 {frame_idx: (start_sec, end_sec)}，end = 下一帧 ts（末帧 end=None，末尾开放区间）。
    # 切分后 align_chunk_times 据此把 chunk 反查到的 #idx 映射成 start_time/end_time。
    full_text = ""
    frame_timeline_map: dict[int, tuple[float | None, float | None]] = {}
    frame_groups: dict[int, list[int]] | None = None
    descriptions_count = 0
    # VLM 失败帧出参（引擎写入 failed 计数；全失败走异常路径不写）
    vlm_stats: dict[str, int] = {}

    try:
        if strategy == "grouped":
            # grouped：每 group_size 帧一组喂 VLM 多图；锚点用组首帧 idx，frame_groups 展开组内所有帧
            grouped_prompt = PromptManager.get_template("video_frame_grouped_description")
            grouped_descs = await describe_grouped(
                frames, group_size, vlm_client, grouped_prompt,
                logger=logger, vlm_model=vlm_model_name,
                vlm_fallback_client=vlm_fallback_client, vlm_fallback_model=vlm_fallback_model,
                is_quota_error=_is_vlm_quota_or_auth_error,
                log_context=base_log_ctx, cancelled_check=cancelled_check,
                concurrency=vlm_concurrency, stats=vlm_stats,
            )
            lines: list[str] = []
            frame_groups = {}
            timeline_input: list[tuple[str, float, int]] = []
            for desc, start_ts, _end_ts, idx_list in grouped_descs:
                anchor_idx = idx_list[0]
                lines.append(f"{format_time_anchor(start_ts, anchor_idx)} {desc}")
                frame_groups[anchor_idx] = idx_list
                timeline_input.append((desc, start_ts, anchor_idx))
            full_text = "\n\n".join(lines)
            frame_timeline_map = build_frame_timeline_map(timeline_input)
            descriptions_count = len(grouped_descs)
        elif strategy == "frame_seq":
            # frame_seq（S3 帧序列伪视频）：整段帧以 {"type":"video","video":[...],"fps":N}
            # 喂 VLM，模型感知时序；每段 prompt 注入帧时刻表校准时间定位。
            # 需 VLM 协议配 openai_video（专用视频客户端），缺失即 fail fast 不兜底。
            if not hasattr(vlm_client, "generate_text_from_frames"):
                raise PermanentProcessingError(
                    document_id=document.id,
                    error_message=(
                        f"视频 {document.filename} frame_seq 策略需 VLM 协议为 openai_video，"
                        "请在模型管理中把所选 VLM 模型的协议改为 openai_video"
                    ),
                )
            seq_prompt = PromptManager.get_template("video_frame_sequence_description")
            seq_kwargs: dict[str, Any] = {}
            if frame_seq_chunk_frames:
                seq_kwargs["chunk_frames"] = int(frame_seq_chunk_frames)
            seq_descs = await describe_frame_sequence(
                frames, vlm_client, seq_prompt,
                fps=round(1.0 / max(frame_interval, 1e-6), 4),
                logger=logger, vlm_model=vlm_model_name,
                log_context=base_log_ctx, cancelled_check=cancelled_check,
                stats=vlm_stats, **seq_kwargs,
            )
            seq_lines: list[str] = []
            frame_groups = {}
            seq_timeline_input: list[tuple[str, float, int]] = []
            for desc, start_ts, _end_ts, idx_list in seq_descs:
                anchor_idx = idx_list[0]
                seq_lines.append(f"{format_time_anchor(start_ts, anchor_idx)} {desc}")
                frame_groups[anchor_idx] = idx_list
                seq_timeline_input.append((desc, start_ts, anchor_idx))
            full_text = "\n\n".join(seq_lines)
            frame_timeline_map = build_frame_timeline_map(seq_timeline_input)
            descriptions_count = len(seq_descs)
        elif strategy == "video_native":
            # video_native（S4 视频直输）：切片直输 VLM，慢切换场景最优。
            # 需 VLM 协议配 openai_video；切片吃本地路径（file_path 缺席时落临时文件）。
            if not hasattr(vlm_client, "generate_text_from_video_url"):
                raise PermanentProcessingError(
                    document_id=document.id,
                    error_message=(
                        f"视频 {document.filename} video_native 策略需 VLM 协议为 openai_video，"
                        "请在模型管理中把所选 VLM 模型的协议改为 openai_video"
                    ),
                )
            native_prompt = PromptManager.get_template("video_native_description")
            native_kwargs: dict[str, Any] = {}
            if video_native_chunk_sec:
                native_kwargs["max_segment_sec"] = float(video_native_chunk_sec)
            if video_native_min_tail_sec is not None:
                native_kwargs["min_tail_sec"] = float(video_native_min_tail_sec)
            if video_native_concurrency:
                native_kwargs["concurrency"] = int(video_native_concurrency)

            # 切片源路径：优先 worker 落盘的 file_path；缺席（旧 bytes 路径/测试）落临时文件
            native_video_path = file_path
            tmp_source: Any = None
            if native_video_path is None:
                import tempfile as _tempfile
                tmp_source = _tempfile.NamedTemporaryFile(
                    suffix=f"_{document.id}_native_src", delete=False,
                )
                tmp_source.write(file_content or b"")
                tmp_source.close()
                native_video_path = tmp_source.name

            # 聚片边界的依据：场景帧 ts（extract_frames_scene 产物，含首帧 0）；
            # duration 用真实元数据（末帧 ts + 间隔只是近似，会让末片边界错）
            from novamind.engines.document.media.video.video_utils import read_video_metadata
            try:
                video_duration = float(read_video_metadata(native_video_path).get("duration") or 0)
            except Exception as meta_exc:
                raise DocumentProcessingError(
                    document_id=document.id,
                    error_message=f"视频 {document.filename} 元数据探测失败，无法聚片: {meta_exc}",
                ) from meta_exc
            if video_duration <= 0:
                # 元数据缺失时长时退化用末帧近似（能力缺失方向安全，末片边界略保守）
                video_duration = max(ts for _, ts, _ in frames) + frame_interval
            scene_keyframe_ts = [ts for _, ts, _ in frames]

            # 临时对象命名空间：{base}_vtmp/ 前缀，cleanup 走前缀删除（即用即删）
            vtmp_prefix = f"{base_object}_vtmp/"
            if not getattr(minio_client, "public_endpoint", None):
                logger.warning(
                    "video_native 需 minio.public_endpoint 配置，否则外部 VLM 服务"
                    "无法下载切片 URL，片描述将失败",
                    document_id=document.id,
                )

            # 桶名取 default_bucket（MinioClient 实际属性；upload_file/get_public_file_url
            # 均按此桶工作，勿用不存在的 bucket_name 属性兜底出错误桶名）
            native_bucket = getattr(minio_client, "default_bucket", None) or "novamind"

            async def _upload_segment(seg_bytes: bytes, seg_idx: int) -> str:
                seg_object = f"{vtmp_prefix}seg_{seg_idx:03d}.mp4"
                await minio_client.upload_file(seg_object, seg_bytes, "video/mp4")
                return await minio_client.get_public_file_url(native_bucket, seg_object)

            async def _cleanup_segments() -> None:
                await minio_client.delete_objects_by_prefix(native_bucket, vtmp_prefix)

            try:
                native_descs = await describe_video_native(
                    native_video_path, video_duration, scene_keyframe_ts,
                    vlm_client, native_prompt,
                    upload_segment=_upload_segment,
                    cleanup_segments=_cleanup_segments,
                    logger=logger, vlm_model=vlm_model_name,
                    log_context=base_log_ctx, cancelled_check=cancelled_check,
                    stats=vlm_stats, **native_kwargs,
                )
            except AllFrameDescriptionsFailedError as native_exc:
                if not video_native_fallback_to_frame_seq:
                    raise
                first = native_exc.first_error
                from novamind.shared.ai_models.llm.openai_compatible_video import (
                    VideoInputNotSupportedError,
                )
                if not isinstance(first, VideoInputNotSupportedError):
                    raise
                # 服务商明确拒绝视频输入 → 降级 frame_seq 全套（告警可观测）
                logger.warning(
                    "video_native 被服务商拒绝（VideoInputNotSupportedError），"
                    "按配置降级 frame_seq 帧序列策略",
                    document_id=document.id, first_error=str(first),
                )
                if not hasattr(vlm_client, "generate_text_from_frames"):
                    raise PermanentProcessingError(
                        document_id=document.id,
                        error_message=(
                            f"视频 {document.filename} video_native 降级 frame_seq 也需 "
                            "VLM 协议 openai_video（缺 generate_text_from_frames）"
                        ),
                    ) from native_exc
                seq_prompt_fb = PromptManager.get_template(
                    "video_frame_sequence_description"
                )
                seq_kwargs_fb: dict[str, Any] = {}
                if frame_seq_chunk_frames:
                    seq_kwargs_fb["chunk_frames"] = int(frame_seq_chunk_frames)
                native_descs = await describe_frame_sequence(
                    frames, vlm_client, seq_prompt_fb,
                    fps=round(1.0 / max(frame_interval, 1e-6), 4),
                    logger=logger, vlm_model=vlm_model_name,
                    log_context=base_log_ctx, cancelled_check=cancelled_check,
                    stats=vlm_stats, **seq_kwargs_fb,
                )
            finally:
                if tmp_source is not None:
                    from pathlib import Path as _P
                    _P(tmp_source.name).unlink(missing_ok=True)

            native_lines: list[str] = []
            frame_groups = {}
            native_timeline_input: list[tuple[str, float, int]] = []
            for desc, start_ts, _end_ts, idx_list in native_descs:
                if not idx_list:
                    continue  # 片区间未覆盖任何场景帧（均分兜底片），无锚点可挂
                anchor_idx = idx_list[0]
                native_lines.append(f"{format_time_anchor(start_ts, anchor_idx)} {desc}")
                frame_groups[anchor_idx] = idx_list
                native_timeline_input.append((desc, start_ts, anchor_idx))
            full_text = "\n\n".join(native_lines)
            frame_timeline_map = build_frame_timeline_map(native_timeline_input)
            descriptions_count = len(native_descs)
        elif strategy == "rewrite":
            # rewrite：逐帧 single 描述 + LLM 重写连贯（保留锚点）；返回 (full_text, descriptions)
            single_prompt = PromptManager.get_template("video_frame_description")
            rewrite_prompt = PromptManager.get_template("video_frame_rewrite_prompt")
            llm_model_name = await mcs.get_user_default_model_name(document.uploader_id, "llm")
            if not llm_model_name:
                raise PermanentProcessingError(
                    document_id=document.id,
                    error_message=f"视频 {document.filename} rewrite 策略需配置 LLM 模型",
                )
            llm_client = await mcs.get_llm_client_by_model(document.uploader_id, llm_model_name)
            full_text, descriptions = await describe_rewrite(
                frames, vlm_client, llm_client, single_prompt, rewrite_prompt,
                logger=logger, vlm_model=vlm_model_name, llm_model=llm_model_name,
                vlm_fallback_client=vlm_fallback_client, vlm_fallback_model=vlm_fallback_model,
                is_quota_error=_is_vlm_quota_or_auth_error,
                log_context=base_log_ctx, cancelled_check=cancelled_check,
                concurrency=vlm_concurrency, stats=vlm_stats,
            )
            frame_timeline_map = build_frame_timeline_map(descriptions)
            descriptions_count = len(descriptions)
        else:  # simple / scene / dedup：逐帧单图描述
            single_prompt = PromptManager.get_template("video_frame_description")
            descriptions = await describe_single(
                frames, vlm_client, single_prompt,
                logger=logger, vlm_model=vlm_model_name,
                vlm_fallback_client=vlm_fallback_client, vlm_fallback_model=vlm_fallback_model,
                is_quota_error=_is_vlm_quota_or_auth_error,
                log_context=base_log_ctx, cancelled_check=cancelled_check,
                concurrency=vlm_concurrency, stats=vlm_stats,
            )
            full_text_lines = [f"{format_time_anchor(ts, idx)} {desc}" for desc, ts, idx in descriptions]
            full_text = "\n\n".join(full_text_lines)
            frame_timeline_map = build_frame_timeline_map(descriptions)
            descriptions_count = len(descriptions)
    except AllFrameDescriptionsFailedError as e:
        # 全帧/全组描述均失败：按 vlm_skip_on_quota_error 决策写占位描述或抛业务异常
        all_quota = e.total_frames > 0 and e.quota_failures == e.total_frames
        if vlm_skip_on_quota_error and all_quota:
            logger.warning(
                "视频所有帧VLM描述均失败（配额/鉴权），已按配置跳过并写占位描述",
                document_id=document.id, frame_count=e.total_frames,
                first_error=str(e.first_error) if e.first_error else None,
            )
            first_ts = frames[0][1] if frames else 0.0
            first_idx = frames[0][2] if frames else 0
            full_text = f"{format_time_anchor(first_ts, first_idx)} （视频画面描述因 VLM 配额/鉴权不可用已跳过）"
            frame_timeline_map = {first_idx: (first_ts, None)}
            descriptions_count = 1
        else:
            detail = f"，首个错误: {e.first_error}" if e.first_error else ""
            hint = ""
            if all_quota:
                hint = (
                    "（VLM 配额/鉴权不可用。可在知识库视频解析配置中设置 vlm_fallback_model "
                    "回退备用模型，或开启 vlm_skip_on_quota_error 跳过 VLM。）"
                )
            raise DocumentProcessingError(
                document_id=document.id,
                error_message=f"视频 {document.filename} 所有帧的VLM描述均失败{detail}{hint}",
            )

    # ===== c3 双轨归并：ASR 旁白 segments 注入帧描述行（画面+旁白同锚点）。
    # 归并计数进 task metrics（audio_segments_total/merged/dropped），旁白
    # 有无丢失可观测；dropped>0 时告警日志（帧区间空洞外的 segment 被丢弃）。
    audio_merge_metrics: dict[str, int] = {}
    if audio_segments:
        desc_lines = full_text.split("\n\n")
        merged_lines, audio_merge_metrics = merge_audio_into_frame_lines(
            desc_lines, audio_segments, frame_timeline_map
        )
        full_text = "\n\n".join(merged_lines)
        if audio_merge_metrics.get("dropped"):
            logger.warning(
                "视频旁白 segments 未全部归入帧区间（帧区间空洞外被丢弃）",
                document_id=document.id, **audio_merge_metrics,
            )
        logger.info(
            "视频双轨归并完成", document_id=document.id, **audio_merge_metrics,
        )

    # ===== c4 步骤综合：LLM 汇总双轨描述 → 带帧区间的操作步骤条目。
    # 双层覆盖率校验（帧层全覆盖；旁白已归并进锚点行，帧覆盖即旁白覆盖）；
    # 失败/缺口重试 1 次后降级 None（帧级 chunks 保留，文档不失败）。
    steps_items: list[tuple[str, dict[str, Any]]] | None = None
    if bool(video_config.get("steps_enabled", False)):
        steps_llm_name = video_config.get("steps_llm_model")
        if not steps_llm_name:
            steps_llm_name = await mcs.get_user_default_model_name(document.uploader_id, "llm")
        steps_ok = bool(steps_llm_name)
        if steps_llm_name:
            try:
                steps_llm_client = await mcs.get_llm_client_by_model(document.uploader_id, steps_llm_name)
            except Exception as exc:
                logger.warning(
                    "步骤综合 LLM 客户端装配失败，跳过步骤 chunks（帧级 chunks 保留）",
                    document_id=document.id, model=steps_llm_name, error=str(exc),
                )
                steps_ok = False
        if steps_ok and steps_llm_name:
            max_steps = int(video_config.get("steps_max_steps") or 30)
            steps = await _synthesize_steps(
                document=document,
                full_text=full_text,
                frame_timeline_map=frame_timeline_map,
                frame_groups=frame_groups,
                llm_client=steps_llm_client,
                max_steps=max_steps,
                logger=logger,
            )
            if steps:
                # 步骤条目带首帧锚点进 chunk：对齐后获得 start/end/frame_indices，
                # 锚点被剥离，section 标记步骤类型供前端区分展示
                steps_items = []
                for step in steps:
                    anchor = format_time_anchor(
                        frame_timeline_map[step["start_frame_idx"]][0] or 0.0,
                        step["start_frame_idx"],
                    )
                    title = step["title"] or f"步骤 {step['no']}"
                    body = f"{title}\n{step['body']}"[:2000]
                    steps_items.append((f"{anchor} {body}", {"section": "steps"}))
                logger.info(
                    "步骤 chunks 构造完成", document_id=document.id, step_count=len(steps_items),
                )

    # 帧描述全文 MD 持久化到 MinIO（立刻 commit 落库）
    await persist_parsed_text(document, full_text, session, logger)

    # 断点续跑：计算解析指纹 + 保存带 time_alignment/frame_paths 的解析快照
    # （音视频解析产物含时间对齐/帧路径，resume 时据此免重跑 VLM 描述）。
    video_parse_fp = ""
    if SNAPSHOTS_ENABLED:
        try:
            video_parse_fp = compute_parse_fingerprint(document, parsing_config)
        except Exception as fp_exc:
            logger.warning("视频解析指纹计算失败，不启用快照", document_id=document.id, error=str(fp_exc))
        if video_parse_fp:
            from novamind.shared.storage.client_factory import ClientFactory as _CF

            try:
                snap_minio = await _CF.get_minio_client()
                await save_parse_snapshot(
                    document, session, logger,
                    minio_client=snap_minio,
                    parse_fingerprint=video_parse_fp,
                    payload=build_parse_snapshot_payload(
                        parse_fingerprint=video_parse_fp,
                        full_text=full_text,
                        parse_metadata=None,
                        time_alignment={
                            "timeline_map": frame_timeline_map,
                            "is_video": True,
                            **({"frame_groups": frame_groups} if frame_groups is not None else {}),
                        },
                        frame_paths=frame_paths,
                    ),
                )
            except Exception as snap_exc:
                logger.warning("视频解析快照保存失败（不影响主流程）", document_id=document.id, error=str(snap_exc))

    if task:
        desc_metrics: dict[str, Any] = {"description_count": descriptions_count}
        if vlm_stats.get("failed"):
            # 单帧 VLM 失败从静默留洞变可观测（与音轨归并 metrics 同面板）
            desc_metrics["vlm_failed_frames"] = vlm_stats["failed"]
            logger.warning(
                "部分帧 VLM 描述失败（已跳过留洞）",
                document_id=document.id, failed_frames=vlm_stats["failed"],
            )
        if audio_merge_metrics:
            desc_metrics.update(audio_merge_metrics)
        await finish_step_committed(session, task, "descriptions_generated", metrics=desc_metrics)

    # 3-5. 切分/向量化/问题生成/索引：交由共享后置尾
    tail_result = await run_post_parse_tail(
        document=document,
        session=session,
        task=task,
        model_config_port=model_config_port,
        logger=logger,
        chunk_type=ChunkType.VIDEO,
        embedding_config=ctx.embedding_config,
        pipeline_config=pipeline_config,
        splitting_config=splitting_config,
        full_text=full_text,
        steps_items=steps_items,
        frame_paths=frame_paths,
        time_alignment={
            "timeline_map": frame_timeline_map,
            "is_video": True,
            **({"frame_groups": frame_groups} if frame_groups is not None else {}),
        },
        parse_fingerprint=video_parse_fp or None,
        user_id=document.uploader_id,
    )

    # 5. 写入处理结果到 Task（storage["frames"] 已在帧上传后立即持久化，此处不再重写）
    if task:
        task.mark_completed(result={
            "chunk_count": tail_result["chunk_count"],
            "chunk_type": ChunkType.VIDEO,
            "frame_count": len(frames),
            "indexed_at": now_china().isoformat(),
        })
    await session.commit()

    logger.info(
        "视频文档处理完成", document_id=document.id,
        chunks=tail_result["chunk_count"], frames=len(frames), frame_paths=len(frame_paths),
    )


async def process_audio_document(
    document: Document,
    file_content: bytes,
    session: AsyncSession,
    logger,
    task: DocumentTask | None = None,
    model_config_port: ModelConfigService | None = None,
) -> None:
    """
    音频文档处理管道

    1. ASR 转写（OpenAI Whisper API，带时间戳）
    2. MD 文本拼接 → 上传 MinIO
    3. 统一文本切分
    4. Embedding → ES 索引
    """
    ctx = await load_pipeline_context(session, document, task)
    pipeline_config = ctx.pipeline_config
    audio_config = (pipeline_config.get("parsing", {}) or {}).get("audio", {})
    space_asr_cfg = (ctx.space.config or {}).get("asr", {}) if ctx.space else {}
    # 默认本地 ASR（用户裁定 2026-09-23）：未显式选 ASR 模型时默认走本地
    # faster-whisper（本地推理免费，部署期预装模型，见 deploy.sh
    # prepare_local_whisper_model）——这不是「串用别的云端配置」的静默兜底，
    # 而是有明确默认语义的降级路径；转写日志会记录实际生效的 protocol:model。
    # 显式配置了云端模型但凭证缺失时仍然抛错（不串用其它配置，审计 P1#8）。
    asr_model = audio_config.get("asr_model") or space_asr_cfg.get("model") or "faster-whisper-tiny"
    language = audio_config.get("language")

    # 引擎侧 audio_utils 不再 import setting；宿主在此从 YAML 配置构造 AudioConfig
    # 注入本地 faster-whisper 模型目录，切断 shared/knowledge -> setting 的导入边。
    from novamind.setting.yaml_config import get_config

    engine_audio_config = AudioConfig(
        local_whisper_model_dir=get_config().knowledge_base.parsing.local_whisper_model_dir,
        local_whisper_cpu_threads=get_config().knowledge_base.parsing.local_whisper_cpu_threads,
    )

    # 1. ASR 转写（根据协议路由：openai → Whisper / dashscope → Paraformer / local → faster-whisper）
    # 检查点：ASR 调用前（转写可能耗时较长，允许用户在此处取消）
    await check_document_cancelled(document.id)

    # ===== 批次 5b：用注入的 ModelConfigService，不再内部自建 ModelConfigService
    mcs = model_config_port

    # 凭证解析与协议分发抽成模块级函数（视频音轨复用同一路由）
    asr_protocol, asr_model, asr_api_key, asr_base_url = await _resolve_asr_route(
        document, mcs, asr_model
    )

    # ===== 解析快照命中检查（审计 P1#2：音频快照此前只写不读，RETRY 时 ASR
    # 全量白烧）。指纹形状与保存侧一致（audio:{protocol}:{model} 策略名），
    # 匹配即复用转写全文与时间线，跳过 ASR。
    audio_parse_fp = ""
    if SNAPSHOTS_ENABLED:
        audio_runtime_parsing = dict(pipeline_config.get("parsing", {}) or {})
        audio_runtime_parsing["strategy"] = f"audio:{asr_protocol}:{asr_model}"
        try:
            audio_parse_fp = compute_parse_fingerprint(document, audio_runtime_parsing)
        except Exception as fp_exc:
            logger.warning("音频解析指纹计算失败，不启用快照", document_id=document.id, error=str(fp_exc))

    if audio_parse_fp and snapshot_fingerprint(document, "parse") == audio_parse_fp:
        snap = await load_parse_snapshot(document, await _snap_minio(), logger)
        if snap and payload_fingerprint_matches(snap, "parse_fingerprint", audio_parse_fp):
            snap_text = str(snap.get("full_text") or "")
            if snap_text.strip():
                logger.info(
                    "音频解析快照命中，复用转写全文（跳过 ASR）",
                    document_id=document.id, char_count=len(snap_text),
                )
                if task:
                    await begin_step(session, task, "transcription_done")
                    await finish_step_committed(session, task, "transcription_done", metrics={"resumed": True})
                return await _audio_resume_tail(
                    document=document, session=session, task=task, logger=logger,
                    model_config_port=model_config_port, ctx=ctx,
                    splitting_config=dict(pipeline_config.get("splitting", {})),
                    full_text=snap_text, snap=snap,
                    parse_fingerprint=audio_parse_fp,
                    pipeline_config=pipeline_config,
                )
        logger.info("音频解析快照未命中/不可用，走全量 ASR", document_id=document.id)
        audio_parse_fp = ""  # 未命中置空：下方正常路径保存时按实际 protocol/model 重算

    logger.info(
        "音频转写开始", document_id=document.id,
        file_type=document.file_type, model=asr_model, protocol=asr_protocol,
    )

    # 本地/云端失败语义在调用方（锁获取/永久错误归因），此处只做协议分发
    async def _run_asr(
        protocol: str,
        model: str,
        api_key: str | None,
        base_url: str | None,
    ) -> list:
        return await _run_asr_transcription(
            file_content=file_content,
            file_type=document.file_type,
            protocol=protocol,
            model=model,
            api_key=api_key,
            base_url=base_url,
            language=language,
            engine_audio_config=engine_audio_config,
            document=document,
        )

    if task:
        await begin_step(session, task, "transcription_done")
    if asr_protocol == "local":
        # 本地 faster-whisper 模型 — 无需 API Key，无需网络。
        # 本地 ASR 忙碌时：直接抛 LocalASRBusyError，由 arq worker 延后重入队，
        # 不排队、不溢出云端，释放 Worker 槽位给其它文档处理任务。
        #
        # 关键：用 acquire_asr_or_busy() 非阻塞原子获取锁，消除竞态窗口。
        # 获取不到锁 = ASR 忙碌。
        from novamind.engines.document.media.audio import acquire_asr_or_busy

        asr_acquired = await acquire_asr_or_busy()
        if not asr_acquired:
            # ASR 忙碌：不排队也不溢出云端，直接延后重入队，
            # 释放 Worker 槽位给其它文档处理任务
            logger.info(
                "本地 ASR 忙碌，延后重入队",
                document_id=document.id,
            )
            raise LocalASRBusyError(document_id=document.id)
        else:
            # ASR 空闲，锁已获取。转写完成后在 finally 释放。
            try:
                segments = await _run_asr("local", asr_model, asr_api_key, asr_base_url)
            except AudioFileInvalidError as local_exc:
                # 文件本身损坏/过小/格式不支持是永久性错误——回退云端也救不了
                # （云端要解码同一个损坏文件，或文件根本不是有效音频），且会把根因
                # 藏到云端 FILE_DOWNLOAD_FAILED 之后让用户误以为是网络/MinIO 问题。
                # 直接抛清晰错误引导用户重新上传。
                raise PermanentProcessingError(
                    document_id=document.id,
                    error_message=(
                        f"音频文件损坏或不完整，无法转写: {local_exc}。"
                        f"请重新上传完整的音频文件。"
                    ),
                ) from local_exc
            except Exception as local_exc:
                # 本地 ASR 失败（模型缺失/加载失败等）：显式报错，不自动回退云端
                # ——自动回退会烧用户未授权的云端费用且解析路径不可追踪（审计
                # P1#8，与图片/视频路径的 no-fallback 决策对齐）。错误信息给出
                # 可操作的修复指引。
                raise PermanentProcessingError(
                    document_id=document.id,
                    error_message=(
                        f"本地 ASR 不可用: {local_exc}。请在配置 "
                        f"knowledge_base.parsing.local_whisper_model_dir 中补齐本地模型路径，"
                        f"或将知识库音频解析配置切换为云端 ASR 模型（dashscope/openai）。"
                    ),
                ) from local_exc
            finally:
                # 无论成功失败都释放 ASR 锁，让下一个任务可以进入
                from novamind.engines.document.media.audio import force_release_asr_slot
                force_release_asr_slot()
    else:
        segments = await _run_asr(asr_protocol, asr_model, asr_api_key, asr_base_url)
    logger.info(
        "音频转写完成", document_id=document.id, segment_count=len(segments),
    )

    # 检查点1：ASR 转写完成
    await check_document_cancelled(document.id)

    if not segments:
        # 转写结果为空不是错误——模型能力不足、音频质量差等都是正常情况。
        # 正常完成文档，0 chunk，不触发 arq 重试。
        logger.warning(
            "音频转写结果为空，文档将以空内容完成",
            document_id=document.id, filename=document.filename,
        )
        await persist_parsed_text(document, "", session, logger)
        if task:
            await finish_step_committed(session, task, "transcription_done", metrics={"segment_count": 0, "asr_protocol": asr_protocol})
        if task:
            task.mark_completed(result={
                "chunk_count": 0,
                "chunk_type": ChunkType.AUDIO,
                "segment_count": 0,
                "indexed_at": now_china().isoformat(),
            })
        await session.commit()
        return

    # 转写全文 MD 拼接并持久化到 MinIO（立刻 commit 落库）
    # 双锚点 [HH:MM:SS#seg_idx]：seg_idx 用 enumerate 原始 segments 顺序（跳过空文本仍占原序号，
    # 保持 anchor #idx 与 segment_timeline_map 键一致），切分后反查映射回 segment 时间区间。
    transcript_lines = []
    for seg_idx, seg in enumerate(segments):
        if not seg.get("text", "").strip():
            continue
        transcript_lines.append(f"{format_time_anchor(seg.get('start', 0), seg_idx)} {seg['text']}")
    segment_timeline_map = build_segment_timeline_map(segments)
    if not transcript_lines:
        logger.warning(
            "音频转写段落均为空文本，文档将以空内容完成",
            document_id=document.id, filename=document.filename,
        )
        await persist_parsed_text(document, "", session, logger)
        if task:
            await finish_step_committed(session, task, "transcription_done", metrics={"segment_count": len(segments), "asr_protocol": asr_protocol})
        if task:
            task.mark_completed(result={
                "chunk_count": 0,
                "chunk_type": ChunkType.AUDIO,
                "segment_count": len(segments),
                "indexed_at": now_china().isoformat(),
            })
        await session.commit()
        return

    full_text = "\n".join(transcript_lines)
    await persist_parsed_text(document, full_text, session, logger)

    # 断点续跑：计算解析指纹 + 保存带 time_alignment 的解析快照（resume 时免重跑 ASR）。
    audio_parse_fp = ""
    if SNAPSHOTS_ENABLED:
        audio_runtime_parsing = dict(pipeline_config.get("parsing", {}) or {})
        audio_runtime_parsing["strategy"] = f"audio:{asr_protocol}:{asr_model}"
        try:
            audio_parse_fp = compute_parse_fingerprint(document, audio_runtime_parsing)
        except Exception as fp_exc:
            logger.warning("音频解析指纹计算失败，不启用快照", document_id=document.id, error=str(fp_exc))
        if audio_parse_fp:
            from novamind.shared.storage.client_factory import ClientFactory as _CF

            try:
                snap_minio = await _CF.get_minio_client()
                await save_parse_snapshot(
                    document, session, logger,
                    minio_client=snap_minio,
                    parse_fingerprint=audio_parse_fp,
                    payload=build_parse_snapshot_payload(
                        parse_fingerprint=audio_parse_fp,
                        full_text=full_text,
                        parse_metadata=None,
                        time_alignment={"timeline_map": segment_timeline_map, "is_video": False},
                    ),
                )
            except Exception as snap_exc:
                logger.warning("音频解析快照保存失败（不影响主流程）", document_id=document.id, error=str(snap_exc))

    if task:
        await finish_step_committed(session, task, "transcription_done", metrics={"segment_count": len(segments), "asr_protocol": asr_protocol, "language": language})

    # 2-4. 切分/向量化/问题生成/索引：交由共享后置尾
    splitting_config = dict(pipeline_config.get("splitting", {}))
    tail_result = await run_post_parse_tail(
        document=document,
        session=session,
        task=task,
        model_config_port=model_config_port,
        logger=logger,
        chunk_type=ChunkType.AUDIO,
        embedding_config=ctx.embedding_config,
        pipeline_config=pipeline_config,
        splitting_config=splitting_config,
        full_text=full_text,
        time_alignment={"timeline_map": segment_timeline_map, "is_video": False},
        parse_fingerprint=audio_parse_fp or None,
        user_id=document.uploader_id,
    )

    # 4. 写入处理结果到 Task
    if task:
        task.mark_completed(result={
            "chunk_count": tail_result["chunk_count"],
            "chunk_type": ChunkType.AUDIO,
            "segment_count": len(segments),
            "indexed_at": now_china().isoformat(),
        })
    await session.commit()

    logger.info(
        "音频文档处理完成", document_id=document.id,
        chunks=tail_result["chunk_count"], segments=len(segments),
    )


# ========== 统一文本切分 ==========



