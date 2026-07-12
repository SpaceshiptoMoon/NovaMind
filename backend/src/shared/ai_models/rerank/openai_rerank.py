"""
通用 Rerank 客户端

覆盖所有使用标准 /rerank 端点的服务商：
硅基流动、智谱 AI、阿里云 DashScope 等。
注意：OpenAI 官方不提供 Rerank API，此客户端不调用 OpenAI 服务。
"""

from typing import List, Dict, Any

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from novamind.shared.ai_models.base_model import BaseRerank
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class CompatibleRerankClient(BaseRerank):
    """
    通用 Rerank 客户端

    注意：OpenAI 官方不提供 Rerank API，此客户端用于调用兼容 /rerank 端点的第三方服务商
    （硅基流动、智谱 AI、阿里云 DashScope 等）。

    API 格式: POST {base_url}{endpoint}
    默认 endpoint: /rerank（阿里云 DashScope 用 /reranks）

    请求体: {"model", "query", "documents", "top_n"}
    响应体（标准格式）: {"results": [{"index": int, "relevance_score": float}, ...]}
    响应体（阿里云格式）: {"output": {"results": [{"index": int, "relevance_score": float}, ...]}}
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model_name: str = "",
        timeout: int = 30,
        max_retries: int = 3,
        max_concurrent: int = 5,
        endpoint: str = "/rerank",
        **kwargs,
    ):
        """
        初始化 OpenAI 兼容 Rerank 客户端

        Args:
            api_key: API 密钥
            base_url: API 基础 URL
            model_name: 模型名称
            timeout: 超时时间（秒）
            max_retries: 最大重试次数
            max_concurrent: 最大并发数
            endpoint: 端点路径（默认 /rerank，阿里云用 /reranks）
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model_name=model_name,
            timeout=timeout,
            max_retries=max_retries,
            max_concurrent=max_concurrent,
        )
        self.endpoint = endpoint

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError)),
        reraise=True,
    )
    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        对文档列表进行重排序

        Args:
            query: 查询文本
            documents: 待排序的文档文本列表
            top_k: 返回前 K 个结果

        Returns:
            [{"index": int, "relevance_score": float}, ...]
        """
        async with self._get_semaphore():
            client = await self._get_http_client()

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            response = await client.post(
                f"{self.base_url}{self.endpoint}",
                headers=headers,
                json={
                    "model": self.model,
                    "query": query,
                    "documents": documents,
                    "top_n": top_k,
                },
            )

            response.raise_for_status()
            result = response.json()

            # 兼容两种响应格式：
            # 标准格式: {"results": [...]}
            # 阿里云格式: {"output": {"results": [...]}}
            results_data = result.get("results", None)
            if results_data is None:
                output = result.get("output", {})
                results_data = output.get("results", [])

            rerank_results = []
            for item in results_data:
                rerank_results.append({
                    "index": item["index"],
                    "relevance_score": item["relevance_score"],
                })

            logger.debug(
                "OpenAI Rerank 完成",
                model=self.model,
                endpoint=self.endpoint,
                input_count=len(documents),
                output_count=len(rerank_results),
            )

            return rerank_results
