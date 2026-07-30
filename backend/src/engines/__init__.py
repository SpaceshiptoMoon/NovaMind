"""NovaMind 引擎——纯逻辑组件，不依赖宿主业务（鉴权/多租户/持久化/API 契约）。

引擎通过端口（Port）从宿主注入依赖，自身零 ``features`` / ``setting`` / ``core`` 导入。

目录规划：
  rag/          检索引擎（RetrievalEngine + RetrievalPort）
  agent/        Agent 引擎（未来）
  eval/         测评引擎（未来）
  knowledge/    知识处理引擎（未来）
  search/       外部搜索引擎（未来）
  resume/       简历解析引擎（未来）
  skill/        技能审查引擎（未来）
"""
