"""空间轻查询服务：跨 feature 公共面的空间维度查询集合。

放置约束：本模块及其 import 链不得依赖 user/agent 等 feature（否则跨 feature
消费方经此查询会成 import 环——space_service 即因依赖 user.model_config_service
而不可用，2026-11-15 门禁实锤）。repository 直查已被
test_no_cross_feature_repository_imports 禁止，本模块即其服务面替身。
"""


async def find_spaces_using_embedding(session, model_name: str) -> list[dict]:
    """查绑定指定 embedding 模型的空间影响面（零外部依赖，仅 session）。

    user 侧模型配置删除前的绑定影响检查入口。
    """
    from novamind.features.knowledge_space.repository.space_repository import SpaceRepository

    return await SpaceRepository(session).find_spaces_using_embedding(model_name)
