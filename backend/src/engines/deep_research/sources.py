"""
Deep Research 数据源抽象（可插拔检索源）。

引擎侧统一检索源协议：所有数据源（内部知识库/外部 Web/未来 Confluence、DB 直查、
MCP 数据源等）经同一 ``SearchSourcePort`` 注入引擎，``search`` 迭代循环对源数量
无感知——每轮迭代逐 ``SearchSourceBinding`` 查询、去重，单源失败降级不中断。

本模块不得 import ``novamind.features.*`` / ``novamind.setting.*`` /
（R1 无环约束下的引擎层边界说明，端口化已在迁移批次 3 移除）。

结果 dict 形状契约（与纯函数 ``deduplicate_results`` / ``extract_citations`` /
``format_search_context`` 的 ``.get`` 宽松访问一致）：

- 必填：``content``（str）、``score``（float）
- 标识：``source_type``（str，建议用 ``types.SourceType`` 值；新源可自定义字符串，
  引擎不枚举校验）
- 可选：``url`` / ``title``（外部源去重与引用）；``chunk_id`` / ``document_id`` /
  ``document_name`` / ``kb_id`` / ``kb_name``（内部源去重与引用兜底）

装配链路（host 侧）：feature 装配点按启用的源类型逐个调注册表工厂
``factory(SearchSourceContext) -> SearchSourcePort``，构造 ``SearchSourceBinding``
列表注入 ``DeepResearchEngine.search``；工厂无状态、每请求构造绑定实例（租户上下文
经 Context 传入，引擎不持有）。
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
