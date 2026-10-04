"""视频帧描述引擎：single 逐帧 VLM / grouped 分组多图 / rewrite 逐帧后重写连贯，三种描述策略，纯逻辑层全注入。
single 主 client 配额/鉴权失败且有 fallback client 时回退重试一次；rewrite 校验锚点 idx 集合，不一致回退原逐帧拼接。
所有产出带 [HH:MM:SS#idx] 锚点（格式契约，供 align_chunk_times 切分后反查时间区间）；不碰 model_config_port/PromptManager。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from novamind.engines.document.media.chunk_time_alignment import (
    extract_anchor_indices,
    format_time_anchor,
)
from novamind.engines.document.media.vlm import (
    build_image_data_url,
    build_vlm_image_messages,
    build_vlm_multi_image_messages,
    generate_vlm_text_with_fallback,
)

logger = logging.getLogger(__name__)

# 配额/鉴权类错误谓词：返回 True 表示该异常属可降级的配额/鉴权类（触发 fallback 或跳过）。
QuotaErrorPredicate = Callable[[BaseException], bool]
# 取消检查回调：async，无参，抛异常即表示任务被取消。
CancelledCheck = Callable[[], Awaitable[Any]]

# 帧描述单图 / 多图 / 重写的默认 token 上限与温度。
_DEFAULT_SINGLE_MAX_TOKENS = 1024
_DEFAULT_GROUPED_MAX_TOKENS = 2048
_DEFAULT_REWRITE_MAX_TOKENS = 2048
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_MAX_DESC_LEN = 500


class AllFrameDescriptionsFailedError(Exception):
    """所有帧的 VLM 描述均失败。

    由 ``describe_single`` / ``describe_grouped`` 在全部帧/组均无成功描述时抛出，
    携带首个错误、配额/鉴权类失败计数、总帧数，供 features 编排层按
    ``vlm_skip_on_quota_error`` 决策写占位描述或转 ``DocumentProcessingError``。
    """

    def __init__(
        self,
        *,
        first_error: BaseException | None = None,
        quota_failures: int = 0,
        total_frames: int = 0,
    ):
        """记录首个错误、配额类失败计数与总帧数，供编排层决策占位或转错误。"""
        self.first_error = first_error
        self.quota_failures = quota_failures
        self.total_frames = total_frames
        detail = f"，首个错误: {first_error}" if first_error else ""
        super().__init__(f"所有 {total_frames} 帧/组的 VLM 描述均失败{detail}")


async def describe_single(
    frames: list[tuple[bytes, float, int]],
    vlm_client: Any,
    prompt: str,
    *,
    logger: Any = logger,
    vlm_model: str = "",
    max_tokens: int = _DEFAULT_SINGLE_MAX_TOKENS,
    temperature: float = _DEFAULT_TEMPERATURE,
    max_desc_len: int = _DEFAULT_MAX_DESC_LEN,
    vlm_fallback_client: Any | None = None,
    vlm_fallback_model: str | None = None,
    is_quota_error: QuotaErrorPredicate | None = None,
    log_context: dict[str, Any] | None = None,
    cancelled_check: CancelledCheck | None = None,
    cancel_every: int = 5,
    concurrency: int = 4,
    stats: dict[str, int] | None = None,
) -> list[tuple[str, float, int]]:
    """逐帧单图 VLM 描述（有界并发）。

    返回 ``[(desc, ts, frame_idx), ...]``，按帧顺序。单帧失败记录 warning 并跳过；主 client
    配额/鉴权失败且配置了 ``vlm_fallback_client`` 时回退重试一次。全部帧失败抛
    ``AllFrameDescriptionsFailedError``。``concurrency`` 控制 VLM 逐帧并发数（默认 4），
    缓解长视频串行逼近 arq job_timeout；用 ``asyncio.Semaphore``+``gather`` 保序、保
    quota 累计、保 fallback、保取消检查。

    ``stats`` 传入 dict 时写入 ``{"failed": 部分失败帧数}``（含空响应帧；全失败
    抛错路径不写），供编排层把失败帧计入 task metrics——单帧 VLM 失败不再静默留洞。
    """
    base_ctx: dict[str, Any] = dict(log_context or {})
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _describe_one(i: int, frame_bytes: bytes, ts: float, frame_idx: int):
        # 并发下每个 worker 起跑前按原 cadence 各查一次取消
        if cancelled_check is not None and i > 0 and (cancel_every <= 1 or i % cancel_every == 0):
            await cancelled_check()
        async with sem:
            messages = build_vlm_image_messages(frame_bytes, "image/jpeg", prompt)
            frame_ctx = {**base_ctx, "frame_index": frame_idx}
            try:
                desc = await generate_vlm_text_with_fallback(
                    vlm_client, messages,
                    max_tokens=max_tokens, temperature=temperature,
                    logger=logger, vlm_model=vlm_model, log_context=frame_ctx,
                )
            except Exception as exc:
                is_quota = is_quota_error is not None and is_quota_error(exc)
                if is_quota and vlm_fallback_client is not None:
                    logger.warning(
                        "视频帧VLM主模型配额/鉴权失败，回退备用模型",
                        fallback_model=vlm_fallback_model, frame_index=frame_idx,
                        error=str(exc), **base_ctx,
                    )
                    try:
                        desc = await generate_vlm_text_with_fallback(
                            vlm_fallback_client, messages,
                            max_tokens=max_tokens, temperature=temperature,
                            logger=logger, vlm_model=vlm_fallback_model or "", log_context=frame_ctx,
                        )
                    except Exception as fb_exc:
                        logger.warning(
                            "视频帧VLM备用模型也失败, 跳过",
                            frame_index=frame_idx, error=str(fb_exc), **base_ctx,
                        )
                        return (frame_idx, ts, None, fb_exc, is_quota)
                else:
                    logger.warning(
                        "视频帧VLM描述失败, 跳过",
                        frame_index=frame_idx, error=str(exc), **base_ctx,
                    )
                    return (frame_idx, ts, None, exc, is_quota)
            if desc and desc.strip():
                return (frame_idx, ts, desc.strip()[:max_desc_len], None, False)
            return (frame_idx, ts, None, None, False)

    raw = await asyncio.gather(*[
        _describe_one(i, fb, ts, fi)
        for i, (fb, ts, fi) in enumerate(frames)
    ])

    # gather 保序；按帧顺序汇总描述、首个错误、配额失败计数
    descriptions: list[tuple[str, float, int]] = []
    first_error: BaseException | None = None
    quota_failures = 0
    failed = 0
    for frame_idx, ts, desc, exc, was_quota in raw:
        if desc is not None:
            descriptions.append((desc, ts, frame_idx))
        else:
            failed += 1
            if exc is not None:
                if first_error is None:
                    first_error = exc
                if was_quota:
                    quota_failures += 1

    if not descriptions:
        raise AllFrameDescriptionsFailedError(
            first_error=first_error, quota_failures=quota_failures, total_frames=len(frames),
        )
    if stats is not None:
        stats["failed"] = failed
    return descriptions


async def describe_grouped(
    frames: list[tuple[bytes, float, int]],
    group_size: int,
    vlm_client: Any,
    prompt: str,
    *,
    logger: Any = logger,
    vlm_model: str = "",
    max_tokens: int = _DEFAULT_GROUPED_MAX_TOKENS,
    temperature: float = _DEFAULT_TEMPERATURE,
    max_desc_len: int = _DEFAULT_MAX_DESC_LEN * 4,
    vlm_fallback_client: Any | None = None,
    vlm_fallback_model: str | None = None,
    is_quota_error: QuotaErrorPredicate | None = None,
    log_context: dict[str, Any] | None = None,
    cancelled_check: CancelledCheck | None = None,
    cancel_every: int = 1,
    concurrency: int = 4,
    stats: dict[str, int] | None = None,
) -> list[tuple[str, float, float, list[int]]]:
    """多帧一组喂 VLM 多图消息生成连贯描述。

    返回 ``[(desc, start_ts, end_ts, frame_idx_list), ...]``，锚点用组首帧 idx。
    ``group_size <= 1`` 时退化为逐帧 single（每帧自成一组）。
    某组多图调用失败时该组降级为逐帧 single 描述，不阻塞整体；全部组失败抛
    ``AllFrameDescriptionsFailedError``。

    ``stats`` 传入 dict 时写入 ``{"failed": 彻底失败组的帧数合计}``（组多图失败
    且逐帧回退也全失败的组），供编排层计入 task metrics。
    """
    base_ctx: dict[str, Any] = dict(log_context or {})

    if group_size <= 1 or len(frames) <= 1:
        singles = await describe_single(
            frames, vlm_client, prompt,
            logger=logger, vlm_model=vlm_model,
            max_tokens=_DEFAULT_SINGLE_MAX_TOKENS, temperature=temperature,
            max_desc_len=_DEFAULT_MAX_DESC_LEN,
            vlm_fallback_client=vlm_fallback_client, vlm_fallback_model=vlm_fallback_model,
            is_quota_error=is_quota_error, log_context=base_ctx,
            cancelled_check=cancelled_check, cancel_every=5,
            concurrency=concurrency,
        )
        return [(desc, ts, ts, [idx]) for desc, ts, idx in singles]

    groups = [frames[i:i + group_size] for i in range(0, len(frames), group_size)]
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _describe_group(gi: int, group: list[tuple[bytes, float, int]]) -> dict[str, Any]:
        if cancelled_check is not None and gi > 0 and (cancel_every <= 1 or gi % cancel_every == 0):
            await cancelled_check()
        frames_bytes = [fb for fb, _, _ in group]
        idx_list = [idx for _, _, idx in group]
        start_ts = group[0][1]
        end_ts = group[-1][1]
        group_ctx = {**base_ctx, "group_index": gi, "frame_indices": idx_list}
        messages = build_vlm_multi_image_messages(frames_bytes, "image/jpeg", prompt)
        result: dict[str, Any] = {
            "gi": gi, "ok": False, "desc": None, "start_ts": start_ts, "end_ts": end_ts,
            "idx_list": idx_list, "main_exc": None, "single_quota": 0,
            "single_first_error": None, "singles": None,
        }
        async with sem:
            try:
                desc = await generate_vlm_text_with_fallback(
                    vlm_client, messages,
                    max_tokens=max_tokens, temperature=temperature,
                    logger=logger, vlm_model=vlm_model, log_context=group_ctx,
                )
            except Exception as exc:
                result["main_exc"] = exc
                logger.warning(
                    "grouped 多图VLM失败，该组降级逐帧描述",
                    group_index=gi, error=str(exc), **base_ctx,
                )
                # single 回退用 concurrency=1 串行，避免组级并发叠加帧级并发触发配额 burst
                try:
                    singles = await describe_single(
                        group, vlm_client, prompt,
                        logger=logger, vlm_model=vlm_model,
                        max_tokens=_DEFAULT_SINGLE_MAX_TOKENS, temperature=temperature,
                        max_desc_len=_DEFAULT_MAX_DESC_LEN,
                        vlm_fallback_client=vlm_fallback_client, vlm_fallback_model=vlm_fallback_model,
                        is_quota_error=is_quota_error, log_context=base_ctx,
                        concurrency=1,
                    )
                except AllFrameDescriptionsFailedError as single_err:
                    result["single_quota"] = single_err.quota_failures
                    result["single_first_error"] = single_err.first_error
                else:
                    result["singles"] = singles
                return result
            if desc and desc.strip():
                result["ok"] = True
                result["desc"] = desc.strip()[:max_desc_len]
            return result

    group_results = await asyncio.gather(*[
        _describe_group(gi, g) for gi, g in enumerate(groups)
    ])

    # 按 gi 顺序合并（gather 保序，显式排序防语义漂移）
    results: list[tuple[str, float, float, list[int]]] = []
    first_error: BaseException | None = None
    any_group_succeeded = False
    quota_failures = 0
    failed_frames = 0
    for r in sorted(group_results, key=lambda x: x["gi"]):
        if r["ok"]:
            results.append((r["desc"], r["start_ts"], r["end_ts"], r["idx_list"]))
            any_group_succeeded = True
            continue
        if r["singles"]:
            for s_desc, s_ts, s_idx in r["singles"]:
                results.append((s_desc, s_ts, s_ts, [s_idx]))
                any_group_succeeded = True
            continue
        # 组彻底失败：记首个错误 + 累计 single 回退的配额失败数（single 实际逐帧统计，权威）
        if first_error is None:
            first_error = r["main_exc"] or r["single_first_error"]
        quota_failures += r["single_quota"]
        failed_frames += len(r["idx_list"])

    if not any_group_succeeded:
        raise AllFrameDescriptionsFailedError(
            first_error=first_error,
            quota_failures=min(quota_failures, len(frames)),
            total_frames=len(frames),
        )
    if stats is not None:
        stats["failed"] = failed_frames
    return results


async def describe_rewrite(
    frames: list[tuple[bytes, float, int]],
    vlm_client: Any,
    llm_client: Any,
    single_prompt: str,
    rewrite_prompt: str,
    *,
    logger: Any = logger,
    vlm_model: str = "",
    llm_model: str = "",
    max_tokens: int = _DEFAULT_SINGLE_MAX_TOKENS,
    rewrite_max_tokens: int = _DEFAULT_REWRITE_MAX_TOKENS,
    temperature: float = _DEFAULT_TEMPERATURE,
    max_desc_len: int = _DEFAULT_MAX_DESC_LEN,
    vlm_fallback_client: Any | None = None,
    vlm_fallback_model: str | None = None,
    is_quota_error: QuotaErrorPredicate | None = None,
    log_context: dict[str, Any] | None = None,
    cancelled_check: CancelledCheck | None = None,
    cancel_every: int = 5,
    concurrency: int = 4,
    stats: dict[str, int] | None = None,
) -> tuple[str, list[tuple[str, float, int]]]:
    """逐帧描述 + LLM 重写连贯，保留 ``[HH:MM:SS#idx]`` 锚点。

    流程：
    1. ``describe_single`` 逐帧得带锚点描述 ``[(desc, ts, idx)]``；
    2. 拼接成 ``[HH:MM:SS#idx] desc`` 逐行文本喂 LLM，``rewrite_prompt`` 强约束「只润色描述内容、
       保留锚点格式与逐行结构、不合并/删除帧段」；
    3. 后处理校验输出锚点 idx 集合 == 输入帧 idx 集合，不一致或 LLM 失败/空输出则回退原逐帧拼接。

    返回 ``(full_text, descriptions)``：``full_text`` 为带锚点的最终 md（成功=LLM 重写输出，
    回退=原逐帧拼接），``descriptions`` 为原 single 列表（供 ``build_frame_timeline_map`` 构建时间线）。
    ``stats`` 透传 describe_single（写 failed 计数）。
    """
    base_ctx: dict[str, Any] = dict(log_context or {})

    # 1. 逐帧 single 描述（带锚点反查所需的 ts/idx）
    descriptions = await describe_single(
        frames, vlm_client, single_prompt,
        logger=logger, vlm_model=vlm_model,
        max_tokens=max_tokens, temperature=temperature, max_desc_len=max_desc_len,
        vlm_fallback_client=vlm_fallback_client, vlm_fallback_model=vlm_fallback_model,
        is_quota_error=is_quota_error, log_context=base_ctx,
        cancelled_check=cancelled_check, cancel_every=cancel_every,
        concurrency=concurrency, stats=stats,
    )

    # 2. 拼接带锚点文本
    lines = [f"{format_time_anchor(ts, idx)} {desc}" for desc, ts, idx in descriptions]
    joined = "\n\n".join(lines)

    # 3. LLM 重写
    rewrite_messages = [{
        "role": "user",
        "content": f"{rewrite_prompt}\n\n--- 以下为待润色的逐帧描述 ---\n{joined}",
    }]
    try:
        rewritten = await llm_client.generate_text(
            prompt=rewrite_messages,
            max_tokens=rewrite_max_tokens,
            temperature=temperature,
        )
    except Exception as exc:
        logger.warning("rewrite LLM重写失败，回退原逐帧描述", error=str(exc), **base_ctx)
        return joined, descriptions

    if not rewritten or not rewritten.strip():
        logger.warning("rewrite LLM返回空，回退原逐帧描述", **base_ctx)
        return joined, descriptions

    # 4. 校验锚点 idx 集合一致
    original_idxs = [idx for _, _, idx in descriptions]
    rewritten_idxs = extract_anchor_indices(rewritten)
    if sorted(rewritten_idxs) != sorted(original_idxs):
        logger.warning(
            "rewrite 锚点数不一致，回退原逐帧描述",
            original_count=len(original_idxs), rewritten_count=len(rewritten_idxs),
            **base_ctx,
        )
        return joined, descriptions

    return rewritten.strip(), descriptions


# 帧序列伪视频：单次请求帧数硬限（DashScope 帧列表模式 4-512 张），引擎侧再防一道。
_FRAME_SEQ_MAX_FRAMES = 512
# 帧序列伪视频段级 token 上限（一段描述多个帧，比 single 宽、比 grouped 略宽）。
_DEFAULT_FRAME_SEQ_MAX_TOKENS = 4096
# 帧序列伪视频段描述长度上限（一段覆盖多帧，比单帧 500 字放宽）。
_FRAME_SEQ_MAX_DESC_LEN = _DEFAULT_MAX_DESC_LEN * 4


def _plan_frame_sequence_chunks(
    n_frames: int,
    chunk_frames: int,
    min_tail_frames: int,
) -> list[tuple[int, int]]:
    """把 n 帧切为若干 [start, end) 段（每段 ≤ chunk_frames），尾段过短并入前段。

    固定 size 切分（前段各 chunk_frames 帧、尾段为余数），尾段帧数 <
    min_tail_frames 时并入前段——前段最多达 chunk_frames + min_tail_frames - 1，
    由调用方保证总和不超服务商 512 张硬限（chunk_frames 默认 512 时尾并后
    ≤ 519，DashScope 按 512 拒绝则该段失败走跳过路径，配置层已约束）。

    Args:
        n_frames: 总帧数（>0）。
        chunk_frames: 每段帧数上限（>0）。
        min_tail_frames: 尾段最小帧数，不足则并入前段。

    Returns:
        ``[(start, end), ...]`` 段边界列表（左闭右开，升序连续覆盖全部帧）。
    """
    if n_frames <= chunk_frames:
        return [(0, n_frames)]
    chunks: list[tuple[int, int]] = [
        (s, min(s + chunk_frames, n_frames))
        for s in range(0, n_frames, chunk_frames)
    ]
    if len(chunks) >= 2 and (chunks[-1][1] - chunks[-1][0]) < min_tail_frames:
        prev_start, _ = chunks[-2]
        last_end = chunks[-1][1]
        chunks[-2:] = [(prev_start, last_end)]
    return chunks


def _format_frame_time_table(frames: list[tuple[bytes, float, int]]) -> str:
    """格式化帧时刻表（prompt 注入用），如 ``帧#0=12.5s 帧#1=17.5s ...``。

    实测帧序列模式时间定位系统性偏 ~1s，prompt 显式给帧时刻可校准。
    """
    return " ".join(f"帧#{idx}={ts:.1f}s" for _, ts, idx in frames)


async def describe_frame_sequence(
    frames: list[tuple[bytes, float, int]],
    vlm_client: Any,
    prompt_template: str,
    *,
    fps: float,
    logger: Any = logger,
    vlm_model: str = "",
    chunk_frames: int = _FRAME_SEQ_MAX_FRAMES,
    min_tail_frames: int = 8,
    max_tokens: int = _DEFAULT_FRAME_SEQ_MAX_TOKENS,
    temperature: float = _DEFAULT_TEMPERATURE,
    max_desc_len: int = _FRAME_SEQ_MAX_DESC_LEN,
    log_context: dict[str, Any] | None = None,
    cancelled_check: CancelledCheck | None = None,
    concurrency: int = 2,
    stats: dict[str, int] | None = None,
) -> list[tuple[str, float, float, list[int]]]:
    """帧序列伪视频描述（S3）：整段帧以 ``{"type":"video","video":[...],"fps":N}``
    喂 VLM，模型感知时序。

    长视频按 ``chunk_frames``（DashScope 帧列表 4-512 张硬限）固定 size 分段，
    尾段帧数 < ``min_tail_frames`` 并入前段；每段 prompt 注入帧时刻表校准时间
    定位（实测帧序列模式有 ~1s 系统性偏移）。段间有界并发（默认 2，伪视频
    请求体大、网关超时风险高，不与逐帧并发同档）。

    Args:
        frames: 全量帧 ``[(jpeg_bytes, ts, frame_idx), ...]``，须按时间升序。
        vlm_client: 须提供 ``generate_text_from_frames``（openai_video 协议客户端）。
        prompt_template: 描述指令模板，含 ``{time_table}`` 占位符。
        fps: 相邻帧间隔倒数（固定间隔抽帧 = 1/frame_interval）。
        logger: 日志器。
        vlm_model: 模型名（日志上下文）。
        chunk_frames: 每段帧数上限。
        min_tail_frames: 尾段最小帧数，不足并入前段。
        max_tokens: 生成 token 上限。
        temperature: 采样温度。
        max_desc_len: 单段描述长度上限。
        log_context: 附加日志键值。
        cancelled_check: 取消检查回调（每段起跑前查）。
        concurrency: 段间并发上限。
        stats: 传入 dict 时写 ``{"failed": 失败段覆盖帧数合计}``。

    Returns:
        ``[(desc, start_ts, end_ts, idx_list), ...]`` 按时间升序，与
        ``describe_grouped`` 同构；段锚点 = 段首帧 idx。

    Raises:
        AttributeError: vlm_client 无 ``generate_text_from_frames``（协议未配 openai_video）。
        AllFrameDescriptionsFailedError: 所有段均失败。
    """
    if not frames:
        return []

    gen = getattr(vlm_client, "generate_text_from_frames", None)
    if gen is None:
        raise AttributeError(
            "vlm_client 缺少 generate_text_from_frames 方法："
            "请在模型管理中把 VLM 协议配置为 openai_video"
        )

    chunks = _plan_frame_sequence_chunks(len(frames), chunk_frames, min_tail_frames)
    base_ctx: dict[str, Any] = dict(log_context or {})
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _describe_chunk(ci: int, chunk: list[tuple[bytes, float, int]]) -> dict[str, Any]:
        if cancelled_check is not None and ci > 0:
            await cancelled_check()
        idx_list = [idx for _, _, idx in chunk]
        start_ts = chunk[0][1]
        end_ts = chunk[-1][1]
        chunk_ctx = {**base_ctx, "chunk_index": ci, "frame_indices": idx_list}
        result: dict[str, Any] = {
            "ci": ci, "ok": False, "desc": None,
            "start_ts": start_ts, "end_ts": end_ts, "idx_list": idx_list,
            "exc": None,
        }
        prompt = prompt_template.format(time_table=_format_frame_time_table(chunk))
        frame_urls = [build_image_data_url(fb, "image/jpeg") for fb, _, _ in chunk]
        async with sem:
            try:
                desc = await gen(
                    frame_urls, prompt, fps=fps,
                    max_tokens=max_tokens, temperature=temperature,
                )
            except Exception as exc:
                result["exc"] = exc
                logger.warning(
                    "帧序列伪视频段描述失败，跳过该段",
                    chunk_index=ci, frame_count=len(chunk), error=str(exc), **base_ctx,
                )
                return result
        if desc and desc.strip():
            result["ok"] = True
            result["desc"] = desc.strip()[:max_desc_len]
        return result

    chunk_results = await asyncio.gather(*[
        _describe_chunk(ci, frames[s:e])
        for ci, (s, e) in enumerate(chunks)
    ])

    results: list[tuple[str, float, float, list[int]]] = []
    first_error: BaseException | None = None
    failed_frames = 0
    for r in sorted(chunk_results, key=lambda x: x["ci"]):
        if r["ok"]:
            results.append((r["desc"], r["start_ts"], r["end_ts"], r["idx_list"]))
        else:
            if first_error is None:
                first_error = r["exc"]
            failed_frames += len(r["idx_list"])

    if not results:
        raise AllFrameDescriptionsFailedError(
            first_error=first_error, quota_failures=0, total_frames=len(frames),
        )
    if stats is not None:
        stats["failed"] = failed_frames
    return results