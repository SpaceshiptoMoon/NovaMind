"""
音视频文档处理管道

处理流程：
- 视频: 提取关键帧 → VLM逐帧描述 → MD文本 → 统一文本切分 → Embedding → ES
- 音频: ASR转写 → MD文本 → 统一文本切分 → Embedding → ES
"""

from typing import List, Tuple, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.knowledge_space.exceptions import DocumentProcessingError, LocalASRBusyError
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.document_task import DocumentTask
from novamind.shared.model_config_ports import ModelConfigPort
from novamind.features.knowledge_space.services.document_pipeline import (
    _check_document_cancelled,
    load_pipeline_context,
    persist_parsed_text,
    _run_post_parse_tail,
)
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
    extract_video_frames,
)
from novamind.shared.utils.time_utils import now_china
from novamind.features.knowledge_space.schemas.knowledge_base_schema import build_runtime_parsing_config
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.shared.config import AudioConfig


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


async def maybe_semantic_embedding_client(
    strategy: str,
    embedding_config: Dict[str, Any],
    session: AsyncSession,
    user_id: int,
    model_config_port: Optional[ModelConfigPort] = None,
):
    """strategy == "semantic" 时返回语义切分所需的 embedding_client，否则返回 None。

    延迟导入 _get_embedding_client_static 以避免 document_pipeline ↔ media_processing 循环导入。
    批次 5b：model_config_port 由调用方注入，透传至 _get_embedding_client_static。
    """
    if strategy != "semantic":
        return None
    from novamind.features.knowledge_space.services.document_pipeline import (
        _get_embedding_client_static,
    )

    return await _get_embedding_client_static(
        session=session,
        user_id=user_id,
        model_name=embedding_config.get("model"),
        model_config_port=model_config_port,
    )


async def process_video_document(
    document: Document,
    file_content: bytes,
    session: AsyncSession,
    logger,
    task: Optional[DocumentTask] = None,
    model_config_port: Optional[ModelConfigPort] = None,
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
    # 高级参数（可选，留空用引擎层默认）
    scene_threshold = video_config.get("scene_threshold")
    dedup_similarity_threshold = video_config.get("dedup_similarity_threshold")
    group_size = video_config.get("group_size") or 3

    # 批次 5b：用注入的 ModelConfigPort
    mcs = model_config_port

    # dedup_grouped 策略预留：图像 embedding 去重待 IMAGE_EMBEDDING 模型类型引入后实现
    if strategy == "dedup_grouped":
        raise DocumentProcessingError(
            document_id=document.id,
            error_message=(
                f"视频 {document.filename} 选用策略 dedup_grouped 暂未实现"
                "（图像 embedding 去重待引入），请改用 simple/scene/dedup/grouped/rewrite 策略"
            ),
        )

    # 1. 提取帧（按 strategy 路由：scene 场景抽帧，其余固定间隔）
    logger.info(
        "视频帧提取开始", document_id=document.id,
        strategy=strategy, interval=frame_interval, max_frames=max_frames,
    )
    if task:
        task.start_step("frames_extracted")
    if strategy == "scene":
        scene_kwargs: Dict[str, Any] = {}
        if scene_threshold is not None:
            scene_kwargs["scene_threshold"] = scene_threshold
        frames = await extract_frames_scene(file_content, max_frames, **scene_kwargs)
    else:
        frames = await extract_frames_fixed(file_content, frame_interval, max_frames)
    logger.info(
        "视频帧提取完成", document_id=document.id, frame_count=len(frames),
    )

    # 检查点1：帧提取完成
    await _check_document_cancelled(document.id)

    if not frames:
        raise DocumentProcessingError(
            document_id=document.id,
            error_message=f"视频 {document.filename} 未能提取到任何帧",
        )

    # 1.5 去重（dedup 策略：相邻帧直方图相似度去重，frame_idx 重映射为连续序号）
    if strategy == "dedup":
        dedup_kwargs: Dict[str, Any] = {}
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
    # frame_idx 空洞：engines 抽帧在 _read_frame_at 返回 None 或抛错时跳过该帧但 frame_idx
    # 仍递增（video_utils.py / frame_extraction.py 的 enumerate+continue 模式），若 frame_paths
    # 按位置 append 会与 frame_idx 错位 → ES chunk 帧图指向错误帧或丢失。dict 映射让
    # _build_es_chunks 按 frame_idx 精确取帧，空洞 idx 自动跳过。dedup 策略因 dedup_frame_diff
    # 已用 len(kept) 重映射连续 idx 而天然免疫，此处 dict 同样兼容。
    frame_paths: Dict[int, str] = {}
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

    # 帧上传后立即持久化 storage["frames"]，确保后续切分/嵌入/索引（_run_post_parse_tail）
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
        task.start_step("descriptions_generated")
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

    cancelled_check = lambda: _check_document_cancelled(document.id)
    base_log_ctx: Dict[str, Any] = {"document_id": document.id}

    # 双锚点 [HH:MM:SS#frame_idx]：时间戳给人看，#frame_idx 给切分后反查唯一映射回帧时间区间。
    # 帧时间线 {frame_idx: (start_sec, end_sec)}，end = 下一帧 ts（末帧 end=None，末尾开放区间）。
    # 切分后 align_chunk_times 据此把 chunk 反查到的 #idx 映射成 start_time/end_time。
    full_text = ""
    frame_timeline_map: Dict[int, Tuple[Optional[float], Optional[float]]] = {}
    frame_groups: Optional[Dict[int, List[int]]] = None
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
            )
            lines: List[str] = []
            frame_groups = {}
            timeline_input: List[Tuple[str, float, int]] = []
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

    if task:
        task.finish_step("descriptions_generated", metrics={"description_count": descriptions_count})

    # 3-5. 切分/向量化/问题生成/索引：交由共享后置尾
    tail_result = await _run_post_parse_tail(
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
    task: Optional[DocumentTask] = None,
    model_config_port: Optional[ModelConfigPort] = None,
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
    await _check_document_cancelled(document.id)

    # 批次 5b：用注入的 ModelConfigPort，不再内部自建 ModelConfigService
    mcs = model_config_port

    # 从模型配置系统查找 ASR 凭证（优先精确匹配，找不到用该用户任意 ASR 配置兜底）
    asr_api_key: Optional[str] = None
    asr_base_url: Optional[str] = None
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

    logger.info(
        "音频转写开始", document_id=document.id,
        file_type=document.file_type, model=asr_model, protocol=asr_protocol,
    )

    # 路由 ASR 协议到具体转写实现。抽成内部函数，便于 local 失败时用云端凭证回退重试。
    async def _run_asr(
        protocol: str,
        model: str,
        api_key: Optional[str],
        base_url: Optional[str],
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
        task.start_step("transcription_done")
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
                from novamind.engines.document.media.audio import _asr_busy_lock
                if _asr_busy_lock.locked():
                    _asr_busy_lock.release()
    else:
        segments = await _run_asr(asr_protocol, asr_model, asr_api_key, asr_base_url)
    logger.info(
        "音频转写完成", document_id=document.id, segment_count=len(segments),
    )

    # 检查点1：ASR 转写完成
    await _check_document_cancelled(document.id)

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

    if task:
        task.finish_step("transcription_done", metrics={"segment_count": len(segments), "asr_protocol": asr_protocol, "language": language})

    # 2-4. 切分/向量化/问题生成/索引：交由共享后置尾
    splitting_config = dict(pipeline_config.get("splitting", {}))
    tail_result = await _run_post_parse_tail(
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


def _split_line_aware(md_text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """按行累积切分，绝不切进「[HH:MM:SS#idx] 描述」行内部，保证锚点不分家。

    供 fixed_size 与 recursive 在 line_aware=True 时共用（音视频带时间锚点文本）。
    单行超 chunk_size 时整行成一块（oversized），正确性优先于尺寸软上限。
    overlap 用「保留尾部若干行使其字符和 ≈ chunk_overlap」实现（行单位 overlap）。
    抽自原 fixed_size line_aware 内联实现，供 recursive 复用修复 B3/B4：
    grouped 组描述 >chunk_size 时原 recursive 分隔符层级退到行内，把行首锚点切到
    上一个 chunk、描述切到下一个 chunk，导致 align_chunk_times 丢时间对齐。
    """
    lines = md_text.split("\n")
    chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0
    for line in lines:
        addition = len(line) + (1 if buf else 0)  # 非首行加 \n 连接符长度
        if buf and buf_len + addition > chunk_size:
            chunks.append("\n".join(buf))
            # overlap：从尾部回溯取若干行，使其字符和 ≥ chunk_overlap 即停
            tail: List[str] = []
            tail_len = 0
            for tl in reversed(buf):
                if tail and tail_len + len(tl) >= chunk_overlap:
                    break
                tail.insert(0, tl)
                tail_len += len(tl) + (1 if len(tail) > 1 else 0)
            buf = tail
            buf_len = sum(len(l) for l in tail) + max(0, len(tail) - 1)
        buf.append(line)
        buf_len += addition
    if buf:
        chunks.append("\n".join(buf))
    return [c for c in chunks if c.strip()]


async def _split_md_text(
    md_text: str,
    strategy: str = "recursive",
    embedding_client=None,
    line_aware: bool = False,
    **kwargs,
) -> List[Tuple[str, Dict[str, Any]]]:
    """
    将 MD/纯文本按指定策略切分为 chunks

    Args:
        md_text: 待切分的文本内容
        strategy: 切分策略 (recursive / markdown / fixed_size / semantic)
        line_aware: 仅 fixed_size / recursive 生效——True 时按行累积切分（音视频带
            [HH:MM:SS#idx] 锚点文本，避免切进「[锚点] 描述」行内部导致锚点分家）；
            False 时按字符/分隔符切（图片等无锚点文本）。由调用方据 time_alignment
            是否非空决定（音视频 True，图片/文本 False）。
        **kwargs: 策略相关参数 (chunk_size, chunk_overlap, min_chunk_size, max_chunk_size 等)

    Returns:
        [(text, metadata_dict), ...] — metadata 目前为空 dict，后续可扩展携带标题/层级
    """
    from novamind.engines.document.pipeline import DocumentRegistry

    splitter_class = DocumentRegistry.get_splitter_class(strategy)
    if splitter_class is None:
        raise ValueError(
            f"不支持的切分策略: {strategy}，可用策略: {DocumentRegistry.get_available_strategies()}"
        )

    if strategy == "recursive":
        chunk_size = kwargs.get("chunk_size", 2000)
        chunk_overlap = kwargs.get("chunk_overlap", 50)
        min_chunk_size = kwargs.get("min_chunk_size", 500)
        if line_aware:
            # 音视频带 [HH:MM:SS#idx] 锚点文本：按行边界切，避免组描述 >chunk_size 时
            # recursive 分隔符层级退到行内把锚点切分家（B3/B4）。min_chunk_size 不适用行模式。
            return [(c, {}) for c in _split_line_aware(md_text, chunk_size, chunk_overlap)]
        splitter = splitter_class(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            min_chunk_size=min_chunk_size,
        )
        chunk_texts = await splitter._split_text(md_text)
        return [(text, {}) for text in chunk_texts if text.strip()]

    elif strategy == "markdown":
        from novamind.engines.document.splitters import MarkdownSplitter
        max_chunk_size = kwargs.get("max_chunk_size", 1000)
        min_chunk_size = kwargs.get("min_chunk_size", 50)
        splitter = MarkdownSplitter(
            max_chunk_size=max_chunk_size,
            min_chunk_size=min_chunk_size,
        )
        doc_wrapper = [{
            "text": md_text,
            "source": "media_pipeline",
            "page": 1,
            "doc_id": "0",
            "type": "markdown",
            "title": "",
        }]
        results = await splitter.split(doc_wrapper)
        return [(r["text"], {}) for r in results if r.get("text", "").strip()]

    elif strategy == "fixed_size":
        chunk_size = kwargs.get("chunk_size", 500)
        chunk_overlap = kwargs.get("chunk_overlap", 0)
        if line_aware:
            # 行边界对齐版（音视频带 [HH:MM:SS#idx] 锚点文本）：抽公共 _split_line_aware，
            # 与 recursive 共用，绝不切进「[锚点] 描述」行内部，保证锚点反查不错位。
            return [(c, {}) for c in _split_line_aware(md_text, chunk_size, chunk_overlap)]
        # 字符切（图片等无锚点文本）：原 FixedSizeSplitter 行为
        splitter = splitter_class(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        doc_wrapper = [{
            "text": md_text,
            "source": "media_pipeline",
            "page": 1,
            "doc_id": "0",
            "type": "text",
        }]
        results = await splitter.split(doc_wrapper)
        return [(r["text"], {}) for r in results if r.get("text", "").strip()]

    elif strategy == "semantic":
        max_chunk_size = kwargs.get("max_chunk_size", 1000)
        similarity_threshold = kwargs.get("similarity_threshold", 0.7)
        batch_size = kwargs.get("batch_size", 20)
        if embedding_client is None:
            raise ValueError("semantic splitting requires embedding_client")
        splitter = splitter_class(
            embedding_client=embedding_client,
            max_chunk_size=max_chunk_size,
            similarity_threshold=similarity_threshold,
            batch_size=batch_size,
        )
        doc_wrapper = [{
            "text": md_text,
            "source": "media_pipeline",
            "page": 1,
            "doc_id": "0",
            "type": "text",
        }]
        results = await splitter.split(doc_wrapper)
        return [(r["text"], {}) for r in results if r.get("text", "").strip()]

    else:
        # 其他策略兜底：尝试作为文档切分器处理
        doc_wrapper = [{
            "text": md_text,
            "source": "media_pipeline",
            "page": 1,
            "doc_id": "0",
            "type": "text",
        }]
        splitter = splitter_class(**kwargs)
        results = await splitter.split(doc_wrapper)
        return [(r["text"], {}) for r in results if r.get("text", "").strip()]
