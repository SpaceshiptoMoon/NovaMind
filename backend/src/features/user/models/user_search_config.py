"""
用户搜索配置 ORM 模型

存储用户自定义的联网搜索 provider 凭证（Tavily/SerpAPI/DuckDuckGo），
每条记录绑定具体用户。

与 ``user_model_configs`` 分表的原因：provider 与 model_type/protocol 字段语义不同，
塞进模型表需要扩 ModelType IntEnum + 改 schema/repo/service/routes/manifest 五层，
技术债更大；搜索配置字段集（provider/api_key/extra_config/is_primary）独立且更简单，
单建表更清晰。
"""
from sqlalchemy import Column, BigInteger, String, Boolean, JSON, Index, ForeignKey

from novamind.core.database.base import BaseModel


class UserSearchConfig(BaseModel):
    """用户搜索配置表，存储联网搜索 provider 凭证。"""

    __tablename__ = "user_search_configs"

    # ========== 主键 ==========
    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # ========== 用户关联 ==========
    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID",
    )

    # ========== 搜索服务商配置 ==========
    provider = Column(
        String(20),
        nullable=False,
        comment="搜索服务商: tavily/serpapi/duckduckgo",
    )
    api_key = Column(
        String(500),
        nullable=True,
        comment="API Key（AES-256-GCM 加密存储）；duckduckgo 可空",
    )
    extra_config = Column(
        JSON,
        nullable=True,
        comment="扩展配置（max_results/search_depth/timeout/include_domains 等）",
    )
    is_primary = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否用户首选 provider（择优用，同 user 最多一条 is_primary=True）",
    )

    # 注意：created_at 和 updated_at 由 BaseModel 自动提供，无需重复定义

    # ========== 索引与约束 ==========
    __table_args__ = (
        # 同一用户下 provider 唯一
        Index("idx_user_search_provider", "user_id", "provider", unique=True),
        {"comment": "用户搜索配置表，存储联网搜索 provider 凭证"},
    )

    def __repr__(self) -> str:
        return (
            f"<UserSearchConfig(id={self.id}, user_id={self.user_id}, "
            f"provider={self.provider}, is_primary={self.is_primary})>"
        )