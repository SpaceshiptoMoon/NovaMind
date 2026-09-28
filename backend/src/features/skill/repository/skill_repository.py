"""
技能广场仓储层
"""

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.skill.models.skill import (
    ReviewStatus,
    SkillDefinition,
    SkillInstallation,
    SkillReview,
    SkillStatus,
    SkillVersion,
    SkillVisibility,
)
from sqlalchemy import case, delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class SkillRepository:
    """技能定义仓储"""

    _UPDATABLE_FIELDS = frozenset({
        "display_name", "description", "license", "allowed_tools",
        "frontmatter_raw", "body_markdown", "category", "tags", "icon",
        "version", "version_note", "visibility", "status",
        "install_count", "rating_avg", "rating_count",
        "review_status", "review_result", "reviewed_at", "deleted_at",
    })

    _MARKETPLACE_FILTER = [
        SkillDefinition.deleted_at.is_(None),
        SkillDefinition.visibility == SkillVisibility.PUBLIC,
        SkillDefinition.status == SkillStatus.PUBLISHED,
        SkillDefinition.review_status == ReviewStatus.APPROVED,
    ]

    def __init__(self, session: AsyncSession):
        """绑定请求级数据库会话。"""
        self.session = session

    async def create(self, **kwargs) -> SkillDefinition:
        """创建技能记录（begin_nested 写入，同名唯一约束冲突抛已存在异常）。"""
        from novamind.features.skill.exceptions import SkillAlreadyExistsError
        async with self.session.begin_nested():
            skill = SkillDefinition(**kwargs)
            self.session.add(skill)
            try:
                await self.session.flush()
            except IntegrityError:
                raise SkillAlreadyExistsError(kwargs.get("name", ""))
        await self.session.refresh(skill)
        return skill

    async def get_by_id(self, skill_id: int) -> SkillDefinition | None:
        """按 ID 查技能，自动过滤已软删除记录。

        Args:
            skill_id: 技能 ID。

        Returns:
            技能记录，不存在或已软删除返回 None。
        """
        result = await self.session.execute(
            select(SkillDefinition).where(
                SkillDefinition.id == skill_id,
                SkillDefinition.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def hard_delete_by_name(self, user_id: int, name: str) -> None:
        """彻底删除同名的软删除记录，释放唯一约束。

        Args:
            user_id: 技能归属用户 ID。
            name: 技能名称。
        """
        await self.session.execute(
            delete(SkillDefinition).where(
                SkillDefinition.user_id == user_id,
                SkillDefinition.name == name,
                SkillDefinition.deleted_at.is_not(None),
            )
        )

    async def get_by_name(self, user_id: int | None, name: str) -> SkillDefinition | None:
        """按名称查技能（过滤软删）；user_id 为 None 时只匹配系统预置技能。

        Args:
            user_id: 归属用户 ID；None 表示只查 user_id 为空的系统预置技能。
            name: 技能名称。

        Returns:
            技能记录，无则 None。
        """
        query = select(SkillDefinition).where(
            SkillDefinition.name == name,
            SkillDefinition.deleted_at.is_(None),
        )
        if user_id is not None:
            query = query.where(SkillDefinition.user_id == user_id)
        else:
            query = query.where(SkillDefinition.user_id.is_(None))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: int, status: int | None = None,
        limit: int = 20, offset: int = 0,
    ) -> tuple[list[SkillDefinition], int]:
        """分页列出用户自己的技能（过滤软删，可按状态筛选）。

        Args:
            user_id: 归属用户 ID。
            status: 状态过滤（SkillStatus 值）；None 表示不过滤。
            limit: 每页数量，默认 20。
            offset: 偏移量，默认 0。

        Returns:
            (技能列表, 总数) 二元组，按创建时间降序。
        """
        base = select(SkillDefinition).where(
            SkillDefinition.user_id == user_id,
            SkillDefinition.deleted_at.is_(None),
        )
        if status is not None:
            base = base.where(SkillDefinition.status == status)

        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(SkillDefinition.created_at.desc())
            .offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def list_marketplace(
        self, keyword: str | None = None, category: str | None = None,
        tags: list[str] | None = None, sort: str = "newest",
        limit: int = 20, offset: int = 0,
    ) -> tuple[list[SkillDefinition], int]:
        """技能广场搜索

        搜索策略：
        1. FULLTEXT (ngram 分词) 布尔模式 → 索引扫描，支持中文分词
        2. ILIKE 逐词 OR 匹配 → FULLTEXT 不可用时的降级
        3. 字段加权：name ×3, display_name ×2, description ×1
        4. 标签加分：匹配的标签数计入相关性，不再做硬过滤
        """
        base = select(SkillDefinition).where(
            SkillDefinition.deleted_at.is_(None),
            SkillDefinition.visibility == SkillVisibility.PUBLIC,
            SkillDefinition.status == SkillStatus.PUBLISHED,
            SkillDefinition.review_status == ReviewStatus.APPROVED,
        )

        tokens: list = []
        relevance_expr = None

        if keyword:
            tokens = [t.strip() for t in keyword.split() if t.strip()]
            if tokens:
                # 字段权重配置
                FIELD_WEIGHTS = {"name": 3, "display_name": 2, "description": 1}

                # FULLTEXT 索引仅在 MySQL 上创建（见 core/database/base.py
                # ensure_fulltext_indexes），按连接方言判定而非 try/except——
                # 表达式构建阶段不会抛兼容性错误，try/except 捕不到 execute
                # 阶段的错误，原降级路径是永不触发的 dead code。
                dialect_name = self.session.bind.dialect.name if self.session.bind is not None else ""

                if dialect_name == "mysql":
                    # 布尔模式 WHERE：每个 token 前加 + 表示必须包含
                    ft_tokens = " ".join(
                        f"+{_sanitize_ft_token(t)}" for t in tokens
                    )
                    base = base.where(
                        text(
                            "MATCH(skill_definitions.name, "
                            "skill_definitions.display_name, "
                            "skill_definitions.description) "
                            "AGAINST (:ft IN BOOLEAN MODE)"
                        ).bindparams(ft=ft_tokens)
                    )

                    # FULLTEXT 相关性评分（自然语言模式）
                    ft_score = text(
                        "MATCH(skill_definitions.name, "
                        "skill_definitions.display_name, "
                        "skill_definitions.description) "
                        "AGAINST (:kw)"
                    ).bindparams(kw=keyword)

                    # 字段命中加分（name 命中权重最高）
                    name_bonus = _build_field_bonus(
                        SkillDefinition.name, tokens, FIELD_WEIGHTS["name"]
                    )
                    display_bonus = _build_field_bonus(
                        SkillDefinition.display_name, tokens, FIELD_WEIGHTS["display_name"]
                    )
                    desc_bonus = _build_field_bonus(
                        SkillDefinition.description, tokens, FIELD_WEIGHTS["description"]
                    )

                    relevance_expr = (
                        ft_score + name_bonus + display_bonus + desc_bonus
                    ).label("_relevance")

                else:
                    # 非 MySQL（如 SQLite 测试环境）→ ILIKE 降级
                    logger.debug("非 MySQL 方言，使用 ILIKE 降级搜索", dialect=dialect_name)
                    base, relevance_expr = _build_ilike_relevance(
                        SkillDefinition, tokens, FIELD_WEIGHTS, base
                    )

        if category:
            base = base.where(SkillDefinition.category == category)

        # 标签：匹配数量越多得分越高（不再做硬 AND 过滤）
        if tags:
            tag_bonus = _build_tag_bonus(tags)
            if tag_bonus is not None:
                if relevance_expr is not None:
                    relevance_expr = (relevance_expr + tag_bonus).label("_relevance")
                else:
                    relevance_expr = tag_bonus.label("_relevance")
                # 至少匹配一个标签（OR 逻辑）
                tag_ors = [
                    func.json_contains(SkillDefinition.tags, f'"{t}"')
                    for t in tags
                ]
                base = base.where(
                    SkillDefinition.tags.is_not(None),
                    or_(*tag_ors),
                )

        # 统一添加相关性列（避免多次 add_columns 造成重复列）
        if relevance_expr is not None:
            base = base.add_columns(relevance_expr)

        # 计数
        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        # 排序
        order_col = {
            "popular": SkillDefinition.install_count.desc(),
            "rating": SkillDefinition.rating_avg.desc(),
            "newest": SkillDefinition.created_at.desc(),
            "name": SkillDefinition.display_name.asc(),
        }.get(sort, SkillDefinition.created_at.desc())

        if relevance_expr is not None:
            result = await self.session.execute(
                base.order_by(relevance_expr.desc(), order_col)
                .offset(offset).limit(limit)
            )
        else:
            result = await self.session.execute(
                base.order_by(order_col).offset(offset).limit(limit)
            )
        return result.scalars().all(), total

    async def update(self, skill_id: int, **kwargs) -> SkillDefinition | None:
        """按白名单字段更新技能（未命中字段静默忽略）。

        Args:
            skill_id: 技能 ID；其余关键字参数仅白名单内的字段生效。

        Returns:
            更新后的技能记录，技能不存在返回 None。
        """
        skill = await self.get_by_id(skill_id)
        if not skill:
            return None
        for key, value in kwargs.items():
            if key in self._UPDATABLE_FIELDS:
                setattr(skill, key, value)
        await self.session.flush()
        await self.session.refresh(skill)
        return skill

    async def soft_delete(self, skill_id: int) -> bool:
        """软删除技能：置 deleted_at 并重命名释放唯一约束。

        Args:
            skill_id: 技能 ID。

        Returns:
            实际删除返回 True，记录不存在返回 False。
        """
        from novamind.shared.utils.time_utils import now_china
        ts = int(now_china().timestamp())
        result = await self.session.execute(
            update(SkillDefinition)
            .where(SkillDefinition.id == skill_id)
            .values(deleted_at=now_china(), name=SkillDefinition.name + f"_deleted_{ts}")
        )
        return result.rowcount > 0

    async def increment_install_count(self, skill_id: int) -> None:
        """安装计数加一。

        Args:
            skill_id: 技能 ID。
        """
        await self.session.execute(
            update(SkillDefinition)
            .where(SkillDefinition.id == skill_id)
            .values(install_count=SkillDefinition.install_count + 1)
        )

    async def decrement_install_count(self, skill_id: int) -> None:
        """安装计数减一（下限 0，不为负）。

        Args:
            skill_id: 技能 ID。
        """
        await self.session.execute(
            update(SkillDefinition)
            .where(SkillDefinition.id == skill_id)
            .values(install_count=func.greatest(SkillDefinition.install_count - 1, 0))
        )

    async def get_published_by_name(self, name: str) -> SkillDefinition | None:
        """按名称查已发布且未删除的技能。

        Args:
            name: 技能名称。

        Returns:
            已发布的技能记录，无则 None。
        """
        result = await self.session.execute(
            select(SkillDefinition).where(
                SkillDefinition.name == name,
                SkillDefinition.deleted_at.is_(None),
                SkillDefinition.status == SkillStatus.PUBLISHED,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_review_status(
        self, review_status: int, limit: int = 20, offset: int = 0,
    ) -> tuple[list[SkillDefinition], int]:
        """按审查状态列出技能。

        Args:
            review_status: 审查状态（ReviewStatus 值）。
            limit: 每页数量，默认 20。
            offset: 偏移量，默认 0。

        Returns:
            (技能列表, 总数) 二元组，按创建时间降序。
        """
        base = select(SkillDefinition).where(
            SkillDefinition.deleted_at.is_(None),
            SkillDefinition.review_status == review_status,
        )
        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0
        result = await self.session.execute(
            base.order_by(SkillDefinition.created_at.desc())
            .offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def get_distinct_categories(self) -> list[str]:
        """获取所有已上架技能的去重分类列表"""
        result = await self.session.execute(
            select(SkillDefinition.category)
            .where(
                SkillDefinition.deleted_at.is_(None),
                SkillDefinition.visibility == SkillVisibility.PUBLIC,
                SkillDefinition.status == SkillStatus.PUBLISHED,
                SkillDefinition.review_status == ReviewStatus.APPROVED,
                SkillDefinition.category.is_not(None),
            )
            .distinct()
            .order_by(SkillDefinition.category)
        )
        return [row[0] for row in result.all()]

    async def get_common_tags(self, limit: int = 50) -> list[str]:
        """获取所有已上架技能的常用标签（按出现频率降序）。

        Args:
            limit: 返回标签数上限，默认 50。

        Returns:
            按频率降序的标签列表。
        """
        result = await self.session.execute(
            select(SkillDefinition.tags)
            .where(
                SkillDefinition.deleted_at.is_(None),
                SkillDefinition.visibility == SkillVisibility.PUBLIC,
                SkillDefinition.status == SkillStatus.PUBLISHED,
                SkillDefinition.review_status == ReviewStatus.APPROVED,
                SkillDefinition.tags.is_not(None),
            )
        )
        tag_counter: dict[str, int] = {}
        for row in result.all():
            tags = row[0] or []
            for tag in tags:
                tag_counter[tag] = tag_counter.get(tag, 0) + 1
        sorted_tags = sorted(tag_counter.items(), key=lambda x: -x[1])
        return [tag for tag, _ in sorted_tags[:limit]]


# ==================== 搜索辅助函数 ====================

def _sanitize_ft_token(token: str) -> str:
    """清理 FULLTEXT 特殊字符，保留中文/英文/数字"""
    return "".join(
        c for c in token if c.isalnum() or c.isspace() or c in "_-."
    )


def _build_field_bonus(column, tokens: list, weight: int):
    """构建字段命中加分表达式

    字段中包含任意 token → +weight 分（每个 token 独立计算，取最高命中）
    """
    if not tokens:
        return case((column.isnot(None), 0), else_=0)  # 无 token 不加分
    # 任一 token 命中该字段就得 weight 分
    conditions = [column.ilike(f"%{t}%") for t in tokens]
    return case(
        (or_(*conditions), weight),
        else_=0,
    )


def _build_tag_bonus(tags: list):
    """构建标签加分表达式：匹配的标签数 × 加权系数"""
    if not tags:
        return None
    return sum(
        case(
            (func.json_contains(SkillDefinition.tags, f'"{t}"'), 1),
            else_=0,
        )
        for t in tags
    ) * 2  # 标签匹配权重 ×2


def _build_ilike_relevance(model, tokens: list, weights: dict, base):
    """ILIKE 降级方案：逐词 OR 匹配 + 字段加权

    Returns: (modified_base, relevance_expr)
    """
    token_conditions = []
    relevance_parts = []
    for token in tokens:
        pattern = f"%{token}%"
        token_hit = or_(
            model.name.ilike(pattern),
            model.display_name.ilike(pattern),
            model.description.ilike(pattern),
        )
        token_conditions.append(token_hit)
        # 基础分：命中 1 个 token 得 1 分
        hit_score = case((token_hit, 1), else_=0)

        # 字段加权加分
        field_bonus = (
            case((model.name.ilike(pattern), weights["name"]), else_=0) +
            case((model.display_name.ilike(pattern), weights["display_name"]), else_=0) +
            case((model.description.ilike(pattern), weights["description"]), else_=0)
        )
        relevance_parts.append(hit_score + field_bonus)

    return (
        base.where(or_(*token_conditions)),
        sum(relevance_parts).label("_relevance"),
    )


class SkillVersionRepository:
    """技能版本仓储"""

    def __init__(self, session: AsyncSession):
        """绑定请求级数据库会话。"""
        self.session = session

    async def create(self, **kwargs) -> SkillVersion:
        """创建技能版本记录（只 flush，事务由服务层提交）。"""
        version = SkillVersion(**kwargs)
        self.session.add(version)
        await self.session.flush()
        await self.session.refresh(version)
        return version

    async def list_by_skill(
        self, skill_id: int, limit: int = 20, offset: int = 0,
    ) -> tuple[list[SkillVersion], int]:
        """分页列出技能的版本历史（按版本号降序）。

        Args:
            skill_id: 技能 ID。
            limit: 每页数量，默认 20。
            offset: 偏移量，默认 0。

        Returns:
            (版本列表, 总数) 二元组。
        """
        base = select(SkillVersion).where(SkillVersion.skill_id == skill_id)
        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0
        result = await self.session.execute(
            base.order_by(SkillVersion.version.desc())
            .offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def get_version(self, skill_id: int, version: int) -> SkillVersion | None:
        """查技能的指定版本号记录。

        Args:
            skill_id: 技能 ID。
            version: 版本号。

        Returns:
            版本记录，无则 None。
        """
        result = await self.session.execute(
            select(SkillVersion).where(
                SkillVersion.skill_id == skill_id,
                SkillVersion.version == version,
            )
        )
        return result.scalar_one_or_none()


class SkillReviewRepository:
    """技能评价仓储"""

    def __init__(self, session: AsyncSession):
        """绑定请求级数据库会话。"""
        self.session = session

    async def create_or_update(
        self, skill_id: int, user_id: int, rating: int, content: str | None,
    ) -> SkillReview:
        """创建或更新评价（同用户同技能幂等覆盖）。

        Args:
            skill_id: 技能 ID。
            user_id: 评价所属用户 ID。
            rating: 评分。
            content: 评论文字，可为 None。

        Returns:
            写入后的最新评价记录。
        """
        existing = await self.get_by_user_and_skill(user_id, skill_id)
        if existing:
            existing.rating = rating
            existing.content = content
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        review = SkillReview(
            skill_id=skill_id, user_id=user_id, rating=rating, content=content,
        )
        self.session.add(review)
        await self.session.flush()
        await self.session.refresh(review)
        return review

    async def get_by_user_and_skill(self, user_id: int, skill_id: int) -> SkillReview | None:
        """查用户对某技能的现存评价。

        Args:
            user_id: 评价所属用户 ID。
            skill_id: 技能 ID。

        Returns:
            现存评价记录，无则 None。
        """
        result = await self.session.execute(
            select(SkillReview).where(
                SkillReview.user_id == user_id,
                SkillReview.skill_id == skill_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_skill(
        self, skill_id: int, limit: int = 20, offset: int = 0,
    ) -> tuple[list[SkillReview], int]:
        """分页列出技能的全部评价（按时间降序）。

        Args:
            skill_id: 技能 ID。
            limit: 每页数量，默认 20。
            offset: 偏移量，默认 0。

        Returns:
            (评价列表, 总数) 二元组。
        """
        base = select(SkillReview).where(SkillReview.skill_id == skill_id)
        count_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0
        result = await self.session.execute(
            base.order_by(SkillReview.created_at.desc())
            .offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def delete_review(self, user_id: int, skill_id: int) -> bool:
        """删除用户对技能的评价。

        Args:
            user_id: 评价所属用户 ID。
            skill_id: 技能 ID。

        Returns:
            实际删除返回 True，本无评价返回 False。
        """
        result = await self.session.execute(
            delete(SkillReview).where(
                SkillReview.user_id == user_id,
                SkillReview.skill_id == skill_id,
            )
        )
        return result.rowcount > 0

    async def get_rating_stats(self, skill_id: int) -> tuple[float, int]:
        """聚合技能评分，无评价返回 (0.0, 0)。

        Args:
            skill_id: 技能 ID。

        Returns:
            (平均分, 评价数) 二元组。
        """
        result = await self.session.execute(
            select(
                func.avg(SkillReview.rating),
                func.count(SkillReview.id),
            ).where(SkillReview.skill_id == skill_id)
        )
        row = result.one()
        return float(row[0] or 0), int(row[1] or 0)


class SkillInstallationRepository:
    """技能安装仓储"""

    def __init__(self, session: AsyncSession):
        """绑定请求级数据库会话。"""
        self.session = session

    async def create(self, **kwargs) -> SkillInstallation:
        """创建技能安装记录（只 flush，事务由服务层提交）。"""
        installation = SkillInstallation(**kwargs)
        self.session.add(installation)
        await self.session.flush()
        await self.session.refresh(installation)
        return installation

    async def get_by_skill_and_agent(self, skill_id: int, agent_id: int) -> SkillInstallation | None:
        """查某 Agent 对某技能的安装记录。

        Args:
            skill_id: 技能 ID。
            agent_id: Agent ID。

        Returns:
            安装记录，无则 None。
        """
        result = await self.session.execute(
            select(SkillInstallation).where(
                SkillInstallation.skill_id == skill_id,
                SkillInstallation.agent_id == agent_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_agent(self, agent_id: int) -> list[SkillInstallation]:
        """列出 Agent 已安装的全部技能。

        Args:
            agent_id: Agent ID。

        Returns:
            安装记录列表。
        """
        result = await self.session.execute(
            select(SkillInstallation).where(SkillInstallation.agent_id == agent_id)
        )
        return result.scalars().all()

    async def delete_installation(self, skill_id: int, agent_id: int) -> bool:
        """删除 Agent 的技能安装记录。

        Args:
            skill_id: 技能 ID。
            agent_id: Agent ID。

        Returns:
            实际删除返回 True，记录不存在返回 False。
        """
        result = await self.session.execute(
            delete(SkillInstallation).where(
                SkillInstallation.skill_id == skill_id,
                SkillInstallation.agent_id == agent_id,
            )
        )
        return result.rowcount > 0
