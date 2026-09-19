"""
Wiki 生成管道服务

移植自 WeKnora 的 wiki ingest（Map-Reduce 四阶段）：
  Pass 0   候选 slug 抽取（全文一遍，只出骨架 JSON）
  Pass 1   分块引文标注（chunk 先标注、写作只用已标注 chunk，杜绝幻觉）
  Reduce   按 slug 并发写页（增量合并 + 版本快照）
  Finalize 链接重建 / 死链清理 / 快照裁剪（纯代码，不调 LLM）

依赖经构造注入：feature 层允许持有 ORM 会话与具体客户端；
不 import setting，不反向依赖其它 feature。
"""
import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.models.wiki import (
    WikiEditSource,
    WikiIngestStatus,
    WikiPageStatus,
    WikiPageType,
)
from novamind.features.knowledge_space.repository.wiki_repository import (
    WikiIngestRecordRepository,
    WikiPageRepository,
)
from novamind.features.knowledge_space.services.wiki_handles import HandleTable
from novamind.shared.prompts.prompt_manager import PromptManager
from novamind.shared.utils.llm_response import extract_json_obj

logger = get_logger(__name__)

# 送入 Pass 0 的全文上限（字符）——超长文档截断，候选抽取不需要全文细节
MAX_CONTENT_CHARS_FOR_EXTRACT = 32000
# 单个引文批次的字符预算（近似 token 控制）
MAX_RUNES_PER_CITATION_BATCH = 12000
# 批内 LLM 并发上限（Reduce 与引文批次共用）
LLM_CONCURRENCY = 4
# 候选抽取 / 引文标注 JSON 解析失败时的重试次数
MAX_PARSE_RETRY = 2

_GRANULARITY_GUIDANCE = {
    "focused": (
        "FOCUSED: Extract only the document's main subjects (typically 3-7 items). "
        "Skip incidental technology names, generic concepts, and passing mentions."
    ),
    "standard": (
        "STANDARD: Extract main subjects plus entities/concepts that are substantively "
        "discussed (a dedicated paragraph or multiple bullet points). Skip one-off mentions "
        "and commodity terms."
    ),
    "exhaustive": (
        "EXHAUSTIVE: Extract every named entity and recognizable concept, including stacks/"
        "libs mentioned in passing. Use when the KB is a glossary rather than a curated wiki."
    ),
}

# slug 允许字符：字母数字下划线、CJK、连字符、类型分隔符 /
_SLUG_RE = re.compile(r"[^\w一-鿿/-]+")


@dataclass
class ExtractedItem:
    """Pass 0 产出的候选骨架"""

    type: str          # entity | concept
    name: str
    slug: str
    aliases: List[str] = field(default_factory=list)
    description: str = ""
    details: str = ""
    cited_chunk_ids: List[str] = field(default_factory=list)


@dataclass
class IngestOutcome:
    """一次 ingest 的产出统计"""

    pages_created: int = 0
    pages_updated: int = 0
    candidates: int = 0
    cited_slugs: int = 0
    skipped_no_citation: int = 0
    truncated: bool = False


def normalize_slug(slug: str) -> str:
    """清洗模型产出的 slug：小写、剔除空白与危险字符、保留 CJK 与连字符。

    中文 slug 保守方案：保留原字符（不引 pypinyin），仅清洗空白与非法符号。
    """
    slug = (slug or "").strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    slug = _SLUG_RE.sub("", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = re.sub(r"-+/", "/", slug)   # 分隔符前不允许连字符
    slug = re.sub(r"/-+", "/", slug)   # 分隔符后不允许连字符
    return slug.strip("-/")


class WikiGenerationError(Exception):
    """wiki 生成失败（LLM 不可用等致命错误）"""


class WikiIngestService:
    """Wiki 四阶段生成管道"""

    def __init__(
        self,
        session: AsyncSession,
        *,
        llm_client: Any,
        minio_client: Any,
        es_client: Any,
        wiki_config: Dict[str, Any],
        kb_id: int,
        space_id: int,
        document_id: int,
    ):
        self.session = session
        self.llm = llm_client
        self.minio = minio_client
        self.es = es_client
        self.config = wiki_config or {}
        self.kb_id = kb_id
        self.space_id = space_id
        self.document_id = document_id
        self.page_repo = WikiPageRepository(session)
        self.record_repo = WikiIngestRecordRepository(session)
        self.language = "中文"  # 界面语言；wiki 页面用中文书写
        self._semaphore = asyncio.Semaphore(LLM_CONCURRENCY)

    # ========== 公共入口 ==========

    async def ingest_document(
        self,
        *,
        full_text: str,
        chunks: List[Dict[str, Any]],
    ) -> IngestOutcome:
        """执行四阶段管道。full_text 与 chunks 由任务层准备好后传入。"""
        outcome = IngestOutcome()

        if not full_text or not full_text.strip():
            logger.info("wiki 生成：解析全文为空，跳过", document_id=self.document_id, kb_id=self.kb_id)
            return outcome

        granularity = self.config.get("granularity") or "standard"
        max_pages = int(self.config.get("max_pages_per_ingest") or 50)
        custom_content = (self.config.get("content_instructions") or "").strip()
        custom_extract = (self.config.get("extraction_instructions") or "").strip()

        # 旧 slug 清单（slug 连续性）
        old_slugs = await self.page_repo.list_slugs_by_kb(self.kb_id)

        # ---- Pass 0: 候选抽取 ----
        self._record.start_step("extract")
        candidates = await self._extract_candidates(
            full_text[:MAX_CONTENT_CHARS_FOR_EXTRACT], old_slugs, granularity,
            custom_extract, outcome,
        )
        self._record.finish_step("extract", {"candidates": len(candidates)})
        await self._commit()

        if not candidates:
            # 无候选也执行 finalize：清理历史遗留死链与快照，保持 KB 一致性
            self._record.start_step("finalize")
            await self._finalize()
            self._record.finish_step("finalize")
            await self._commit()
            return outcome

        # ---- Pass 1: 分块引文标注 ----
        self._record.start_step("cite")
        citations, new_candidates = await self._annotate_citations(candidates, chunks)
        for c in new_candidates:
            if c.slug not in {x.slug for x in candidates}:
                candidates.append(c)
        self._record.finish_step("cite", {"cited_slugs": len(citations)})
        await self._commit()

        cited = [c for c in candidates if c.cited_chunk_ids]
        outcome.candidates = len(candidates)
        outcome.cited_slugs = len(cited)
        outcome.skipped_no_citation = len(candidates) - len(cited)

        # 无引用的候选不写页（强制接地：没有证据就没有页面）
        if max_pages and len(cited) > max_pages:
            cited = cited[:max_pages]
            outcome.truncated = True

        # ---- Reduce: 先并发生成页面内容，再串行落库 ----
        # AsyncSession 非并发安全：begin_nested/flush 不能跨 gather 并发，
        # 因此 DB 读写（预取已有页 + upsert）全部串行，只有 LLM 调用并发。
        self._record.start_step("reduce")
        valid_slugs = {c.slug for c in cited}
        # 有效链接清单：本次引用的 slug + KB 内已有页面（供 [[slug|title]] 交叉引用）
        existing_slugs = set(old_slugs)
        valid_link_slugs = sorted(s for s in (valid_slugs | existing_slugs) if s)

        # slug 句柄表（对齐 WeKnora wiki_slug_handles.go）：模型不复述高熵 slug，
        # 只抄 ref-N 短句柄，生成后 decode 还原——防 UUID slug 被改错一个字符
        slug_handles = HandleTable(prefix="ref-", start=1, width=1)
        link_handle_lines = [
            f"- {slug_handles.register(s)} = {s}" for s in valid_link_slugs if s
        ]

        chunk_id_map = {str(c.get("chunk_id")): c for c in chunks}
        existing_map = await self.page_repo.list_by_slugs(
            self.kb_id, [c.slug for c in cited]
        )

        # 并发控制收敛到 _call_llm_text/_call_llm_json 内部单层获取信号量；
        # 这里不得再在外层嵌套获取同一 Semaphore（嵌套获取会死锁：外层持锁者
        # 等内层许可，许可被只持一半的协程占死，端到端实测已复现）。
        generated = await asyncio.gather(*[
            self._generate_page_content(
                c, chunk_id_map, valid_link_slugs, link_handle_lines, slug_handles,
                custom_content, existing_map.get(c.slug),
            )
            for c in cited
        ])

        # 本批写入的 slug（draft→publish 范围）
        batch_slugs: List[str] = []
        for item, gen in zip(cited, generated):
            if gen is None:
                continue  # 生成失败或无素材，跳过（强制接地）
            summary, content, out_links = gen
            try:
                async with self.session.begin_nested():
                    _, created = await self.page_repo.upsert_with_snapshot(
                        self.kb_id,
                        item.slug,
                        space_id=self.space_id,
                        title=item.name,
                        content=content,
                        summary=summary,
                        page_type=item.type,
                        status=WikiPageStatus.DRAFT,
                        aliases=item.aliases or None,
                        source_refs=[f"{self.document_id}|"],
                        chunk_refs=[f"{self.document_id}_{cid}" for cid in item.cited_chunk_ids],
                        edit_source=WikiEditSource.PIPELINE,
                        link_slugs=out_links,
                    )
                batch_slugs.append(item.slug)
                if created:
                    outcome.pages_created += 1
                else:
                    outcome.pages_updated += 1
            except Exception as e:
                logger.warning(
                    "wiki 页面写入失败",
                    kb_id=self.kb_id, slug=item.slug, error=str(e),
                )
        self._record.finish_step("reduce", {
            "pages_created": outcome.pages_created, "pages_updated": outcome.pages_updated,
        })
        await self._commit()

        # 批尾发布（对齐 WeKnora publishDraftPages）：draft→published 簿记写，
        # 不递增 version；用户不见半成品页
        if batch_slugs:
            await self.page_repo.publish_draft_pages(self.kb_id, batch_slugs)

        # ---- Finalize: 链接重建 / 死链清理 / 快照裁剪（纯代码） ----
        self._record.start_step("finalize")
        await self._finalize()
        self._record.finish_step("finalize")
        await self._commit()

        return outcome

    # ========== 阶段实现 ==========

    async def _extract_candidates(
        self,
        content: str,
        old_slugs: List[str],
        granularity: str,
        custom_instructions: str,
        outcome: IngestOutcome,
    ) -> List[ExtractedItem]:
        prev_text = "\n".join(f"- {s}" for s in old_slugs) if old_slugs else "(none — this is a new document)"
        prompt = PromptManager.format_prompt(
            "wiki_candidate_slug_user",
            content=content,
            previous_slugs=prev_text,
            language=self.language,
            granularity=granularity,
            granularity_guidance=_GRANULARITY_GUIDANCE.get(granularity, _GRANULARITY_GUIDANCE["standard"]),
        )
        if custom_instructions:
            prompt += f"\n\n<custom_instructions>\n{custom_instructions}\n</custom_instructions>"

        raw = await self._call_llm_json(prompt)
        if not raw:
            return []

        items: List[ExtractedItem] = []
        for arr, item_type in ((raw.get("entities") or [], "entity"), (raw.get("concepts") or [], "concept")):
            for entry in arr:
                if not isinstance(entry, dict):
                    continue
                slug = normalize_slug(str(entry.get("slug") or ""))
                name = str(entry.get("name") or "").strip()
                if not slug or not name:
                    continue
                # 补全类型前缀（模型偶尔漏掉）
                if "/" not in slug:
                    slug = f"{item_type}/{slug}"
                items.append(ExtractedItem(
                    type=item_type,
                    name=name,
                    slug=slug,
                    aliases=[str(a) for a in (entry.get("aliases") or []) if str(a).strip()],
                    description=str(entry.get("description") or "").strip(),
                    details=str(entry.get("details") or "").strip(),
                ))
        # 同批去重（同 slug 保留首个）
        seen: set = set()
        deduped = []
        for it in items:
            if it.slug in seen:
                continue
            seen.add(it.slug)
            deduped.append(it)
        return deduped

    async def _annotate_citations(
        self,
        candidates: List[ExtractedItem],
        chunks: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, List[str]], List[ExtractedItem]]:
        """分批标注引文，返回 ({slug: [chunk_id]}, 新发现的候选)

        chunk 句柄（对齐 WeKnora splitChunksIntoCitationBatches）：每批给 chunk
        分配 c000/c001 短句柄，prompt 中只出现句柄；模型返回句柄，批内还原为
        真实 chunk_id，未知句柄丢弃——防模型复述长 UUID 时打错字符。
        """
        usable = [
            c for c in chunks
            if str(c.get("content") or "").strip()
        ]
        batches = self._build_citation_batches(usable)
        candidate_slugs_text = "\n".join(
            f"- {c.slug} = {c.name}" for c in candidates
        )

        citations: Dict[str, List[str]] = {}
        new_candidates: List[ExtractedItem] = []
        lock = asyncio.Lock()

        async def run_batch(batch: List[Tuple[HandleTable, Dict[str, Any]]]) -> None:
            handles, chunk_list = batch
            chunks_xml = "\n".join(
                f'<c id="{handles.register(str(c.get("chunk_id")))}">{str(c.get("content"))[:2000]}</c>'
                for c in chunk_list
            )
            prompt = PromptManager.format_prompt(
                "wiki_chunk_citation_user",
                language=self.language,
                candidate_slugs=candidate_slugs_text,
                chunks_xml=chunks_xml,
            )
            raw = await self._call_llm_json(prompt)
            if not raw:
                return
            batch_citations = raw.get("citations") or {}
            batch_new = raw.get("new_slugs") or []
            async with lock:
                for slug, chunk_handles in batch_citations.items():
                    clean_slug = normalize_slug(str(slug))
                    if not clean_slug or not chunk_handles:
                        continue
                    holdings = citations.setdefault(clean_slug, [])
                    for h in chunk_handles:
                        # 句柄还原；未知句柄丢弃（模型幻觉的 id）
                        real_id = handles.resolve(str(h))
                        if real_id is None or real_id in holdings:
                            continue
                        holdings.append(real_id)
                for entry in batch_new:
                    if not isinstance(entry, dict):
                        continue
                    slug = normalize_slug(str(entry.get("slug") or ""))
                    name = str(entry.get("name") or "").strip()
                    if not slug or not name:
                        continue
                    if "/" not in slug:
                        slug = f"{entry.get('type', 'concept')}/{slug}"
                    # 新候选自带的 source_chunks 同样过句柄还原
                    cited_ids: List[str] = []
                    for h in entry.get("source_chunks") or []:
                        real_id = handles.resolve(str(h))
                        if real_id is not None and real_id not in cited_ids:
                            cited_ids.append(real_id)
                    new_candidates.append(ExtractedItem(
                        type=str(entry.get("type") or "concept"),
                        name=name,
                        slug=slug,
                        aliases=[str(a) for a in (entry.get("aliases") or []) if str(a).strip()],
                        description=str(entry.get("description") or "").strip(),
                        details=str(entry.get("details") or "").strip(),
                        cited_chunk_ids=cited_ids,
                    ))

        # 每批独立句柄表（编号从 0 起，批间不串）
        prepared = [(HandleTable(prefix="c", start=0, width=3), b) for b in batches]
        if prepared:
            await asyncio.gather(*[run_batch(pb) for pb in prepared])

        # 回填引文到候选
        for c in candidates:
            c.cited_chunk_ids = citations.get(c.slug, [])

        return citations, new_candidates

    @staticmethod
    def _build_citation_batches(chunks: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        batches: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        current_chars = 0
        for chunk in chunks:
            clen = len(str(chunk.get("content") or ""))
            if current and current_chars + clen > MAX_RUNES_PER_CITATION_BATCH:
                batches.append(current)
                current = []
                current_chars = 0
            current.append(chunk)
            current_chars += clen
        if current:
            batches.append(current)
        return batches

    async def _generate_page_content(
        self,
        item: ExtractedItem,
        chunk_id_map: Dict[str, Dict[str, Any]],
        valid_link_slugs: List[str],
        link_handle_lines: List[str],
        slug_handles: HandleTable,
        custom_content: str,
        existing: Optional[Any],
    ) -> Optional[Tuple[str, str, List[str]]]:
        """单个 slug 的页面内容生成（只调 LLM，不碰 DB）。

        返回 (summary, content, out_links)；失败或无素材返回 None。
        DB 写入由调用方在 gather 之后串行执行。
        注意：本函数不得再获取 self._semaphore——并发控制由 _call_llm_text
        统一负责（外层+内层嵌套获取同一 Semaphore 会死锁）。
        """
        # 取引用 chunk 的 verbatim 文本（无映射的引用 id 剔除）
        cited_texts: List[str] = []
        for cid in item.cited_chunk_ids:
            chunk = chunk_id_map.get(cid)
            if chunk and str(chunk.get("content") or "").strip():
                cited_texts.append(f"<chunk id=\"{cid}\">\n{str(chunk.get('content'))[:3000]}\n</chunk>")
        if not cited_texts and not existing:
            # 既无引用文本又无已有内容 → 没有写作素材，跳过（强制接地）
            return None

        shared_ctx = f"<document_sources>\n  <doc id=\"{self.document_id}\">本次处理文档</doc>\n</document_sources>\n"
        prompt = PromptManager.format_prompt(
            "wiki_page_modify_user",
            shared_source_contexts=shared_ctx,
            page_slug=item.slug,
            page_title=item.name,
            page_type=item.type,
            existing_content=(existing.content if existing else ""),
            new_content="\n\n".join(cited_texts) if cited_texts else "（本次无新增引用，仅基于现有内容整理）",
            valid_links="\n".join(link_handle_lines) if link_handle_lines else "（无可用链接）",
            custom_instructions=custom_content or "（无自定义要求）",
            language=self.language,
        )

        raw = await self._call_llm_text(PromptManager.get_template("wiki_page_modify_system"), prompt)
        if not raw:
            return None

        summary, content = self._split_summary_line(raw)
        if not content.strip():
            return None

        # slug 句柄还原（对齐 WeKnora decodeContent）：[[ref-N|显示名]] → [[real|显示名]]。
        # 无映射句柄原样保留，由下方白名单校验当作死链剔除。
        content = slug_handles.decode_text(content, r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")

        # 只保留指向有效 slug 且非自指的 [[slug|title]] 链接
        out_links = self._extract_wiki_links(content, item.slug, set(valid_link_slugs))
        return summary, content, out_links

    async def _finalize(self) -> None:
        """链接双向对齐 + 死链清理 + 快照裁剪（纯代码，无 LLM）"""
        pages = await self.page_repo.all_live_pages(self.kb_id)
        live_slugs = {p.slug for p in pages}

        for page in pages:
            # 清死链（指向不存在/已删 slug 的 out_links 剔除）+ 去自指
            out_links = [s for s in (page.out_links or []) if s in live_slugs and s != page.slug]
            if out_links != (page.out_links or []):
                page.out_links = out_links

        # 双向对齐 in_links
        slug_map = {p.slug: p for p in pages}
        in_map: Dict[str, List[str]] = {p.slug: [] for p in pages}
        for page in pages:
            for target in page.out_links or []:
                if target in slug_map and target != page.slug:
                    in_map[target].append(page.slug)
        for slug, page in slug_map.items():
            aligned = sorted(set(in_map.get(slug, [])))
            if aligned != (page.in_links or []):
                page.in_links = aligned

        # 快照裁剪（两级保留）
        for page in pages:
            try:
                await self.page_repo.prune_revisions(page.id)
            except Exception as e:
                logger.warning("wiki 快照裁剪失败", page_id=page.id, error=str(e))

    # ========== LLM 与工具方法 ==========

    async def _call_llm_json(self, prompt: str) -> Optional[dict]:
        """JSON mode 调用 + 解析重试"""
        for attempt in range(MAX_PARSE_RETRY + 1):
            try:
                async with self._semaphore:
                    response = await self.llm.generate_text(
                        prompt=prompt,
                        max_tokens=4096,
                        temperature=0.2,
                        response_format={"type": "json_object"},
                    )
            except Exception as e:
                raise WikiGenerationError(f"LLM 调用失败: {e}") from e
            parsed = extract_json_obj(response)
            if parsed is not None:
                return parsed
            if attempt < MAX_PARSE_RETRY:
                logger.warning(
                    "wiki JSON 解析失败，重试",
                    attempt=attempt + 1, document_id=self.document_id,
                    response_preview=str(response)[:100],
                )
        return None

    async def _call_llm_text(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """页面正文生成（非 JSON）"""
        try:
            async with self._semaphore:
                response = await self.llm.generate_text(
                    prompt=f"{system_prompt}\n\n---\n\n{user_prompt}",
                    max_tokens=4096,
                    temperature=0.3,
                )
            return response
        except Exception as e:
            logger.warning("wiki 页面生成 LLM 调用失败", document_id=self.document_id, error=str(e))
            return None

    @staticmethod
    def _split_summary_line(raw: str) -> Tuple[str, str]:
        """拆分「SUMMARY: ...」首行与正文"""
        text = (raw or "").strip()
        m = re.match(r"^SUMMARY:\s*(.+?)\n", text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip(), text[m.end():].strip()
        # 没有 SUMMARY 行：取第一段当摘要
        first_para = text.split("\n\n", 1)[0][:200]
        return first_para, text

    @staticmethod
    def _extract_wiki_links(content: str, self_slug: str, valid_slugs: set) -> List[str]:
        """从正文中提取 [[slug|title]] 形式的有效链接（去重、去自指、剔无效）"""
        links = []
        for m in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", content):
            slug = normalize_slug(m.group(1))
            if slug and slug != self_slug and slug in valid_slugs and slug not in links:
                links.append(slug)
        return links

    @property
    def _record(self) -> Any:
        """当前履历对象（任务层 bind_record 注入；未绑定返回 no-op 桩）"""
        record = getattr(self, "_ingest_record", None)
        if record is None:
            return self._record_guard()
        return record

    def bind_record(self, record: Any) -> None:
        self._ingest_record = record

    @staticmethod
    def _record_guard() -> Any:
        class _Noop:
            def start_step(self, *a, **k): pass
            def finish_step(self, *a, **k): pass
            def fail_step(self, *a, **k): pass
        return _Noop()

    async def _commit(self) -> None:
        """阶段边界提交（进度立即可见）"""
        try:
            await self.session.commit()
        except Exception as e:
            logger.warning("wiki ingest 阶段提交失败", document_id=self.document_id, error=str(e))
