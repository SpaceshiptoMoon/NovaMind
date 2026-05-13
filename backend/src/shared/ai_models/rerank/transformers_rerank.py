"""
Transformers 本地 Rerank 客户端

使用 HuggingFace CrossEncoder 模型进行本地文本重排序。
"""

import asyncio
from typing import List, Dict, Any, Optional

from src.shared.ai_models.base_model import BaseRerank
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class TransformersRerankClient(BaseRerank):
    """
    Transformers 本地 Rerank 客户端

    使用 HuggingFace CrossEncoder 模型进行本地推理。
    模型延迟加载，首次调用时初始化。

    支持模型: BAAI/bge-reranker-v2-m3、cross-encoder/ms-marco-MiniLM-L-6-v2 等
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model_name: str = "BAAI/bge-reranker-v2-m3",
        timeout: int = 30,
        max_retries: int = 3,
        max_concurrent: int = 5,
        device: str | None = None,
        max_length: int = 512,
        **kwargs,
    ):
        """
        初始化 Transformers Rerank 客户端

        Args:
            api_key: 未使用（保持接口一致性）
            base_url: 未使用（保持接口一致性）
            model_name: HuggingFace 模型 ID
            timeout: 超时时间（秒）
            max_retries: 最大重试次数
            max_concurrent: 最大并发数
            device: 推理设备（None 为自动选择，可选 "cuda"、"cpu"）
            max_length: 最大序列长度
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            timeout=timeout,
            max_retries=max_retries,
            max_concurrent=max_concurrent,
        )
        self.device = device
        self.max_length = max_length
        self._model: Optional[Any] = None

    async def _load_model(self) -> Any:
        """延迟加载 CrossEncoder 模型（异步，避免阻塞事件循环）"""
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError:
                raise ImportError(
                    "使用 Transformers Rerank 需要安装 sentence-transformers: "
                    "pip install sentence-transformers"
                )

            logger.info("正在加载 Rerank 模型", model=self.model)
            loop = asyncio.get_running_loop()
            self._model = await loop.run_in_executor(
                None,
                lambda: CrossEncoder(
                    self.model,
                    device=self.device,
                    max_length=self.max_length,
                ),
            )
            logger.info("Rerank 模型加载完成", model=self.model)

        return self._model

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
            model = await self._load_model()

            # 构建查询-文档对
            pairs = [(query, doc) for doc in documents]

            # 在线程池中运行同步推理
            loop = asyncio.get_running_loop()
            scores = await loop.run_in_executor(
                None,
                lambda: model.predict(pairs),
            )

            # 按分数降序排序，取 top_k
            indexed_scores = [
                {"index": i, "relevance_score": float(scores[i])}
                for i in range(len(documents))
            ]
            indexed_scores.sort(key=lambda x: x["relevance_score"], reverse=True)

            rerank_results = indexed_scores[:top_k]

            logger.debug(
                "Transformers Rerank 完成",
                model=self.model,
                input_count=len(documents),
                output_count=len(rerank_results),
            )

            return rerank_results

    async def close(self) -> None:
        """释放模型资源"""
        if self._model is not None:
            del self._model
            self._model = None
            logger.info("Transformers Rerank 模型已释放", model=self.model)
        await super().close()
