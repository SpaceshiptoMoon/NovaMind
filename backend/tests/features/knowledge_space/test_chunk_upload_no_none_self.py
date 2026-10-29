"""分片上传 init 模态上限调用形态回归守卫。

历史 bug：init_chunk_upload 以 ``DocumentUploadService._get_max_file_size(
None, kb, ext)`` 把 None 当 self 调实例方法——方法体历史上不使用 self 时
碰巧可用，模态上限改造引入 ``self.MODALITY_TO_FILE_TYPES`` 后任何分片上传
init 请求 500（端到端实测暴露）。

实例方法必须经实例调用；此守卫在源码层拦截 None-self 调用形态回归。
"""
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROUTES = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "features"
    / "knowledge_space"
    / "api"
    / "document_routes.py"
)


def test_no_none_self_call_on_get_max_file_size():
    """反例守卫：禁止 ``_get_max_file_size(None, ...)`` None-self 调用形态。"""
    src = _ROUTES.read_text(encoding="utf-8")
    assert "_get_max_file_size(None" not in src, (
        "document_routes.py 出现 None-self 调用 _get_max_file_size——"
        "实例方法经 None 调用会在访问 self.MODALITY_TO_FILE_TYPES 时 500，"
        "请改用 Depends(get_document_upload_service) 注入实例"
    )


def test_init_uses_injected_service_for_modality_cap():
    """正例：init 端点经注入实例读取模态上限。"""
    src = _ROUTES.read_text(encoding="utf-8")
    assert "document_upload_service._get_max_file_size(kb" in src
