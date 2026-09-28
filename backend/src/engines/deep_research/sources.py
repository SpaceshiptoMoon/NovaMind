"""Deep Research 可插拔数据源抽象：所有检索源经同一 SearchSourcePort 注入引擎，搜索循环对源数量无感知，单源失败降级不中断。
结果 dict 契约：content 与 score 必填；url/title 与 chunk_id/kb_id 等标识可选，供去重与引用。
本模块不得 import novamind.features.* / novamind.setting.*（引擎层边界）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SearchSourcePort(Protocol):
    """统一检索源端口：任意数据源的引擎侧接口。

    与 ``InternalSearchPort`` 同形（``search(query, *, top_k) -> List[Dict]``），
    故 ``HostInternalSearchPort`` 天然满足；外部 Web 源由 feature 适配器
    （WebSearchSourceAdapter）包装 ``WebSearchPort`` 抹平签名与归一化差异。
    """

    async def search(self, query: str, *, top_k: int) -> list[dict[str, Any]]:
        """执行检索，返回统一 dict 形状结果列表（见模块 docstring 契约）。"""
        ...


@dataclass
class SearchSourceContext:
    """源工厂入参（纯 dataclass，无 feature DTO）。

    工厂据此构造绑定租户上下文与请求级配置的 port 实例：

    - ``space_id``/``user_id``：多租户上下文（内部源 KB 归属校验用）
    - ``config``：该源的请求级配置段（schema dump 的 dict，如 kb_ids/top_k 或
      provider/max_results）；未来新源的配置经 schema ``sources.extra`` 透传，
      引擎与注册表不感知具体字段
    - ``deps``：宿主依赖容器（如已装配的 ``RetrievalPort``、logger）。部分源的
      工厂需要宿主运行时对象（内部源复用 service 的检索 port），经此注入而非
      工厂内自建；engines 层仅透传，不感知其内容
    """

    space_id: int
    user_id: int
    config: dict[str, Any]
    deps: dict[str, Any]


@dataclass
class SearchSourceBinding:
    """已启用的数据源绑定（引擎迭代循环的消费单元）。

    - ``source_type``：源类型标识（str 承载，未登记 ``SourceType`` 的新源免改引擎）
    - ``port``：满足 ``SearchSourcePort`` 的检索实现
    - ``top_k``：per-source 返回上限（internal 取检索 top_k，external 取
      max_results），装配期决定，引擎不读 params 里的 per-source 数量
    """

    source_type: str
    port: SearchSourcePort
    top_k: int


__all__ = ["SearchSourcePort", "SearchSourceContext", "SearchSourceBinding"]
