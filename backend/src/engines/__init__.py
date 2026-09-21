"""
NovaMind 引擎包：按引擎域分目录的可复用纯逻辑组件。

- ``agent/``：Agent 引擎（ReAct 循环、工具系统、记忆、MCP、安全审批、PlanningFlow、子 agent）
- ``deep_research/``：深度研究引擎（查询分析/计划规划/迭代检索/综合报告 + 可插拔数据源）
- ``document/``：文档处理引擎（pipeline / splitters / converters / media / deepdoc vendored）
- ``eval/``：测评引擎（retrieval / generation / embedding / claim 评估器）
- ``rag/``：RAG 引擎（RetrievalEngine、GradeRetrier、QueryRewriter）
- ``resume/``：简历解析引擎（ResumeParser / ResumeAnalyzer / AutoProbingEngine）
- ``search/``：Web 搜索引擎组件（中立端口 WebSearchPort + 引擎默认实现 + 中立异常）

engines 层只抛中立异常、不持有 ORM session；宿主（features）按 R1/R4 直接 import
引擎类并注入具体客户端实例。
"""
