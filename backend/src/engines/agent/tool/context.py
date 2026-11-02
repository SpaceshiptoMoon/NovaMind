"""
工具执行上下文：强类型数据载体，端口依赖显式化（解耦 context god-dict）。

独立成模块（不经 base.py）以控制 import 边：base/hooks/executor 引本模块，
本模块只引叶子契约（ports/interfaces/approval_registry），图保持无环。
安全钩子（safety/approval.py）经 TYPE_CHECKING 引用本模块——其父包
``__init__`` 连带加载 approval.py，真实 import 会成运行时环。

三种历史角色已拆分：
- 工具端口容器：本类的端口字段（全部 Optional，宿主按需注入）；
- 引擎调参：tool_result_turn_budget 移为 AgentEngine 构造参数；
- 服务层落库状态板：iteration/plan_*/tc_* 等归 chat_service 私有状态对象，
  工具与引擎不可见。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from novamind.engines.agent.memory.interfaces import IMemorySearch, IMemoryStore
from novamind.engines.agent.tool.ports import (
    AttachmentReadPort,
    KnowledgePipelineConfig,
    KnowledgeSearchPort,
    LocalWorkspacePort,
    WebSearchPort,
)


@dataclass
class ToolContext:
    """工具执行上下文（单次对话请求一份，工具链路全程透传）。

    身份字段必有；端口字段按 Agent 勾选与会话形态注入，缺失即该能力不可用
    （工具执行时显式报「未配置」，不做静默兜底）。子 agent 经
    ``dataclasses.replace`` 派生（subagent_runner 置 None 防递归），不再
    浅拷贝裸 dict。
    """

    # ---------- 身份（必有） ----------
    db_session: Any
    """宿主数据库会话，引擎层保持不透明（Any）——引擎不感知 ORM。"""
    user_id: int
    agent_id: int
    session_id: str | None = None
    conversation_id: int | None = None

    # ---------- 能力端口（按需注入，缺省 None = 能力不可用） ----------
    web_search_port: WebSearchPort | None = None
    knowledge_search_port: KnowledgeSearchPort | None = None
    memory_store_port: IMemoryStore | None = None
    memory_search_port: IMemorySearch | None = None
    embedding_client_resolver: Callable[[], Awaitable[Any]] | None = None
    attachment_read_port: AttachmentReadPort | None = None
    local_workspace_port: LocalWorkspacePort | None = None
    knowledge_pipeline: KnowledgePipelineConfig | None = None
    approval_registry: Any = None
    """异步审批注册表（ApprovalRegistry 实例，宿主注入）。Any 标注防 import 环：
    本模块被 hooks 真实引用，而 safety/__init__ 连带加载 approval.py，反向真实
    import 会成运行时环；钩子侧鸭子访问 register/resolve/wait/cleanup。"""
    event_sink: Callable[[dict], Awaitable[None]] | None = None
    """审批请求/研究进度等旁路事件的接收器（WS 端点注入，群聊恒 None）。"""
    memory_limit_per_user_agent: int | None = None
    """单用户单 Agent 记忆条数上限；None 时工具侧用内置默认。"""

    # ---------- 组合能力（宿主构造，引擎鸭子调用） ----------
    subagent_runner: Any = None
    """SubAgentRunner 实例（宿主注入）；Any 标注防与 subagent 包成 import 环。"""
    research_service_factory: Callable[[], Any] | None = None
    """DeepResearchService 工厂（每次调用新实例，独立 db session）。"""

    # ---------- 群聊专属（纯透传，引擎不感知内容，对齐 deep_research deps 先例） ----------
    group_consult: Any = None
    group_messaging: Any = None
