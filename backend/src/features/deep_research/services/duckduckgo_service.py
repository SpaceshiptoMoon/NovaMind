"""
DuckDuckGo 搜索服务

免费、无需 API Key 的搜索服务
使用 DuckDuckGo HTML 搜索接口
"""

from typing import List, Optional
import httpx
from bs4 import BeautifulSoup
from urllib.parse import parse_qs, unquote

from novamind.features.deep_research.services.external_search_service import (
    ExternalSearchService,
    ExternalSearchResult,
)
from novamind.setting.yaml_config import get_config
from novamind.core.middleware.structured_logging import get_logger


class DuckDuckGoSearchService(ExternalSearchService):
    """
    DuckDuckGo 搜索服务

    特点：
    - 免费，无需 API Key
    - 注重隐私保护
    - 结果质量一般
    - 作为降级备选方案
    """

    def __init__(self):
        self.logger = get_logger(__name__)
        self._load_config()
        self._client: Optional[httpx.AsyncClient] = None

    def _load_config(self):
        """加载配置"""
        try:
            config = get_config()
            ddg = config.external_search.duckduckgo
            self.max_results = ddg.max_results
            self.timeout = ddg.timeout
        except Exception as e:
            self.logger.warning("加载 DuckDuckGo 配置失败，使用默认值", error=str(e))
            self.max_results = 10
            self.timeout = 15

    @property
    def provider_name(self) -> str:
        return "duckduckgo"

    def is_available(self) -> bool:
        """DuckDuckGo 始终可用（无需 API Key）"""
        return True

    async def search(
        self,
        query: str,
        max_results: int = 10,
        **kwargs,
    ) -> List[ExternalSearchResult]:
        """
        执行 DuckDuckGo 搜索

        Args:
            query: 搜索查询
            max_results: 最大结果数量

        Returns:
            搜索结果列表
        """
        max_res = max_results or self.max_results

        # DuckDuckGo HTML 搜索 URL
        url = "https://html.duckduckgo.com/html/"
        params = {
            "q": query,
            "kl": "wt-wt",  # 全球搜索
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        try:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(timeout=self.timeout)
            response = await self._client.get(url, params=params, headers=headers)
            response.raise_for_status()

            # 解析 HTML
            soup = BeautifulSoup(response.text, "html.parser")
            results = []

            # 查找搜索结果容器
            result_elements = soup.find_all("div", class_="result")[:max_res]

            for element in result_elements:
                try:
                    # 提取标题
                    title_elem = element.find("a", class_="result__a")
                    title = title_elem.get_text(strip=True) if title_elem else ""

                    # 提取 URL
                    url_elem = element.find("a", class_="result__url")
                    href = url_elem.get("href", "") if url_elem else ""
                    # DuckDuckGo 使用重定向 URL，需要提取真实 URL
                    if "uddg=" in href:
                        query_part = href.split("?", 1)[-1] if "?" in href else href
                        qs_params = parse_qs(query_part)
                        uddg_values = qs_params.get("uddg", [])
                        if uddg_values:
                            href = unquote(uddg_values[0])

                    # 提取摘要
                    snippet_elem = element.find("a", class_="result__snippet")
                    snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

                    if title and snippet:
                        results.append({
                            "title": title,
                            "url": href,
                            "content": snippet,
                            "score": 0.5,  # DuckDuckGo 不提供分数
                        })
                except Exception as e:
                    self.logger.debug("解析搜索结果失败", error=str(e))
                    continue

            self.logger.debug(
                "DuckDuckGo 搜索完成",
                query=query,
                results_count=len(results)
            )

            return self._normalize_results(results)

        except httpx.HTTPStatusError as e:
            self.logger.error(
                "DuckDuckGo 请求失败",
                query=query,
                status_code=e.response.status_code,
                error=str(e)
            )
            return []
        except httpx.TimeoutException:
            self.logger.error("DuckDuckGo 请求超时", query=query)
            return []
        except Exception as e:
            self.logger.error("DuckDuckGo 搜索异常", query=query, error=str(e))
            return []

    async def close(self) -> None:
        """关闭 HTTP 客户端连接"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
