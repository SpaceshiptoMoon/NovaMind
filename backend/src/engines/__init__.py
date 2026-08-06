"""NovaMind 引擎——纯逻辑组件，不依赖宿主业务（鉴权/多租户/持久化/API 契约）。

引擎通过端口（Port）从宿主注入依赖，自身零 ``features`` / ``setting`` / ``core`` 导入。

目录规划：
  rag/          检索引擎（RetrievalEngine/RetrievalPort + GradeRetrier；cache_port/errors）
  agent/        Agent 引擎（AgentEngine + ports）
  eval/         测评引擎（Embedding/Claim/Generation/Retrieval Evaluator）
  resume/       简历解析引擎（ResumeParser/ResumeAnalyzer/AutoProbingEngine + Schema）

注：知识处理（pipeline/splitters/converters/media/deepdoc）是知识库域业务能力，
归 ``features/knowledge_space/``，不进 engines；技能审查（SkillChecker）是技能域
校验器，归 ``features/skill/services/``，非编排引擎。

注：Web 搜索 provider（DuckDuckGo/Tavily/SerpAPI）是外部 SaaS HTTP 客户端，归
``shared/clients/search/``（基础能力）；引擎层仅留 ``search_ports.py`` 定义
``WebSearchPort``/``WebSearchResult`` 端口（端口在 engines、实现在 shared，同
``CachePort``/``RedisCache`` 约定）。
"""
