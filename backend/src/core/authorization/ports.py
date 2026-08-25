"""RBAC 授权端口定义。"""
from abc import ABC, abstractmethod


class PermissionCheckerPort(ABC):
    """权限查询端口。

    消费方（如 ``core/auth`` 的依赖、各 feature 的路由守卫）通过此端口
    获取用户的权限码集合，无需关心底层实现来自 DB 还是缓存。
    """

    @abstractmethod
    async def get_user_permissions(self, user_id: int) -> set[str]:
        """返回指定用户的全部权限码集合。"""
        ...

    @abstractmethod
    async def invalidate(self, user_id: int) -> None:
        """清除指定用户的权限缓存。"""
        ...
