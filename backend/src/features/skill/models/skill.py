"""
技能广场模型 — 基于 Anthropic SKILL.md 开放标准
"""
from enum import IntEnum, StrEnum

from sqlalchemy import (
    Column, BigInteger, String, Text, Integer, Float,
    SmallInteger, JSON, DateTime, ForeignKey, UniqueConstraint, Index,
)

from novamind.core.database.base import BaseModel


class SkillSource(StrEnum):
    """技能来源"""
    BUILTIN = "builtin"
    CUSTOM = "custom"


class SkillVisibility(IntEnum):
    """技能可见性"""
    PRIVATE = 0
    TEAM = 1
    PUBLIC = 2


class SkillStatus(IntEnum):
    """技能状态"""
    DRAFT = 0
    PUBLISHED = 1
    ARCHIVED = 2


class ReviewStatus(IntEnum):
    """安全审查状态"""
    PENDING = 0
    APPROVED = 1
    SUSPICIOUS = 2
    REJECTED = 3


class SkillDefinition(BaseModel):
    """技能定义 — 存储用户上传的 SKILL.md 解析结果"""
    __tablename__ = "skill_definitions"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_skill_user_name"),
        Index("idx_category_status", "category", "status"),
        Index("idx_visibility_status", "visibility", "status"),
        {"comment": "技能定义表，存储 SKILL.md 解析后的元数据和指令内容"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        BigInteger, ForeignKey("users.id"), nullable=True,
        index=True, comment="所属用户ID，NULL为系统内置",
    )
    name = Column(String(64), nullable=False, comment="技能标识，kebab-case 格式")
    display_name = Column(String(100), nullable=False, comment="显示名称")

    description = Column(String(1024), nullable=False, comment="技能描述，含触发词")
    license = Column(String(100), nullable=True, comment="许可证标识")
    allowed_tools = Column(JSON, nullable=True, comment="允许的工具名列表")

    frontmatter_raw = Column(Text, nullable=True, comment="完整 YAML frontmatter 原文")
    body_markdown = Column(Text, nullable=False, comment="Markdown 指令正文")

    category = Column(String(50), nullable=True, comment="分类")
    tags = Column(JSON, nullable=True, comment="标签列表")
    icon = Column(String(50), nullable=True, comment="图标标识")

    version = Column(Integer, default=1, comment="当前版本号")
    version_note = Column(String(500), nullable=True, comment="版本说明")

    skill_source = Column(String(20), nullable=False, default=SkillSource.CUSTOM, comment="来源: builtin/custom")
    visibility = Column(SmallInteger, default=SkillVisibility.PRIVATE, comment="可见性: 0=PRIVATE/1=TEAM/2=PUBLIC")
    status = Column(SmallInteger, default=SkillStatus.DRAFT, comment="状态: 0=DRAFT/1=PUBLISHED/2=ARCHIVED")

    install_count = Column(Integer, default=0, comment="安装次数")
    rating_avg = Column(Float, default=0.0, comment="平均评分")
    rating_count = Column(Integer, default=0, comment="评价数量")

    review_status = Column(
        SmallInteger, default=ReviewStatus.PENDING,
        comment="审查状态: 0=PENDING/1=APPROVED/2=SUSPICIOUS/3=REJECTED",
    )
    review_result = Column(JSON, nullable=True, comment="审查结果: {rules: [...], llm: {...}}")
    reviewed_at = Column(DateTime, nullable=True, comment="审查时间")

    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")

    def __repr__(self) -> str:
        return f"<SkillDefinition(id={self.id}, name='{self.name}')>"


class SkillVersion(BaseModel):
    """技能版本历史"""
    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="uq_skill_version"),
        {"comment": "技能版本历史表"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    skill_id = Column(BigInteger, ForeignKey("skill_definitions.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)

    frontmatter_raw = Column(Text, nullable=True, comment="该版本的 YAML frontmatter")
    body_markdown = Column(Text, nullable=False, comment="该版本的 Markdown 正文")
    allowed_tools = Column(JSON, nullable=True, comment="该版本的工具列表")
    resource_manifest = Column(JSON, nullable=True, comment="资源文件清单 [{path, type, size}]")
    version_note = Column(String(500), nullable=True, comment="版本说明")

    def __repr__(self) -> str:
        return f"<SkillVersion(id={self.id}, skill_id={self.skill_id}, v={self.version})>"


class SkillReview(BaseModel):
    """技能评价"""
    __tablename__ = "skill_reviews"
    __table_args__ = (
        UniqueConstraint("skill_id", "user_id", name="uq_skill_review_user"),
        {"comment": "技能评价表"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    skill_id = Column(BigInteger, ForeignKey("skill_definitions.id"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    rating = Column(SmallInteger, nullable=False, comment="评分 1-5")
    content = Column(Text, nullable=True, comment="评价内容")

    def __repr__(self) -> str:
        return f"<SkillReview(id={self.id}, skill_id={self.skill_id}, rating={self.rating})>"


class SkillInstallation(BaseModel):
    """技能安装记录"""
    __tablename__ = "skill_installations"
    __table_args__ = (
        UniqueConstraint("skill_id", "agent_id", name="uq_skill_agent"),
        {"comment": "技能安装记录表"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    skill_id = Column(BigInteger, ForeignKey("skill_definitions.id"), nullable=False, index=True)
    agent_id = Column(BigInteger, ForeignKey("agent_definitions.id"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)

    def __repr__(self) -> str:
        return f"<SkillInstallation(id={self.id}, skill_id={self.skill_id}, agent_id={self.agent_id})>"
