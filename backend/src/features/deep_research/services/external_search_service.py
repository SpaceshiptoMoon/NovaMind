"""
外部搜索服务抽象基类

定义统一的外部搜索接口
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExternalSearchResult:
    """外部搜索结果"""
    title: str                              # 标题
    url: str                                # URL
    content: str                            # 内容摘要
    score: float = 0.0                      # 相关性分数
    published_date: Optional[str] = None    # 发布日期
    source: str = ""                        # 来源


class ExternalSearchService(ABC):
    """
    外部搜索服务抽象基类

    所有外部搜索服务商需要实现此接口
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """服务商名称"""
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 10,
        **kwargs,
    ) -> List[ExternalSearchResult]:
        """
        执行搜索

        Args:
            query: 搜索查询
            max_results: 最大结果数量
            **kwargs: 额外参数

        Returns:
            搜索结果列表
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        检查服务是否可用

        Returns:
            是否可用
        """
        pass

    def _normalize_results(
        self,
        raw_results: List[Dict[str, Any]]
    ) -> List[ExternalSearchResult]:
        """
        标准化搜索结果

        Args:
            raw_results: 原始结果列表

        Returns:
            标准化后的结果列表
        """
        normalized = []
        for r in raw_results:
            try:
                result = ExternalSearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", r.get("link", "")),
                    content=r.get("content", r.get("snippet", r.get("body", ""))),
                    score=float(r.get("score", 0.0)),
                    published_date=r.get("published_date"),
                    source=self.provider_name,
                )
                normalized.append(result)
            except Exception:
                logger.warning("标准化搜索结果条目失败，跳过", raw_result=r, exc_info=True)
                continue
        return normalized
