"""公式识别模型：pix2text-mfr（TrOCR 架构），equation 区域图片 → LaTeX。

模型：``breezedeus/pix2text-mfr``（DeiT encoder 12 层 + TrOCR decoder 6 层，
词表仅 1200，自带 fp32 ONNX 权重，112 MB）。下载后做 INT8 动态量化
（112 MB → 29.9 MB），推理优先用 INT8；量化需 `onnx` 包（deepdoc-vision
extras 提供），缺失时跳过并继续用 fp32，不阻断。

纯 onnxruntime + tokenizers 推理，零 PyTorch/transformers 依赖。2026-09-15
spike 实测：INT8 与 fp32 输出 76% 逐字一致（编辑距离 6%，差异均为渲染等价的
表面 token），62 个真实论文公式质量可用。

模型缺失时的降级口径与 layout/text_concat 一致：WARNING 可见 + 跳过公式识别
（公式区域保留 OCR 文本），不阻断解析。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from novamind.engines.document.integrations.deepdoc.vision.model_manager import (
    default_model_dir,
    download_hf_files,
)
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

FORMULA_MODEL_REPO_ID = os.getenv(
    "DEEPDOC_FORMULA_MODEL_REPO_ID",
    "breezedeus/pix2text-mfr",
)
# fp32 权重与分词器（下载源）；INT8 量化版由 download_formula_model 本地生成。
FORMULA_MODEL_FILES = (
    "encoder_model.onnx",
    "decoder_model.onnx",
    "tokenizer.json",
)
FORMULA_INT8_FILES = (
    "encoder_model_int8.onnx",
    "decoder_model_int8.onnx",
)

# 推理常量（pix2text-mfr config.json / preprocessor_config.json 固化值）。
FORMULA_IMAGE_SIZE = 384
FORMULA_EOS_TOKEN_ID = 2  # </s>，同时是 decoder_start_token_id
FORMULA_MAX_NEW_TOKENS = 512  # max_position_embeddings

_LOADED_RECOGNIZERS: dict[str, FormulaRecognizer] = {}


def default_formula_model_dir() -> Path:
    env_dir = os.getenv("DEEPDOC_FORMULA_MODEL_DIR")
    if env_dir:
        return Path(env_dir)
    return default_model_dir() / "pix2text_mfr"


def get_formula_model_status(model_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    base_dir = Path(model_dir) if model_dir is not None else default_formula_model_dir()
    missing = [name for name in FORMULA_MODEL_FILES if not (base_dir / name).exists()]
    quantized = all((base_dir / name).exists() for name in FORMULA_INT8_FILES)
    return {
        "model_dir": str(base_dir),
        "repo_id": FORMULA_MODEL_REPO_ID,
        "files": list(FORMULA_MODEL_FILES),
        "missing": missing,
        "available": not missing,
        "quantized": quantized,
        "precision": "int8" if quantized else ("fp32" if not missing else None),
    }


def ensure_formula_model_available(model_dir: str | os.PathLike[str] | None = None) -> Path:
    status = get_formula_model_status(model_dir)
    if not status["available"]:
        raise FileNotFoundError(
            f"DeepDoc formula model is missing under '{status['model_dir']}': "
            f"expected {', '.join(status['missing'])}"
        )
    return Path(status["model_dir"])


def _quantize_to_int8(model_dir: Path) -> bool:
    """把 fp32 ONNX 权重做 INT8 动态量化（仅压权重、激活保持 fp32）。

    幂等：INT8 文件已存在直接返回。`onnx` 包缺失或量化异常时 INFO 跳过，
    运行时回退 fp32——量化是体积优化，不是可用性前提。
    """
    if os.getenv("DEEPDOC_FORMULA_QUANTIZE", "1") == "0":
        return False
    if all((model_dir / name).exists() for name in FORMULA_INT8_FILES):
        return True
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
    except ImportError:
        logger.info(
            "DeepDoc 公式模型 INT8 量化跳过（缺 onnx 包，回退 fp32 推理）",
            model_dir=str(model_dir),
        )
        return False
    try:
        for name in ("encoder_model.onnx", "decoder_model.onnx"):
            quantize_dynamic(
                model_input=str(model_dir / name),
                model_output=str(model_dir / name.replace(".onnx", "_int8.onnx")),
                weight_type=QuantType.QInt8,
                per_channel=True,
            )
    except Exception as exc:
        logger.warning(
            "DeepDoc 公式模型 INT8 量化失败（回退 fp32 推理）",
            error=str(exc),
            model_dir=str(model_dir),
        )
        return False
    return True


def download_formula_model(model_dir: str | os.PathLike[str] | None = None) -> Path:
    base_dir = Path(model_dir) if model_dir is not None else default_formula_model_dir()
    # 统一走 model_manager 共享下载实现（镜像直链 / 官方 snapshot+直链兜底，幂等）
    download_hf_files(base_dir, FORMULA_MODEL_REPO_ID, list(FORMULA_MODEL_FILES))
    _quantize_to_int8(base_dir)
    return base_dir


class FormulaRecognizer:
    """pix2text-mfr 推理器：公式裁剪图（H×W×3 uint8）→ LaTeX 字符串。

    生成循环为无 KV cache 的朴素贪心自回归（decoder 每步全量重算），
    公式长度通常 <200 token，CPU 上单公式秒级（INT8 实测 ~7s/长公式）。
    """

    def __init__(self, model_dir: str | os.PathLike[str] | None = None):
        base_dir = ensure_formula_model_available(model_dir)
        import onnxruntime as ort
        from tokenizers import Tokenizer

        status = get_formula_model_status(base_dir)
        precision = status["precision"]
        suffix = "_int8" if precision == "int8" else ""
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.encoder = ort.InferenceSession(
            str(base_dir / f"encoder_model{suffix}.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        self.decoder = ort.InferenceSession(
            str(base_dir / f"decoder_model{suffix}.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        self.tokenizer = Tokenizer.from_file(str(base_dir / "tokenizer.json"))
        self.precision = precision
        self.model_dir = str(base_dir)

    @staticmethod
    def preprocess(crop: np.ndarray) -> np.ndarray:
        """H×W×3 uint8 → [1,3,384,384] float32，(x/255−0.5)/0.5 归一化。

        与 pix2text-mfr 的 TrOCRProcessor（DeiTImageProcessor）一致：
        整图 resize 384×384（公式裁剪图本身已带 padding，不保纵横比）。
        """
        from PIL import Image

        img = Image.fromarray(np.asarray(crop)).convert("RGB").resize(
            (FORMULA_IMAGE_SIZE, FORMULA_IMAGE_SIZE), Image.BILINEAR
        )
        arr = np.asarray(img, dtype=np.float32) / 255.0
        arr = (arr - 0.5) / 0.5
        return arr.transpose(2, 0, 1)[np.newaxis, ...].astype(np.float32)

    def recognize(self, crop: np.ndarray) -> str:
        """公式裁剪图 → LaTeX（无 $ 包裹，由调用方决定行内/块级格式）。"""
        hidden = self.encoder.run(None, {"pixel_values": self.preprocess(crop)})[0]
        tokens: list[int] = [FORMULA_EOS_TOKEN_ID]  # decoder_start_token_id = </s>
        for _ in range(FORMULA_MAX_NEW_TOKENS):
            input_ids = np.asarray([tokens], dtype=np.int64)
            logits = self.decoder.run(
                None, {"input_ids": input_ids, "encoder_hidden_states": hidden}
            )[0]
            next_id = int(np.argmax(logits[0, -1]))
            if next_id == FORMULA_EOS_TOKEN_ID:
                break
            tokens.append(next_id)
        return self.tokenizer.decode(tokens[1:], skip_special_tokens=True).strip()


def load_formula_recognizer(model_dir: str | os.PathLike[str] | None = None) -> FormulaRecognizer:
    base_dir = Path(model_dir) if model_dir is not None else default_formula_model_dir()
    cache_key = str(base_dir)
    cached = _LOADED_RECOGNIZERS.get(cache_key)
    if cached is not None:
        return cached
    recognizer = FormulaRecognizer(base_dir)
    _LOADED_RECOGNIZERS[cache_key] = recognizer
    return recognizer