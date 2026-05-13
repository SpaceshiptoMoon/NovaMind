"""
SerpAPI 搜索服务

SerpAPI 提供 Google 搜索结果 API
官网: https://serpapi.com
"""

from typing import List, Optional
import httpx

from src.features.deep_research.services.external_search_service import (
    ExternalSearchService,
    ExternalSearchResult,
)
from src.setting.yaml_config import get_config
from src.core.middleware.structured_logging import get_logger


class SerpAPISearchService(ExternalSearchService):
    """
    SerpAPI 搜索服务

    特点：
    - 提供真实 Google 搜索结果
    - 支持多种搜索引擎（Google、Bing、Yahoo 等）
    - 返回结构化数据
    - 支持位置、日期等过滤
    """

    def __init__(self):
        self.logger = get_logger(__name__)
        self._load_config()
        self._client: Optional[httpx.AsyncClient] = None

    def _load_config(self):
        """加载配置"""
        try:
            config = get_config()
            sa = config.external_search.serpapi
            self.api_key = sa.api_key
            self.max_results = sa.max_results
            self.timeout = sa.timeout
            self.engine = sa.engine
        except Exception as e:
            self.logger.warning("加载 SerpAPI 配置失败，使用默认值", error=str(e))
            self.api_key = ""
            self.max_results = 10
            self.timeout = 30
            self.engine = "google"

    @property
    def provider_name(self) -> str:
        return "serpapi"

    def is_available(self) -> bool:
        """检查 SerpAPI 服务是否可用"""
        return bool(self.api_key)

    async def search(
        self,
        query: str,
        max_results: int = 10,
        engine: Optional[str] = None,
        location: Optional[str] = None,
        **kwargs,
    ) -> List[ExternalSearchResult]:
        """
        执行 SerpAPI 搜索

        Args:
            query: 搜索查询
            max_results: 最大结果数量
            engine: 搜索引擎（google/bing/yahoo）
            location: 位置（用于本地搜索）

        Returns:
            搜索结果列表
        """
        if not self.is_available():
            self.logger.warning("SerpAPI API Key 未配置，跳过外部搜索")
            return []

        url = "https://serpapi.com/search"
        search_engine = engine or self.engine
        max_res = max_results or self.max_results

        params = {
            "api_key": self.api_key,
            "q": query,
            "engine": search_engine,
            "num": max_res,
        }

        if location:
            params["location"] = location

        try:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(timeout=self.timeout)
            response = await self._client.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            # 提取有机搜索结果
            results = []

            # 添加知识图谱信息（如果有）
            if data.get("knowledge_graph"):
                kg = data["knowledge_graph"]
                results.append({
                    "title": kg.get("title", ""),
                    "url": kg.get("website", ""),
                    "content": kg.get("description", ""),
                    "score": 1.0,
                })

            # 添加有机搜索结果
            for item in data.get("organic_results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "content": item.get("snippet", ""),
                    "score": 0.8,  # SerpAPI 不提供分数，使用固定值
                    "published_date": item.get("date"),
                })

            # 添加相关问题（如果有）
            for item in data.get("related_questions", [])[:3]:
                results.append({
                    "title": item.get("question", ""),
                    "url": "",
                    "content": item.get("snippet", ""),
                    "score": 0.6,
                })

            self.logger.debug(
                "SerpAPI 搜索完成",
                query=query,
                results_count=len(results)
            )

            return self._normalize_results(results)

        except httpx.HTTPStatusError as e:
            self.logger.error(
                "SerpAPI API 请求失败",
                query=query,
                status_code=e.response.status_code,
                error=str(e)
            )
            return []
        except httpx.TimeoutException:
            self.logger.error("SerpAPI API 请求超时", query=query)
            return []
        except Exception as e:
            self.logger.error("SerpAPI 搜索异常", query=query, error=str(e))
            return []

    async def close(self) -> None:
        """关闭 HTTP 客户端连接"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
