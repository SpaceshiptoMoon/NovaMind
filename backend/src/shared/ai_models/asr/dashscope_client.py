"""DashScope Paraformer ASR 协议胶水（提交/轮询/解析的唯一实现）。

await_transcription 同步阻塞（SDK wait 无总超时），不得在事件循环内直调；
async 调用方必须改用 await_transcription_async（to_thread 隔离 + 总超时）。
"""
from __future__ import annotations

import asyncio
from http import HTTPStatus
from typing import Any

# 轮询总超时（秒）。SDK wait() 无任何超时，任务卡 RUNNING 会永远挂着；
# 长音频（数小时录音）Paraformer 通常分钟级完成，30 分钟已是极宽松上界。
TRANSCRIPTION_WAIT_TIMEOUT_SECONDS = 1800


class DashScopeTranscriptionError(RuntimeError):
    """DashScope 转写提交/轮询/解析失败（携带 status_code 与 message）。"""


def configure_dashscope(api_key: str | None, base_url: str | None) -> None:
    """设置 DashScope SDK 全局凭据与百炼 base URL。"""
    import dashscope

    if api_key:
        dashscope.api_key = api_key

    # 百炼平台需要设置 workspace 级别的 base URL
    if base_url:
        url = base_url.rstrip("/")
        # 去掉用户误填的兼容模式路径（/compatible-mode/v1 → OpenAI 协议用的）
        if url.endswith("/compatible-mode/v1"):
            url = url[: -len("/compatible-mode/v1")]
        if not url.endswith("/api/v1"):
            url += "/api/v1"
        dashscope.base_http_api_url = url


def submit_transcription(
    *,
    model: str,
    file_urls: list[str],
    language_hints: list[str] | None = None,
):
    """提交转写任务（HTTP URL 形态，非 fileid://）。失败抛 DashScopeTranscriptionError。"""
    from dashscope.audio.asr import Transcription

    call_kwargs: dict[str, Any] = {
        "model": model,
        "file_urls": file_urls,
    }
    if language_hints:
        call_kwargs["language_hints"] = language_hints

    task_response = Transcription.async_call(**call_kwargs)

    if task_response.output is None:
        raise DashScopeTranscriptionError(
            f"DashScope 转写任务提交失败: status={task_response.status_code}, "
            f"message={getattr(task_response, 'message', 'unknown')}"
        )
    if task_response.status_code != HTTPStatus.OK:
        raise DashScopeTranscriptionError(
            f"DashScope 转写任务提交失败: status={task_response.status_code}, "
            f"message={getattr(task_response, 'message', 'unknown')}"
        )
    return task_response


def await_transcription(task_id: str) -> dict[str, Any]:
    """轮询等待转写完成，返回 dict 化 output（兼容 SDK 返回对象/字典两形态）。

    同步阻塞（SDK wait 内部 time.sleep 轮询）——只允许在 to_thread/executor 内跑，
    async 代码请用 ``await_transcription_async``。
    """
    from dashscope.audio.asr import Transcription

    transcribe_response = Transcription.wait(task=task_id)
    if transcribe_response.status_code != HTTPStatus.OK:
        raise DashScopeTranscriptionError(
            f"DashScope 转写失败: status={transcribe_response.status_code}, "
            f"message={getattr(transcribe_response, 'message', 'unknown')}"
        )
    output = transcribe_response.output
    if isinstance(output, dict):
        return output
    return {k: v for k, v in output.__dict__.items() if not k.startswith("_")}


async def await_transcription_async(
    task_id: str,
    *,
    timeout_seconds: int = TRANSCRIPTION_WAIT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """await_transcription 的 async 包装：轮询下放线程池 + 总超时。

    事件循环安全：同步轮询经 ``asyncio.to_thread`` 隔离，转写全程不再冻结
    worker/API 的事件循环；asyncio.timeout 保证任务卡 RUNNING 时也不会永远挂住
    （超时抛 ``TimeoutError``，由调用方转译为业务错误）。
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(await_transcription, task_id),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise DashScopeTranscriptionError(
            f"DashScope 转写轮询超时（>{timeout_seconds}s），task_id={task_id}"
        ) from exc


def _as_dict(obj: Any) -> dict[str, Any]:
    """dict 直传 / SDK 对象转 dict。"""
    if isinstance(obj, dict):
        return obj
    return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}


def extract_segments(output_dict: dict[str, Any]) -> list[dict]:
    """解析 output 为句子级时间戳段落；任务 FAILED 抛 DashScopeTranscriptionError。

    Returns:
        [{"text": "...", "start": 0.0, "end": 5.2}, ...]
        （无 sentences 时回退整段 transcription，start/end 为 0）
    """
    results = output_dict.get("results", [])

    task_status = output_dict.get("task_status", "")
    if task_status == "FAILED":
        error_code = output_dict.get("code", "UNKNOWN")
        detail_parts: list[str] = []
        for item in results:
            item_dict = _as_dict(item)
            item_code = item_dict.get("code", "")
            item_status = item_dict.get("subtask_status", "")
            if item_code or item_status:
                detail_parts.append(f"subtask[{item_code or item_status}]")
            output_data = item_dict.get("output", {})
            if isinstance(output_data, dict):
                inner_results = output_data.get("results", [])
            elif hasattr(output_data, "results"):
                inner_results = getattr(output_data, "results", [])
            else:
                inner_results = []
            for ir in inner_results:
                ir_dict = _as_dict(ir)
                ir_code = ir_dict.get("code", "")
                ir_status = ir_dict.get("subtask_status", "")
                if ir_code or ir_status:
                    detail_parts.append(f"inner[{ir_code or ir_status}]")
        detail = ", ".join(detail_parts) if detail_parts else "no details"
        raise DashScopeTranscriptionError(
            f"DashScope 转写任务失败: code={error_code}, "
            f"task_id={output_dict.get('task_id', 'unknown')}, "
            f"details={detail}"
        )

    segments: list[dict] = []
    for item in results:
        item_dict = _as_dict(item)
        sentences = item_dict.get("sentences", [])
        if sentences:
            for sent in sentences:
                sent_dict = _as_dict(sent)
                text = sent_dict.get("text", "").strip()
                if text:
                    segments.append({
                        "text": text,
                        "start": sent_dict.get("begin_time", 0) / 1000.0,
                        "end": sent_dict.get("end_time", 0) / 1000.0,
                    })
        else:
            text = item_dict.get("transcription", "").strip()
            if text:
                segments.append({
                    "text": text,
                    "start": 0.0,
                    "end": 0.0,
                })
    return segments


__all__ = [
    "DashScopeTranscriptionError",
    "TRANSCRIPTION_WAIT_TIMEOUT_SECONDS",
    "configure_dashscope",
    "submit_transcription",
    "await_transcription",
    "await_transcription_async",
    "extract_segments",
]
