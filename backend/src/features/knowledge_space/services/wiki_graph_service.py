"""Wiki 图谱/链接域服务（批次 4.1 从 wiki_routes 下沉）。

- ``finalize_links``：软删页后的死链清理 + in/out 双向对齐
- ``WikiGraphService``：get_graph 的 ego BFS / overview 连通度排序、get_stats
"""
from __future__ import annotations

from collections import deque

from novamind.features.knowledge_space.exceptions import (
    InvalidParameterError,
    WikiPageNotFoundError,
)
from novamind.features.knowledge_space.repository.wiki_repository import (
    WikiPageRepository,
)
from novamind.features.knowledge_space.schemas.wiki_schema import (
    WikiGraphEdge,
    WikiGraphMeta,
    WikiGraphNode,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def finalize_links(repo: WikiPageRepository, kb_id: int) -> None:
    """死链清理 + in/out 双向对齐（软删页面后调用）。"""
    pages = await repo.all_live_pages(kb_id)
    live_slugs = {p.slug for p in pages}
    slug_map = {p.slug: p for p in pages}
    in_map = {p.slug: [] for p in pages}
    for page in pages:
        cleaned = [s for s in (page.out_links or []) if s in live_slugs and s != page.slug]
        if cleaned != (page.out_links or []):
            page.out_links = cleaned
        for target in page.out_links or []:
            if target in slug_map and target != page.slug:
                in_map[target].append(page.slug)
    for slug, page in slug_map.items():
        aligned = sorted(set(in_map.get(slug, [])))
        if aligned != (page.in_links or []):
            page.in_links = aligned


class WikiGraphService:
    """Wiki 链接图/统计读服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = WikiPageRepository(db)

    async def build_graph(
        self, *, kb_id: int, mode: str, center: str | None, depth: int, limit: int
    ):
        """构造链接图（overview 按连通度 top-N / ego BFS 邻域）。

        Returns: WikiGraphResponse 的构造数据（nodes/edges/meta 原料）。
        """
        pages = await self.repo.all_live_pages(kb_id)

        if mode == "ego":
            if not center:
                raise InvalidParameterError("ego 模式必须提供 center slug", field="center")
            slug_map = {p.slug: p for p in pages}
            if center not in slug_map:
                raise WikiPageNotFoundError(center)
            # BFS 收集邻域
            visited = {center}
            queue = deque([(center, 0)])
            while queue:
                slug, d = queue.popleft()
                if d >= depth:
                    continue
                page = slug_map.get(slug)
                if not page:
                    continue
                neighbors = set(page.out_links or []) | set(page.in_links or [])
                for n in neighbors:
                    if n in slug_map and n not in visited:
                        visited.add(n)
                        queue.append((n, d + 1))
            selected_slugs = set(list(visited)[:limit])
        else:
            # overview：按连通度（in+out）取 top-N
            ranked = sorted(
                pages,
                key=lambda p: len(p.out_links or []) + len(p.in_links or []),
                reverse=True,
            )
            selected_slugs = {p.slug for p in ranked[:limit]}

        nodes = [
            WikiGraphNode(
                slug=p.slug,
                title=p.title,
                page_type=p.page_type,
                link_count=len(p.out_links or []) + len(p.in_links or []),
            )
            for p in pages if p.slug in selected_slugs
        ]
        edges = [
            WikiGraphEdge(source=p.slug, target=t)
            for p in pages if p.slug in selected_slugs
            for t in (p.out_links or [])
            if t in selected_slugs and t != p.slug
        ]
        meta = WikiGraphMeta(
            mode=mode,
            total=len(pages),
            returned=len(nodes),
            truncated=len(nodes) < len(pages),
            center=center if mode == "ego" else None,
            depth=depth if mode == "ego" else None,
        )
        return nodes, edges, meta
