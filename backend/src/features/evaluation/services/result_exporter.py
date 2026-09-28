"""
测评结果导出工具

支持 JSON 原始格式导出和 CSV 扁平化导出
"""
import csv
import io
import json
from typing import Any

CSV_COLUMNS = [
    "index",
    "question",
    "expected_answer",
    "generated_answer",
    "faithfulness",
    "answer_relevance",
    "correctness",
    "quality",
    "context_precision",
    "answer_similarity",
    "human_score",
    "human_comment",
]


def result_to_csv(result_data: dict[str, Any]) -> str:
    """把测评结果 JSON 扁平化为 CSV 字符串（固定列，缺失值留空）。

    Args:
        result_data: 任务结果 dict，须含 details 列表；缺 details 视为空导出。

    Returns:
        带表头的 CSV 文本（不含 BOM，字节层由调用方补 utf-8-sig）。
    """
    details = result_data.get("details", [])
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()

    for detail in details:
        row = _flatten_detail(detail)
        writer.writerow(row)

    return output.getvalue()


def result_to_json_bytes(result_data: dict[str, Any]) -> bytes:
    """把测评结果序列化为 UTF-8 JSON 字节（ensure_ascii 关，两空格缩进）。

    Args:
        result_data: 任务结果 dict，原样序列化。

    Returns:
        可直接上传 MinIO 或落盘的 JSON 字节流。
    """
    return json.dumps(result_data, ensure_ascii=False, indent=2).encode("utf-8")


def _flatten_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """将单条详情扁平化为 CSV 行"""
    gen_scores = detail.get("generation_scores", {})
    end_to_end = detail.get("end_to_end", {})

    return {
        "index": detail.get("index", ""),
        "question": detail.get("question", ""),
        "expected_answer": detail.get("expected_answer", ""),
        "generated_answer": detail.get("generated_answer", ""),
        "faithfulness": _extract_score(gen_scores.get("faithfulness")),
        "answer_relevance": _extract_score(gen_scores.get("answer_relevance")),
        "correctness": _extract_score(gen_scores.get("correctness")),
        "quality": _extract_score(gen_scores.get("quality")),
        "context_precision": end_to_end.get("context_precision", ""),
        "answer_similarity": end_to_end.get("answer_similarity", ""),
        "human_score": detail.get("human_score", ""),
        "human_comment": detail.get("human_comment", ""),
    }


def _extract_score(value: Any) -> Any:
    """从 (score, detail) tuple 或纯数值中提取分数"""
    if isinstance(value, tuple):
        return value[0]
    if isinstance(value, (int, float)):
        return value
    return ""
