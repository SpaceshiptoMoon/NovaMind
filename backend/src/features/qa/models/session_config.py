"""
会话配置模型

存储会话的压缩配置与知识库绑定配置（会话级自动 RAG）
"""


from novamind.core.database.base import BaseModel
from novamind.features.qa.api.constants import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
)
from sqlalchemy import JSON, BigInteger, Column, String


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
            "threshold": 70000,
            "target_tokens": 2000,
            "keep_recent": 6,
            "custom_prompt": None,
        },
        comment="压缩配置"
    )

    # 知识库绑定配置（JSON 格式，用于会话级自动 RAG）
    # 结构: {space_id, kb_ids:[], auto_rag, refusal_enabled, score_threshold, search_mode, top_k,
    #        vector_weight, bm25_weight}  # 后两者仅 hybrid 类模式消费，和需=1.0
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

    # 联网搜索引擎配置（JSON 格式，会话级持久化）
    # 结构: {provider, max_results}；不含 enabled——启用开关由请求级 enable_web_search（聊天 chip）控制
    # provider=None 表示自动择优（用户首选 is_primary → YAML 兜底）
    web_search_config = Column(
        JSON,
        nullable=True,
        default=None,
        comment="联网搜索引擎配置（provider/max_results，会话级持久化）"
    )

    def __repr__(self) -> str:
        return f"<SessionConfig(session_id={self.session_id})>"

    # ========== 压缩配置访问方法 ==========

    def get_compression_config(self) -> dict:
        """读取压缩参数节（键缺省回退内置阈值）。"""
        return self.compression_config or {}

    @property
    def enable_compression(self) -> bool:
        """是否启用会话压缩（JSON 配置字段，缺省开启）。"""
        return self.get_compression_config().get("enable_compression", True)

    @property
    def compression_strategy(self) -> str:
        """压缩策略：summary/sliding_window/keep_recent/truncate。"""
        return self.get_compression_config().get("strategy", "summary")

    @property
    def compression_threshold(self) -> int:
        """触发压缩的上下文 token 阈值。"""
        return self.get_compression_config().get("threshold", 70000)

    @property
    def compression_target_tokens(self) -> int:
        """压缩后摘要的目标 token 数上限。"""
        return self.get_compression_config().get("target_tokens", 2000)

    @property
    def keep_recent_messages(self) -> int:
        """压缩时保留的最近消息条数。"""
        return self.get_compression_config().get("keep_recent", 6)

    @property
    def custom_summary_prompt(self) -> str | None:
        """自定义压缩摘要提示词（None 用内置模板）。"""
        return self.get_compression_config().get("custom_prompt")

    # ========== 知识库绑定访问方法（会话级自动 RAG） ==========

    def get_kb_bindings(self) -> dict:
        """获取知识库绑定配置"""
        return self.kb_bindings or {}

    @property
    def auto_rag(self) -> bool:
        """是否启用会话级自动 RAG（发消息前自动检索注入）。"""
        return self.get_kb_bindings().get("auto_rag", False)

    @property
    def rag_space_id(self) -> int | None:
        """自动 RAG 绑定的知识空间 ID（None 未绑定）。"""
        return self.get_kb_bindings().get("space_id")

    @property
    def rag_kb_ids(self) -> list:
        """自动 RAG 绑定的知识库 ID 列表（空列表未绑定）。"""
        return self.get_kb_bindings().get("kb_ids", []) or []

    @property
    def rag_refusal_enabled(self) -> bool:
        """是否启用分级拒答（检索为空拒答、低分标记）。"""
        return self.get_kb_bindings().get("refusal_enabled", False)

    @property
    def rag_score_threshold(self) -> float:
        # null 也兜底默认（避免 top_score < None 比较报错）
        """低置信度阈值，检索最高分低于它时标记（None 兜底 0.3）。"""
        val = self.get_kb_bindings().get("score_threshold")
        return val if val is not None else 0.3

    # 历史非法检索模式迁移：旧版前端下拉写入过 "vector"/"bm25"（非后端合法枚举），
    # 会触发 SearchRequest 校验失败被上层静默吃掉 → 检索无召回。读侧统一迁移到合法值。
    _LEGACY_SEARCH_MODE = {"vector": "content_vector", "bm25": "content_bm25"}

    @property
    def rag_search_mode(self) -> str:
        """检索模式；旧版非法值 vector/bm25 读侧迁移为合法枚举。"""
        mode = self.get_kb_bindings().get("search_mode", "content_hybrid")
        return self._LEGACY_SEARCH_MODE.get(mode, mode)

    @property
    def rag_top_k(self) -> int:
        """检索返回条数（缺省 5）。"""
        return self.get_kb_bindings().get("top_k", 5)

    @property
    def rag_vector_weight(self) -> float:
        # hybrid 类模式向量检索权重；null 兜底默认 0.7（与下游 SearchRequest.weights=None 兜底一致）
        """hybrid 模式向量检索权重（None 兜底 0.7）。"""
        val = self.get_kb_bindings().get("vector_weight")
        return val if val is not None else 0.7

    @property
    def rag_bm25_weight(self) -> float:
        # hybrid 类模式 BM25 检索权重；null 兜底默认 0.3，与 rag_vector_weight 之和需=1.0
        """hybrid 模式 BM25 检索权重（None 兜底 0.3，与向量权重和为 1）。"""
        val = self.get_kb_bindings().get("bm25_weight")
        return val if val is not None else 0.3

    @property
    def rag_query_rewriting(self) -> str:
        """检索前查询改写策略：none/completion/synonym/decompose/hyde。"""
        return self.get_kb_bindings().get("query_rewriting", "none")

    @property
    def rag_grade_retry_enabled(self) -> bool:
        """是否启用检索后自评估重试。"""
        return self.get_kb_bindings().get("grade_retry_enabled", False)

    @property
    def rag_grade_retry_passing_score(self) -> int:
        """检索及格分数（1-10），低于则触发重试。"""
        return self.get_kb_bindings().get("grade_retry_passing_score", 5)

    # ========== 模型生成参数访问方法（会话级持久化） ==========

    def get_llm_config(self) -> dict:
        """获取模型生成参数配置"""
        return self.llm_config or {}

    @property
    def llm_max_tokens(self) -> int:
        # null 也兜底默认（用户在弹窗清空时存 null）
        """会话级最大生成 token 数（None 兜底默认值）。"""
        val = self.get_llm_config().get("max_tokens")
        return val if val is not None else DEFAULT_MAX_TOKENS

    @property
    def llm_temperature(self) -> float:
        """会话级采样温度（None 兜底默认值）。"""
        val = self.get_llm_config().get("temperature")
        return val if val is not None else DEFAULT_TEMPERATURE

    @property
    def llm_top_p(self) -> float:
        """会话级核采样概率（None 兜底默认值）。"""
        val = self.get_llm_config().get("top_p")
        return val if val is not None else DEFAULT_TOP_P

    @property
    def llm_system_prompt(self) -> str | None:
        # None 是合法值，表示「用后端 QA 模板」，不兜底
        """会话级系统提示词（None 表示用后端 QA 模板，是合法值不兜底）。"""
        return self.get_llm_config().get("system_prompt")

    # ========== 联网搜索引擎配置访问方法（会话级持久化） ==========

    def get_web_search_config(self) -> dict:
        """获取联网搜索引擎配置"""
        return self.web_search_config or {}

    @property
    def web_search_provider(self) -> str | None:
        # None 是合法值，表示「自动择优」（用户首选 → YAML 兜底），不兜底
        """联网搜索引擎（None 表示自动择优，是合法值不兜底）。"""
        return self.get_web_search_config().get("provider")

    @property
    def web_search_max_results(self) -> int:
        """联网搜索返回条数（None 兜底 5）。"""
        val = self.get_web_search_config().get("max_results")
        return val if val is not None else 5

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "compression_config": self.compression_config,
            "kb_bindings": self.kb_bindings,
            "llm_config": self.llm_config,
            "web_search_config": self.web_search_config,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
