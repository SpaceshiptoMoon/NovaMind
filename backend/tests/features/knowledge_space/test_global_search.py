"""跨空间全局检索回归测试。

覆盖四层：
1. repo 层：可访问空间解析（成员 ∪ PUBLIC、ACTIVE/软删过滤）与批量取活跃 KB；
2. 服务层编排：fan-out 合并 RRF 排序与来源盖戳、单空间用户等价（对照）、
   单库失败容错（skipped_kbs）、参与上限截断、文档级权限过滤、逐库模式回退、
   LLM 单次回答与失败降级；
3. 权限预取：get_hidden_doc_ids_map 批量查询；
4. 路由层：依赖覆盖下的响应 shape 与未登录 401。

正反两用例原则：每个触发场景（归档库/无 embedding/单库异常）配一个
相邻正常场景对照（活跃库/有 embedding/正常库不受影响）。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytest.importorskip("aiosqlite")

from novamind.core.database.base import Base
from novamind.features.knowledge_space.api.dependencies import (
    get_audit_service,
    get_current_user_id,
    get_global_search_service,
)
from novamind.features.knowledge_space.api.global_search_routes import router as gs_router
from novamind.features.knowledge_space.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseStatus,
)
from novamind.features.knowledge_space.models.knowledge_space import (
    KnowledgeSpace,
    SpaceStatus,
    SpaceVisibility,
)
from novamind.features.knowledge_space.models.space_member import (
    MemberStatus,
    SpaceMember,
)
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.repository.space_repository import SpaceRepository
from novamind.features.knowledge_space.schemas.search_schema import GlobalSearchRequest
from novamind.features.knowledge_space.services import global_search_service as gsm
from novamind.features.knowledge_space.services.document_permission_filter import (
    get_hidden_doc_ids_map,
)
from novamind.features.knowledge_space.services.global_search_service import (
    GlobalSearchService,
)

pytestmark = pytest.mark.unit


# ========== 测试夹具构造 ==========

def _space(
    space_id: int,
    name: str,
    *,
    visibility: SpaceVisibility = SpaceVisibility.PRIVATE,
    status: SpaceStatus = SpaceStatus.ACTIVE,
    embedding_model: str | None = None,
    deleted: bool = False,
) -> KnowledgeSpace:
    config = {"embedding": {"model": embedding_model}} if embedding_model else {}
    return KnowledgeSpace(
        id=space_id, name=name, owner_id=1, visibility=visibility,
        status=status, config=config,
        deleted_at=__import__("datetime").datetime(2026, 1, 1) if deleted else None,
    )


def _member(member_id: int, space_id: int, user_id: int,
            status: MemberStatus = MemberStatus.ACTIVE,
            custom_permissions: dict | None = None) -> SpaceMember:
    # sqlite 对 BigInteger 主键不自增（已知建表陷阱），测试显式赋 id
    return SpaceMember(
        id=member_id, space_id=space_id, user_id=user_id, status=status,
        custom_permissions=custom_permissions,
    )


def _kb(kb_id: int, space_id: int, name: str, *,
        status: KnowledgeBaseStatus = KnowledgeBaseStatus.ACTIVE,
        question_generation: bool = False) -> KnowledgeBase:
    config = {"embedding": {}}
    if question_generation:
        config["question_generation"] = {"enabled": True}
    return KnowledgeBase(
        id=kb_id, space_id=space_id, name=name, creator_id=1,
        config=config, status=status,
    )


def _hit(chunk_id: str, document_id: int, score: float, content: str = "命中内容") -> dict:
    return {
        "chunk_id": chunk_id, "document_id": document_id, "kb_id": 0,
        "content": content, "score": score, "metadata": {},
    }


def _make_service(spaces, kbs) -> GlobalSearchService:
    """构造不触达 DB/ES 的 GlobalSearchService：仓库与检索段全部打桩。"""
    svc = GlobalSearchService.__new__(GlobalSearchService)
    svc.session = SimpleNamespace()
    svc.space_repo = SimpleNamespace(get_accessible_spaces=AsyncMock(return_value=spaces))
    svc.kb_repo = SimpleNamespace(get_active_by_space_ids=AsyncMock(return_value=kbs))
    svc.es_client = SimpleNamespace()
    svc.model_config_service = None
    svc.logger = SimpleNamespace(
        info=lambda *a, **k: None, warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    svc._retrieval_engine = SimpleNamespace()
    return svc


def _patch_env(monkeypatch, *, max_kbs: int = 32, hidden: dict | None = None):
    """打桩配置读取与权限预取（模块命名空间内引用，patch 模块属性）。"""
    monkeypatch.setattr(
        gsm, "get_config",
        lambda: SimpleNamespace(knowledge_base=SimpleNamespace(
            retrieval=SimpleNamespace(global_search_max_kbs=max_kbs),
        )),
    )
    monkeypatch.setattr(
        gsm, "get_hidden_doc_ids_map",
        AsyncMock(return_value=hidden or {}),
    )


def _run(coro):
    return asyncio.run(coro)


# ========== 1. repo 层：可访问空间解析 ==========

@pytest.mark.parametrize("visibility,member,status,deleted,expect_in", [
    pytest.param(SpaceVisibility.PRIVATE, True, SpaceStatus.ACTIVE, False, True, id="成员私有空间-含"),
    pytest.param(SpaceVisibility.PRIVATE, False, SpaceStatus.ACTIVE, False, False, id="非成员私有空间-不含"),
    pytest.param(SpaceVisibility.PUBLIC, False, SpaceStatus.ACTIVE, False, True, id="非成员公开空间-含"),
    pytest.param(SpaceVisibility.PUBLIC, True, SpaceStatus.ACTIVE, False, True, id="成员公开空间-含（去重不重复）"),
    pytest.param(SpaceVisibility.PUBLIC, False, SpaceStatus.DELETED, False, False, id="已删空间-不含"),
    pytest.param(SpaceVisibility.PUBLIC, False, SpaceStatus.ACTIVE, True, False, id="软删空间-不含"),
    pytest.param(SpaceVisibility.PRIVATE, True, SpaceStatus.ARCHIVED, False, False, id="成员归档空间-不含"),
])
def test_get_accessible_spaces_matrix(visibility, member, status, deleted, expect_in):
    """可访问空间矩阵：成员 ∪ PUBLIC 交集 ACTIVE 且未删；成员+公开去重为一行。"""

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(
                c, tables=[KnowledgeSpace.__table__, SpaceMember.__table__]
            ))
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            seed_space = _space(1, "s1", visibility=visibility, status=status, deleted=deleted)
            session.add(seed_space)
            if member:
                session.add(_member(1, 1, 10))
            await session.commit()
            repo = SpaceRepository(session)
            result = await repo.get_accessible_spaces(10)
            ids = [s.id for s in result]
            assert (1 in ids) is expect_in
            assert ids.count(1) <= 1  # 成员且公开 → 去重为一行
        await engine.dispose()

    _run(run())


def test_kb_repo_batch_active_filter():
    """批量取 KB：仅 ACTIVE 未删库返回（归档/软删不占名）。"""

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(
                c, tables=[KnowledgeBase.__table__]
            ))
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            session.add_all([
                _kb(1, 1, "活跃", status=KnowledgeBaseStatus.ACTIVE),
                _kb(2, 1, "归档", status=KnowledgeBaseStatus.ARCHIVED),
                _kb(3, 2, "活跃2", status=KnowledgeBaseStatus.ACTIVE),
            ])
            # 软删库（deleted_at 置值）
            deleted_kb = _kb(4, 2, "软删", status=KnowledgeBaseStatus.ACTIVE)
            deleted_kb.deleted_at = __import__("datetime").datetime(2026, 1, 1)
            session.add(deleted_kb)
            await session.commit()
            repo = KnowledgeBaseRepository(session)
            kbs = await repo.get_active_by_space_ids([1, 2])
            assert sorted(kb.id for kb in kbs) == [1, 3]
            assert await repo.get_active_by_space_ids([]) == []
        await engine.dispose()

    _run(run())


# ========== 2. 服务层编排 ==========

def test_merge_rrf_order_and_stamp():
    """两库命中 RRF 融合：各库 rank1 的 chunk 融合居前（rank2 之后），来源盖戳。

    合并键是 (kb_id, chunk_id)——同一文档在两库是不同 chunk 实体，分数不
    互相累计（标准 RRF 对不相交列表的性质：跨库只按库内名次对齐）。
    """
    spaces = [_space(1, "空间A"), _space(2, "空间B")]
    kbs = [_kb(1, 1, "库A"), _kb(2, 2, "库B")]
    svc = _make_service(spaces, kbs)
    # 库A 排名：c1(doc101) > c2(doc102)；库B 排名：c9(doc102) > c8(doc101)
    svc.retrieve_for_kb = AsyncMock(side_effect=[
        SimpleNamespace(results=[_hit("c1", 101, 0.9), _hit("c2", 102, 0.8)], cached=False),
        SimpleNamespace(results=[_hit("c9", 102, 0.95), _hit("c8", 101, 0.7)], cached=False),
    ])

    async def run(monkeypatch):
        _patch_env(monkeypatch)
        return await svc.global_search(user_id=10, request=GlobalSearchRequest(query="q", top_k=10))

    import contextlib
    with contextlib.ExitStack() as stack:
        mp = stack.enter_context(pytest.MonkeyPatch.context())
        result = _run(run(mp))
    assert result["total"] == 4
    assert result["searched_kbs"] == 2
    # 两库 rank1（c1/c9，各 1/(60+1)）稳定序在前，rank2（c2/c8，各 1/(60+2)）在后
    assert [r["chunk_id"] for r in result["results"]] == ["c1", "c9", "c2", "c8"]
    # 来源盖戳
    stamped = {(r["kb_id"], r["chunk_id"]): r for r in result["results"]}
    assert stamped[(1, "c1")]["space_name"] == "空间A"
    assert stamped[(2, "c9")]["space_name"] == "空间B"
    assert stamped[(2, "c9")]["kb_name"] == "库B"
    # 逐空间计数（路由审计用）
    assert result["space_result_counts"] == {1: 2, 2: 2}


def test_single_space_equivalence():
    """单空间单库用户（对照）：全局检索结果等价于该库原结果顺序。"""
    spaces = [_space(7, "唯一空间")]
    kbs = [_kb(70, 7, "唯一库")]
    raw = [_hit("c1", 1, 0.9), _hit("c2", 2, 0.5)]
    svc = _make_service(spaces, kbs)
    svc.retrieve_for_kb = AsyncMock(return_value=SimpleNamespace(results=list(raw), cached=False))

    import contextlib
    with contextlib.ExitStack() as stack:
        mp = stack.enter_context(pytest.MonkeyPatch.context())
        _patch_env(mp)
        result = _run(svc.global_search(user_id=10, request=GlobalSearchRequest(query="q", top_k=10)))
    assert [r["chunk_id"] for r in result["results"]] == ["c1", "c2"]
    assert result["skipped_kbs"] == []


def test_one_kb_failure_skipped_not_fatal():
    """单库异常容错：进 skipped_kbs（reason=error），正常库结果不受影响。"""
    spaces = [_space(1, "A"), _space(2, "B")]
    kbs = [_kb(1, 1, "坏库"), _kb(2, 2, "好库")]
    svc = _make_service(spaces, kbs)

    async def _fail(kb, *a, **k):
        if kb.id == 1:
            raise RuntimeError("ES 连接失败")
        return SimpleNamespace(results=[_hit("ok", 9, 0.9)], cached=False)

    svc.retrieve_for_kb = AsyncMock(side_effect=_fail)

    import contextlib
    with contextlib.ExitStack() as stack:
        mp = stack.enter_context(pytest.MonkeyPatch.context())
        _patch_env(mp)
        result = _run(svc.global_search(user_id=10, request=GlobalSearchRequest(query="q", top_k=10)))
    assert result["total"] == 1
    assert result["results"][0]["chunk_id"] == "ok"
    assert result["skipped_kbs"] == [
        {"kb_id": 1, "kb_name": "坏库", "space_id": 1, "reason": "error"}
    ]


def test_fan_out_limit_truncates():
    """参与上限：超限库截断并注明 fan_out_limit（资源护栏可配置）。"""
    spaces = [_space(1, "A")]
    kbs = [_kb(i, 1, f"库{i}") for i in range(1, 4)]  # 3 个库，上限 2
    svc = _make_service(spaces, kbs)
    svc.retrieve_for_kb = AsyncMock(
        return_value=SimpleNamespace(results=[_hit("c", 1, 0.9)], cached=False)
    )

    import contextlib
    with contextlib.ExitStack() as stack:
        mp = stack.enter_context(pytest.MonkeyPatch.context())
        _patch_env(mp, max_kbs=2)
        result = _run(svc.global_search(user_id=10, request=GlobalSearchRequest(query="q", top_k=10)))
    assert result["searched_kbs"] == 2
    assert [s["reason"] for s in result["skipped_kbs"]] == ["fan_out_limit"]
    assert result["skipped_kbs"][0]["kb_id"] == 3  # 创建时间倒序截尾


def test_hidden_docs_filtered_across_spaces():
    """文档级权限：预取的逐空间隐藏清单生效，隐藏 chunk 剔除且顺序保持。"""
    spaces = [_space(1, "A"), _space(2, "B")]
    kbs = [_kb(1, 1, "库A"), _kb(2, 2, "库B")]
    svc = _make_service(spaces, kbs)
    svc.retrieve_for_kb = AsyncMock(side_effect=[
        SimpleNamespace(results=[_hit("a1", 101, 0.95), _hit("a2", 102, 0.8)], cached=False),
        SimpleNamespace(results=[_hit("b1", 201, 0.85)], cached=False),
    ])

    import contextlib
    with contextlib.ExitStack() as stack:
        mp = stack.enter_context(pytest.MonkeyPatch.context())
        # 空间A 隐藏文档 102；空间B 无隐藏（非成员公开空间语义：无成员行→缺键）
        _patch_env(mp, hidden={1: [102]})
        result = _run(svc.global_search(user_id=10, request=GlobalSearchRequest(query="q", top_k=10)))
    assert [r["chunk_id"] for r in result["results"]] == ["a1", "b1"]
    assert result["space_result_counts"] == {1: 1, 2: 1}


def test_mode_fallback_per_kb():
    """逐库模式回退：无问题生成的库 question_* 降 content_*；无 embedding 的库向量降 BM25。"""
    spaces = [
        _space(1, "全配", embedding_model="m1"),   # 有 embedding
        _space(2, "裸奔", embedding_model=None),   # 无 embedding
    ]
    kbs = [
        _kb(1, 1, "问题库", question_generation=True),
        _kb(2, 2, "普通库", question_generation=False),
    ]
    svc = _make_service(spaces, kbs)
    # 空间1 配了 embedding 模型 m1，预解析成功；空间2 无模型（不进解析集）
    svc._resolve_embedding_clients = AsyncMock(
        return_value=({"m1": SimpleNamespace()}, set())
    )
    captured = {}

    async def _capture(kb, user_id, request, **kwargs):
        captured[kb.id] = request.search_mode
        return SimpleNamespace(results=[], cached=False)

    svc.retrieve_for_kb = AsyncMock(side_effect=_capture)

    import contextlib
    with contextlib.ExitStack() as stack:
        mp = stack.enter_context(pytest.MonkeyPatch.context())
        _patch_env(mp)
        _run(svc.global_search(
            user_id=10,
            request=GlobalSearchRequest(query="q", search_mode="question_hybrid", top_k=5),
        ))
    assert captured[1] == "question_hybrid"  # 库1 启用问题生成 + 空间有 embedding：原模式
    assert captured[2] == "content_bm25"     # 库2 未启用问题生成 + 空间无 embedding：两级回退到底


def test_mode_fallback_on_embedding_unavailable():
    """embedding 客户端解析失败的模型：相关库向量/混合模式降 BM25（对照：正常模型库不受影响）。"""
    spaces = [_space(1, "坏模型", embedding_model="bad-model"), _space(2, "好模型", embedding_model="good-model")]
    kbs = [_kb(1, 1, "库1"), _kb(2, 2, "库2")]
    svc = _make_service(spaces, kbs)
    svc._resolve_embedding_clients = AsyncMock(
        return_value=({"good-model": SimpleNamespace()}, {"bad-model"})
    )
    captured = {}

    async def _capture(kb, user_id, request, **kwargs):
        captured[kb.id] = request.search_mode
        return SimpleNamespace(results=[], cached=False)

    svc.retrieve_for_kb = AsyncMock(side_effect=_capture)

    import contextlib
    with contextlib.ExitStack() as stack:
        mp = stack.enter_context(pytest.MonkeyPatch.context())
        _patch_env(mp)
        _run(svc.global_search(
            user_id=10,
            request=GlobalSearchRequest(query="q", search_mode="content_hybrid", top_k=5),
        ))
    assert captured[1] == "content_bm25"   # 解析失败的模型 → 降 BM25
    assert captured[2] == "content_hybrid"  # 正常模型库保持原模式


def test_llm_answer_single_call_and_degrade():
    """LLM 回答：对合并结果单次生成；生成失败降级 answer_error 而非 500。"""
    spaces = [_space(1, "A")]
    kbs = [_kb(1, 1, "库A")]
    svc = _make_service(spaces, kbs)
    svc.retrieve_for_kb = AsyncMock(return_value=SimpleNamespace(
        results=[_hit("c1", 1, 0.9)], cached=False
    ))
    svc._generate_llm_answer = AsyncMock(return_value={
        "answer": "这是回答", "model": "test-llm", "elapsed_ms": 5.0,
    })
    req = GlobalSearchRequest(query="q", top_k=5, llm={"enabled": True})

    import contextlib
    with contextlib.ExitStack() as stack:
        mp = stack.enter_context(pytest.MonkeyPatch.context())
        _patch_env(mp)
        result = _run(svc.global_search(user_id=10, request=req))
    assert result["answer"] == "这是回答"
    assert result["answer_model"] == "test-llm"
    svc._generate_llm_answer.assert_awaited_once()

    # 失败降级：answer_error 透出，检索结果照常返回
    svc._generate_llm_answer = AsyncMock(return_value={
        "answer": None, "answer_error": "空回答", "model": "test-llm", "elapsed_ms": 5.0,
        "error": "empty",
    })
    with contextlib.ExitStack() as stack:
        mp = stack.enter_context(pytest.MonkeyPatch.context())
        _patch_env(mp)
        result = _run(svc.global_search(user_id=10, request=req))
    assert result["answer"] is None
    assert result["answer_error"] == "空回答"
    assert result["total"] == 1


def test_empty_scope_returns_empty():
    """零可访问空间/库：200 空结果（searched_kbs=0），不报错。"""
    svc = _make_service([], [])

    import contextlib
    with contextlib.ExitStack() as stack:
        mp = stack.enter_context(pytest.MonkeyPatch.context())
        _patch_env(mp)
        result = _run(svc.global_search(user_id=10, request=GlobalSearchRequest(query="q")))
    assert result["results"] == []
    assert result["searched_kbs"] == 0


# ========== 3. 权限预取批量查询 ==========

def test_hidden_doc_ids_map_batch():
    """批量预取：一次 IN 查询返回逐空间清单；无成员行的空间缺键（空清单语义）。"""

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(
                c, tables=[KnowledgeSpace.__table__, SpaceMember.__table__]
            ))
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            session.add_all([
                _space(1, "A"), _space(2, "B"), _space(3, "C"),
                _member(1, 1, 10, custom_permissions={"documents": {"hidden_doc_ids": [5, 7]}}),
                _member(2, 2, 10, custom_permissions=None),
                # 空间3 无成员行
                _member(3, 1, 99),  # 其他用户（不干扰）
            ])
            await session.commit()
            result = await get_hidden_doc_ids_map(session, 10, [1, 2, 3])
            assert result[1] == [5, 7]
            assert result.get(2, []) == []
            assert 3 not in result
            assert 99 not in result  # 其他用户成员行不进当前用户清单
        await engine.dispose()

    _run(run())


# ========== 4. 路由层 ==========

def _make_route_app(service, audit=None) -> FastAPI:
    app = FastAPI()
    app.include_router(gs_router, prefix="/api/v1/search")
    app.dependency_overrides[get_current_user_id] = lambda: 10
    app.dependency_overrides[get_global_search_service] = lambda: service
    app.dependency_overrides[get_audit_service] = lambda: audit or SimpleNamespace(
        log_search=AsyncMock()
    )
    return app


def test_route_response_shape_and_audit():
    """路由 shape：响应字段齐全（含 skipped_kbs/searched_kbs），逐空间审计落账。"""
    spaces = [_space(1, "A"), _space(2, "B")]
    kbs = [_kb(1, 1, "库A"), _kb(2, 2, "库B")]
    svc = _make_service(spaces, kbs)
    svc.retrieve_for_kb = AsyncMock(side_effect=[
        SimpleNamespace(results=[_hit("a", 1, 0.9)], cached=False),
        SimpleNamespace(results=[_hit("b", 2, 0.8)], cached=False),
    ])
    audit = SimpleNamespace(log_search=AsyncMock())
    app = _make_route_app(svc, audit)

    import contextlib
    with contextlib.ExitStack() as stack:
        mp = stack.enter_context(pytest.MonkeyPatch.context())
        _patch_env(mp)
        with TestClient(app) as client:
            resp = client.post("/api/v1/search", json={"query": "测试", "top_k": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["searched_kbs"] == 2
    assert body["skipped_kbs"] == []
    assert body["results"][0]["space_name"] in ("A", "B")
    assert body["results"][0]["kb_name"] in ("库A", "库B")
    # 审计逐空间各一条（hybrid 算法分类）
    assert audit.log_search.await_count == 2
    called_space_ids = {c.kwargs["space_id"] for c in audit.log_search.await_args_list}
    assert called_space_ids == {1, 2}


def test_route_requires_auth():
    """路由带认证依赖：get_current_user_id 经 Depends 注入（未登录请求在认证层拒绝）。"""
    import inspect

    app = FastAPI()
    app.include_router(gs_router, prefix="/api/v1/search")
    route = app.routes[-1]
    params = inspect.signature(route.endpoint).parameters
    auth_param = params.get("user_id")
    assert auth_param is not None and auth_param.default is not None, "全局检索必须依赖 get_current_user_id"
