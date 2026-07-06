"""
测试 — 官方示例代码模式：SDK + HTTP URL
"""
import asyncio
from http import HTTPStatus
import json
import os

API_KEY = "***REMOVED***"
WORKSPACE = "llm-s77iv26518bf3xfd"

os.environ["DASHSCOPE_API_KEY"] = API_KEY

import dashscope
from dashscope.audio.asr import Transcription

dashscope.api_key = API_KEY
dashscope.base_http_api_url = f"https://{WORKSPACE}.cn-beijing.maas.aliyuncs.com/api/v1"

SAMPLE = "https://dashscope.oss-cn-beijing.aliyuncs.com/samples/audio/paraformer/hello_world_female2.wav"


async def main():
    print(f"API Key: {API_KEY[:20]}...")
    print(f"Base URL: {dashscope.base_http_api_url}")
    print(f"文件: {SAMPLE}")
    print("提交转写...")

    task_response = Transcription.async_call(
        model="paraformer-v1",
        file_urls=[SAMPLE],
        language_hints=["zh", "en"],
    )
    print(f"提交状态: {task_response.status_code}")
    if task_response.output is None:
        print(f"output=None, message={getattr(task_response, 'message', 'N/A')}")
        return
    if task_response.status_code != 200:
        print(f"提交失败: {getattr(task_response, 'message', 'N/A')}")
        return

    print(f"task_id: {task_response.output.task_id}")
    print("等待完成...")

    transcribe_response = Transcription.wait(task=task_response.output.task_id)
    print(f"转写状态: {transcribe_response.status_code}")

    if transcribe_response.status_code == HTTPStatus.OK:
        output = transcribe_response.output
        d = output if isinstance(output, dict) else output.__dict__
        print(json.dumps(d, indent=2, ensure_ascii=False, default=str)[:2000])
    else:
        print(f"code={transcribe_response.status_code}, msg={getattr(transcribe_response, 'message', 'N/A')}")


if __name__ == "__main__":
    asyncio.run(main())
