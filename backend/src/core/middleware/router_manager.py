"""
路由管理器，负责注册所有应用路由，支持 API 版本控制。
"""

from fastapi import APIRouter
from novamind.core.middleware.manifest_loader import get_route_sorted_manifests


class RouterManager:
    """路由管理器"""

    def __init__(self):
        self.routers: dict[str, APIRouter] = {}
        # manifest 路径无需在此预加载 router 对象；get_all_routers 时按需聚合
        # （批次 6.2：NOVAMIND_LEGACY_MANIFEST 双路径已删，manifest 为唯一路径）

    # ==================== manifest 聚合路径（默认） ====================

    def get_router(self, name: str) -> APIRouter:
        """获取指定的路由（仅 legacy 路径填充 self.routers；manifest 路径返回 None）"""
        return self.routers.get(name)

    def get_all_routers(self) -> list[tuple[APIRouter, str, list[str]]]:
        """
        获取所有路由及其配置。

        Returns:
            List[tuple]: 路由配置列表，每个元素为 (router, prefix, tags)

        逐字复刻原 get_all_routers 的产出：每条 (router, prefix, [tag])，prefix 与 tag
        来自 manifest 的 RouterSpec（与原 prefix_mapping/tag_mapping 一致）。health
        路由（system manifest，prefix=""）随其 route_order=0 排在最前，与原显式 append
        行为一致。按 `route_order` 遍历（匹配 legacy 路由注册序），而非初始化拓扑序。
        """
        router_configs: list[tuple[APIRouter, str, list[str]]] = []
        for m in get_route_sorted_manifests():
            if not m.enabled:
                continue
            for spec in m.routers:
                router_configs.append((spec.router, spec.prefix, [spec.tag]))
        return router_configs

    # ==================== legacy 硬编码路径（回滚用） ====================

