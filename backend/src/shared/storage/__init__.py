"""
存储模块初始化

提供 MinIO 和 Elasticsearch 的客户端封装
"""

from src.shared.storage.minio_client import MinioClient
from src.shared.storage.elasticsearch_client import ElasticsearchClient

__all__ = [
    "MinioClient",
    "ElasticsearchClient",
]
