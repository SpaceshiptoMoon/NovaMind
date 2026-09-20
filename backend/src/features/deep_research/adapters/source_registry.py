"""Deep Research 数据源注册表（feature 侧装配）。

管理"数据源类型 → 工厂"映射，供 service 装配点按启用的源类型构造绑定实例。
工厂无状态（``Callable[[SearchSourceContext], SearchSourcePort]``），租户上下文与
请求级配置全部经 ``SearchSourceContext`` 传入，每请求 build 出新 port 实例
（绑定 space_id/user_id/config），不跨请求复用。

新增一种数据源的接入点（目标：四处收敛）：

1. engines 侧：实现 ``SearchSourcePort`` 同形 search（若为 Web 类可包 ``WebSearchPort``）
2. feature 侧：本模块 ``register_source_factory(type, factory)`` 注册工厂 + 适配器
   （归一化为统一 dict 形状，见 ``engines/deep_research/sources.py`` 契约）
3. schema 侧：请求级配置段（``SourcesConfig.extra`` 透传，无需改 schema 时零改动）
4. 前端：源选择选项数组加一行

builtin 注册在模块加载期执行（``register_builtin_sources``）：internal/external
两工厂各一行。工厂抛 engines 中立异常（``WebSearchProviderNotConfiguredError`` 等）
在 ``build`` 处捕获映射为 feature API 异常（异常镜像模式）。
"""
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
        self._factories: dict[str, SourceFactory] = {}
        self._display_names: dict[str, str] = {}

    def register(self, source_type: str, factory: SourceFactory, display_name: str = "") -> None:
        """注册源工厂（幂等：同 type 重复注册覆盖）。"""
        self._factories[source_type] = factory
        if display_name:
            self._display_names[source_type] = display_name

    def get_factory(self, source_type: str) -> SourceFactory | None:
        return self._factories.get(source_type)

    def known_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def display_name(self, source_type: str) -> str:
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
    from novamind.features.deep_research.adapters.internal_search_port_adapter import (
        build_internal_source,
    )
    from novamind.features.deep_research.adapters.web_search_port_adapter import (
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
