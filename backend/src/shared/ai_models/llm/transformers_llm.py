"""
Transformers 本地推理 LLM 客户端

基于 HuggingFace Transformers 库，本地加载模型进行推理。
"""

import asyncio
from typing import AsyncGenerator, Optional

from novamind.shared.ai_models.base_model import BaseLLM
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class TransformersLLM(BaseLLM):
    """
    Transformers 本地推理 LLM 客户端

    使用 HuggingFace Transformers 库在本地加载模型进行文本生成。
    适用于无外部 API 依赖、数据隐私要求高的场景。
    """

    def __init__(
        self,
        model_name: str,
        api_key: str = "",  # 本地推理不需要 API Key
        base_url: str = "",  # 本地推理不需要 URL
        timeout: int = 300,
        max_retries: int = 0,
        max_concurrent: int = 1,  # 本地推理建议并发为 1
        device: str = "auto",  # auto / cuda / cpu /mps
        max_model_length: int = 4096,
        load_in_8bit: bool = False,
        load_in_4bit: bool = False,
        **kwargs,
    ):
        """
        初始化 Transformers LLM 客户端

        Args:
            model_name: HuggingFace 模型 ID 或本地路径
            device: 推理设备 (auto/cuda/cpu/mps)
            max_model_length: 模型最大上下文长度
            load_in_8bit: 是否使用 8-bit 量化
            load_in_4bit: 是否使用 4-bit 量化
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
        self.max_model_length = max_model_length
        self.load_in_8bit = load_in_8bit
        self.load_in_4bit = load_in_4bit

        # 延迟导入，避免未安装 transformers 时报错
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch
        except ImportError:
            raise ImportError(
                "使用 Transformers 协议需要安装: pip install transformers torch"
            )

        self._torch = torch
        self._tokenizer = None
        self._model = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure_initialized(self):
        """延迟加载模型（避免导入时即加载）"""
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            from transformers import AutoModelForCausalLM, AutoTokenizer

            logger.info(
                "正在加载 Transformers 模型",
                model=self.model,
                device=self.device,
            )

            # 在线程池中执行同步的模型加载
            loop = asyncio.get_running_loop()
            self._tokenizer = await loop.run_in_executor(
                None,
                lambda: AutoTokenizer.from_pretrained(self.model, trust_remote_code=True),
            )

            quantization_kwargs = {}
            if self.load_in_8bit:
                quantization_kwargs["load_in_8bit"] = True
            elif self.load_in_4bit:
                quantization_kwargs["load_in_4bit"] = True

            self._model = await loop.run_in_executor(
                None,
                lambda: AutoModelForCausalLM.from_pretrained(
                    self.model,
                    trust_remote_code=True,
                    device_map=self.device if not quantization_kwargs else "auto",
                    **quantization_kwargs,
                ),
            )
            self._model.eval()
            self._initialized = True

            logger.info("Transformers 模型加载完成", model=self.model)

    @staticmethod
    def _build_messages_text(prompt: str | list) -> str:
        """将 prompt 转为文本"""
        if isinstance(prompt, list):
            parts = []
            for msg in prompt:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                parts.append(f"{role}: {content}")
            return "\n".join(parts)
        return prompt

    async def generate_text(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        response_format: Optional[dict] = None,
        enable_thinking: bool = False,
    ) -> str:
        """
        本地推理生成文本
        """
        await self._ensure_initialized()

        async with self._get_semaphore():
            text = self._build_messages_text(prompt)

            # 在线程池中执行同步推理
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                self._sync_generate,
                text,
                max_tokens,
                temperature,
                top_p,
            )
            return result

    def _sync_generate(
        self, text: str, max_tokens: int, temperature: float, top_p: float
    ) -> str:
        """同步推理（在线程池中执行）"""
        with self._torch.no_grad():
            inputs = self._tokenizer(text, return_tensors="pt")
            if hasattr(inputs, "to"):
                inputs = inputs.to(self._model.device)

            outputs = self._model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature if temperature > 0 else None,
                top_p=top_p,
                do_sample=temperature > 0,
                pad_token_id=self._tokenizer.eos_token_id,
            )

            # 只取生成的新 token（去掉输入部分）
            input_length = inputs["input_ids"].shape[1]
            generated_ids = outputs[0][input_length:]
            result = self._tokenizer.decode(generated_ids, skip_special_tokens=True)

        return result

    async def generate_text_stream(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        enable_thinking: bool = False,
    ) -> AsyncGenerator[str, None]:
        """
        流式生成文本（Transformers 本地不支持真正的流式，一次性返回）
        """
        result = await self.generate_text(prompt, max_tokens, temperature, top_p)
        yield result

    async def close(self) -> None:
        """释放模型资源"""
        if self._model is not None:
            del self._model
            del self._tokenizer
            self._model = None
            self._tokenizer = None
            self._initialized = False

            # 尝试释放 GPU 显存
            if self._torch.cuda.is_available():
                self._torch.cuda.empty_cache()

            logger.info("Transformers 模型资源已释放", model=self.model)
