"""Agent 执行引擎——``novamind.engines.agent`` 核心组件。

纯逻辑 ReAct 循环引擎，通过端口（``engines/agent/ports``）从宿主注入依赖，
自身零 ``features`` / ``setting`` / ORM 导入。

公共面：
  - ``AgentEngine`` — ReAct 循环引擎（Think→Act→Observe→Respond，流式/非流式）
  - ``AgentEvent`` — 引擎事件 dataclass

宿主在 ``features/agent/services/chat_service.py`` 装配引擎，经
``features/agent/adapters/`` 注入端口实现（KnowledgeSearchPort/MemoryStorePort/
MemorySearchPort/WebSearchPort）。

依赖方向：features → engines → shared。
"""
from novamind.engines.agent.agent_engine import AgentEngine, AgentEvent

__all__ = ["AgentEngine", "AgentEvent"]