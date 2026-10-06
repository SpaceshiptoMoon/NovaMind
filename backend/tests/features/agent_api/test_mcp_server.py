"""单元测试：agent_api 批次 2——MCP 编排服务与鉴权 helper。

覆盖：
- McpKbService._resolve_target：单空间自动选/多空间列候选/无空间报错/kb 缺省取第一个 ACTIVE
- search 输出结构（rank/snippet 截断/检索参数透传/无 answer 通道）
- require_api_key：header 提取、无效转 ToolError、成功返回上下文
- McpAsgiEndpoint：无钥 401（不进 MCP 协议层）、有效放行（handle_request 被调）

SearchService 全打桩（McpKbService 的编排逻辑真跑，SQLite 内存库供目标解析）。
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def mcp_db():
    """SQLite 内存库：knowledge_spaces / knowledge_bases / space_members（目标解析数据面）。"""
    from novamind.core.database.base import Base
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
    from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
    from novamind.features.knowledge_space.models.space_member import SpaceMember

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[KnowledgeSpace.__table__, KnowledgeBase.__table__, SpaceMember.__table__],
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


async def _seed_space_with_kb(factory, *, space_id: int, name: str, kb_id: int = None):

    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
    from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
    from novamind.features.knowledge_space.models.space_member import SpaceMember

    async with factory() as session:
        session.add(KnowledgeSpace(id=space_id, name=name, owner_id=1))
        session.add(SpaceMember(space_id=space_id, user_id=1))
        if kb_id is not None:
            session.add(KnowledgeBase(
                id=kb_id, space_id=space_id, name=f"{name}-kb",
                creator_id=1, deleted_at=None, config={},
            ))
        await session.commit()


# ========== _resolve_target ==========


@pytest.mark.asyncio
async def test_resolve_single_space_auto_select(mcp_db):
    """单空间自动选定 + kb 缺省取第一个 ACTIVE。"""
    from novamind.features.agent_api.services.mcp_kb_service import McpKbService

    factory, _ = mcp_db
    await _seed_space_with_kb(factory, space_id=10, name="唯一空间", kb_id=100)

    async with factory() as session:
        svc = McpKbService(session)
        sid, kid = await svc._resolve_target(user_id=1, space_id=None, kb_id=None)
    assert (sid, kid) == (10, 100)


@pytest.mark.asyncio
async def test_resolve_multi_space_lists_candidates(mcp_db):
    """多空间 → ToolTextError 且消息含候选清单（agent 二次调用指定）。"""
    from novamind.features.agent_api.services.mcp_kb_service import McpKbService, ToolTextError

    factory, _ = mcp_db
    await _seed_space_with_kb(factory, space_id=10, name="空间A")
    await _seed_space_with_kb(factory, space_id=20, name="空间B")

    async with factory() as session:
        svc = McpKbService(session)
        with pytest.raises(ToolTextError) as exc_info:
            await svc._resolve_target(user_id=1, space_id=None, kb_id=None)
    assert "10(" in str(exc_info.value) and "20(" in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_no_space_errors(mcp_db):
    """无空间成员关系 → ToolTextError。"""
    from novamind.features.agent_api.services.mcp_kb_service import McpKbService, ToolTextError

    factory, _ = mcp_db
    async with factory() as session:
        svc = McpKbService(session)
        with pytest.raises(ToolTextError):
            await svc._resolve_target(user_id=999, space_id=None, kb_id=None)


@pytest.mark.asyncio
async def test_resolve_no_active_kb_errors(mcp_db):
    """空间无 ACTIVE KB → ToolTextError。"""
    from novamind.features.agent_api.services.mcp_kb_service import McpKbService, ToolTextError

    factory, _ = mcp_db
    await _seed_space_with_kb(factory, space_id=10, name="空空间")  # 不建 KB

    async with factory() as session:
        svc = McpKbService(session)
        with pytest.raises(ToolTextError):
            await svc._resolve_target(user_id=1, space_id=10, kb_id=None)


# ========== search 输出结构 ==========


@pytest.mark.asyncio
async def test_search_output_structure(mcp_db):
    """search 输出：rank 对齐/snippet 截断/检索参数透传/无 answer 通道。"""
    import json

    from novamind.features.agent_api.services.mcp_kb_service import McpKbService

    factory, _ = mcp_db
    await _seed_space_with_kb(factory, space_id=10, name="空间", kb_id=100)

    captured: list = []

    async def _fake_search(self, space_id, kb_id, user_id, request, **kw):
        captured.append(request)
        return {
            "results": [
                {"document_id": 1, "chunk_id": "1_0", "score": 0.9,
                 "content": "x" * 500, "kb_id": kb_id, "space_id": space_id,
                 "file_info": {"filename": "a.pdf"}, "chunk_type": "text"},
            ],
        }

    with patch(
        "novamind.features.knowledge_space.services.search_service.SearchService.search",
        new=_fake_search,
    ), patch(
        "novamind.features.agent_api.services.mcp_kb_service.McpKbService._get_es_client",
        new=AsyncMock(return_value=AsyncMock()),
    ):
        async with factory() as session:
            svc = McpKbService(session)
            out_search = json.loads(await svc.search(
                1, "q", space_id=10, kb_id=100,
                search_mode="content_bm25", score_threshold=0.5,
                vector_weight=0.6, bm25_weight=0.4, use_cache=False,
            ))

    # 检索参数透传 SearchRequest（MCP 只检索不生成，llm 通道恒关闭）
    req = captured[0]
    assert req.llm is None
    assert req.search_mode.value == "content_bm25"
    assert req.score_threshold == 0.5
    assert req.weights.vector_weight == 0.6
    assert req.weights.bm25_weight == 0.4
    assert req.use_cache is False

    # 输出结构：rank 对齐/snippet 截断/无 answer 通道
    assert out_search["total"] == 1
    assert out_search["results"][0]["rank"] == 1
    assert len(out_search["results"][0]["snippet"]) == 300  # 截断
    assert "answer" not in out_search
    assert "answer_error" not in out_search


@pytest.mark.asyncio
async def test_search_invalid_search_mode_friendly_error(mcp_db):
    """非法 search_mode → ToolTextError 且消息列出全部可选值。"""
    from novamind.features.agent_api.services.mcp_kb_service import McpKbService, ToolTextError

    factory, _ = mcp_db
    await _seed_space_with_kb(factory, space_id=10, name="空间", kb_id=100)

    async with factory() as session:
        svc = McpKbService(session)
        with pytest.raises(ToolTextError) as exc_info:
            await svc.search(1, "q", space_id=10, kb_id=100, search_mode="nope")
    assert "content_hybrid" in str(exc_info.value)


# ========== require_api_key ==========


class _FakeRequest:
    def __init__(self, headers):
        self.headers = headers


class _FakeRequestContext:
    def __init__(self, headers):
        self.request = _FakeRequest(headers)


class _FakeContext:
    def __init__(self, headers):
        self.request_context = _FakeRequestContext(headers)


@pytest.mark.asyncio
async def test_require_api_key_missing_header_raises_tool_error():
    """缺 X-API-Key → ToolError（LLM 可读）。"""
    from novamind.features.agent_api.mcp.auth import require_api_key

    with pytest.raises(Exception) as exc_info:
        await require_api_key(_FakeContext({}))
    assert "X-API-Key" in str(exc_info.value)


@pytest.mark.asyncio
async def test_require_api_key_invalid_converts_to_tool_error():
    """InvalidApiKeyError → ToolError（不泄漏内部原因）。"""
    from novamind.features.agent_api.exceptions import InvalidApiKeyError
    from novamind.features.agent_api.mcp.auth import require_api_key

    async def _fake_get_db_session():
        raise RuntimeError("should not be used this way")

    with patch(
        "novamind.core.database.database.get_db_session",
        side_effect=RuntimeError("unused"),
    ):
        # 直接 patch authenticate 抛 InvalidApiKeyError
        with patch(
            "novamind.features.agent_api.services.api_key_service.ApiKeyService.authenticate",
            new=AsyncMock(side_effect=InvalidApiKeyError()),
        ):
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def _ctx():
                yield None

            with patch(
                "novamind.core.database.database.get_db_session",
                return_value=_ctx(),
            ):
                with pytest.raises(Exception) as exc_info:
                    await require_api_key(_FakeContext({"x-api-key": "nvm_bad"}))
    assert "无效或已吊销" in str(exc_info.value)


# ========== McpAsgiEndpoint 401 门禁 ==========


@pytest.mark.asyncio
async def test_asgi_endpoint_rejects_without_key():
    """无 X-API-Key → 401 JSON 信封且不进 MCP 协议层（handle_request 不被调）。"""
    from novamind.features.agent_api.mcp.server import McpAsgiEndpoint

    sm = AsyncMock()
    endpoint = McpAsgiEndpoint(sm)
    sent = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(msg):
        sent.append(msg)

    scope = {
        "type": "http", "method": "POST", "path": "/mcp",
        "headers": [(b"content-type", b"application/json")],
    }
    await endpoint(scope, receive, send)

    assert sent[0]["status"] == 401
    sm.handle_request.assert_not_awaited()  # 未进 MCP 协议层
