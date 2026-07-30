"""
存储模块初始化

提供 MinIO 和 Elasticsearch 的客户端封装
"""

from novamind_engine_core.storage.minio_client import MinioClient
from novamind_engine_core.storage.elasticsearch_client import ElasticsearchClient

__all__ = [
    "MinioClient",
    "ElasticsearchClient",
]
