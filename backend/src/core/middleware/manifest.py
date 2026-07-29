"""Feature Manifest 数据模型

批次 1 的核心抽象：每个 feature 用一个 `FeatureManifest` 描述自己的路由、
依赖、初始化钩子、ORM 模型与开关，由 `manifest_loader` 统一发现并拓扑排序，
替代 `router_manager` 与 `startup_manager` 中原先硬编码的三张表/注册表。

设计原则：
- 路由以 `RouterSpec` 描述（key + router 对象 + prefix + tag），prefix/tag 与
  原 `router_manager` 的 `prefix_mapping`/`tag_mapping` 逐字一致，确保
  `GET /openapi.json` 逐字不变（前端契约源头）。
- `order` 是拓扑排序的稳定 tiebreaker：当多个 feature 的依赖都已满足时，
  按 `order` 升序挑选。这样无需伪造依赖边即可得到确定的初始化顺序
  （如 user→knowledge_space→agent→notification→clawmate）。
- `init_hook` 为可选的异步初始化函数（接收 app）；无副作用的 feature 可留 None。
- `models_loader` 为可选的同步函数，负责导入该 feature 的全部 ORM 模型以注册到
  SQLAlchemy metadata；无 ORM 模型的 feature（如 clawmate）留 None。
- `enabled` 由 `manifest_loader` 从 `FeaturesConfig` 解析后注入，manifest 自身
  声明时不写死 enabled，保持「配置驱动开关」。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional

from fastapi import APIRouter


# API 版本前缀（原 router_manager.API_V1_PREFIX，集中到 manifest 层供各 feature 共用）
API_V1_PREFIX = "/api/v1"


@dataclass
class RouterSpec:
    """单个路由规格

    Attributes:
        key: 内部稳定键（原 `routers` dict 的 key，用于去重/调试）。
        router: FastAPI APIRouter 对象。
        prefix: 路由前缀，含 `{space_id}` 等路径模板，逐字复刻原 `prefix_mapping`。
        tag: OpenAPI tag（中文，原 `tag_mapping`）。
    """

    key: str
    router: APIRouter
    prefix: str
    tag: str


@dataclass
class FeatureManifest:
    """单个 feature 的 manifest

    Attributes:
        name: feature 名（唯一标识，与 `features/<name>/` 目录名一致）。
        routers: 该 feature 的路由规格列表（按声明顺序）。
        depends_on: 依赖的 feature 名列表（拓扑排序用）。
        order: 初始化拓扑 tiebreaker，越小越优先；system manifest 设 0 以最先。
        route_order: 路由注册顺序，越小越先注册。与 `order` **分离**：路由注册顺序
            决定 FastAPI 对**同名 Pydantic 响应模型**的去重胜出者（先注册者胜），
            必须与 legacy `router_manager` 硬编码顺序逐字一致，否则
            `GET /openapi.json` 中碰撞 schema 的内容会翻转，破坏前端契约。
            未指定时回退到 `order`。
        init_hook: 可选异步初始化函数 `(app) -> Awaitable[None]`。
        models_loader: 可选同步函数，导入该 feature 的 ORM 模型（注册 metadata）。
        enabled: 是否启用，由 manifest_loader 从 FeaturesConfig 解析注入。
    """

    name: str
    routers: List[RouterSpec] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    order: int = 100
    route_order: Optional[int] = None
    init_hook: Optional[Callable[[object], Awaitable[None]]] = None
    models_loader: Optional[Callable[[], None]] = None
    enabled: bool = True

    def __post_init__(self) -> None:
        # route_order 未显式指定时回退到 init 拓扑序 order
        if self.route_order is None:
            self.route_order = self.order


__all__ = ["RouterSpec", "FeatureManifest", "API_V1_PREFIX"]