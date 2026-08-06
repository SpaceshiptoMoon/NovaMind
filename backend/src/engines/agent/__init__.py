"""
Agent 执行引擎——纯逻辑 ReAct 循环引擎。
AgentEngine（Think→Act→Observe→Respond），通过端口从宿主注入依赖，
零 features/setting/ORM 导入。宿主在 features/agent 装配并注入端口实现。
"""
from novamind.engines.agent.agent_engine import AgentEngine, AgentEvent

__all__ = ["AgentEngine", "AgentEvent"]