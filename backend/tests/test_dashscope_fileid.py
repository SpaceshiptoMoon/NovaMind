"""
测试 DashScope 平台（非百炼）：Files.upload() + fileid:// 方案
不需要暴露 MinIO，由 DashScope 托管音频文件
"""
import asyncio
import json
import os
import tempfile
from http import HTTPStatus
from pathlib import Path

API_KEY = "***REMOVED***"

os.environ["DASHSCOPE_API_KEY"] = API_KEY

import dashscope
from dashscope.audio.asr import Transcription
from dashscope import Files

# 不设 base_http_api_url，走默认 DashScope 平台
dashscope.api_key = API_KEY
# dashscope.base_http_api_url 保持默认 → https://dashscope.aliyuncs.com/api/v1

# 用官方示例音频（DashScope 平台可以直接用 HTTP URL，也可以先用 Files.upload）
SAMPLE_URL = "https://dashscope.oss-cn-beijing.aliyuncs.com/samples/audio/paraformer/hello_world_female2.wav"


async def test_fileid():
    """方案一：Files.upload() + fileid://"""
    print("=== 测试1: Files.upload() + fileid:// ===")
    print(f"DashScope base_url: {dashscope.base_http_api_url}")

    # 下载示例音频到临时文件
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(SAMPLE_URL)
        audio_bytes = resp.content
    print(f"下载示例音频: {len(audio_bytes)} bytes")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        # DashScope Files.upload() → 阿里云托管，返回 fileid
        upload_resp = Files.upload(file_path=tmp_path, purpose="inference")
        print(f"上传状态: {upload_resp.status_code}")

        if upload_resp.status_code != 200:
            print(f"上传失败: {getattr(upload_resp, 'message', 'unknown')}")
            return

        upload_output = upload_resp.output
        uploaded_files = (
            upload_output.get("uploaded_files", []) if isinstance(upload_output, dict)
            else getattr(upload_output, "uploaded_files", [])
        )
        if not uploaded_files:
            print(f"无上传文件: output={upload_output}")
            return

        file_id = uploaded_files[0].get("file_id") if isinstance(uploaded_files[0], dict) else getattr(uploaded_files[0], "file_id", "")
        file_url = f"fileid://{file_id}"
        print(f"file_url: {file_url}")

        # 提交转写
        task_response = Transcription.async_call(
            model="paraformer-v2",
            file_urls=[file_url],
            language_hints=["zh", "en"],
        )
        print(f"提交状态: {task_response.status_code}")

        if task_response.output is None:
            print(f"output=None, message={getattr(task_response, 'message', 'N/A')}")
            return

        if task_response.status_code != HTTPStatus.OK:
            print(f"提交失败: {getattr(task_response, 'message', 'N/A')}")
            return

        print(f"task_id: {task_response.output.task_id}")
        print("等待完成...")

        transcribe_response = Transcription.wait(task=task_response.output.task_id)
        print(f"转写状态: {transcribe_response.status_code}")

        if transcribe_response.status_code == HTTPStatus.OK:
            output = transcribe_response.output
            d = output if isinstance(output, dict) else output.__dict__
            print(json.dumps(d, indent=2, ensure_ascii=False, default=str)[:3000])
            print("\n✅ DashScope 平台 fileid:// 方案可用！")
        else:
            print(f"失败: code={transcribe_response.status_code}, msg={getattr(transcribe_response, 'message', 'N/A')}")

    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def main():
    await test_fileid()


if __name__ == "__main__":
    asyncio.run(main())
