"""Deep Research 数据源注册表：工厂每请求 build 新 port 实例，不跨请求复用；新源接入点四处收敛（engines/本模块/schema/前端）。"""
from __future__ import annotations

from collections.abc import Callable

from novamind.engines.deep_research.sources import (
    SearchSourceContext,
    SearchSourcePort,
)
from novamind.features.deep_research.exceptions import (
    SearchProviderNotConfiguredError,
)

# 源工厂签名：Context → 满足 SearchSourcePort 的实例
SourceFactory = Callable[[SearchSourceContext], SearchSourcePort]


class DataSearchSourceRegistry:
    """数据源注册表：type → (factory, display_name)。

    实例级 dict（模块级单例 ``source_registry``），工厂无状态、build 时构造绑定实例。
    """

    def __init__(self) -> None:
        """初始化空工厂与显示名映射，builtin 源在模块加载期注册。"""
        self._factories: dict[str, SourceFactory] = {}
        self._display_names: dict[str, str] = {}

    def register(self, source_type: str, factory: SourceFactory, display_name: str = "") -> None:
        """注册源工厂（幂等：同 type 重复注册覆盖）。"""
        self._factories[source_type] = factory
        if display_name:
            self._display_names[source_type] = display_name

    def get_factory(self, source_type: str) -> SourceFactory | None:
        """按源类型取注册工厂，未注册返回 None。"""
        return self._factories.get(source_type)

    def known_types(self) -> tuple[str, ...]:
        """返回已注册源类型的有序元组，供前端选项与校验。"""
        return tuple(sorted(self._factories))

    def display_name(self, source_type: str) -> str:
        """返回源类型的展示名，未注册回退为类型名本身。"""
        return self._display_names.get(source_type, source_type)

    def build(self, source_type: str, context: SearchSourceContext) -> SearchSourcePort:
        """按类型构造源 port 实例。未注册类型抛 ``SearchProviderNotConfiguredError``。"""
        factory = self._factories.get(source_type)
        if factory is None:
            raise SearchProviderNotConfiguredError(source_type)
        return factory(context)


# 模块级单例（feature 装配点与测试共用）
source_registry = DataSearchSourceRegistry()


def register_source_factory(
    source_type: str, factory: SourceFactory, display_name: str = ""
) -> None:
    """向全局注册表注册数据源工厂（新源接入点）。"""
    source_registry.register(source_type, factory, display_name)


def register_builtin_sources() -> None:
    """注册 builtin 数据源（internal/external），模块加载期执行（幂等）。"""
    from novamind.features.deep_research.services.internal_search_source import (
        build_internal_source,
    )
    from novamind.features.deep_research.services.web_search_source import (
        build_web_search_source,
    )

    register_source_factory("internal", build_internal_source, "知识库检索")
    register_source_factory("external", build_web_search_source, "网络搜索")


# 模块加载期自注册：pytest import 即生效，不动 startup_manager 单点共享文件
register_builtin_sources()


__all__ = [
    "SourceFactory",
    "DataSearchSourceRegistry",
    "source_registry",
    "register_source_factory",
    "register_builtin_sources",
]
