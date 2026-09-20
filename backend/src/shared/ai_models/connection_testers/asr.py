"""ASR 连通测试器（local / openai / dashscope 三协议，从 user service 下沉）。

行为语义原样保留：
- local：检查 faster-whisper tiny 模型目录与文件完整性 + 可加载性（不实际推理）；
- openai：发 0.1s 最小静音 WAV 到 ``/audio/transcriptions``，2xx/4xx 均视为可达，
  401/403/5xx 抛 ValueError；
- dashscope：官方示例音频 URL → async_call → wait 全链路验证。
"""
from __future__ import annotations

from pathlib import Path

# OpenAI 协议缺省 base URL（业务层不再各自硬编码；消 model_config_service 的 :815 旧位置）
OPENAI_ASR_DEFAULT_BASE_URL = "https://api.openai.com/v1"
# DashScope 官方示例音频（公开 HTTP URL，与生产转写路径一致）
DASHSCOPE_ASR_SAMPLE_URL = (
    "https://dashscope.oss-cn-beijing.aliyuncs.com/samples/audio/paraformer/hello_world_female2.wav"
)


class ASRConnectionTester:
    """ASR 连接测试（按协议路由）。请求字段（model/api_key/base_url/protocol）由调用方传入。"""

    async def test(self, *, protocol: str | None, model: str, api_key: str, base_url: str | None) -> None:
        p = protocol or "openai"
        if p == "local":
            await self._test_local()
        elif p == "dashscope":
            await self._test_dashscope(model=model, api_key=api_key, base_url=base_url)
        else:
            await self._test_openai(model=model, api_key=api_key, base_url=base_url)

    async def _test_local(self) -> None:
        """测试本地 ASR 模型是否可用（检查模型文件完整性）"""
        # 模型路径与 audio_utils._resolve_local_whisper_model_dir 一致
        model_dir = Path(__file__).resolve().parents[5] / "models" / "faster-whisper" / "tiny"

        if not model_dir.exists():
            raise ValueError(
                f"本地 ASR 模型目录不存在: {model_dir}，"
                f"请先下载 faster-whisper tiny 模型到 backend/models/faster-whisper/tiny/"
            )

        required_files = ["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"]
        missing = [f for f in required_files if not (model_dir / f).exists()]
        if missing:
            raise ValueError(
                f"本地 ASR 模型文件缺失: {missing}，"
                f"模型目录: {model_dir}"
            )

        # 快速验证模型可以加载（不执行实际推理）
        try:
            import asyncio

            from faster_whisper import WhisperModel
            model = await asyncio.to_thread(
                WhisperModel,
                str(model_dir),
                device="cpu",
                compute_type="int8",
                local_files_only=True,
            )
            del model
        except Exception as e:
            raise ValueError(f"本地 ASR 模型加载失败: {e}") from e

    async def _test_openai(self, *, model: str, api_key: str, base_url: str | None) -> None:
        """测试 ASR 连接（OpenAI Whisper API）"""
        import io
        import struct

        import httpx

        # 生成最小有效 WAV：0.1 秒 8000Hz 16-bit 单声道静音
        sample_rate = 8000
        duration = 0.1  # 秒
        num_samples = int(sample_rate * duration)
        pcm_data = b"\x00\x00" * num_samples  # 静音

        wav = io.BytesIO()
        wav.write(b"RIFF")
        wav.write(struct.pack("<I", 36 + len(pcm_data)))
        wav.write(b"WAVE")
        wav.write(b"fmt ")
        wav.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate,
                              sample_rate * 2, 2, 16))
        wav.write(b"data")
        wav.write(struct.pack("<I", len(pcm_data)))
        wav.write(pcm_data)
        test_wav = wav.getvalue()

        base = (base_url or OPENAI_ASR_DEFAULT_BASE_URL).rstrip("/")
        url = f"{base}/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {api_key}",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                headers=headers,
                data={"model": model, "response_format": "json"},
                files={"file": ("test.wav", test_wav, "audio/wav")},
            )
            if resp.status_code == 401:
                raise ValueError("ASR API Key 无效（401）")
            if resp.status_code == 403:
                raise ValueError("ASR API Key 无权限（403）")
            if resp.status_code >= 500:
                raise ValueError(f"ASR 服务端错误（{resp.status_code}）")
            # 2xx 或 4xx（模型不存在等）均视为连接可达

    async def _test_dashscope(self, *, model: str, api_key: str, base_url: str | None) -> None:
        """测试 ASR 连接（DashScope Paraformer API，HTTP URL → async_call → wait）"""
        from http import HTTPStatus

        import dashscope
        from dashscope.audio.asr import Transcription

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

        # 提交转写任务
        task_response = Transcription.async_call(
            model=model,
            file_urls=[DASHSCOPE_ASR_SAMPLE_URL],
            language_hints=["zh", "en"],
        )

        if task_response.output is None:
            raise ValueError(
                f"DashScope 转写任务提交失败: status={task_response.status_code}, "
                f"message={getattr(task_response, 'message', 'unknown')}"
            )

        if task_response.status_code != HTTPStatus.OK:
            raise ValueError(
                f"DashScope 转写任务提交失败: status={task_response.status_code}, "
                f"message={getattr(task_response, 'message', 'unknown')}"
            )

        # 等待转写完成（验证真实可用性，而非仅提交成功）
        transcribe_response = Transcription.wait(task=task_response.output.task_id)

        if transcribe_response.status_code != HTTPStatus.OK:
            raise ValueError(
                f"DashScope 转写失败: status={transcribe_response.status_code}, "
                f"message={getattr(transcribe_response, 'message', 'unknown')}"
            )
        # 转写成功 = 连接可达
