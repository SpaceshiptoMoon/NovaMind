"""
知识空间 arq 任务入口，承载文档处理任务的宿主编排（装配、重试、取消、兜底）。
"""
from novamind.shared.logging import get_logger

logger = get_logger(__name__)