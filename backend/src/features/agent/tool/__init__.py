"""Agent 宿主侧工具。

宿主专属工具（依赖 ORM / DB session 的工具）放这里，与引擎内置工具分离。
引擎内置工具（web_search/knowledge_search/memory/todo/code_execution）经端口注入宿主能力，
迁入 ``novamind.engines.agent.tool.builtins``；本目录只留必须直接访问宿主持久化的工具。
"""