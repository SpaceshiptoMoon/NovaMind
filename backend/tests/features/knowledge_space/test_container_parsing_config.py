"""容器/邮件族解析策略路由回归：zip/eml/msg/ofd 固定 deepdoc。

断点背景：build_runtime_parsing_config 的文档类型归一链对未登记类型
兜底成 pdf——用户 KB 给 PDF 配 external_ocr/mineru/default 时，上传
zip 会被喂给外部 OCR（前置守卫拒）或 shared reader（不认识 zip），
必失败。容器族只有 deepdoc 认识（容器递归/附件解析都在 deepdoc 路径），
策略固定，不经配置域。pdf/txt/docx 既有路由零漂移一并锁定。
"""

import pytest
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    build_runtime_parsing_config,
)

pytestmark = pytest.mark.unit

# 用户把 PDF 配成 external_ocr 的场景——容器族不得被该配置污染
_PARSING = {
    "text": {
        "pdf": {"strategy": "external_ocr", "ocr_task": "document_parsing"},
        "txt": {"strategy": "default"},
        "docx": {"strategy": "deepdoc"},
    }
}


@pytest.mark.parametrize("file_type", ["zip", "eml", "msg", "ofd"])
def test_container_types_fixed_to_deepdoc(file_type):
    """容器/邮件族策略恒为 deepdoc，PDF 的 external_ocr 配置不渗透。"""
    cfg = build_runtime_parsing_config(_PARSING, file_type)
    assert cfg["strategy"] == "deepdoc"
    assert "pdf_ocr_task" not in cfg
    assert "deepdoc_parser_id" not in cfg


@pytest.mark.parametrize(
    "file_type, expect",
    [
        ("pdf", {"strategy": "external_ocr", "pdf_ocr_task": "document_parsing"}),
        ("txt", {"strategy": "default"}),
        ("docx", {"strategy": "deepdoc", "deepdoc_parser_id": "docx"}),
    ],
)
def test_existing_type_routing_unchanged(file_type, expect):
    """既有类型的路由零漂移（容器分支不改变原归一链）。"""
    cfg = build_runtime_parsing_config(_PARSING, file_type)
    for key, value in expect.items():
        assert cfg.get(key) == value, f"{file_type}.{key} 应为 {value}"
