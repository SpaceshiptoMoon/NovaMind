"""
Agent 工具端口契约：工具消费面接口的单一权威定义（消费者所有，实现归宿主）。

R4 边界：接口定义在引擎侧（消费者所有），宿主（features/agent）实现后经
ToolContext 强类型字段注入；工具与钩子只依赖本模块的接口形状，不感知宿主
实现（SQLAlchemy/ES/业务服务）。方法签名以既有宿主实现为权威对齐，新增
端口方法先在此登记，再在实现与工具两侧展开——杜绝「接口与实现签名分叉」
（IMemoryStore 的历史教训）。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from novamind.engines.agent.context_types import (
    DocumentListResult,
    KbInfo,
    KnowledgeSearchItem,
    SpaceInfo,
)
from novamind.engines.search.ports import WebSearchPort

__all__ = [
    "AttachmentReadPort",
    "KnowledgePipelineConfig",
    "KnowledgeSearchPort",
    "LocalWorkspacePort",
    "WebSearchPort",
]


class KnowledgeSearchPort(ABC):
    """知识库检索端口（knowledge_search 五子工具共用消费面）。"""

    @abstractmethod
    async def can_access_space(self, space_id: int, user_id: int) -> bool:
        """空间级访问判定。"""

    @abstractmethod
    async def list_spaces(self, user_id: int) -> list[SpaceInfo]:
        """列出用户可访问的空间。"""

    @abstractmethod
    async def list_knowledge_bases(self, space_id: int, user_id: int) -> list[KbInfo]:
        """列出空间下 ACTIVE 状态的知识库。"""

    @abstractmethod
    async def list_all_knowledge_bases(self, user_id: int) -> list[KbInfo]:
        """跨空间列出用户全部可访问知识库（KbInfo 附带 space_name）。"""

    @abstractmethod
    async def search(
        self,
        space_id: int,
        user_id: int,
        query: str,
        top_k: int = 5,
        search_mode: str = "content_hybrid",
        kb_id: int | None = None,
        tags: list[str] | None = None,
    ) -> list[KnowledgeSearchItem]:
        """按模式检索知识库内容，按分数排序返回。"""

    @abstractmethod
    async def list_documents(
        self,
        space_id: int,
        kb_id: int,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> DocumentListResult:
        """分页列出知识库文档并返回总数。"""

    @abstractmethod
    async def pipeline_search(
        self,
        space_id: int,
        user_id: int,
        query: str,
        *,
        llm_client: Any | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        rewrite_strategy: str = "completion",
        grade_retry_enabled: bool = False,
        grade_passing_score: int = 5,
        score_threshold: float = 0.3,
        top_k: int = 5,
        search_mode: str = "content_hybrid",
        kb_ids: list[int] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """带质量保障层的检索管线（改写→检索→grade-retry→阈值过滤）。

        返回 dict 含 items/insufficient_evidence/rewritten_query/rewrite_degraded/
        grade_traces 五键。
        """


class AttachmentReadPort(ABC):
    """会话附件文本读取端口（read_attachment 工具消费面）。"""

    @abstractmethod
    async def get_attachment_text(
        self, attachment_id: int, user_id: int, offset: int = 0, limit: int = 8000
    ) -> dict[str, Any]:
        """按 offset/limit 分片返回附件提取文本。

        Raises:
            KeyError: 附件不存在或归属不符。
        """


class LocalWorkspacePort(ABC):
    """本地工作区执行端口（read/glob/grep/bash 等工作区工具统一入口）。

    自 features/agent/services/local_workspace/port.py 下沉归位（消费者所有）；
    进程内与 runner 两种宿主形态实现留原地继承。设备离线等错误以
    ``{"error": ..., "error_code": ...}`` dict 返回（能力缺失优于悬死）。
    """

    @abstractmethod
    async def execute(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """执行一次工作区工具调用，返回结果 dict（ok/result 或 ok=False/error）。"""

    @abstractmethod
    async def aclose(self) -> None:
        """释放底层资源（runner 形态无持有资源则空实现）。"""


@dataclass
class KnowledgePipelineConfig:
    """知识检索质量管线配置（knowledge_search 与 research 工具共用消费面）。

    替代原 context["knowledge_pipeline"] 裸 dict——质量参数此前只有读者没有
    写者（恒走工具侧默认），正式化为带默认值的字段后，宿主可按配置显式覆盖，
    工具侧不再字典取值。
    """

    llm_client: Any | None = None
    knowledge_bindings: dict[str, Any] | None = None
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    rewrite_strategy: str = "completion"
    grade_retry_enabled: bool = False
    grade_passing_score: int = 5
    score_threshold: float = 0.3
