"""用户模型配置 ORM 模型：凭证分离——只存 api_key/base_url，前端传模型名称后端按名称查凭证。"""
from enum import IntEnum
from typing import Any

from novamind.core.database.base import BaseModel
from sqlalchemy import JSON, BigInteger, Column, ForeignKey, Index, Integer, String


class ModelType(IntEnum):
    """模型类型枚举"""
    LLM = 1                  # 大语言模型
    EMBEDDING = 2            # 向量化模型
    RERANK = 3               # 重排序模型
    VLM = 4                  # 视觉语言模型
    # 5 已废弃（原 MULTIMODAL_EMBEDDING），保留编号不重用避免数据库冲突
    ASR = 6                  # 语音识别模型（Whisper等）


class UserModelConfig(BaseModel):
    """
    用户模型配置表

    存储连接凭证，每条记录绑定具体用户
    """
    __tablename__ = "user_model_configs"

    # ========== 主键 ==========
    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # ========== 用户关联 ==========
    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID"
    )

    # ========== 模型配置 ==========
    model_type = Column(Integer, nullable=False, comment="模型类型: 1-LLM, 2-Embedding, 3-Rerank, 4-VLM, 6-ASR")
    protocol = Column(String(50), nullable=False, default="openai", comment="通信协议: openai/anthropic/ollama/transformers")
    model = Column(String(100), nullable=False, comment="模型名称（如 gpt-4o、embedding-3）")
    base_url = Column(String(500), nullable=True, comment="API Base URL")
    api_key = Column(String(500), nullable=True, comment="API Key（加密存储）")

    # ========== 扩展信息 ==========
    extra_config = Column(JSON, nullable=True, comment="扩展配置（如 dimension、timeout、max_retries 等）")

    # 注意：created_at 和 updated_at 由 BaseModel 自动提供，无需重复定义

    # ========== 索引与约束 ==========
    __table_args__ = (
        # 同一用户下 (model_type, model) 唯一
        Index("idx_user_model_type_model", "user_id", "model_type", "model", unique=True),
        {"comment": "用户模型配置表，存储用户自定义的 LLM/Embedding/Rerank 模型连接凭证"},
    )

    def __repr__(self) -> str:
        return f"<UserModelConfig(id={self.id}, user_id={self.user_id}, type={self.model_type}, model={self.model})>"

    def get_extra(self, key: str, default: Any = None) -> Any:
        """获取扩展配置 extra_config 中的值。

        Args:
            key: 扩展配置键名。
            default: 键缺失或 extra_config 为空时的返回值，默认 None。

        Returns:
            键对应值或 default。
        """
        if self.extra_config is None:
            return default
        return self.extra_config.get(key, default)
