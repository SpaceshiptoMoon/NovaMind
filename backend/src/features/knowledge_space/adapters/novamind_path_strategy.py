"""
NovaMind 宿主 MinIO 对象路径策略

实现 `shared/storage/path_strategy.py` 的 `PathStrategy` 协议，固化 NovaMind 部署的
对象路径方案（``spaces/{id}/kbs/{id}/documents/{id}/...``、``avatars/{id}/avatar.{ext}``、
``temp/{session}/{file}``）。当前与引擎默认 `DefaultPathStrategy` 逐字一致，故直接继承；
将来 NovaMind 需定制路径方案时覆写对应方法即可，引擎侧 `MinioClient` 无需改动。

由 `shared/clients/__init__.py` 的 `ClientFactory.get_minio_client` 注入到 `MinioClient`。
"""
from novamind_engine_core.storage.path_strategy import DefaultPathStrategy


class NovamindPathStrategy(DefaultPathStrategy):
    """NovaMind MinIO 对象路径策略（现 ``spaces/``、``avatars/``、``temp/`` 方案）。

    归 `features/knowledge_space/adapters/` 所有，体现「对象路径方案是宿主业务」。
    """


__all__ = ["NovamindPathStrategy"]