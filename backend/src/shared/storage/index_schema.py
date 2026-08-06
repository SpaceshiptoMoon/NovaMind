"""
Elasticsearch 索引 schema 端口，把索引命名与 mapping 从 ElasticsearchClient 解耦。

引擎经 IndexSchema 协议获取索引名与建索引体，宿主经 ClientFactory 注入实现。
DefaultIndexSchema 逐字复刻原逻辑，保证不注入时行为一致。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol, runtime_checkable


@dataclass(frozen=True)
class IndexFieldNames:
    """ES 文档字段名集合。

    检索方法构造查询时引用字段名统一走此处，避免在引擎中散写字符串字面量。
    `question_embeddings_vector` 是 `question_embeddings` 嵌套对象内部子字段名。
    """

    space_id: str = "space_id"
    kb_id: str = "kb_id"
    document_id: str = "document_id"
    chunk_id: str = "chunk_id"
    chunk_index: str = "chunk_index"
    chunk_type: str = "chunk_type"
    content: str = "content"
    embedding: str = "embedding"
    questions: str = "questions"
    question_embeddings: str = "question_embeddings"
    question_embeddings_vector: str = "vector"


@runtime_checkable
class IndexSchema(Protocol):
    """索引 schema 端口：引擎经此获取索引名与建索引体，不硬编码宿主命名/mapping。"""

    @property
    def field_names(self) -> IndexFieldNames:
        """检索方法引用的 ES 字段名集合。"""
        ...

    def index_name(self, space_id: int) -> str:
        """生成空间索引名。"""
        ...

    def build_create_body(self, embedding_dim: int, analyzer: str) -> Dict[str, Any]:
        """构造建索引体，返回 ``{"settings": {...}, "mappings": {"properties": {...}}}``。

        引擎侧 ``indices.create(settings=body["settings"], mappings=body["mappings"])``。
        """
        ...


class DefaultIndexSchema:
    """默认索引 schema：逐字复刻 NovaMind 现行 ``space_{space_id}`` 命名与 mapping。

    不注入 schema 时 ``ElasticsearchClient`` 使用本实现，行为与端口化前逐字一致。
    宿主可注入 ``NovamindIndexSchema``（同值，归 knowledge_space adapter 所有）以
    明确所有权；批次 6 抽包时本类随引擎迁出，宿主侧注入自己的实现。
    """

    def __init__(self) -> None:
        self._field_names = IndexFieldNames()

    @property
    def field_names(self) -> IndexFieldNames:
        return self._field_names

    def index_name(self, space_id: int) -> str:
        return f"space_{space_id}"

    def build_create_body(self, embedding_dim: int, analyzer: str) -> Dict[str, Any]:
        is_ik = analyzer.startswith("ik_")
        search_analyzer = "ik_smart" if is_ik else "standard"

        properties: Dict[str, Any] = {
            "space_id": {"type": "long"},
            "kb_id": {"type": "long"},
            "document_id": {"type": "long"},
            "chunk_id": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "content": {
                "type": "text",
                "analyzer": analyzer,
                "search_analyzer": search_analyzer,
            },
            "embedding": {
                "type": "dense_vector",
                "dims": embedding_dim,
                "index": True,
                "similarity": "cosine",
            },
            "questions": {
                "type": "text",
                "analyzer": analyzer,
                "search_analyzer": search_analyzer,
            },
            "question_embeddings": {
                "type": "nested",
                "properties": {
                    "vector": {
                        "type": "dense_vector",
                        "dims": embedding_dim,
                        "index": True,
                        "similarity": "cosine",
                    }
                },
            },
            "chunk_type": {"type": "keyword"},
            "image_url": {"type": "keyword"},
            "media_url": {"type": "keyword"},
            "metadata": {
                "properties": {
                    "page_number": {"type": "integer"},
                    "section_title": {"type": "text"},
                    "char_start": {"type": "integer"},
                    "char_end": {"type": "integer"},
                    "content_hash": {"type": "keyword"},
                    "start_time": {"type": "float"},
                    "end_time": {"type": "float"},
                    "duration": {"type": "float"},
                    "speaker_id": {"type": "keyword"},
                }
            },
            "file_info": {
                "properties": {
                    "filename": {"type": "keyword"},
                    "file_type": {"type": "keyword"},
                }
            },
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }

        return {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
            "mappings": {
                "properties": properties,
            },
        }


__all__ = ["IndexFieldNames", "IndexSchema", "DefaultIndexSchema"]