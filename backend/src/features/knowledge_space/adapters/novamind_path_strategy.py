"""
NovaMind 宿主 MinIO 对象路径策略，实现 PathStrategy 协议，固化对象路径方案。

支持 spaces/、avatars/、temp/ 三类路径，当前继承 DefaultPathStrategy，需定制时覆写即可。
"""
from novamind.shared.storage.path_strategy import DefaultPathStrategy


class NovamindPathStrategy(DefaultPathStrategy):
    """NovaMind MinIO 对象路径策略（现 ``spaces/``、``avatars/``、``temp/`` 方案）。

    归 `features/knowledge_space/adapters/` 所有，体现「对象路径方案是宿主业务」。
    """


__all__ = ["NovamindPathStrategy"]