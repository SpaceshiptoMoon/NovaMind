"""deep_research 宿主适配器层。

把 deep_research 的搜索服务实现桥接到引擎端口（如 ``WebSearchPort``）。
deep_research 拥有搜索服务实现（Tavily/DuckDuckGo/Serpapi），故同时拥有其端口
适配器——这是 DDD 正确归属。其他 feature（agent / app-resume）经依赖注入消费
``WebSearchPort``，装配时从本适配器取实现，避免 feature 间直接 import
deep_research 内部服务。
"""