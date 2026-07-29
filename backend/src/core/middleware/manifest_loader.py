"""Feature Manifest 发现与拓扑排序

替代 `router_manager._register_routers` 的硬编码路由表与 `startup_manager` 的
硬编码 `_feature_initializers` / `_import_models`：

1. `discover_feature_manifests()`：扫描 `features/*/manifest.py`，调用各模块的
   `manifest()` 工厂函数收集 `FeatureManifest`；并附带 `system_manifest`（健康检查
   等系统路由）。
2. 从 `FeaturesConfig` 解析 `enabled` 注入每个 manifest。
3. Kahn 拓扑排序 + 环检测，按 `order` 升序作稳定 tiebreaker。

`get_sorted_manifests()` 返回拓扑有序的 `FeatureManifest` 列表，供：
- `router_manager.get_all_routers()` 聚合路由；
- `startup_manager._init_features()` 按序执行 init_hook；
- `startup_manager._import_models()` 调各 `models_loader`。

依赖边由 manifest 的 `depends_on` 声明；`order` 仅作 tiebreaker，不改变拓扑
正确性。缺失的依赖名（声明的 depends_on 不存在）记为警告但不阻断（容错）。
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Dict, List

from novamind.core.middleware.structured_logging import get_logger
from novamind.setting.yaml_config import FeatureFlag, get_config
from novamind.setting.yaml_config.config import FeaturesConfig

from .manifest import FeatureManifest

logger = get_logger(__name__)

# feature 子包名（features/<name>）
_FEATURES_PACKAGE = "novamind.features"
# system manifest 模块（健康检查等系统路由，非 feature）
_SYSTEM_MANIFEST_MODULE = "novamind.core.middleware.system_manifest"


def _load_feature_manifests() -> List[FeatureManifest]:
    """扫描 `features/*/manifest.py`，调用 `manifest()` 收集 FeatureManifest。

    用 pkgutil 遍历 features 包的所有子模块，对每个子包尝试 import
    `.manifest` 子模块并调用其 `manifest()` 工厂。无 manifest.py 的 feature
    （暂未迁移）被跳过并记录，不影响其余 feature。
    """
    manifests: List[FeatureManifest] = []
    try:
        features_pkg = importlib.import_module(_FEATURES_PACKAGE)
    except ImportError as e:  # pragma: no cover - features 包必存在
        logger.error("无法导入 features 包", error=str(e))
        return manifests

    for _finder, name, ispkg in pkgutil.iter_modules(features_pkg.__path__):
        if not ispkg:
            continue  # feature 必须是子包
        module_name = f"{_FEATURES_PACKAGE}.{name}.manifest"
        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            # 该 feature 暂无 manifest.py，跳过
            continue
        except Exception as e:  # manifest 模块自身报错：记警告，不阻断其余
            logger.warning("feature manifest 加载失败", feature=name, error=str(e))
            continue
        factory = getattr(mod, "manifest", None)
        if factory is None:
            logger.warning("feature manifest 模块缺少 manifest() 工厂", feature=name)
            continue
        try:
            m = factory()
        except Exception as e:
            logger.warning("feature manifest() 构造失败", feature=name, error=str(e))
            continue
        if not isinstance(m, FeatureManifest):
            logger.warning("manifest() 返回类型非 FeatureManifest", feature=name, got=type(m).__name__)
            continue
        if m.name != name:
            logger.warning(
                "manifest name 与目录名不一致，以目录名为准",
                declared=m.name, directory=name,
            )
            m.name = name
        manifests.append(m)
    return manifests


def _load_system_manifest() -> FeatureManifest | None:
    """加载 system manifest（健康检查等系统路由）。"""
    try:
        mod = importlib.import_module(_SYSTEM_MANIFEST_MODULE)
    except ImportError:
        logger.warning("system manifest 模块缺失", module=_SYSTEM_MANIFEST_MODULE)
        return None
    factory = getattr(mod, "manifest", None)
    if factory is None:
        return None
    return factory()


def _resolve_enabled(manifests: List[FeatureManifest], config_features: FeaturesConfig) -> None:
    """从 FeaturesConfig 解析每个 manifest 的 enabled 并注入。"""
    for m in manifests:
        m.enabled = config_features.flags.get(m.name, FeatureFlag()).enabled


def _topo_sort(manifests: List[FeatureManifest]) -> List[FeatureManifest]:
    """Kahn 拓扑排序 + 环检测，按 `order` 升序作稳定 tiebreaker。

    - 仅对 enabled 的 manifest 排序；disabled 的不参与（也不被依赖）。
    - 依赖指向的 feature 若缺失或被禁用，记警告并忽略该依赖边（容错降级），
      不阻断启动。
    - 检测到环则抛 RuntimeError（启动期 fail-fast，避免静默错误顺序）。
    """
    enabled = [m for m in manifests if m.enabled]
    by_name: Dict[str, FeatureManifest] = {m.name: m for m in enabled}

    # 入度表（仅统计存在的依赖）
    in_degree: Dict[str, int] = {m.name: 0 for m in enabled}
    adj: Dict[str, List[str]] = {m.name: [] for m in enabled}
    for m in enabled:
        for dep in m.depends_on:
            if dep not in by_name:
                logger.warning(
                    "manifest 依赖的 feature 不存在或被禁用，忽略该依赖边",
                    feature=m.name, depends_on=dep,
                )
                continue
            adj[dep].append(m.name)
            in_degree[m.name] += 1

    # 就绪队列：入度为 0 的节点，按 order 升序稳定挑选
    ready = sorted([m for m in enabled if in_degree[m.name] == 0], key=lambda x: x.order)
    result: List[FeatureManifest] = []
    while ready:
        # 取 order 最小的就绪节点
        ready.sort(key=lambda x: x.order)
        current = ready.pop(0)
        result.append(current)
        for nxt in adj[current.name]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                ready.append(by_name[nxt])

    if len(result) != len(enabled):
        cyclic = [m.name for m in enabled if m not in result]
        raise RuntimeError(
            f"feature manifest 依赖存在环，无法拓扑排序，涉及 feature: {cyclic}"
        )
    return result


def discover_feature_manifests() -> List[FeatureManifest]:
    """发现全部 feature manifest（不含 enabled 过滤，enabled 字段已注入但未排序）。"""
    return _load_feature_manifests()


def _resolve_all() -> List[FeatureManifest]:
    """发现全部 manifest（features + system）并从 FeaturesConfig 注入 enabled。

    供 `get_sorted_manifests`（拓扑序，用于 init）与 `get_route_sorted_manifests`
    （路由序，用于路由注册）共用，避免两路径分别发现导致清单漂移。
    """
    feature_manifests = _load_feature_manifests()
    system_manifest = _load_system_manifest()

    all_manifests = list(feature_manifests)
    if system_manifest is not None:
        all_manifests.append(system_manifest)

    config = get_config()
    _resolve_enabled(all_manifests, config.features)
    return all_manifests


def get_sorted_manifests() -> List[FeatureManifest]:
    """发现 + 解析 enabled + 拓扑排序，返回有序 FeatureManifest 列表（含 system manifest 在前）。

    用于初始化（`startup_manager._init_features` / `_import_models`）：按依赖拓扑序
    执行 init_hook 与 models_loader，日志呈现 user→knowledge_space→agent→… 拓扑顺序。
    """
    # system manifest 永远参与（其 enabled 也受 FeaturesConfig 控制，name="system"，
    # 默认未列出 → 启用），且其 order=0 保证排在最前。
    return _topo_sort(_resolve_all())


def get_route_sorted_manifests() -> List[FeatureManifest]:
    """发现 + 解析 enabled + 按 `route_order` 升序排序，返回 FeatureManifest 列表。

    用于路由注册（`router_manager.get_all_routers`）：路由注册顺序决定 FastAPI 对
    **同名 Pydantic 响应模型**的去重胜出者（先注册者胜），必须与 legacy
    `router_manager` 硬编码顺序逐字一致，否则 `GET /openapi.json` 中碰撞 schema
    的内容翻转，破坏前端契约。`route_order` 与 init 拓扑序 `order` 解耦：
    legacy 路由序（health,qa,user,ks,…）与 init 拓扑序（user,ks,qa,…）不同。

    排序为稳定排序；各 manifest 的 `route_order` 互不相同（0/10/…/100），无 tiebreak
    歧义。disabled manifest 不参与。
    """
    enabled = [m for m in _resolve_all() if m.enabled]
    return sorted(enabled, key=lambda m: m.route_order if m.route_order is not None else m.order)


__all__ = [
    "discover_feature_manifests",
    "get_sorted_manifests",
    "get_route_sorted_manifests",
]