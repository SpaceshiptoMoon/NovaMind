"""DashScope Paraformer ASR 客户端胶水（批次 5 收敛）。

此前 ``engines/document/media/audio/audio_utils.transcribe_audio_with_dashscope``
与 ``shared/ai_models/connection_testers/asr.py._test_dashscope`` 各写一份
逐字级重复的协议胶水（api_key/base_url 归一 + async_call 提交 + wait 轮询 +
output dict 兼容解析）。本模块成为唯一实现，两消费方改调此处。

- ``configure_dashscope(api_key, base_url)``：设置 SDK 全局 key 与百炼 base URL
  （剥离误填的 /compatible-mode/v1、补 /api/v1 后缀）
- ``submit_transcription(model, file_urls, language_hints)``：提交任务，失败抛
  ``DashScopeTranscriptionError``
- ``await_transcription(task_id)``：轮询等待，返回统一 dict 化的 output
  （同步阻塞——SDK ``Transcription.wait`` 是 ``while True + time.sleep`` 的
  同步轮询且无总超时，**不得**在事件循环内直接调用）
- ``await_transcription_async(task_id, timeout_seconds)``：async 包装——轮询经
  ``asyncio.to_thread`` 下放线程池 + asyncio.timeout 总超时（防长音频转写冻结
  worker/API 事件循环，2026-09 链路审计 P0）。所有 async 调用方必须用它。
- ``extract_segments(output_dict)``：句子级时间戳解析（含无 sentences 的整段回退）

转写的编排（临时文件/MinIO 上传/清理）仍留在 audio_utils——那是文档管道职责，
本模块只管 DashScope 协议本身。
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
