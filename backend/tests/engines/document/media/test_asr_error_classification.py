"""DashScope 云端 ASR 错误分类边界（SERVER_ERROR 等 FAILED 任务的解析语义）。

背景（真机日志：DashScope 转写任务失败 code=SERVER_ERROR）：云端 ASR 任务
FAILED 时 extract_segments 抛 DashScopeTranscriptionError，其语义边界——

- 消息组装：code/task_id/子任务与内部明细完整可追；
- **可重试语义**：SERVER_ERROR 属供应商瞬态（5xx），异常类不得是永久错误
  （不得阻断 arq 重试）也不属本地忙碌（不得误走延后重入队）；
- 成功路径回退：SUCCEEDED 无 sentences → 回退整段 transcription。
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.ai_models.asr.dashscope_client import (
    DashScopeTranscriptionError,
    extract_segments,
)

pytestmark = pytest.mark.unit


def test_failed_task_raises_with_code_and_task_id():
    """FAILED 任务：错误消息带 code 与 task_id（排障可追溯）。"""
    output = {
        "task_id": "040c8599-1a27-4286-a277-334f48a19f63",
        "task_status": "FAILED",
        "code": "SERVER_ERROR",
        "results": [],
    }
    with pytest.raises(DashScopeTranscriptionError) as ei:
        extract_segments(output)
    msg = str(ei.value)
    assert "SERVER_ERROR" in msg
    assert "040c8599-1a27-4286-a277-334f48a19f63" in msg


def test_failed_task_detail_assembles_subtask_and_inner():
    """子任务/内部条目的 code 与状态拼进 details（两级明细可追）。"""
    output = {
        "task_id": "t-1",
        "task_status": "FAILED",
        "code": "SERVER_ERROR",
        "results": [
            {"code": "ASR", "subtask_status": "FAILED",
             "output": {"results": [{"code": "INTERNAL", "subtask_status": "ERROR"}]}},
            {"subtask_status": "SUCCEEDED", "output": {}},
        ],
    }
    with pytest.raises(DashScopeTranscriptionError) as ei:
        extract_segments(output)
    assert "subtask[ASR]" in str(ei.value)
    assert "inner[INTERNAL]" in str(ei.value)


def test_failed_task_without_details_falls_back():
    """无任何明细（真机 SERVER_ERROR 形态）：details 落 'no details'，不裸栈。"""
    output = {"task_id": "t-2", "task_status": "FAILED", "code": "SERVER_ERROR"}
    with pytest.raises(DashScopeTranscriptionError) as ei:
        extract_segments(output)
    assert "no details" in str(ei.value)


def test_server_error_is_transient_not_permanent():
    """SERVER_ERROR 语义契约：瞬态错误——不得是永久错误子类（阻断 arq 重试），
    不得是本地忙碌类（误走延后重入队），保持普通可重试错误语义。"""
    from novamind.features.knowledge_space.exceptions import (
        LocalASRBusyError,
        PermanentProcessingError,
    )

    assert not issubclass(DashScopeTranscriptionError, PermanentProcessingError), (
        "SERVER_ERROR 是供应商瞬态：不得被归类为永久错误阻断 arq 重试"
    )
    assert not issubclass(DashScopeTranscriptionError, LocalASRBusyError), (
        "云端 ASR 失败不得误判为本地忙碌（延后重入队语义）"
    )


def test_succeeded_without_sentences_falls_back_to_transcription():
    """SUCCEEDED 无句子级结果：回退整段 transcription 文本（单段、时间归零）。"""
    output = {
        "task_status": "SUCCEEDED",
        "results": [
            {"transcription": "整段转写文本", "sentences": []},
        ],
    }
    segments = extract_segments(output)
    assert segments == [{"text": "整段转写文本", "start": 0.0, "end": 0.0}]


def test_succeeded_with_sentences_keeps_millisecond_timestamps():
    """句子级结果：毫秒时间戳换算为秒。"""
    output = {
        "task_status": "SUCCEEDED",
        "results": [
            {"sentences": [
                {"text": " 第一句 ", "begin_time": 0, "end_time": 1500},
                {"text": "第二句", "begin_time": 1600, "end_time": 3200},
            ]},
        ],
    }
    segments = extract_segments(output)
    assert segments[0] == {"text": "第一句", "start": 0.0, "end": 1.5}
    assert segments[1] == {"text": "第二句", "start": 1.6, "end": 3.2}


class PermanentBase(Exception):
    """占位基类：断言用（真实现位于 features 异常族，引擎侧不可依赖）。"""
