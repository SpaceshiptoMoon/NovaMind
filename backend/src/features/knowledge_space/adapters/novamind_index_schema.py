"""
NovaMind 宿主 ES 索引 schema

实现 `shared/storage/index_schema.py` 的 `IndexSchema` 协议，固化 NovaMind 部署的
索引命名（``space_{space_id}``）与 mapping。当前与引擎默认 `DefaultIndexSchema`
逐字一致，故直接继承；将来 NovaMind 需定制 mapping/字段名时，覆写 `build_create_body`/
`field_names` 即可，引擎侧 `ElasticsearchClient` 无需改动。

由 `shared/clients/__init__.py` 的 `ClientFactory.get_elasticsearch_client` 注入到
`ElasticsearchClient`。
"""
from novamind.shared.storage.index_schema import DefaultIndexSchema


class NovamindIndexSchema(DefaultIndexSchema):
    """NovaMind 知识空间索引 schema（``space_{space_id}`` + 现 mapping）。

    归 `features/knowledge_space/adapters/` 所有，体现「索引命名/mapping 是宿主业务」。
    """


__all__ = ["NovamindIndexSchema"]