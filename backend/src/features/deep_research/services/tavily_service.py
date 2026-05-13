"""
Tavily 搜索服务

Tavily 是专为 AI 优化的搜索引擎 API
官网: https://tavily.com
"""

from typing import List, Optional
import httpx

from src.features.deep_research.services.external_search_service import (
    ExternalSearchService,
    ExternalSearchResult,
)
from src.setting.yaml_config import get_config
from src.core.middleware.structured_logging import get_logger


class TavilySearchService(ExternalSearchService):
    """
    Tavily 搜索服务

    特点：
    - 专为 AI 设计的搜索引擎
    - 支持深度搜索模式
    - 返回结构化、高质量结果
    - 支持包含答案摘要
    """

    def __init__(self):
        self.logger = get_logger(__name__)
        self._load_config()
        self._client: Optional[httpx.AsyncClient] = None

    def _load_config(self):
        """加载配置"""
        try:
            config = get_config()
            tv = config.external_search.tavily
            self.api_key = tv.api_key
            self.max_results = tv.max_results
            self.search_depth = tv.search_depth
            self.timeout = tv.timeout
        except Exception as e:
            self.logger.warning("加载 Tavily 配置失败，使用默认值", error=str(e))
            self.api_key = ""
            self.max_results = 10
            self.search_depth = "basic"
            self.timeout = 30

    @property
    def provider_name(self) -> str:
        return "tavily"

    def is_available(self) -> bool:
        """检查 Tavily 服务是否可用"""
        return bool(self.api_key)

    async def search(
        self,
        query: str,
        max_results: int = 10,
        search_depth: Optional[str] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        include_answer: bool = True,
        include_raw_content: bool = False,
        **kwargs,
    ) -> List[ExternalSearchResult]:
        """
        执行 Tavily 搜索

        Args:
            query: 搜索查询
            max_results: 最大结果数量
            search_depth: 搜索深度（basic/advanced）
            include_domains: 包含的域名列表
            exclude_domains: 排除的域名列表
            include_answer: 是否包含 AI 生成的答案
            include_raw_content: 是否包含原始内容

        Returns:
            搜索结果列表
        """
        if not self.is_available():
            self.logger.warning("Tavily API Key 未配置，跳过外部搜索")
            return []

        url = "https://api.tavily.com/search"
        depth = search_depth or self.search_depth
        max_res = max_results or self.max_results

        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_res,
            "search_depth": depth,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
            "include_images": False,
        }

        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        try:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(timeout=self.timeout)
            response = await self._client.post(url, json=payload)
            response.raise_for_status()

            data = response.json()

            # 提取结果
            results = []

            # 如果有 AI 答案，作为第一个结果
            if include_answer and data.get("answer"):
                results.append({
                    "title": "AI Summary",
                    "url": "",
                    "content": data["answer"],
                    "score": 1.0,
                })

            # 添加搜索结果
            for item in data.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                    "score": item.get("score", 0.0),
                    "published_date": item.get("published_date"),
                })

            self.logger.debug(
                "Tavily 搜索完成",
                query=query,
                results_count=len(results)
            )

            return self._normalize_results(results)

        except httpx.HTTPStatusError as e:
            self.logger.error(
                "Tavily API 请求失败",
                query=query,
                status_code=e.response.status_code,
                error=str(e)
            )
            return []
        except httpx.TimeoutException:
            self.logger.error("Tavily API 请求超时", query=query)
            return []
        except Exception as e:
            self.logger.error("Tavily 搜索异常", query=query, error=str(e))
            return []

    async def close(self) -> None:
        """关闭 HTTP 客户端连接"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
