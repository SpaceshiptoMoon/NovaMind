"""
会话配置模型

存储会话的压缩配置与知识库绑定配置（会话级自动 RAG）
"""

from typing import Optional
from sqlalchemy import Column, BigInteger, String, Text, JSON

from src.core.database.base import BaseModel


class SessionConfig(BaseModel):
    """
    会话配置模型

    存储压缩配置与知识库绑定配置；LLM 配置由前端在对话时传入
    """
    __tablename__ = "qa_session_configs"
    __table_args__ = (
        {"comment": "QA 会话配置表，存储会话的压缩配置与知识库绑定配置"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String(36), nullable=False, unique=True, index=True, comment="会话ID（UUID格式）")
    user_id = Column(BigInteger, nullable=False, index=True, comment="用户ID")

    # 压缩配置（JSON 格式）
    compression_config = Column(
        JSON,
        nullable=False,
        default=lambda: {
            "enable_compression": True,
            "strategy": "summary",
            "threshold": 3000,
            "target_tokens": 500,
            "keep_recent": 2,
            "custom_prompt": None,
        },
        comment="压缩配置"
    )

    # 知识库绑定配置（JSON 格式，用于会话级自动 RAG）
    # 结构: {space_id, kb_ids:[], auto_rag, refusal_enabled, score_threshold, search_mode, top_k}
    kb_bindings = Column(
        JSON,
        nullable=True,
        default=None,
        comment="知识库绑定配置（会话级自动 RAG）"
    )

    # 模型生成参数配置（JSON 格式，会话级持久化）
    # 结构: {max_tokens, temperature, top_p, system_prompt}
    # 注意：llm_model/enable_thinking 由前端请求传，不在此列
    llm_config = Column(
        JSON,
        nullable=True,
        default=None,
        comment="模型生成参数配置（max_tokens/temperature/top_p/system_prompt）"
    )

    def __repr__(self) -> str:
        return f"<SessionConfig(session_id={self.session_id})>"

    # ========== 压缩配置访问方法 ==========

    def get_compression_config(self) -> dict:
        """获取压缩配置"""
        return self.compression_config or {}

    @property
    def enable_compression(self) -> bool:
        return self.get_compression_config().get("enable_compression", True)

    @property
    def compression_strategy(self) -> str:
        return self.get_compression_config().get("strategy", "summary")

    @property
    def compression_threshold(self) -> int:
        return self.get_compression_config().get("threshold", 3000)

    @property
    def compression_target_tokens(self) -> int:
        return self.get_compression_config().get("target_tokens", 500)

    @property
    def keep_recent_messages(self) -> int:
        return self.get_compression_config().get("keep_recent", 2)

    @property
    def custom_summary_prompt(self) -> Optional[str]:
        return self.get_compression_config().get("custom_prompt")

    # ========== 知识库绑定访问方法（会话级自动 RAG） ==========

    def get_kb_bindings(self) -> dict:
        """获取知识库绑定配置"""
        return self.kb_bindings or {}

    @property
    def auto_rag(self) -> bool:
        return self.get_kb_bindings().get("auto_rag", False)

    @property
    def rag_space_id(self) -> Optional[int]:
        return self.get_kb_bindings().get("space_id")

    @property
    def rag_kb_ids(self) -> list:
        return self.get_kb_bindings().get("kb_ids", []) or []

    @property
    def rag_refusal_enabled(self) -> bool:
        return self.get_kb_bindings().get("refusal_enabled", False)

    @property
    def rag_score_threshold(self) -> float:
        # null 也兜底默认（避免 top_score < None 比较报错）
        val = self.get_kb_bindings().get("score_threshold")
        return val if val is not None else 0.3

    @property
    def rag_search_mode(self) -> str:
        return self.get_kb_bindings().get("search_mode", "content_hybrid")

    @property
    def rag_top_k(self) -> int:
        return self.get_kb_bindings().get("top_k", 5)

    # ========== 模型生成参数访问方法（会话级持久化） ==========

    def get_llm_config(self) -> dict:
        """获取模型生成参数配置"""
        return self.llm_config or {}

    @property
    def llm_max_tokens(self) -> int:
        # null 也兜底默认（用户在弹窗清空时存 null）
        val = self.get_llm_config().get("max_tokens")
        return val if val is not None else 2048

    @property
    def llm_temperature(self) -> float:
        val = self.get_llm_config().get("temperature")
        return val if val is not None else 0.7

    @property
    def llm_top_p(self) -> float:
        val = self.get_llm_config().get("top_p")
        return val if val is not None else 0.8

    @property
    def llm_system_prompt(self) -> Optional[str]:
        # None 是合法值，表示「用后端 QA 模板」，不兜底
        return self.get_llm_config().get("system_prompt")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "compression_config": self.compression_config,
            "kb_bindings": self.kb_bindings,
            "llm_config": self.llm_config,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
