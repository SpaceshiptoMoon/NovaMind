"""
NovaMind 宿主 ES 索引 schema，实现 IndexSchema 协议，固化索引命名与 mapping。

当前继承 DefaultIndexSchema，需定制时覆写 build_create_body/field_names 即可。
"""
from novamind.shared.storage.index_schema import DefaultIndexSchema


class NovamindIndexSchema(DefaultIndexSchema):
    """NovaMind 知识空间索引 schema（``space_{space_id}`` + 现 mapping）。

    归 `features/knowledge_space/adapters/` 所有，体现「索引命名/mapping 是宿主业务」。
    """


__all__ = ["NovamindIndexSchema"]