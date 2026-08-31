"""视频帧描述引擎：single / grouped / rewrite 三种描述策略。

纯逻辑层，不 import features/setting/ORM。三个函数均接收 ``vlm_client`` / ``llm_client`` /
``prompt`` 作注入参数（features 装配点从 ModelConfigPort 取 client、从 PromptManager 取 prompt
后注入），引擎不碰 ``model_config_port`` / ``PromptManager``。

- ``describe_single``：逐帧单图 VLM 描述，返回 ``[(desc, ts, frame_idx)]``；单帧主 client 配额/鉴权
  失败且有 fallback client 时回退重试一次，全部帧失败抛 ``AllFrameDescriptionsFailedError``。
- ``describe_grouped``：每 ``group_size`` 帧一组喂 VLM 多图消息生成连贯描述，返回
  ``[(desc, start_ts, end_ts, frame_idx_list)]``；多图调用失败时该组降级为逐帧 single。
- ``describe_rewrite``：先 single 逐帧描述，再调 LLM 重写连贯（强约束保留 ``[HH:MM:SS#idx]`` 锚点），
  后处理校验锚点 idx 集合一致，不一致回退原逐帧拼接；返回 ``(full_text, descriptions)``。

所有策略产出的描述/文本均带 ``[HH:MM:SS#idx]`` 锚点，供 ``align_chunk_times`` 切分后反查时间区间。
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from novamind.engines.document.media.chunk_time_alignment import (
    extract_anchor_indices,
    format_time_anchor,
)
from novamind.engines.document.media.vlm import (
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
        first_error: Optional[BaseException] = None,
        quota_failures: int = 0,
        total_frames: int = 0,
    ):
        self.first_error = first_error
        self.quota_failures = quota_failures
        self.total_frames = total_frames
        detail = f"，首个错误: {first_error}" if first_error else ""
        super().__init__(f"所有 {total_frames} 帧/组的 VLM 描述均失败{detail}")


async def describe_single(
    frames: List[Tuple[bytes, float, int]],
    vlm_client: Any,
    prompt: str,
    *,
    logger: Any = logger,
    vlm_model: str = "",
    max_tokens: int = _DEFAULT_SINGLE_MAX_TOKENS,
    temperature: float = _DEFAULT_TEMPERATURE,
    max_desc_len: int = _DEFAULT_MAX_DESC_LEN,
    vlm_fallback_client: Optional[Any] = None,
    vlm_fallback_model: Optional[str] = None,
    is_quota_error: Optional[QuotaErrorPredicate] = None,
    log_context: Optional[Dict[str, Any]] = None,
    cancelled_check: Optional[CancelledCheck] = None,
    cancel_every: int = 5,
) -> List[Tuple[str, float, int]]:
    """逐帧单图 VLM 描述。

    返回 ``[(desc, ts, frame_idx), ...]``。单帧失败记录 warning 并跳过；主 client 配额/鉴权
    失败且配置了 ``vlm_fallback_client`` 时回退重试一次。全部帧失败抛
    ``AllFrameDescriptionsFailedError``。
    """
    base_ctx: Dict[str, Any] = dict(log_context or {})
    descriptions: List[Tuple[str, float, int]] = []
    first_error: Optional[BaseException] = None
    quota_failures = 0

    for i, (frame_bytes, ts, frame_idx) in enumerate(frames):
        if cancelled_check is not None and i > 0 and i % cancel_every == 0:
            await cancelled_check()

        messages = build_vlm_image_messages(frame_bytes, "image/jpeg", prompt)
        frame_ctx = {**base_ctx, "frame_index": frame_idx}

        try:
            desc = await generate_vlm_text_with_fallback(
                vlm_client, messages,
                max_tokens=max_tokens, temperature=temperature,
                logger=logger, vlm_model=vlm_model, log_context=frame_ctx,
            )
        except Exception as exc:
            if first_error is None:
                first_error = exc
            is_quota = is_quota_error is not None and is_quota_error(exc)
            if is_quota:
                quota_failures += 1

            # 配额/鉴权类错误且有备用 client：回退重试一次
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
                    continue
            else:
                logger.warning(
                    "视频帧VLM描述失败, 跳过",
                    frame_index=frame_idx, error=str(exc), **base_ctx,
                )
                continue

        if desc and desc.strip():
            descriptions.append((desc.strip()[:max_desc_len], ts, frame_idx))

    if not descriptions:
        raise AllFrameDescriptionsFailedError(
            first_error=first_error, quota_failures=quota_failures, total_frames=len(frames),
        )
    return descriptions


async def describe_grouped(
    frames: List[Tuple[bytes, float, int]],
    group_size: int,
    vlm_client: Any,
    prompt: str,
    *,
    logger: Any = logger,
    vlm_model: str = "",
    max_tokens: int = _DEFAULT_GROUPED_MAX_TOKENS,
    temperature: float = _DEFAULT_TEMPERATURE,
    max_desc_len: int = _DEFAULT_MAX_DESC_LEN * 4,
    vlm_fallback_client: Optional[Any] = None,
    vlm_fallback_model: Optional[str] = None,
    is_quota_error: Optional[QuotaErrorPredicate] = None,
    log_context: Optional[Dict[str, Any]] = None,
    cancelled_check: Optional[CancelledCheck] = None,
    cancel_every: int = 1,
) -> List[Tuple[str, float, float, List[int]]]:
    """多帧一组喂 VLM 多图消息生成连贯描述。

    返回 ``[(desc, start_ts, end_ts, frame_idx_list), ...]``，锚点用组首帧 idx。
    ``group_size <= 1`` 时退化为逐帧 single（每帧自成一组）。
    某组多图调用失败时该组降级为逐帧 single 描述，不阻塞整体；全部组失败抛
    ``AllFrameDescriptionsFailedError``。
    """
    base_ctx: Dict[str, Any] = dict(log_context or {})

    if group_size <= 1 or len(frames) <= 1:
        singles = await describe_single(
            frames, vlm_client, prompt,
            logger=logger, vlm_model=vlm_model,
            max_tokens=_DEFAULT_SINGLE_MAX_TOKENS, temperature=temperature,
            max_desc_len=_DEFAULT_MAX_DESC_LEN,
            vlm_fallback_client=vlm_fallback_client, vlm_fallback_model=vlm_fallback_model,
            is_quota_error=is_quota_error, log_context=base_ctx,
            cancelled_check=cancelled_check, cancel_every=5,
        )
        return [(desc, ts, ts, [idx]) for desc, ts, idx in singles]

    groups = [frames[i:i + group_size] for i in range(0, len(frames), group_size)]
    results: List[Tuple[str, float, float, List[int]]] = []
    first_error: Optional[BaseException] = None
    any_group_succeeded = False
    # 累计配额/鉴权类失败帧数，供 vlm_skip_on_quota_error 判断"全帧配额失败"降级。
    # 原硬编码 quota_failures=0 导致该开关在 grouped 策略下永远不生效。
    quota_failures = 0

    for gi, group in enumerate(groups):
        if cancelled_check is not None and gi > 0 and gi % cancel_every == 0:
            await cancelled_check()

        frames_bytes = [fb for fb, _, _ in group]
        idx_list = [idx for _, _, idx in group]
        start_ts = group[0][1]
        end_ts = group[-1][1]
        group_ctx = {**base_ctx, "group_index": gi, "frame_indices": idx_list}

        messages = build_vlm_multi_image_messages(frames_bytes, "image/jpeg", prompt)
        try:
            desc = await generate_vlm_text_with_fallback(
                vlm_client, messages,
                max_tokens=max_tokens, temperature=temperature,
                logger=logger, vlm_model=vlm_model, log_context=group_ctx,
            )
        except Exception as exc:
            if first_error is None:
                first_error = exc
            # 主多图调用若为配额/鉴权类错误，该组 len(group) 帧计为配额失败
            if is_quota_error is not None and is_quota_error(exc):
                quota_failures += len(group)
            logger.warning(
                "grouped 多图VLM失败，该组降级逐帧描述",
                group_index=gi, error=str(exc), **base_ctx,
            )
            try:
                singles = await describe_single(
                    group, vlm_client, prompt,
                    logger=logger, vlm_model=vlm_model,
                    max_tokens=_DEFAULT_SINGLE_MAX_TOKENS, temperature=temperature,
                    max_desc_len=_DEFAULT_MAX_DESC_LEN,
                    vlm_fallback_client=vlm_fallback_client, vlm_fallback_model=vlm_fallback_model,
                    is_quota_error=is_quota_error, log_context=base_ctx,
                )
            except AllFrameDescriptionsFailedError as single_err:
                # 累计 single 回退抛出的配额失败数（原 continue 吞掉了该计数）
                quota_failures += single_err.quota_failures
                continue
            for s_desc, s_ts, s_idx in singles:
                results.append((s_desc, s_ts, s_ts, [s_idx]))
                any_group_succeeded = True
            continue

        if desc and desc.strip():
            results.append((desc.strip()[:max_desc_len], start_ts, end_ts, idx_list))
            any_group_succeeded = True

    if not any_group_succeeded:
        raise AllFrameDescriptionsFailedError(
            first_error=first_error,
            quota_failures=min(quota_failures, len(frames)),
            total_frames=len(frames),
        )
    return results


async def describe_rewrite(
    frames: List[Tuple[bytes, float, int]],
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
    vlm_fallback_client: Optional[Any] = None,
    vlm_fallback_model: Optional[str] = None,
    is_quota_error: Optional[QuotaErrorPredicate] = None,
    log_context: Optional[Dict[str, Any]] = None,
    cancelled_check: Optional[CancelledCheck] = None,
    cancel_every: int = 5,
) -> Tuple[str, List[Tuple[str, float, int]]]:
    """逐帧描述 + LLM 重写连贯，保留 ``[HH:MM:SS#idx]`` 锚点。

    流程：
    1. ``describe_single`` 逐帧得带锚点描述 ``[(desc, ts, idx)]``；
    2. 拼接成 ``[HH:MM:SS#idx] desc`` 逐行文本喂 LLM，``rewrite_prompt`` 强约束「只润色描述内容、
       保留锚点格式与逐行结构、不合并/删除帧段」；
    3. 后处理校验输出锚点 idx 集合 == 输入帧 idx 集合，不一致或 LLM 失败/空输出则回退原逐帧拼接。

    返回 ``(full_text, descriptions)``：``full_text`` 为带锚点的最终 md（成功=LLM 重写输出，
    回退=原逐帧拼接），``descriptions`` 为原 single 列表（供 ``build_frame_timeline_map`` 构建时间线）。
    """
    base_ctx: Dict[str, Any] = dict(log_context or {})

    # 1. 逐帧 single 描述（带锚点反查所需的 ts/idx）
    descriptions = await describe_single(
        frames, vlm_client, single_prompt,
        logger=logger, vlm_model=vlm_model,
        max_tokens=max_tokens, temperature=temperature, max_desc_len=max_desc_len,
        vlm_fallback_client=vlm_fallback_client, vlm_fallback_model=vlm_fallback_model,
        is_quota_error=is_quota_error, log_context=base_ctx,
        cancelled_check=cancelled_check, cancel_every=cancel_every,
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