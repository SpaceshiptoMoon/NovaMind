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
from typing import Any, Dict, List, Optional, Set, Tuple

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
from novamind.features.knowledge_space.services.wiki_retract_service import tombstone_exists
from novamind.features.knowledge_space.services.wiki_dedup import (
    DEDUP_CANDIDATE_SCORE_FLOOR,
    DEDUP_CORPUS_HARD_LIMIT,
    DedupCandidate,
    dedup_pair_score,
    exact_identity_target,
    grams_per_surface,
    merge_reject_reason,
    select_dedup_candidate_pages,
    slug_base_tokens,
    stabilize_extracted_items,
)
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
    merged_into_existing: int = 0
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

        # 删除竞态守卫（检查点 1，对齐 WeKnora isKnowledgeGone）：
        # 文档在排队/执行窗口被删 → 直接放弃，不留幽灵 source_ref
        if await tombstone_exists(self.kb_id, self.document_id):
            logger.info(
                "wiki 生成：文档已删除（tombstone 命中），放弃",
                document_id=self.document_id, kb_id=self.kb_id,
            )
            return outcome

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
        # dedup：新候选 vs 已有页面的归并（对齐 WeKnora deduplicateExtractedBatch）
        candidates = await self._deduplicate_candidates(candidates, outcome)
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
        fresh: List[ExtractedItem] = []
        for c in new_candidates:
            if c.slug not in {x.slug for x in candidates}:
                fresh.append(c)
        # 引文新 slug 跳过了 extract 期 dedup（对齐 WeKnora reclaimExtractedIdentities）：
        # 补一轮 exact-title 归并，防引文阶段二次建同题页
        if fresh:
            fresh = await self._reclaim_exact_identities(candidates, fresh)
            for c in fresh:
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

        # 批级 taxonomy 规划（对齐 WeKnora planBatchTaxonomy）：一次 LLM 调用为
        # 整批 entity/concept 分配 ≤2 级 category_path。串行调用，在 gather 之前。
        category_plans = await self._plan_taxonomy(cited)

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
        # 删除竞态守卫（检查点 2）：落库前文档又被删了 → 本批全部放弃。
        # 重跑无害（幂等），继续写会留下幽灵 source_ref。
        if await tombstone_exists(self.kb_id, self.document_id):
            logger.warning(
                "wiki 生成：落库前文档被删除（tombstone 命中），本批放弃",
                document_id=self.document_id, kb_id=self.kb_id,
            )
            self._record.finish_step("reduce", {"aborted": "tombstone"})
            await self._commit()
            return outcome
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
                        # taxonomy 只规划 entity/concept；只填空目录
                        # （upsert 对非 None 才覆盖；规划缺失传 None 保用户已填）
                        category_path=category_plans.get(item.slug),
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

        # ---- Finalize 前的补链与延伸页 ----
        self._record.start_step("finalize")

        # linkify 自动互链（对齐 WeKnora injectCrossLinks）：正文提及其他页
        # 标题/别名 → 注入 [[slug|title]]。纯文本替换，走不 bump version 的
        # 机器写通道
        await self._inject_cross_links(cited, batch_slugs)

        # summary 摘要页（对齐 WeKnora WikiSummaryPrompt 路径）：每文档一页，
        # slug 固定 summary/{document_id}——是 retract 的主要删除对象与
        # index intro 的语料
        await self._generate_summary_page(full_text, slug_handles)

        # index 页 intro 维护（对齐 WeKnora rebuildIndexPage）：首建/增量更新
        await self._update_index_intro(outcome)

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

    async def _deduplicate_candidates(
        self,
        candidates: List[ExtractedItem],
        outcome: IngestOutcome,
    ) -> List[ExtractedItem]:
        """dedup 管线（对齐 WeKnora deduplicateExtractedBatch）。

        三层：相似度预筛（纯 Python，MySQL 无 trigram）→ exact-title 确定性
        归并（免 LLM）→ LLM 语义判断（逐 item 候选分组 + 双守卫）。重定向后
        批内同 slug 折叠合并。所有 LLM 调用串行（在 gather 之外）。
        """
        if not candidates:
            return candidates

        existing_lite = await self.page_repo.list_entity_concept_lite(self.kb_id)

        # 语料硬顶：跳过 LLM dedup 只做批内 identity 收敛（保守不误并）
        if len(existing_lite) > DEDUP_CORPUS_HARD_LIMIT:
            logger.warning(
                "wiki dedup：已有页语料超硬顶，退化为仅 exact-title 归并",
                kb_id=self.kb_id, existing=len(existing_lite),
            )
            existing_lite = []

        candidate_pages = [DedupCandidate(
            slug=p["slug"], title=p["title"], aliases=p["aliases"], page_type=p["page_type"],
        ) for p in existing_lite]
        item_dicts = [self._item_dict(c) for c in candidates]

        # 1) 相似度预筛（top-K + floor + small-corpus bypass 模块内实现）
        selected_pages = select_dedup_candidate_pages(item_dicts, candidate_pages)
        pages_by_slug = {p.slug: p for p in selected_pages}

        # 2) per-item 候选集（LLM dedup 双守卫的数据基础）
        item_candidates: Dict[str, Set[str]] = {}
        for it in item_dicts:
            own: Set[str] = set()
            for p in selected_pages:
                surfaces = [it.get("name") or "", *(it.get("aliases") or [])]
                for q in surfaces:
                    if not q:
                        continue
                    # 判定 q 是否与该页面命中（复用同一相似度信号）
                    score = dedup_pair_score(
                        grams_per_surface([q]), slug_base_tokens(it.get("slug") or ""),
                        grams_per_surface([p.title, *p.aliases]), slug_base_tokens(p.slug),
                    )
                    if score >= DEDUP_CANDIDATE_SCORE_FLOOR or score > 0:
                        own.add(p.slug)
                        break
            item_candidates[it["slug"]] = own

        # 3) exact-title 确定性归并（免 LLM）
        exact_targets: Dict[str, str] = {}
        merge_targets: Dict[str, str] = {}
        for it in item_dicts:
            target = exact_identity_target(
                it.get("name") or "", it.get("type") or "",
                item_candidates.get(it["slug"]) or set(), pages_by_slug,
                own_slug=it["slug"],
            )
            if target:
                exact_targets[it["slug"]] = target
        if exact_targets:
            outcome.merged_into_existing = len(exact_targets)

        # 4) LLM 语义 dedup（有候选且非全部 exact 命中才调）
        llm_groups = self._render_dedup_groups(
            candidates, item_candidates, pages_by_slug, exact_targets,
        )
        if llm_groups:
            prompt = PromptManager.format_prompt("wiki_dedup_user", candidates=llm_groups)
            raw = await self._call_llm_json(prompt)
            merges = (raw or {}).get("merges") or {}
            for src, dst in merges.items():
                src, dst = str(src).strip(), str(dst).strip()
                if src in exact_targets:
                    continue
                reason = merge_reject_reason(src, dst, item_candidates.get(src) or set())
                if reason:
                    logger.warning("wiki dedup 拒绝合并", src=src, dst=dst, reason=reason)
                    continue
                merge_targets[src] = dst
            if merge_targets:
                outcome.merged_into_existing = outcome.merged_into_existing + len(
                    [s for s in merge_targets if s not in exact_targets]
                )

        # 5) 应用重定向 + 批内 identity 收敛 + 同 slug 折叠
        stabilized = stabilize_extracted_items(item_dicts, merge_targets, exact_targets)
        return [self._dict_item(d) for d in stabilized]

    async def _reclaim_exact_identities(
        self,
        existing_candidates: List[ExtractedItem],
        fresh: List[ExtractedItem],
    ) -> List[ExtractedItem]:
        """引文新 slug 的 exact-title 归并回收（对齐 WeKnora reclaimExtractedIdentities）。

        引文 new_slugs 跳过 extract 期 dedup，不回收会二次建同题页。轻量路径：
        只在已有页 title 精确（归一化）匹配新条目时重定向。
        """
        if not fresh:
            return fresh
        existing_lite = await self.page_repo.list_entity_concept_lite(self.kb_id)
        pages_by_slug = {
            p["slug"]: DedupCandidate(p["slug"], p["title"], p["aliases"], p["page_type"])
            for p in existing_lite
        }
        items = [self._item_dict(c) for c in fresh]
        exact_targets: Dict[str, str] = {}
        for it in items:
            # 候选集=全部已有页（exact match 自带严格约束，无需预筛）
            target = exact_identity_target(
                it.get("name") or "", it.get("type") or "",
                set(pages_by_slug.keys()), pages_by_slug,
                own_slug=it["slug"],
            )
            if target:
                exact_targets[it["slug"]] = target
        stabilized = stabilize_extracted_items(items, {}, exact_targets)
        return [self._dict_item(d) for d in stabilized]

    async def _plan_taxonomy(self, cited: List[ExtractedItem]) -> Dict[str, List[str]]:
        """批级目录规划（对齐 WeKnora planBatchTaxonomy）。失败不阻断页面生成。"""
        from novamind.features.knowledge_space.services.wiki_taxonomy import (
            TAXONOMY_FOLDER_POOL_MAX,
            plan_batch_taxonomy,
        )

        items = [
            {"slug": c.slug, "title": c.name, "page_type": c.type, "about": c.description}
            for c in cited if c.type in ("entity", "concept")
        ]
        if not items:
            return {}
        try:
            paths = await self.page_repo.list_distinct_category_paths(self.kb_id)
            return await plan_batch_taxonomy(
                items, paths[:TAXONOMY_FOLDER_POOL_MAX], self.language, self._call_llm_json,
            )
        except Exception as e:
            logger.warning("wiki taxonomy 规划失败，本批无目录", kb_id=self.kb_id, error=str(e))
            return {}

    @staticmethod
    def _item_dict(c: ExtractedItem) -> Dict[str, Any]:
        return {
            "type": c.type, "name": c.name, "slug": c.slug,
            "aliases": list(c.aliases), "description": c.description,
            "details": c.details, "cited_chunk_ids": list(c.cited_chunk_ids),
        }

    @staticmethod
    def _dict_item(d: Dict[str, Any]) -> ExtractedItem:
        return ExtractedItem(
            type=d.get("type") or "concept", name=d.get("name") or "",
            slug=d.get("slug") or "", aliases=d.get("aliases") or [],
            description=d.get("description") or "", details=d.get("details") or "",
            cited_chunk_ids=d.get("cited_chunk_ids") or [],
        )

    @staticmethod
    def _render_dedup_groups(
        candidates: List[ExtractedItem],
        item_candidates: Dict[str, Set[str]],
        pages_by_slug: Dict[str, DedupCandidate],
        exact_targets: Dict[str, str],
    ) -> str:
        """渲染逐 item 候选分组（对齐 WeKnora writeDedupCandidateGroup）。

        exact 命中或无候选的 item 不进 prompt（无合并可能只添幻觉面）。
        """
        blocks: List[str] = []
        for c in candidates:
            if c.slug in exact_targets:
                continue
            slugs = sorted(s for s in (item_candidates.get(c.slug) or set()) if s != c.slug and s in pages_by_slug)
            if not slugs:
                continue

            def esc(s: str) -> str:
                return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            lines = [f'  <item slug="{esc(c.slug)}" type="{esc(c.type)}">', f"    <name>{esc(c.name)}</name>"]
            for alias in c.aliases:
                if alias:
                    lines.append(f"    <alias>{esc(alias)}</alias>")
            lines.append("    <candidates>")
            for slug in slugs:
                p = pages_by_slug[slug]
                lines.append(f'      <page slug="{esc(p.slug)}" type="{esc(p.page_type)}">')
                lines.append(f"        <name>{esc(p.title)}</name>")
                for alias in p.aliases:
                    if alias:
                        lines.append(f"        <alias>{esc(alias)}</alias>")
                lines.append("      </page>")
            lines.append("    </candidates>")
            lines.append("  </item>")
            blocks.append("\n".join(lines))
        return "\n".join(blocks)

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

    async def _inject_cross_links(
        self,
        cited: List[ExtractedItem],
        batch_slugs: List[str],
    ) -> None:
        """linkify 自动互链（对齐 WeKnora injectCrossLinks）。

        候选 refs = 本批新写页面的 (title+aliases) + 受影响页自身已有
        out_links 解析出的 title。只改本批受影响页的正文（不碰用户手写页），
        走 update_auto_linked_content 机器写（不快照不递增 version）。
        """
        from novamind.features.knowledge_space.services.wiki_linkify import linkify_content

        if not batch_slugs:
            return
        try:
            affected = await self.page_repo.list_by_slugs(self.kb_id, batch_slugs)
            if not affected:
                return

            # refs 池：本批页面的 title+aliases（批内互链）
            fresh_refs: List[Tuple[str, str]] = []
            for p in affected.values():
                if p.title:
                    fresh_refs.append((p.slug, p.title))
                for alias in p.aliases or []:
                    if alias:
                        fresh_refs.append((p.slug, alias))

            for page in affected.values():
                if page.page_type == "index":
                    continue
                # refs = 批内池 + 该页已有 out_links 对应页的 title
                refs = list(fresh_refs)
                if page.out_links:
                    linked = await self.page_repo.list_by_slugs(self.kb_id, list(page.out_links))
                    for p in linked.values():
                        if p.title:
                            refs.append((p.slug, p.title))
                new_content, changed = linkify_content(page.content, refs, page.slug)
                if changed:
                    await self.page_repo.update_auto_linked_content(page, new_content)
        except Exception as e:
            logger.warning("wiki linkify 失败（不阻断）", kb_id=self.kb_id, error=str(e))

    async def _generate_summary_page(self, full_text: str, slug_handles: HandleTable) -> None:
        """每文档摘要页（对齐 WeKnora WikiSummaryPrompt 路径）。

        slug 固定 summary/{document_id}；draft 生命周期与实体/概念页一致
        （本批 publish 已跑，summary 页单独 publish）。文件名不喂给 LLM——
        扫描件常以扫描仪型号命名，喂了只会诱发幻觉。
        """
        summary_slug = f"summary/{self.document_id}"
        existing = await self.page_repo.get_by_slug(self.kb_id, summary_slug)

        # 可用链接清单（句柄化，同 Reduce 机制）
        old_slugs = await self.page_repo.list_slugs_by_kb(self.kb_id)
        handles = HandleTable(prefix="ref-", start=1, width=1)
        available_lines = [f"- [[{handles.register(s)}]] = {s}" for s in old_slugs if s]

        prompt = PromptManager.format_prompt(
            "wiki_summary_page_user",
            content=(full_text or "")[:MAX_CONTENT_CHARS_FOR_EXTRACT],
            available_slugs="\n".join(available_lines) if available_lines else "（暂无其他 wiki 页面）",
            language=self.language,
        )
        raw = await self._call_llm_text(PromptManager.get_template("wiki_page_modify_system"), prompt)
        if not raw:
            return
        summary, content = self._split_summary_line(raw)
        if not content.strip():
            return
        # 句柄还原 + 白名单链接提取
        content = handles.decode_text(content, r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
        out_links = self._extract_wiki_links(content, summary_slug, set(old_slugs))

        try:
            async with self.session.begin_nested():
                _, _ = await self.page_repo.upsert_with_snapshot(
                    self.kb_id, summary_slug,
                    space_id=self.space_id,
                    title=summary or "文档摘要",
                    content=content,
                    summary=summary,
                    page_type=WikiPageType.SUMMARY,
                    status=WikiPageStatus.DRAFT,
                    source_refs=[f"{self.document_id}|"],
                    edit_source=WikiEditSource.PIPELINE,
                    link_slugs=out_links,
                )
            await self.page_repo.publish_draft_pages(self.kb_id, [summary_slug])
        except Exception as e:
            logger.warning("wiki 摘要页写入失败", kb_id=self.kb_id, error=str(e))

    async def _update_index_intro(self, outcome: IngestOutcome) -> None:
        """index 页 intro 维护（对齐 WeKnora rebuildIndexPage 的 intro 部分）。

        首建：用最近 200 条 summary 生成；增量：只喂现有 intro + 本批变更。
        目录列表本体不持久化（GET /index 按需装配）。失败不阻断。
        """
        try:
            index_page = await self.page_repo.get_by_slug(self.kb_id, "index")
            existing_intro = (index_page.content if index_page and not index_page.is_deleted else "")

            if existing_intro.strip():
                # 增量：现有 intro + 本批变更描述
                change_desc = f"本次更新：新增 {outcome.pages_created} 页、更新 {outcome.pages_updated} 页。"
                prompt = PromptManager.format_prompt(
                    "wiki_index_intro_update_user",
                    existing_intro=existing_intro,
                    changes=change_desc,
                    language=self.language,
                )
            else:
                # 首建：最近 200 条页面 summary 作为语料
                pages = await self.page_repo.all_live_pages(self.kb_id)
                pages = [p for p in pages if p.page_type != "index"]
                pages.sort(key=lambda p: p.updated_at or p.created_at, reverse=True)
                summaries = [
                    f"- {p.title}: {p.summary}" for p in pages[:200] if p.summary
                ]
                if not summaries:
                    return
                prompt = PromptManager.format_prompt(
                    "wiki_index_intro_user",
                    summaries="\n".join(summaries),
                    language=self.language,
                )

            raw = await self._call_llm_text(PromptManager.get_template("wiki_page_modify_system"), prompt)
            if not raw:
                return
            _, intro = self._split_summary_line(raw)
            intro = intro.split("\n## ", 1)[0].strip()  # 防目录回流（对齐 WeKnora 截断）
            if not intro.strip():
                return

            if index_page is None:
                await self.page_repo.create_page({
                    "space_id": self.space_id, "kb_id": self.kb_id, "slug": "index",
                    "title": "知识库索引", "content": intro, "summary": "",
                    "page_type": WikiPageType.SUMMARY, "status": WikiPageStatus.PUBLISHED,
                })
            else:
                index_page.content = intro  # intro 更新是簿记，不走版本快照
                await self.session.flush()
        except Exception as e:
            logger.warning("wiki index intro 更新失败", kb_id=self.kb_id, error=str(e))

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
