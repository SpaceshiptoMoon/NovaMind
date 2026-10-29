"""单元测试：kb-ops D 治理视图——重复分组 + 贡献统计 + 矛盾候选带。

覆盖：
- find_duplicate_groups：精确 hash 组 / 同归一化名组 / 软删不算 / 无重复空
- support_stats_by_document：sources 提取聚合 / 同消息去重 / web 来源排除
- contradiction 候选带：相似度带边界（复用 char_trigram_similarity 实测）
- contradiction LLM 判定容错：坏 JSON / contradiction=false / 异常 → None

DB 交互 SQLite 内存库定向建表。
"""
import sys
from datetime import datetime
from pathlib import Path

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
async def gov_db():
    """SQLite 内存库：documents + question_answers + kb_events + qa_session_configs。"""
    from novamind.core.database.base import Base
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_ops.models.question_answer import QuestionAnswer
    from novamind.features.knowledge_ops.models.session_config import SessionConfig
    from novamind.features.knowledge_space.models.document import Document

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[
                    Document.__table__,
                    QuestionAnswer.__table__,
                    KbEvent.__table__,
                    SessionConfig.__table__,
                ]
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


async def _seed_doc(factory, *, doc_id: int, kb_id: int = 1, filename: str,
                    file_hash: str | None = None, deleted: bool = False,
                    space_id: int = 10, uploader_id: int = 1):
    from novamind.features.knowledge_space.models.document import Document

    async with factory() as session:
        session.add(Document(
            id=doc_id, space_id=space_id, kb_id=kb_id, uploader_id=uploader_id,
            filename=filename, file_type="pdf", file_size=100,
            file_hash=file_hash or f"h{doc_id}",
            deleted_at=datetime.now() if deleted else None,
        ))
        await session.commit()


# ========== 重复分组 ==========


@pytest.mark.asyncio
async def test_exact_hash_group(gov_db):
    """精确重复：同 KB 同 file_hash 两文档成组；hash 不同不组。"""
    from novamind.features.knowledge_ops.repository.governance_repository import (
        GovernanceRepository,
    )

    factory, _ = gov_db
    # 精确重复的真实场景=不同成员各自上传同一文件（同 uploader 会撞
    # uq_kb_uploader_file_hash 唯一约束——这正是该约束的语义）
    await _seed_doc(factory, doc_id=1, filename="退货政策.pdf", file_hash="same-hash", uploader_id=1)
    await _seed_doc(factory, doc_id=2, filename="退货政策v2.pdf", file_hash="same-hash", uploader_id=2)
    await _seed_doc(factory, doc_id=3, filename="不同内容.pdf", file_hash="other-hash")

    async with factory() as session:
        repo = GovernanceRepository(session)
        groups = await repo.find_duplicate_groups(10)

    exact = [g for g in groups if g["group_type"] == "exact_hash"]
    assert len(exact) == 1
    assert {d["document_id"] for d in exact[0]["documents"]} == {1, 2}


@pytest.mark.asyncio
async def test_same_normalized_name_group_and_softdelete_excluded(gov_db):
    """同归一化名分组；软删文档不计入。"""
    from novamind.features.knowledge_ops.repository.governance_repository import (
        GovernanceRepository,
    )

    factory, _ = gov_db
    await _seed_doc(factory, doc_id=1, filename="政策v1.pdf")
    await _seed_doc(factory, doc_id=2, filename="政策_final.pdf")
    await _seed_doc(factory, doc_id=3, filename="政策旧版.pdf", deleted=True)  # 软删不算

    async with factory() as session:
        repo = GovernanceRepository(session)
        groups = await repo.find_duplicate_groups(10)

    name_groups = [g for g in groups if g["group_type"] == "same_normalized_name"]
    assert len(name_groups) == 1
    ids = {d["document_id"] for d in name_groups[0]["documents"]}
    assert ids == {1, 2}  # 软删的 3 不在


@pytest.mark.asyncio
async def test_no_duplicates_returns_empty(gov_db):
    """无重复返回空（反例）。"""
    from novamind.features.knowledge_ops.repository.governance_repository import (
        GovernanceRepository,
    )

    factory, _ = gov_db
    await _seed_doc(factory, doc_id=1, filename="a.pdf", file_hash="h1")
    await _seed_doc(factory, doc_id=2, filename="b.pdf", file_hash="h2")

    async with factory() as session:
        repo = GovernanceRepository(session)
        groups = await repo.find_duplicate_groups(10)
    assert groups == []


# ========== 支撑回答统计 ==========


@pytest.mark.asyncio
async def test_support_stats_aggregation(gov_db):
    """sources 聚合：kb 来源计数、同消息去重、web 来源排除。"""
    from novamind.features.knowledge_ops.models.question_answer import QuestionAnswer
    from novamind.features.knowledge_ops.repository.governance_repository import (
        GovernanceRepository,
    )

    factory, _ = gov_db
    async with factory() as session:
        # 一条消息引用 doc1 两次 + doc2 一次 + web 一次 → doc1 只算 1 次支撑
        session.add(QuestionAnswer(
            id=1, session_id="s1", user_id=1, role="assistant", content="a",
            space_id=10,
            extra={"sources": [
                {"kind": "kb", "document_id": 1},
                {"kind": "kb", "document_id": 1},
                {"kind": "kb", "document_id": 2},
                {"kind": "web", "url": "http://x"},
            ]},
        ))
        # 第二条消息引用 doc1
        session.add(QuestionAnswer(
            id=2, session_id="s2", user_id=1, role="assistant", content="b",
            space_id=10,
            extra={"sources": [{"kind": "kb", "document_id": 1}]},
        ))
        await session.commit()

    async with factory() as session:
        repo = GovernanceRepository(session)
        stats = await repo.support_stats_by_document(10)

    by_doc = {s["document_id"]: s["support_count"] for s in stats}
    assert by_doc[1] == 2  # 两条消息各支撑 1 次
    assert by_doc[2] == 1
    assert all(k != "http://x" for k in by_doc)  # web 不进


# ========== 点击核验统计（citation_click 聚合 + 存量空间归属兜底） ==========


@pytest.mark.asyncio
async def test_citation_stats_with_session_fallback(gov_db):
    """点击统计双通道：space_id 直配命中 + NULL 存量经会话 RAG 绑定兜底找回。"""
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_ops.models.session_config import SessionConfig
    from novamind.features.knowledge_ops.repository.governance_repository import (
        GovernanceRepository,
    )

    factory, _ = gov_db
    async with factory() as session:
        # 会话配置：s-bound 绑定空间 10（新链路场景），s-legacy 绑定空间 10（存量 NULL 事件）
        session.add(SessionConfig(
            session_id="s-bound", user_id=1,
            kb_bindings={"space_id": 10, "kb_ids": [1], "auto_rag": True},
        ))
        session.add(SessionConfig(
            session_id="s-legacy", user_id=1,
            kb_bindings={"space_id": 10, "kb_ids": [1], "auto_rag": True},
        ))
        # 直接归属空间 10 的事件（新链路）
        session.add(KbEvent(
            event_type="citation_click", user_id=1, session_id="s-bound",
            space_id=10, kb_id=1, extra={"document_id": 1},
        ))
        # 存量 NULL space 事件（写侧收口前），经 s-legacy 兜底找回
        session.add(KbEvent(
            event_type="citation_click", user_id=1, session_id="s-legacy",
            space_id=None, kb_id=1, extra={"document_id": 2},
        ))
        session.add(KbEvent(
            event_type="citation_click", user_id=1, session_id="s-legacy",
            space_id=None, kb_id=1, extra={"document_id": 2},
        ))
        await session.commit()

    async with factory() as session:
        repo = GovernanceRepository(session)
        stats = await repo.citation_stats_by_document(10)

    by_doc = {s["document_id"]: s["click_count"] for s in stats}
    assert by_doc == {1: 1, 2: 2}  # 兜底找回 doc2 的两次点击


@pytest.mark.asyncio
async def test_citation_stats_excludes_unresolvable_and_other_space(gov_db):
    """反例：兜底后仍无法判定归属（无会话配置/配置绑别空间）的事件不计入。"""
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_ops.models.session_config import SessionConfig
    from novamind.features.knowledge_ops.repository.governance_repository import (
        GovernanceRepository,
    )

    factory, _ = gov_db
    async with factory() as session:
        # no-cfg 无会话配置（无从兜底）；other 绑定空间 99
        session.add(SessionConfig(
            session_id="other", user_id=1,
            kb_bindings={"space_id": 99, "kb_ids": [1], "auto_rag": True},
        ))
        session.add(KbEvent(
            event_type="citation_click", user_id=1, session_id="no-cfg",
            space_id=None, kb_id=1, extra={"document_id": 1},
        ))
        session.add(KbEvent(
            event_type="citation_click", user_id=1, session_id="other",
            space_id=None, kb_id=1, extra={"document_id": 2},
        ))
        await session.commit()

    async with factory() as session:
        repo = GovernanceRepository(session)
        stats = await repo.citation_stats_by_document(10)

    assert stats == []  # 两类都不可归到空间 10


# ========== 矛盾候选带 ==========


def test_contradiction_similarity_band():
    """候选带边界：相似改写落入带内；完全相同/无关落在带外（用真实文本验证）。"""
    from novamind.features.knowledge_ops.services.contradiction_detector import (
        SIMILARITY_BAND_HIGH,
        SIMILARITY_BAND_LOW,
    )
    from novamind.features.knowledge_ops.services.query_reformulate_detector import (
        char_trigram_similarity,
        normalize_query,
    )

    # 实测 sim=0.741（「7天」vs「15天」在 3-gram 下差异太小不足以落带，
    # 用长句让单点数字差异占比收敛到带内——判定依赖上下文而非单数字）
    raw = "退货期限是自收货之日起7天内，逾期将无法办理退货服务"
    a = normalize_query(raw)
    b = normalize_query("退货期限是自收货之日起15天内，逾期将无法办理退货服务")
    c = normalize_query(raw)  # 完全相同 → 带外（重复而非矛盾）
    d = normalize_query("今天天气很好适合出门散步运动")

    sim_ab = char_trigram_similarity(a, b)
    assert SIMILARITY_BAND_LOW <= sim_ab <= SIMILARITY_BAND_HIGH  # 矛盾候选
    assert char_trigram_similarity(a, c) > SIMILARITY_BAND_HIGH   # 重复，带外
    assert char_trigram_similarity(a, d) < SIMILARITY_BAND_LOW    # 无关，带外


# ========== LLM 判定容错 ==========


@pytest.mark.asyncio
async def test_llm_contradiction_verdict_tolerant():
    """判定容错：矛盾 true 返回理由；false/坏 JSON/异常返回 None（宁漏勿误）。"""
    from novamind.features.knowledge_ops.services.contradiction_detector import (
        _llm_check_contradiction,
    )

    class _LLM:
        def __init__(self, resp=None, raise_exc=None):
            self._resp = resp
            self._raise = raise_exc

        async def generate_text(self, **kwargs):
            if self._raise:
                raise self._raise
            return self._resp

    yes = await _llm_check_contradiction(
        _LLM('{"contradiction": true, "reason": "退货期限 7 天 vs 15 天"}'), "a", "b",
    )
    assert yes == "退货期限 7 天 vs 15 天"

    no = await _llm_check_contradiction(
        _LLM('{"contradiction": false, "reason": "无矛盾"}'), "a", "b",
    )
    assert no is None

    bad = await _llm_check_contradiction(_LLM("不是JSON"), "a", "b")
    assert bad is None

    err = await _llm_check_contradiction(_LLM(raise_exc=RuntimeError("timeout")), "a", "b")
    assert err is None
