"""
Transformers 本地推理 Embedding 客户端

基于 HuggingFace Transformers / sentence-transformers，本地加载模型生成向量。
"""

import asyncio

from novamind.shared.ai_models.base_model import BaseEmbedding
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class TransformersEmbedding(BaseEmbedding):
    """
    Transformers 本地推理 Embedding 客户端

    使用 sentence-transformers 或 transformers 库在本地加载模型生成向量。
    适用于无外部 API 依赖、数据隐私要求高的场景。
    """

    def __init__(
        self,
        model_name: str,
        api_key: str = "",
        base_url: str = "",
        expected_dimension: int | None = None,
        timeout: int = 300,
        max_retries: int = 0,
        max_concurrent: int = 1,
        device: str = "auto",
        normalize_embeddings: bool = True,
        **kwargs,
    ):
        """
        初始化 Transformers Embedding 客户端

        Args:
            model_name: HuggingFace 模型 ID 或本地路径
            device: 推理设备 (auto/cuda/cpu/mps)
            normalize_embeddings: 是否归一化向量
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            expected_dimension=expected_dimension,
            timeout=timeout,
            max_retries=max_retries,
            max_concurrent=max_concurrent,
        )
        self.device = device
        self.normalize_embeddings = normalize_embeddings

        self._model = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure_initialized(self):
        """延迟加载模型"""
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise ImportError(
                    "使用 Transformers Embedding 需要安装: "
                    "pip install sentence-transformers torch"
                )

            logger.info("正在加载 Embedding 模型", model=self.model)

            loop = asyncio.get_running_loop()
            self._model = await loop.run_in_executor(
                None,
                lambda: SentenceTransformer(
                    self.model,
                    device=self.device,
                ),
            )
            self._initialized = True

        logger.info("Embedding 模型加载完成", model=self.model)

    @staticmethod
    def _validate_dimension(embedding: list[float], expected: int | None) -> None:
        """验证向量维度"""
        if expected is not None:
            actual_dim = len(embedding)
            if actual_dim != expected:
                raise ValueError(
                    f"向量维度不匹配: 期望 {expected} 维, 实际 {actual_dim} 维"
                )

    async def generate_embedding(self, text: str) -> list[float]:
        """生成单个文本的嵌入向量"""
        await self._ensure_initialized()

        async with self._get_semaphore():
            loop = asyncio.get_running_loop()
            embedding = await loop.run_in_executor(
                None,
                lambda: self._model.encode(
                    text,
                    normalize_embeddings=self.normalize_embeddings,
                ).tolist(),
            )

            self._validate_dimension(embedding, self.expected_dimension)
            return embedding

    async def generate_embeddings_batch(
        self, texts: list[str], batch_size: int = 32
    ) -> list[list[float]]:
        """批量生成文本嵌入向量"""
        if not texts:
            return []

        await self._ensure_initialized()

        async with self._get_semaphore():
            loop = asyncio.get_running_loop()
            embeddings = await loop.run_in_executor(
                None,
                lambda: self._model.encode(
                    texts,
                    batch_size=batch_size,
                    normalize_embeddings=self.normalize_embeddings,
                    show_progress_bar=False,
                ).tolist(),
            )

            for emb in embeddings:
                self._validate_dimension(emb, self.expected_dimension)

            return embeddings

    async def close(self) -> None:
        """释放模型资源"""
        if self._model is not None:
            del self._model
            self._model = None
            self._initialized = False

            # 尝试释放 GPU 显存
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

            logger.info("Embedding 模型资源已释放", model=self.model)
