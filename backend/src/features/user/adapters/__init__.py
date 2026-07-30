"""user feature 宿主适配器。

批次 5b 新增 ``knowledge_space_info_adapter.py``：实现 ``KnowledgeSpaceInfoPort``，
解开 ``ModelConfigService._check_delete_impact`` 对 knowledge_space models 的反向依赖。
"""