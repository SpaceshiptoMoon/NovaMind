"""Wiki 生成管道四阶段流程测试。

mock LLM 验证完整数据流：Pass 0 候选抽取 → 分块引文 → Reduce 写页 →
Finalize 链接对齐。同时覆盖 slug 连续性、无引用拒写、max_pages 截断。
SQLite 定向建表（BigInteger 降级）。
"""
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.wiki import (
    WikiEditSource,
    WikiIngestRecord,
    WikiPage,
    WikiPageRevision,
    WikiIngestStatus,
)
from novamind.features.knowledge_space.repository.wiki_repository import (
    WikiPageRepository,
)
from novamind.features.knowledge_space.services.wiki_ingest_service import (
    IngestOutcome,
    WikiIngestService,
    normalize_slug,
)

# 编译期把 BigInteger 降为 INTEGER，仅影响本测试的 SQLite 建表，不改模型。
from sqlalchemy import BigInteger as _B


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


def _make_service(session: AsyncSession, llm, wiki_config=None) -> WikiIngestService:
    svc = WikiIngestService(
        session,
        llm_client=llm,
        minio_client=None,
        es_client=None,
        wiki_config=wiki_config or {},
        kb_id=1,
        space_id=1,
        document_id=100,
    )
    svc.bind_record(SimpleNamespace(
        start_step=lambda *a, **k: None,
        finish_step=lambda *a, **k: None,
        fail_step=lambda *a, **k: None,
    ))
    return svc


class MockLLM:
    """按调用序返回预设响应；记录 prompt 供断言"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    async def generate_text(self, *, prompt, **kwargs):
        self.prompts.append(prompt)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest_asyncio.fixture
async def wiki_db():
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
    tables = [WikiPage.__table__, WikiPageRevision.__table__, WikiIngestRecord.__table__,
              KnowledgeBase.__table__]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _cand_json():
    return json.dumps({
        "entities": [
            {"name": "甲公司", "slug": "entity/jia-gong-si", "aliases": ["Acme"],
             "description": "一家技术公司", "details": "成立于 2020 年"},
            {"name": "乙产品", "slug": "entity/yi-chan-pin", "aliases": [],
             "description": "旗舰产品", "details": "RAG 平台"},
        ],
        "concepts": [
            {"name": "检索增强生成", "slug": "concept/rag", "aliases": ["RAG"],
             "description": "检索与生成结合的技术", "details": "先检索后生成"},
        ],
    }, ensure_ascii=False)


# 句柄机制（对齐 WeKnora）：引文批内 chunk 以 c000/c001 短句柄呈现，
# 模型（mock）返回句柄，管道还原为真实 chunk_id
_CITE_JSON = json.dumps({
    "citations": {
        "entity/jia-gong-si": ["c000"],
        "entity/yi-chan-pin": ["c000", "c001"],
        "concept/rag": ["c001"],
    },
    "new_slugs": [],
}, ensure_ascii=False)


def _page_md(name):
    return f"SUMMARY: {name}的测试页面\n\n# {name}\n\n详见 [[concept/rag|检索增强生成]]。"


_CHUNKS = [
    {"chunk_id": "100_0", "content": "甲公司成立于2020年，专注企业AI产品。"},
    {"chunk_id": "100_1", "content": "乙产品是甲公司的旗舰RAG平台，实现了检索增强生成。"},
]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_full_pipeline(wiki_db):
    """四阶段完整流程：3 个候选全部有引用 → 3 页落库 + 互链 + 快照不产生"""
    llm = MockLLM([
        _cand_json(),          # Pass 0
        _CITE_JSON,            # Pass 1（单批）
        _page_md("甲公司"),     # Reduce ×3
        _page_md("乙产品"),
        _page_md("检索增强生成"),
    ])
    svc = _make_service(wiki_db, llm)
    outcome = await svc.ingest_document(full_text="甲公司文档正文……", chunks=_CHUNKS)

    assert outcome.pages_created == 3
    assert outcome.pages_updated == 0
    assert outcome.candidates == 3
    assert outcome.skipped_no_citation == 0

    repo = WikiPageRepository(wiki_db)
    page = await repo.get_by_slug(1, "entity/jia-gong-si")
    assert page is not None
    assert page.summary == "甲公司的测试页面"
    assert page.source_refs == ["100|"]
    assert page.chunk_refs == ["100_100_0"]
    assert page.last_edit_source == WikiEditSource.PIPELINE
    assert page.version == 1
    # 指向 concept/rag 的链接保留（该 slug 存活）
    assert "concept/rag" in (page.out_links or [])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_slug_continuity_prompt(wiki_db):
    """KB 已有 slug 必须传给 Pass 0 提示词（slug 连续性）"""
    repo = WikiPageRepository(wiki_db)
    await repo.create_page({"space_id": 1, "kb_id": 1, "slug": "entity/jia-gong-si", "title": "甲公司",
                            "page_type": "entity", "content": "旧内容"})

    llm = MockLLM([_cand_json(), _CITE_JSON, _page_md("甲公司"), _page_md("乙产品"), _page_md("检索增强生成")])
    svc = _make_service(wiki_db, llm)
    await svc.ingest_document(full_text="正文", chunks=_CHUNKS)

    assert "<previous_slugs>" in llm.prompts[0]
    assert "- entity/jia-gong-si" in llm.prompts[0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_updates_existing_page_with_snapshot(wiki_db):
    """已有页面：内容变化 → 版本递增 + 旧版本快照落库"""
    repo = WikiPageRepository(wiki_db)
    await repo.create_page({"space_id": 1, "kb_id": 1, "slug": "concept/rag", "title": "检索增强生成",
                            "page_type": "concept", "content": "旧版内容", "version": 3})

    llm = MockLLM([_cand_json(), _CITE_JSON, _page_md("甲公司"), _page_md("乙产品"),
                   "SUMMARY: 更新后的RAG页\n\n# 检索增强生成\n\n新内容"])
    svc = _make_service(wiki_db, llm)
    await svc.ingest_document(full_text="正文", chunks=_CHUNKS)

    page = await repo.get_by_slug(1, "concept/rag")
    assert page.version == 4
    assert "新内容" in page.content
    assert page.source_refs == ["100|"]  # 来源合并

    revisions = await repo.list_revisions(page.id)
    assert len(revisions) == 1
    assert revisions[0].version == 3
    assert revisions[0].content == "旧版内容"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_unchanged_content_no_version_bump(wiki_db):
    """内容无变化 → version 不递增、不产生快照（簿记写语义）"""
    repo = WikiPageRepository(wiki_db)
    stable_md = "SUMMARY: 甲公司的测试页面\n\n# 甲公司\n\n详见 [[concept/rag|检索增强生成]]。"
    await repo.create_page({"space_id": 1, "kb_id": 1, "slug": "entity/jia-gong-si", "title": "甲公司",
                            "page_type": "entity", "content": stable_md.split("\n\n", 1)[1],
                            "summary": "甲公司的测试页面"})
    # concept/rag 也存在（否则链接被判死链剔除，第二次生成内容就变了）
    await repo.create_page({"space_id": 1, "kb_id": 1, "slug": "concept/rag", "title": "检索增强生成",
                            "page_type": "concept", "content": "x"})

    llm = MockLLM([_cand_json(), _CITE_JSON, stable_md, _page_md("乙产品"), _page_md("检索增强生成")])
    svc = _make_service(wiki_db, llm)
    await svc.ingest_document(full_text="正文", chunks=_CHUNKS)

    page = await repo.get_by_slug(1, "entity/jia-gong-si")
    assert page.version == 1
    revisions = await repo.list_revisions(page.id)
    assert len(revisions) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_empty_text_skips(wiki_db):
    """解析全文为空 → 直接返回，不调 LLM"""
    llm = MockLLM([])
    svc = _make_service(wiki_db, llm)
    outcome = await svc.ingest_document(full_text="   ", chunks=_CHUNKS)
    assert outcome.pages_created == 0
    assert llm.prompts == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_no_candidates_skips_reduce(wiki_db):
    """Pass 0 返回空 → 无页面写入"""
    llm = MockLLM([json.dumps({"entities": [], "concepts": []})])
    svc = _make_service(wiki_db, llm)
    outcome = await svc.ingest_document(full_text="正文", chunks=_CHUNKS)
    assert outcome.pages_created == 0
    assert len(llm.prompts) == 1  # 只有 Pass 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_max_pages_truncation(wiki_db):
    """max_pages_per_ingest 截断：只写前 N 个有引用的候选"""
    llm = MockLLM([_cand_json(), _CITE_JSON, _page_md("甲公司"), _page_md("乙产品"), _page_md("检索增强生成")])
    svc = _make_service(wiki_db, llm, wiki_config={"max_pages_per_ingest": 2})
    outcome = await svc.ingest_document(full_text="正文", chunks=_CHUNKS)
    assert outcome.pages_created == 2
    assert outcome.truncated is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finalize_realigns_links_and_removes_dead_links(wiki_db):
    """Finalize：死链剔除 + in/out 双向对齐"""
    repo = WikiPageRepository(wiki_db)
    a = await repo.create_page({"space_id": 1, "kb_id": 1, "slug": "entity/a", "title": "A",
                                "page_type": "entity", "content": "x",
                                "out_links": ["entity/b", "entity/ghost", "entity/a"]})
    b = await repo.create_page({"space_id": 1, "kb_id": 1, "slug": "entity/b", "title": "B",
                                "page_type": "entity", "content": "x",
                                "in_links": ["entity/ghost"]})

    llm = MockLLM([json.dumps({"entities": [], "concepts": []})])
    svc = _make_service(wiki_db, llm)
    await svc.ingest_document(full_text="正文", chunks=_CHUNKS)

    await wiki_db.refresh(a)
    await wiki_db.refresh(b)
    assert a.out_links == ["entity/b"]
    assert b.in_links == ["entity/a"]
    assert a.in_links == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reduce_failure_does_not_block_others(wiki_db):
    """单页 LLM 失败 → 该页跳过，其余照常落库"""
    llm = MockLLM([
        _cand_json(),
        _CITE_JSON,
        RuntimeError("llm down"),   # 第一个 Reduce 调用失败
        _page_md("乙产品"),
        _page_md("检索增强生成"),
    ])
    svc = _make_service(wiki_db, llm)
    outcome = await svc.ingest_document(full_text="正文", chunks=_CHUNKS)
    assert outcome.pages_created == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reduce_no_semaphore_deadlock_under_many_candidates(wiki_db):
    """回归：Reduce 并发控制收敛到 _call_llm_text 单层信号量。

    历史缺陷：_generate_page_content 外层持有 self._semaphore，内部
    _call_llm_text 再次获取同一 Semaphore。并发数 N、候选数 > N 时，
    许可被「外层已获取、内层在等待」的协程占死 → gather 永久挂起
    （端到端实测：4 并发 14 候选，2 个 LLM 调用完成后全场停滞）。
    本测试用超过 LLM_CONCURRENCY 的候选数跑完整管道，超时即判死锁。
    """
    import asyncio as _asyncio

    n_candidates = 15  # > LLM_CONCURRENCY(4)，旧代码必然死锁

    entities = []
    cite_map = {}
    for i in range(n_candidates):
        slug = f"entity/e{i}"
        entities.append({"name": f"实体{i}", "slug": slug, "aliases": [],
                         "description": "d", "details": "x"})
        cite_map[slug] = ["c000"]  # chunk 句柄（批内 c000 = chunk 100_0）
    cand_json = json.dumps({"entities": entities, "concepts": []}, ensure_ascii=False)
    cite_json = json.dumps({"citations": cite_map, "new_slugs": []}, ensure_ascii=False)

    class SlowLLM:
        """真实异步延迟，逼出信号量交错；记录同时在途的调用数"""

        def __init__(self):
            self.in_flight = 0
            self.peak = 0

        async def generate_text(self, *, prompt, **kwargs):
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            await _asyncio.sleep(0.05)
            self.in_flight -= 1
            return _page_md("页")

    llm = SlowLLM()
    llm.responses = None  # 兼容 MockLLM 字段约定（未使用）

    class CandLLM:
        """前两次调用（extract/cite）返回 JSON，其余返回页面正文"""

        def __init__(self):
            self.calls = 0
            self.inner = SlowLLM()

        async def generate_text(self, *, prompt, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return cand_json
            if self.calls == 2:
                return cite_json
            return await self.inner.generate_text(prompt=prompt, **kwargs)

    svc = _make_service(wiki_db, CandLLM())
    outcome = await _asyncio.wait_for(
        svc.ingest_document(full_text="正文", chunks=_CHUNKS),
        timeout=10,
    )
    assert outcome.pages_created == n_candidates


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prune_revisions_two_tier(wiki_db):
    """快照两级保留：软上限只清 pipeline 来源，user 来源保留到硬上限"""
    repo = WikiPageRepository(wiki_db)
    page = await repo.create_page({"space_id": 1, "kb_id": 1, "slug": "entity/a", "title": "A",
                                   "page_type": "entity", "content": "v0"})
    # 造 60 条：前 5 条 user 来源，其余 pipeline 来源
    for i in range(60):
        rev = WikiPageRevision(
            page_id=page.id, kb_id=1, version=i + 1, slug=page.slug,
            title="A", page_type="entity", status="published",
            content=f"v{i}", summary="", aliases=[],
            edit_source="user" if i < 5 else "pipeline",
        )
        wiki_db.add(rev)
    await wiki_db.flush()

    pruned = await repo.prune_revisions(page.id)
    # 60 条 > 软上限 50：版本倒序最旧的 10 条（版本 1-10）进入裁剪候选，
    # 其中版本 6-10 是 pipeline 来源可裁 5 条，版本 1-5 是 user 来源保留
    assert pruned == 5
    remaining = await repo.list_revisions(page.id)
    assert len(remaining) == 55
    # user 来源的版本 1-5 全部保留；被裁的是 pipeline 的 6-10
    versions = {r.version for r in remaining}
    assert {1, 2, 3, 4, 5} <= versions
    assert not versions & {6, 7, 8, 9, 10}


def test_normalize_slug_edge_cases():
    """slug 规范化边界"""
    assert normalize_slug('Entity/Acme Corp') == 'entity/acme-corp'
    assert normalize_slug('concept/--x--') == 'concept/x'
    assert normalize_slug('///') == ''
    assert normalize_slug('概念/RAG 检索') == '概念/rag-检索'


# ==================== 批1 对齐：句柄防错 + draft→publish ====================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_slug_handles_in_valid_links_prompt(wiki_db):
    """Reduce 的 valid_links 以 ref-N = slug 句柄形式喂给模型（防 slug 复述错误）"""
    llm = MockLLM([_cand_json(), _CITE_JSON, _page_md("甲公司"), _page_md("乙产品"), _page_md("检索增强生成")])
    svc = _make_service(wiki_db, llm)
    await svc.ingest_document(full_text="正文", chunks=_CHUNKS)

    # Reduce 阶段的 prompt（第 3 个起）应含句柄行而不含裸 slug 清单
    reduce_prompts = llm.prompts[2:]
    assert any("- ref-1 = " in p for p in reduce_prompts)
    assert all("<valid_links>" in p for p in reduce_prompts)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_model_handle_output_decoded(wiki_db):
    """模型返回 [[ref-N|显示名]] → 管道 decode 还原为真实 slug 并进 out_links。

    valid_link_slugs 排序后 concept/rag 居首 → rag = ref-1。生成正文引用
    ref-1（有效）与 ref-99（幻觉），前者还原并保留出链，后者无映射被白名单剔除。
    """
    rag_handle_md = "SUMMARY: 乙产品测试页\n\n# 乙产品\n\n平台能力见 [[ref-1|检索增强生成]]与[[ref-99|幻觉]]。"

    llm = MockLLM([_cand_json(), _CITE_JSON, _page_md("甲公司"), rag_handle_md, _page_md("检索增强生成")])
    svc = _make_service(wiki_db, llm)
    outcome = await svc.ingest_document(full_text="正文", chunks=_CHUNKS)
    assert outcome.pages_created == 3

    repo = WikiPageRepository(wiki_db)
    page = await repo.get_by_slug(1, "entity/yi-chan-pin")
    # ref-3 → concept/rag 还原成功且在白名单内 → 出链保留
    assert "concept/rag" in (page.out_links or [])
    # ref-99 无映射 → 白名单剔除，不出链
    assert "ref-99" not in (page.out_links or [])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_citation_unknown_chunk_handle_dropped(wiki_db):
    """引文阶段模型返回未知句柄 → 丢弃，不产生幽灵 chunk_id"""
    bad_cite = json.dumps({
        "citations": {
            "entity/jia-gong-si": ["c000", "c777"],  # c777 幻觉句柄
        },
        "new_slugs": [],
    }, ensure_ascii=False)
    llm = MockLLM([
        _cand_json(), bad_cite,
        _page_md("甲公司"), _page_md("乙产品"), _page_md("检索增强生成"),
    ])
    svc = _make_service(wiki_db, llm)
    outcome = await svc.ingest_document(full_text="正文", chunks=_CHUNKS)

    repo = WikiPageRepository(wiki_db)
    page = await repo.get_by_slug(1, "entity/jia-gong-si")
    # 只有 c000（真实 100_0）被还原；c777 丢弃后只剩一个 chunk 引用
    assert page.chunk_refs == ["100_100_0"]
    # 乙产品/RAG 无引用 → 不写页（强制接地）
    assert outcome.pages_created == 1
    assert outcome.skipped_no_citation == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_pages_published_after_batch(wiki_db):
    """批尾发布：reduce 落库 draft → publish 后全部 published"""
    llm = MockLLM([_cand_json(), _CITE_JSON, _page_md("甲公司"), _page_md("乙产品"), _page_md("检索增强生成")])
    svc = _make_service(wiki_db, llm)
    await svc.ingest_document(full_text="正文", chunks=_CHUNKS)

    repo = WikiPageRepository(wiki_db)
    for slug in ("entity/jia-gong-si", "entity/yi-chan-pin", "concept/rag"):
        page = await repo.get_by_slug(1, slug)
        assert page is not None
        assert page.status == "published", f"{slug} 应在批尾翻转为 published"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_unchanged_published_page_status_not_downgraded(wiki_db):
    """已存在 published 页内容无变化：draft 入参不应触发快照/版本递增/状态回退"""
    repo = WikiPageRepository(wiki_db)
    stable_md = "SUMMARY: 甲公司的测试页面\n\n# 甲公司\n\n详见 [[concept/rag|检索增强生成]]。"
    await repo.create_page({"space_id": 1, "kb_id": 1, "slug": "entity/jia-gong-si", "title": "甲公司",
                            "page_type": "entity", "content": stable_md.split("\n\n", 1)[1],
                            "summary": "甲公司的测试页面", "status": "published"})
    await repo.create_page({"space_id": 1, "kb_id": 1, "slug": "concept/rag", "title": "检索增强生成",
                            "page_type": "concept", "content": "x"})

    llm = MockLLM([_cand_json(), _CITE_JSON, stable_md, _page_md("乙产品"), _page_md("检索增强生成")])
    svc = _make_service(wiki_db, llm)
    await svc.ingest_document(full_text="正文", chunks=_CHUNKS)

    page = await repo.get_by_slug(1, "entity/jia-gong-si")
    # 内容无变化 → 不递增不快照；状态不被 draft 化
    assert page.version == 1
    assert page.status == "published"
    assert await repo.list_revisions(page.id) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_publish_draft_pages_meta_write_only(wiki_db):
    """publish_draft_pages：只翻转 draft→published，不动 published/其他页，不递增 version"""
    repo = WikiPageRepository(wiki_db)
    d1 = await repo.create_page({"space_id": 1, "kb_id": 1, "slug": "entity/d1", "title": "D1",
                                 "page_type": "entity", "content": "x", "status": "draft"})
    p1 = await repo.create_page({"space_id": 1, "kb_id": 1, "slug": "entity/p1", "title": "P1",
                                 "page_type": "entity", "content": "x", "status": "published"})

    flipped = await repo.publish_draft_pages(1, ["entity/d1", "entity/p1", "entity/ghost"])
    assert flipped == 1

    await wiki_db.refresh(d1)
    await wiki_db.refresh(p1)
    assert d1.status == "published"
    assert p1.status == "published"   # 已发布页不受影响
    assert d1.version == 1            # 簿记写不递增 version
