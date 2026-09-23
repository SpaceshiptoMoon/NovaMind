"""
音视频文档处理管道

处理流程：
- 视频: 提取关键帧 → VLM逐帧描述 → MD文本 → 统一文本切分 → Embedding → ES
- 音频: ASR转写 → MD文本 → 统一文本切分 → Embedding → ES
"""

from typing import Any

from novamind.engines.document.media.audio import (
    AudioFileInvalidError,
    transcribe_audio_local,
    transcribe_audio_with_timestamps,
)
from novamind.engines.document.media.chunk_time_alignment import (
    build_frame_timeline_map,
    build_segment_timeline_map,
    format_time_anchor,
)
from novamind.engines.document.media.video import (
    AllFrameDescriptionsFailedError,
    dedup_frame_diff,
    describe_grouped,
    describe_rewrite,
    describe_single,
    extract_frames_fixed,
    extract_frames_scene,
)
from novamind.features.knowledge_space.exceptions import DocumentProcessingError, LocalASRBusyError
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
    load_pipeline_context,
    persist_parsed_text,
    run_post_parse_tail,
)
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.config import AudioConfig
from novamind.shared.utils.time_utils import now_china
from sqlalchemy.ext.asyncio import AsyncSession


async def _find_cloud_asr_credentials(mcs, uploader_id: int, exclude_protocol: str = "local"):
    """在该用户的 ASR 模型配置中找一个非 local（云端）的可用凭证，用于本地 ASR 失败时回退。"""
    try:
        configs = await mcs.repo.list_by_user(uploader_id, "asr")
    except Exception:
        return None
    for cfg in configs:
        protocol = getattr(cfg, "protocol", None) or "openai"
        if protocol == exclude_protocol:
            continue
        creds = await mcs.get_credentials_by_model(uploader_id, "asr", cfg.model)
        if creds:
            return creds
    return None



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
        task.finish_step("descriptions_generated", metrics={"resumed": True})

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
    file_content: bytes,
    session: AsyncSession,
    logger,
    task: DocumentTask | None = None,
    model_config_port: ModelConfigService | None = None,
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
    dedup_similarity_threshold = video_config.get("dedup_similarity_threshold")
    group_size = video_config.get("group_size") or 3

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
                    task.finish_step("frames_extracted", metrics={"resumed": True, "frame_count": None})
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

    if strategy == "scene":
        scene_kwargs: dict[str, Any] = {}
        if scene_threshold is not None:
            scene_kwargs["scene_threshold"] = scene_threshold
        frames = await extract_frames_scene(file_content, max_frames, **scene_kwargs)
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
        task.finish_step("frames_extracted", metrics={"frame_count": len(frames)})

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
        raise DocumentProcessingError(
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
                concurrency=vlm_concurrency,
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
        elif strategy == "rewrite":
            # rewrite：逐帧 single 描述 + LLM 重写连贯（保留锚点）；返回 (full_text, descriptions)
            single_prompt = PromptManager.get_template("video_frame_description")
            rewrite_prompt = PromptManager.get_template("video_frame_rewrite_prompt")
            llm_model_name = await mcs.get_user_default_model_name(document.uploader_id, "llm")
            if not llm_model_name:
                raise DocumentProcessingError(
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
                concurrency=vlm_concurrency,
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
                concurrency=vlm_concurrency,
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
        task.finish_step("descriptions_generated", metrics={"description_count": descriptions_count})

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
    asr_model = audio_config.get("asr_model") or space_asr_cfg.get("model") or "whisper-1"
    language = audio_config.get("language")

    # 引擎侧 audio_utils 不再 import setting；宿主在此从 YAML 配置构造 AudioConfig
    # 注入本地 faster-whisper 模型目录，切断 shared/knowledge -> setting 的导入边。
    from novamind.setting.yaml_config import get_config

    engine_audio_config = AudioConfig(
        local_whisper_model_dir=get_config().knowledge_base.parsing.local_whisper_model_dir,
        local_whisper_cpu_threads=get_config().knowledge_base.parsing.local_whisper_cpu_threads,
    )

    # 1. ASR 转写（根据协议路由：openai → Whisper / dashscope → Paraformer / local → faster-whisper）
    from novamind.engines.document.media.audio import transcribe_audio_with_dashscope

    # 检查点：ASR 调用前（转写可能耗时较长，允许用户在此处取消）
    await check_document_cancelled(document.id)

    # ===== 批次 5b：用注入的 ModelConfigService，不再内部自建 ModelConfigService
    mcs = model_config_port

    # 先查 ASR 凭证（优先精确匹配）：快照指纹含实际生效的 protocol:model，
    # 必须在命中检查前确定（与保存快照时的指纹形状一致，否则永远 miss）。
    asr_api_key: str | None = None
    asr_base_url: str | None = None
    asr_protocol = "openai"  # 默认

    asr_creds = await mcs.get_credentials_by_model(document.uploader_id, "asr", asr_model)
    if not asr_creds:
        # 兜底：用户配的 ASR 模型名与 KB 默认名不一致，取该用户第一个 ASR 配置
        asr_configs = await mcs.repo.list_by_user(document.uploader_id, "asr")
        if asr_configs:
            asr_creds = await mcs.get_credentials_by_model(document.uploader_id, "asr", asr_configs[0].model)
    if asr_creds:
        asr_api_key = asr_creds.api_key
        asr_base_url = asr_creds.base_url
        asr_protocol = asr_creds.protocol or "openai"
        asr_model = asr_creds.model or asr_model  # 以实际凭证的模型名为准

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
                    task.finish_step("transcription_done", metrics={"resumed": True})
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

    # 路由 ASR 协议到具体转写实现。抽成内部函数，便于 local 失败时用云端凭证回退重试。
    async def _run_asr(
        protocol: str,
        model: str,
        api_key: str | None,
        base_url: str | None,
    ) -> list:
        if protocol == "local":
            return await transcribe_audio_local(
                file_content=file_content,
                file_type=document.file_type,
                language=language,
                audio_config=engine_audio_config,
            )
        if protocol == "dashscope":
            # 批次 6a-5：minio_client 由宿主装配获取后注入引擎函数（引擎不再 import ClientFactory）
            from novamind.shared.storage.client_factory import ClientFactory
            minio_client = await ClientFactory.get_minio_client()
            storage_info = document.get_storage_info()
            language_hints = [language] if language else None
            return await transcribe_audio_with_dashscope(
                file_content=file_content,
                file_type=document.file_type,
                model=model,
                api_key=api_key,
                base_url=base_url,
                minio_bucket=storage_info.get("minio_bucket"),
                language_hints=language_hints,
                minio_client=minio_client,
            )
        return await transcribe_audio_with_timestamps(
            file_content=file_content,
            file_type=document.file_type,
            model=model,
            api_key=api_key,
            base_url=base_url,
            language=language,
        )

    if task:
        await begin_step(session, task, "transcription_done")
    if asr_protocol == "local":
        # 本地 faster-whisper 模型 — 无需 API Key，无需网络。
        # 模型缺失/解码失败时，若用户配了云端 ASR，则回退云端，避免整任务硬失败。
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
            except Exception as local_exc:
                # 文件本身损坏/过小/格式不支持是永久性错误——回退云端也救不了
                # （云端要解码同一个损坏文件，或文件根本不是有效音频），且会把根因
                # 藏到云端 FILE_DOWNLOAD_FAILED 之后让用户误以为是网络/MinIO 问题。
                # 直接抛清晰错误引导用户重新上传。
                if isinstance(local_exc, AudioFileInvalidError):
                    raise DocumentProcessingError(
                        document_id=document.id,
                        error_message=(
                            f"音频文件损坏或不完整，无法转写: {local_exc}。"
                            f"请重新上传完整的音频文件。"
                        ),
                    ) from local_exc
                logger.warning(
                    "本地 ASR 失败，尝试回退云端 ASR",
                    document_id=document.id, error=str(local_exc),
                )
                cloud_creds = await _find_cloud_asr_credentials(mcs, document.uploader_id)
                if cloud_creds is None:
                    raise DocumentProcessingError(
                        document_id=document.id,
                        error_message=(
                            f"本地 ASR 不可用: {local_exc}。未找到可回退的云端 ASR 配置，"
                            f"请在模型管理中配置 dashscope/openai ASR，或在配置 "
                            f"knowledge_base.parsing.local_whisper_model_dir 中补齐本地模型路径。"
                        ),
                    ) from local_exc
                cloud_protocol = cloud_creds.protocol or "openai"
                logger.info(
                    "回退云端 ASR", document_id=document.id,
                    protocol=cloud_protocol, model=cloud_creds.model,
                )
                segments = await _run_asr(
                    cloud_protocol,
                    cloud_creds.model or asr_model,
                    cloud_creds.api_key,
                    cloud_creds.base_url,
                )
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
            task.finish_step("transcription_done", metrics={"segment_count": 0, "asr_protocol": asr_protocol})
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
            task.finish_step("transcription_done", metrics={"segment_count": len(segments), "asr_protocol": asr_protocol})
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
        task.finish_step("transcription_done", metrics={"segment_count": len(segments), "asr_protocol": asr_protocol, "language": language})

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



