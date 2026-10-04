"""单元测试：AIChatService._retrieve_knowledge 透传 chunk_type（批次 A）。

覆盖：
- wiki_page 命中 → source 含 chunk_type=wiki_page（前端据此显示 Wiki 徽标）
- 普通 chunk → chunk_type 为 None / 'chunk'，不误标 wiki

与 test_ai_chat_web_search 同模式：__new__ 跳过完整 __init__，最小桩覆盖单方法。
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


def _kb_repo_patch(monkeypatch, kb_ids):
    """让 KnowledgeBaseRepository.get_by_space 返回 kb_ids 对应的轻量对象列表。"""

    class _KB:
        def __init__(self, id):
            self.id = id

    class _Repo:
        def __init__(self, db):
            pass

        async def get_by_space(self, space_id, status=None, skip=0, limit=100):
            return [_KB(i) for i in kb_ids]

    from novamind.features.knowledge_space.repository import knowledge_base_repository as mod

    monkeypatch.setattr(mod, "KnowledgeBaseRepository", _Repo)


def _make_chat_service(monkeypatch, search_stub, kb_ids=(1,)):
    """构造仅装好 _retrieve_knowledge 依赖的 AIChatService 实例。"""
    from novamind.features.qa.services.ai_chat_service import AIChatService
    from novamind.core.middleware.structured_logging import get_logger

    svc = AIChatService.__new__(AIChatService)
    svc.logger = get_logger("test.ai_chat_chunk_type")
    svc.db = None  # _Repo 桩不真实访问 db
    svc._search_service = search_stub
    _kb_repo_patch(monkeypatch, list(kb_ids))
    return svc


class _SearchStub:
    """SearchService 桩：search 返回预设 results dict。"""

    def __init__(self, results):
        self._results = results

    async def search(self, space_id, kb_id, user_id, request):
        return {"results": self._results}


@pytest.mark.asyncio
async def test_retrieve_knowledge_wiki_chunk_type_passthrough(monkeypatch):
    """正例：检索结果含 chunk_type=wiki_page → source 原样透传。"""
    stub = _SearchStub([
        {
            "content": "RAG 是检索增强生成的缩写……",
            "document_id": None,
            "file_info": {"filename": ""},
            "metadata": {},
            "chunk_id": "wiki:overview",
            "chunk_type": "wiki_page",
            "kb_id": 1,
            "space_id": 4,
            "score": 0.95,
        }
    ])
    svc = _make_chat_service(monkeypatch, stub)

    res = await svc._retrieve_knowledge(query="RAG 是什么", user_id=1, space_id=4, top_k=5)
    assert res is not None
    _, sources = res
    assert sources[0]["chunk_type"] == "wiki_page"


@pytest.mark.asyncio
async def test_retrieve_knowledge_normal_chunk_not_marked_wiki(monkeypatch):
    """反例：普通 chunk（无 chunk_type 键）→ source chunk_type 为 None，不误标。"""
    stub = _SearchStub([
        {
            "content": "普通文档片段内容",
            "document_id": 12,
            "file_info": {"filename": "manual.pdf"},
            "metadata": {"page_number": 3, "file_type": "pdf"},
            "chunk_id": "chunk-abc",
            "kb_id": 1,
            "space_id": 4,
            "score": 0.7,
        }
    ])
    svc = _make_chat_service(monkeypatch, stub)

    res = await svc._retrieve_knowledge(query="随便问", user_id=1, space_id=4, top_k=5)
    assert res is not None
    _, sources = res
    assert sources[0]["chunk_type"] is None
    assert sources[0]["document_name"] == "manual.pdf"
