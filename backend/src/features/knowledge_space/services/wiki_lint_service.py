"""Wiki 质量检查与自动修复——对齐 WeKnora wiki_lint.go

六类问题（WeKnora WikiLintIssueType）：
- orphan_page        孤儿页（无入链；排除 index 页）      warning
- broken_link        出链指向不存在 slug                  error   可自动修
- stale_ref          source_ref 指向已删文档              error   可自动修
- missing_cross_ref  正文提及他页标题但未链               info
- empty_content      正文过短（<50 字符）                 warning 可自动修
- duplicate_slug     重复 slug（MySQL 唯一约束下不可达，保留常量壳）

HealthScore 0-100（WeKnora 扣分规则）：
- orphan 比例 >25% -10、>50% -25（不叠加取大）
- broken_link 每个 ×5
- 无任何链接的 KB -15
- empty_content 每个 ×3

AutoFix（对齐 WeKnora AutoFix）：
- broken_link → [[target]]/[[target| 替换为纯文本（机器写通道）
- empty_content → 归档（index 页除外）
- stale_ref → 剥 source_ref；无剩余来源则整页软删
- 修后重建全 KB 链接
"""
import re
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.repository.wiki_repository import WikiPageRepository

logger = get_logger(__name__)

# ---- 六类常量（对齐 WeKnora WikiLintIssueType）----
LINT_ORPHAN_PAGE = "orphan_page"
LINT_BROKEN_LINK = "broken_link"
LINT_STALE_REF = "stale_ref"
LINT_MISSING_CROSS_REF = "missing_cross_ref"
LINT_EMPTY_CONTENT = "empty_content"
LINT_DUPLICATE_SLUG = "duplicate_slug"

# 问题登记允许的类型（与人工/agent 的 create_issue 白名单并集来源）
LINT_ISSUE_TYPES = {
    LINT_ORPHAN_PAGE, LINT_BROKEN_LINK, LINT_STALE_REF,
    LINT_MISSING_CROSS_REF, LINT_EMPTY_CONTENT, LINT_DUPLICATE_SLUG,
}

# empty_content 正文阈值（字符，WeKnora <50 runes）
EMPTY_CONTENT_THRESHOLD = 50

# HealthScore 扣分参数（对齐 WeKnora）
HEALTH_ORPHAN_RATIO_MILD = 0.25   # >25% -10
HEALTH_ORPHAN_RATIO_SEVERE = 0.50  # >50% -25
HEALTH_ORPHAN_MILD_PENALTY = 10
HEALTH_ORPHAN_SEVERE_PENALTY = 25
HEALTH_BROKEN_PENALTY_EACH = 5
HEALTH_NO_LINKS_PENALTY = 15
HEALTH_EMPTY_PENALTY_EACH = 3

# lint 持久化时 reported_by 标识
LINT_REPORTER = "lint"


class WikiLintIssue:
    """单条 lint 结果"""

    __slots__ = ("issue_type", "severity", "slug", "target_slug", "description", "auto_fixable")

    def __init__(self, issue_type: str, severity: str, slug: str,
                 description: str, target_slug: str = "", auto_fixable: bool = False):
        self.issue_type = issue_type
        self.severity = severity
        self.slug = slug
        self.target_slug = target_slug
        self.description = description
        self.auto_fixable = auto_fixable


class WikiLintService:
    """wiki 健康巡检 + 自动修复"""

    def __init__(self, session: AsyncSession, *, kb_id: int, space_id: int):
        self.session = session
        self.kb_id = kb_id
        self.space_id = space_id
        self.page_repo = WikiPageRepository(session)

    # ---------- 检查 ----------

    async def run_lint(self) -> Dict[str, Any]:
        """全 KB 巡检，返回 {issues, health_score, stats, summary}"""
        from novamind.features.knowledge_space.repository.document_repository import DocumentRepository

        pages = await self.page_repo.all_live_pages(self.kb_id)
        live_slugs = {p.slug for p in pages}

        # 已删文档检查（stale_ref 用）：一次批量查存活文档 id 集合
        doc_repo = DocumentRepository(self.session)
        ref_doc_ids = sorted({d for d in (
            self._doc_id_of(ref) for p in pages for ref in (p.source_refs or [])
        ) if d is not None})
        existing_docs = await doc_repo.get_by_ids(ref_doc_ids) if ref_doc_ids else []
        live_doc_ids = {d.id for d in existing_docs}

        issues: List[WikiLintIssue] = []
        seen_targets: Set[str] = set()

        for page in pages:
            is_index = page.page_type == "index"

            # broken_link：出链指向不存在/自指
            for target in page.out_links or []:
                if target not in live_slugs:
                    issues.append(WikiLintIssue(
                        LINT_BROKEN_LINK, "error", page.slug,
                        f"指向不存在页面的链接：[[{target}]]",
                        target_slug=target, auto_fixable=True,
                    ))
                elif target == page.slug:
                    issues.append(WikiLintIssue(
                        LINT_BROKEN_LINK, "error", page.slug,
                        f"自指链接：[[{target}]]",
                        target_slug=target, auto_fixable=True,
                    ))

            # stale_ref：source_ref 指向已删文档
            for ref in page.source_refs or []:
                doc_id = self._doc_id_of(ref)
                if doc_id and doc_id not in live_doc_ids:
                    issues.append(WikiLintIssue(
                        LINT_STALE_REF, "error", page.slug,
                        f"来源文档已被删除：{ref}",
                        target_slug=str(doc_id), auto_fixable=True,
                    ))

            if not is_index and not (page.in_links or []):
                issues.append(WikiLintIssue(
                    LINT_ORPHAN_PAGE, "warning", page.slug,
                    "孤儿页面：没有任何入链",
                ))

            content_len = len((page.content or "").strip())
            if not is_index and content_len < EMPTY_CONTENT_THRESHOLD:
                issues.append(WikiLintIssue(
                    LINT_EMPTY_CONTENT, "warning", page.slug,
                    f"空页面：正文不足 {EMPTY_CONTENT_THRESHOLD} 字符",
                    auto_fixable=True,
                ))

            # missing_cross_ref：正文提及他页标题/别名但未链（info，启发式）
            for other in pages:
                if other.slug == page.slug or other.page_type in ("index", "summary"):
                    continue
                if other.slug in (page.out_links or []):
                    continue
                for name in (other.title, *(other.aliases or [])):
                    if name and len(name) >= 2 and name in (page.content or "") and (page.slug, other.slug) not in seen_targets:
                        seen_targets.add((page.slug, other.slug))
                        issues.append(WikiLintIssue(
                            LINT_MISSING_CROSS_REF, "info", page.slug,
                            f"正文提及「{name}」但未建立链接",
                            target_slug=other.slug,
                        ))
                        break

        # duplicate_slug：MySQL (kb_id, slug, deleted_flag) 唯一约束下不可达，
        # 保留类型常量与检测壳供未来存储更换后的对齐（当前恒不触发）
        health_score = self._health_score(pages, issues)
        summary = self._summary(len(pages), issues, health_score)
        return {
            "issues": issues,
            "health_score": health_score,
            "stats": await self.page_repo.get_stats(self.kb_id),
            "summary": summary,
        }

    @staticmethod
    def _doc_id_of(ref: str) -> Optional[int]:
        """source_ref "docid|filename" → docid"""
        try:
            return int(str(ref).split("|", 1)[0])
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _health_score(pages: List[Any], issues: List[WikiLintIssue]) -> int:
        """HealthScore 0-100（对齐 WeKnora 扣分规则）"""
        score = 100
        n = len(pages)
        orphans = [i for i in issues if i.issue_type == LINT_ORPHAN_PAGE]
        broken = [i for i in issues if i.issue_type == LINT_BROKEN_LINK]
        empty = [i for i in issues if i.issue_type == LINT_EMPTY_CONTENT]

        if n:
            ratio = len(orphans) / n
            if ratio > HEALTH_ORPHAN_RATIO_SEVERE:
                score -= HEALTH_ORPHAN_SEVERE_PENALTY
            elif ratio > HEALTH_ORPHAN_RATIO_MILD:
                score -= HEALTH_ORPHAN_MILD_PENALTY
        score -= len(broken) * HEALTH_BROKEN_PENALTY_EACH
        if n and not any(p.out_links or p.in_links for p in pages):
            score -= HEALTH_NO_LINKS_PENALTY
        score -= len(empty) * HEALTH_EMPTY_PENALTY_EACH
        return max(0, min(100, score))

    @staticmethod
    def _summary(n_pages: int, issues: List[WikiLintIssue], score: int) -> str:
        if not n_pages:
            return "知识库暂无 Wiki 页面"
        errors = sum(1 for i in issues if i.severity == "error")
        warnings = sum(1 for i in issues if i.severity == "warning")
        return f"共 {n_pages} 页，健康分 {score}/100，{errors} 个错误、{warnings} 个警告"

    # ---------- 自动修复 ----------

    async def auto_fix(self) -> Dict[str, Any]:
        """修复所有 auto_fixable 问题（对齐 WeKnora AutoFix），返回明细"""
        report = await self.run_lint()
        fixed = 0
        details: List[str] = []

        for issue in report["issues"]:
            if not issue.auto_fixable:
                continue
            page = await self.page_repo.get_by_slug(self.kb_id, issue.slug)
            if page is None or page.is_deleted:
                continue

            if issue.issue_type == LINT_BROKEN_LINK:
                target = issue.target_slug
                # [[target]] → target；[[target|display]] → display（保文字去链接）
                content = (page.content or "").replace(f"[[{target}]]", target)
                content = re.sub(
                    r"\[\[" + re.escape(target) + r"\|([^\]]+)\]\]", r"\1", content,
                )
                if content != page.content:
                    await self.page_repo.update_auto_linked_content(page, content)
                    fixed += 1
                    details.append(f"{page.slug}: 剥除死链 [[{target}]]")

            elif issue.issue_type == LINT_EMPTY_CONTENT:
                if page.page_type != "index":
                    page.status = "archived"  # meta 写：归档而非删除
                    await self.session.flush()
                    fixed += 1
                    details.append(f"{page.slug}: 空页归档")

            elif issue.issue_type == LINT_STALE_REF:
                doc_id = self._doc_id_of(issue.target_slug) or self._doc_id_of(issue.description)
                remaining = [
                    r for r in (page.source_refs or [])
                    if self._doc_id_of(r) != doc_id
                ]
                if not remaining:
                    await self.page_repo.soft_delete_page(page)
                    fixed += 1
                    details.append(f"{page.slug}: 无剩余来源，页面删除")
                else:
                    page.source_refs = remaining
                    prefix = f"{doc_id}_" if doc_id is not None else ""
                    if prefix:
                        page.chunk_refs = [
                            r for r in (page.chunk_refs or []) if not str(r).startswith(prefix)
                        ]
                    await self.session.flush()
                    fixed += 1
                    details.append(f"{page.slug}: 剥除失效来源 {issue.target_slug}")

        # 修后重建全 KB 链接（对齐 WeKnora RebuildLinks）
        if fixed:
            await self._rebuild_links()
        return {"fixed": fixed, "details": details}

    async def _rebuild_links(self) -> None:
        """全 KB 死链剔除 + in_links 双向对齐（复用管道 Finalize 语义）"""
        pages = await self.page_repo.all_live_pages(self.kb_id)
        live_slugs = {p.slug for p in pages}

        for page in pages:
            out_links = [s for s in (page.out_links or []) if s in live_slugs and s != page.slug]
            if out_links != (page.out_links or []):
                page.out_links = out_links

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
        await self.session.flush()
