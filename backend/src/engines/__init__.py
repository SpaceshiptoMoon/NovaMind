"""
NovaMind 引擎——纯逻辑组件，不依赖宿主业务（鉴权/多租户/持久化/API 契约）。

引擎通过端口从宿主注入依赖，零 features / setting / core 导入。

目录：rag/（检索）、agent/（Agent）、eval/（测评）、resume/（简历解析）。
知识处理归 features/knowledge_space/，技能审查归 features/skill/。
Web 搜索 provider 归 shared/clients/search/，引擎层仅留 search_ports.py 定义端口。
"""
