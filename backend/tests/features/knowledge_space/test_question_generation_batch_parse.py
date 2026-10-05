"""question_generation 批量解析提取容错回归测试。

背景：_parse_batch_response 原为裸 json.loads，LLM 输出被 ```json 围栏
包裹或带前导文字时判 None → 触发无谓的整批重试（多烧 API 调用）甚至
逐块降级。修复后换 extract_json_obj（提取容错），垃圾输出仍返回 None
（重试语义不变）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    QuestionGenerationConfig,
)
from novamind.features.knowledge_space.services.question_generation_service import (
    QuestionGenerationService,
)

pytestmark = pytest.mark.unit


def _make_service() -> QuestionGenerationService:
    """构造只测解析的服务实例（不触 LLM / DB）。"""
    return QuestionGenerationService(
        session=None,  # 解析路径不触 DB
        config=QuestionGenerationConfig(),
    )


class TestParseBatchResponse:
    def test_plain_json(self):
        svc = _make_service()
        result = svc._parse_batch_response(
            '{"chunks": [{"questions": [{"question": "Q1", "category": "factual"}]}]}',
            expected_count=1,
        )
        assert result is not None
        assert len(result) == 1
        assert result[0][0].question == "Q1"

    def test_fenced_json_parses(self):
        """正例：围栏包裹（旧实现返回 None 触发无谓重试）。"""
        svc = _make_service()
        response = '这是生成结果：\n```json\n{"chunks": [{"questions": [{"question": "围栏Q"}]}]}\n```\n'
        result = svc._parse_batch_response(response, expected_count=1)
        assert result is not None
        assert result[0][0].question == "围栏Q"

    def test_leading_text_json_parses(self):
        svc = _make_service()
        response = 'Sure! {"chunks": [{"questions": ["纯字符串问题"]}]}'
        result = svc._parse_batch_response(response, expected_count=1)
        assert result is not None
        assert result[0][0].question == "纯字符串问题"

    def test_garbage_still_none(self):
        """反例：垃圾输出仍返回 None（重试语义不变）。"""
        svc = _make_service()
        assert svc._parse_batch_response("完全不是 JSON", expected_count=1) is None
        assert svc._parse_batch_response("", expected_count=1) is None

    def test_pad_to_expected_count(self):
        svc = _make_service()
        result = svc._parse_batch_response(
            '{"chunks": [{"questions": [{"question": "只有一块"}]}]}',
            expected_count=3,
        )
        assert len(result) == 3
        assert result[0][0].question == "只有一块"
        assert result[1] == []
        assert result[2] == []
