"""知识空间 arq 任务入口（宿主编排层）。

批次 6e 收口：本模块从 ``shared/mq/worker.py`` 下沉而来，承载文档处理 arq 任务的
宿主编排（装配 DocumentService、重试/取消/失败兜底、孤儿恢复、入队）。``shared/mq``
只保留通用 arq 运行时；本模块在 ``features/`` 下，允许 import features models/repo/
services 与 setting 配置。

任务函数经 ``core/middleware/startup_manager`` 收集后注入 ``start_embedded_worker``。
"""
from novamind.shared.logging import get_logger

logger = get_logger(__name__)