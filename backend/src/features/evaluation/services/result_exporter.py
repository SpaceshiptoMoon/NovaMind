"""
测评结果导出工具

支持 JSON 原始格式导出和 CSV 扁平化导出
"""
import csv
import io
import json
from typing import Any, Dict, List


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


def result_to_csv(result_data: Dict[str, Any]) -> str:
    """将测评结果 JSON 转换为 CSV 字符串"""
    details = result_data.get("details", [])
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()

    for detail in details:
        row = _flatten_detail(detail)
        writer.writerow(row)

    return output.getvalue()


def result_to_json_bytes(result_data: Dict[str, Any]) -> bytes:
    """将测评结果序列化为 JSON bytes"""
    return json.dumps(result_data, ensure_ascii=False, indent=2).encode("utf-8")


def _flatten_detail(detail: Dict[str, Any]) -> Dict[str, Any]:
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
