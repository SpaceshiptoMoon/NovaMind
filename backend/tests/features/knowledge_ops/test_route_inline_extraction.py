"""kb-ops 路由内联业务下沉回归测试（处置联动 + gap 转测试集）。

SuggestionResolveService：跨空间按不存在处理（不泄漏）、new_version accept
触发 supersede 联动、contradiction accept 走通知、dismiss 不联动；
GapToTestSetService：空窗口拒绝、query→用例映射语义。
"""
from types import SimpleNamespace

import pytest

from novamind.features.knowledge_ops.exceptions import (
    KbOpsError,
    KbOpsNotFoundError,
)
from novamind.features.knowledge_ops.services.gap_to_testset_service import (
    GapToTestSetService,
)
from novamind.features.knowledge_ops.services.suggestion_resolve_service import (
    SuggestionResolveService,
)

pytestmark = pytest.mark.unit


# ========== SuggestionResolveService ==========


def _make_resolve_service(suggestion, resolved_row=None, supersede_calls=None):
    """桩 repository 与 session；supersede 走函数内懒 import，用 monkeypatch 替换。"""
    async def _get_by_id(_id):
        return suggestion

    async def _resolve(_id, action, user_id):
        return resolved_row or SimpleNamespace(status=action, resolved_by=user_id)

    repo = SimpleNamespace(get_by_id=_get_by_id, resolve=_resolve)

    async def _commit():
        pass

    session = SimpleNamespace(commit=_commit)
    svc = SuggestionResolveService.__new__(SuggestionResolveService)
    svc.session = session
    svc.repo = repo
    svc._supersede_calls = supersede_calls if supersede_calls is not None else []
    return svc


@pytest.mark.asyncio
async def test_resolve_cross_space_treated_as_not_found(monkeypatch):
    """跨空间建议按不存在处理，不泄漏存在性"""
    suggestion = SimpleNamespace(space_id=999, suggestion_type="new_version")
    svc = _make_resolve_service(suggestion)

    with pytest.raises(KbOpsNotFoundError):
        await svc.resolve(space_id=10, suggestion_id=1, action="accepted", user_id=9)


@pytest.mark.asyncio
async def test_resolve_accept_new_version_triggers_supersede(monkeypatch):
    """new_version 建议 accept 且新旧文档齐全 → 联动 supersede 并返回旧文档 ID"""
    suggestion = SimpleNamespace(
        space_id=10, suggestion_type="new_version", old_doc_id=5, new_doc_id=6,
    )
    svc = _make_resolve_service(suggestion)

    import novamind.features.knowledge_ops.services.suggestion_resolve_service as mod

    class _FakeLifecycle:
        def __init__(self, session):
            pass

        async def supersede(self, old_doc_id, new_doc_id):
            svc._supersede_calls.append((old_doc_id, new_doc_id))
            return SimpleNamespace(id=old_doc_id)

    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.lifecycle_service.LifecycleService",
        _FakeLifecycle,
    )

    resolved, superseded_doc_id = await svc.resolve(
        space_id=10, suggestion_id=1, action="accepted", user_id=9,
    )

    assert svc._supersede_calls == [(5, 6)]
    assert superseded_doc_id == 5
    assert resolved.status == "accepted"


@pytest.mark.asyncio
async def test_resolve_accept_new_version_without_docs_skips_supersede(monkeypatch):
    """新旧文档任一缺失 → 不触发 supersede，superseded_doc_id 为 None"""
    suggestion = SimpleNamespace(
        space_id=10, suggestion_type="new_version", old_doc_id=None, new_doc_id=6,
    )
    svc = _make_resolve_service(suggestion)

    resolved, superseded_doc_id = await svc.resolve(
        space_id=10, suggestion_id=1, action="accepted", user_id=9,
    )

    assert svc._supersede_calls == []
    assert superseded_doc_id is None
    assert resolved.status == "accepted"


@pytest.mark.asyncio
async def test_resolve_dismiss_no_side_effects(monkeypatch):
    """dismiss：不联动 supersede/通知，仅状态翻转"""
    suggestion = SimpleNamespace(
        space_id=10, suggestion_type="new_version", old_doc_id=5, new_doc_id=6,
    )
    svc = _make_resolve_service(suggestion)

    resolved, superseded_doc_id = await svc.resolve(
        space_id=10, suggestion_id=1, action="dismissed", user_id=9,
    )

    assert svc._supersede_calls == []
    assert superseded_doc_id is None
    assert resolved.status == "dismissed"


# ========== GapToTestSetService ==========


def _make_gap_service(items, captured=None):
    async def _list_gap_items(_space_id, _start, _end, **kw):
        return items

    repo = SimpleNamespace(list_gap_items=_list_gap_items)
    eval_calls = {"append": [], "create": []}

    class _FakeEval:
        async def append_cases_to_test_set(self, **kw):
            eval_calls["append"].append(kw)
            return SimpleNamespace(id=kw["test_set_id"], total_cases=99)

        async def create_test_set_from_cases(self, **kw):
            eval_calls["create"].append(kw)
            return SimpleNamespace(id=77, total_cases=len(kw["cases"]))

    async def _commit():
        pass

    session = SimpleNamespace(commit=_commit)
    svc = GapToTestSetService(session, _FakeEval())
    svc.repo = repo
    svc._eval_calls = eval_calls
    return svc


@pytest.mark.asyncio
async def test_gap_convert_empty_window_rejects():
    """窗口内无 gap 条目 → KbOpsError，不建空测试集"""
    svc = _make_gap_service([])

    with pytest.raises(KbOpsError, match="没有内容缺口"):
        await svc.convert(space_id=10, kb_id=2, user_id=1)


@pytest.mark.asyncio
async def test_gap_convert_maps_query_to_case():
    """gap 条目 → 检索命中验证型用例映射：question=query，expected_answer 带命中频次"""
    svc = _make_gap_service([{"query": "退货流程", "hit_count": 3}])

    result = await svc.convert(space_id=10, kb_id=2, user_id=1)

    created = svc._eval_calls["create"]
    assert len(created) == 1
    assert created[0]["space_id"] == 10
    assert created[0]["kb_id"] == 2
    case = created[0]["cases"][0]
    assert case["question"] == "退货流程"
    assert "3" in case["expected_answer"]
    assert result == {
        "test_set_id": 77,
        "total_cases": 1,
        "added_cases": 1,
        "message": "gap 条目转测试用例已创建",
    }


@pytest.mark.asyncio
async def test_gap_convert_existing_set_appends():
    """传 test_set_id 走追加路径，不新建"""
    svc = _make_gap_service([{"query": "发票", "hit_count": 1}])

    result = await svc.convert(space_id=10, kb_id=2, user_id=1, test_set_id=55)

    assert svc._eval_calls["create"] == []
    assert len(svc._eval_calls["append"]) == 1
    assert svc._eval_calls["append"][0]["test_set_id"] == 55
    assert result["test_set_id"] == 55
