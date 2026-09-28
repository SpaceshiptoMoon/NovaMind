"""NovaMind 引擎包：按引擎域分目录的可复用纯逻辑组件（agent/deep_research/document/eval/rag/resume/search）。
engines 层只抛中立异常、不持有 ORM session；宿主（features）按 R1/R4 直接 import 引擎类并注入具体客户端实例。
"""
