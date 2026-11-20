"""视频叙事任务模型归属回归测试（红队 A6：user_id=1 死分支）。

历史缺陷：process_narrative_task / enqueue_narrative_synthesis 的 user_id 默认
int 1（恒真），把「未传时回退文档上传者」的兜底短路成死分支——解析完成钩子
不传 user_id 时叙事合成串用用户 1 的模型凭据。修复后默认 None、兜底生效，
触发钩子显式传上传者。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytestmark = pytest.mark.unit


class _FakeSession:
    """get_db_session 的假上下文：yield 一个带 async get 的假会话。"""

    def __init__(self, doc=None):
        self._doc = doc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, model, key):
        return self._doc


def _patch_db_and_models(monkeypatch, uploader_id):
    """mock 数据库会话、文档仓储与 LLM 客户端工厂，捕获模型解析的归属用户。"""
    captured: dict = {}

    fake_doc = SimpleNamespace(uploader_id=uploader_id)

    class _FakeDocRepo:
        def __init__(self, session):
            pass

        async def get_by_id(self, document_id):
            return fake_doc

    import novamind.core.database.database as db_mod

    monkeypatch.setattr(db_mod, "get_db_session", lambda: _FakeSession())
    import novamind.features.knowledge_space.repository.document_repository as repo_mod

    monkeypatch.setattr(repo_mod, "DocumentRepository", _FakeDocRepo)

    class _FakeMCS:
        def __init__(self, session):
            pass

        async def get_user_default_model_name(self, user_id, model_type):
            captured["default_model_user_id"] = user_id
            return "qwen-plus"

        async def get_llm_client_by_model(self, user_id, model):
            captured["client_user_id"] = user_id
            return object()

    import novamind.features.user.services.model_config_service as mcs_mod

    monkeypatch.setattr(mcs_mod, "ModelConfigService", _FakeMCS)

    import novamind.features.knowledge_space.services.video_narrative_service as vn_mod

    class _FakeService:
        def __init__(self, session, llm_client=None, llm_model=""):
            pass

        async def synthesize(self, **kw):
            return {"status": "completed", "chunks_used": 0, "error": None}

    monkeypatch.setattr(vn_mod, "VideoNarrativeService", _FakeService)
    return captured


@pytest.mark.asyncio
async def test_narrative_user_id_none_falls_back_to_uploader(monkeypatch):
    """回归核心：user_id=None（解析完成钩子形态）必须回退 doc.uploader_id。

    修复前默认 int 1 恒真 → 兜底死分支 → captured==1（串用他人凭据）。
    """
    from novamind.features.knowledge_space.tasks import video_narrative_task

    captured = _patch_db_and_models(monkeypatch, uploader_id=42)
    result = await video_narrative_task.process_narrative_task(
        ctx=None, space_id=1, kb_id=2, document_id=3,
        llm_model=None, user_id=None,
    )
    assert result["status"] == "completed"
    assert captured["default_model_user_id"] == 42, "未传 user_id 必须回退文档上传者"
    assert captured["client_user_id"] == 42


@pytest.mark.asyncio
async def test_narrative_explicit_user_id_wins(monkeypatch):
    """显式触发者（API 按需路径）优先于上传者。"""
    from novamind.features.knowledge_space.tasks import video_narrative_task

    captured = _patch_db_and_models(monkeypatch, uploader_id=42)
    await video_narrative_task.process_narrative_task(
        ctx=None, space_id=1, kb_id=2, document_id=3,
        llm_model=None, user_id=7,
    )
    assert captured["default_model_user_id"] == 7


@pytest.mark.asyncio
async def test_narrative_doc_missing_falls_back_to_safe_default(monkeypatch):
    """文档查不到（repo 异常/None）：无兜底基准时退安全默认 1，不抛未定义。"""
    from novamind.features.knowledge_space.tasks import video_narrative_task

    captured = _patch_db_and_models(monkeypatch, uploader_id=42)

    import novamind.features.knowledge_space.repository.document_repository as repo_mod

    class _NoneDocRepo:
        def __init__(self, session):
            pass

        async def get_by_id(self, document_id):
            return None

    monkeypatch.setattr(repo_mod, "DocumentRepository", _NoneDocRepo)

    await video_narrative_task.process_narrative_task(
        ctx=None, space_id=1, kb_id=2, document_id=3,
        llm_model=None, user_id=None,
    )
    assert captured["default_model_user_id"] == 1, "无任何归属基准时才允许安全默认 1"


@pytest.mark.asyncio
async def test_trigger_hook_passes_uploader_id(monkeypatch):
    """解析完成钩子必须把 doc.uploader_id 传给入队（修复前根本不传）。"""
    from novamind.features.knowledge_space.tasks import document_tasks

    fake_kb = SimpleNamespace(
        status=1,
        get_config=lambda: {"parsing": {"video": {"narrative_synthesis": True}}},
    )

    class _FakeKBRepo:
        def __init__(self, session):
            pass

        async def get_by_id(self, kb_id):
            return fake_kb

    import novamind.features.knowledge_space.repository.knowledge_base_repository as kb_repo_mod

    monkeypatch.setattr(kb_repo_mod, "KnowledgeBaseRepository", _FakeKBRepo)
    import novamind.features.knowledge_space.models.knowledge_base as kb_model_mod

    monkeypatch.setattr(kb_model_mod, "KnowledgeBaseStatus", SimpleNamespace(ACTIVE=1))

    class _FakeHookSession(_FakeSession):
        def __init__(self):
            super().__init__(doc=SimpleNamespace(file_type="mp4", uploader_id=42))

    import novamind.core.database.database as db_mod

    monkeypatch.setattr(db_mod, "get_db_session", lambda: _FakeHookSession())
    # Document 以类引用传入 session.get，直接被 FakeHookSession 忽略，无需 patch

    enqueue_calls: list[dict] = []
    from novamind.features.knowledge_space.tasks import video_narrative_task as vnt_mod

    async def _fake_enqueue(**kw):
        enqueue_calls.append(kw)
        return "job-1"

    monkeypatch.setattr(vnt_mod, "enqueue_narrative_synthesis", _fake_enqueue)

    await document_tasks._trigger_narrative_if_enabled(
        kb_id=2, space_id=1, document_id=3,
    )
    assert enqueue_calls, "满足条件时必须入队"
    assert enqueue_calls[0]["user_id"] == 42, "触发钩子必须显式传上传者"
