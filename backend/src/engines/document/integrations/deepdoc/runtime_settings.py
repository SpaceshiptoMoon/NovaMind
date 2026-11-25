"""DeepDoc 引擎运行时配置单一注入点（发包模式：引擎不再直读进程环境）。

此前 8 个模块共 25 处 ``os.getenv`` 直读进程环境（OCR 线程数/显存、模型
目录与仓库、镜像清单、checksum 逃生门、页批大小等）——引擎与部署环境
强耦合，无法作为独立包复用。收敛为本模块后：

- ``load_settings(env)``：纯函数，从任意 env 映射解析（默认 ``os.environ``），
  保留既有环境变量名与默认值——存量部署零破坏；
- ``set_settings()``：宿主注入口（启动期从 YAML/部署配置构造后覆盖，
  满足「参数由调用方透传」）；
- ``get_settings()``：引擎内唯一允许的消费口（无缓存现读进程环境，
  运行期环境变更即时生效；宿主注入后 env 不再参与）。

边界：``vendor/``（逐字拷贝）内的环境变量读取不在本收口范围，随上游
升级单独处理。
"""
from __future__ import annotations

import functools
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from novamind.shared.logging import get_logger

_logger = get_logger(__name__)


def _env_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(env: Mapping[str, str], key: str, default: bool, *, off: str = "false") -> bool:
    """「出现且 ≠ off 值」为开（TABLE_AUTO_ROTATE=false 关 等关开关型）。

    比较大小写不敏感（原散落实现含 ``.lower()``——``False``/``FALSE``
    与 ``false`` 同义，红队 P1-1 大小写回归修复）。
    """
    raw = (env.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw != off


def _env_flag(env: Mapping[str, str], key: str, default: bool, *, on: str = "1") -> bool:
    """「= on 值」才为开（SKIP_CHECKSUM=1 等''=1 开''型）。"""
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    return raw == on


@dataclass(frozen=True)
class DeepDocSettings:
    """DeepDoc 引擎运行时参数（全部可由宿主注入覆盖）。

    语义与既有环境变量一一对应（变量名见各字段注释），默认值即原
    ``os.getenv`` 的缺省值——存量部署行为零变化。
    """

    # ── 模型源与目录（vision/model_manager）──
    model_repo_id: str = "InfiniFlow/deepdoc"          # DEEPDOC_MODEL_REPO_ID
    model_dir: str = ""                                 # DEEPDOC_MODEL_DIR（空=仓库根 .cache/deepdoc）
    hf_endpoint: str = "https://huggingface.co"         # HF_ENDPOINT
    mirrors_json: str = ""                              # DEEPDOC_MIRRORS（JSON 降级源清单）
    disable_mirrors: bool = False                       # DEEPDOC_DISABLE_MIRRORS=1（降级换源逃生门）
    skip_checksum: bool = False                         # DEEPDOC_SKIP_MODEL_CHECKSUM=1
    hf_etag_timeout: int = 60                           # DEEPDOC_HF_ETAG_TIMEOUT
    hf_max_workers: int = 4                             # DEEPDOC_HF_MAX_WORKERS

    # ── 设备策略（唯一探针 resolve_device_policy）──
    device: str = "auto"                                # DEEPDOC_DEVICE（auto/cuda/cpu）
    install_flavor: str = ""                            # DEVICE_FLAVOR（安装期构建标记 gpu/cpu，仅用于一致性对账）

    # ── OCR ONNX 运行时（vision/ocr）──
    ocr_intra_op_threads: int = 2                       # OCR_INTRA_OP_NUM_THREADS
    ocr_inter_op_threads: int = 2                       # OCR_INTER_OP_NUM_THREADS
    ocr_gpu_mem_limit_mb: int = 2048                    # OCR_GPU_MEM_LIMIT_MB
    ocr_arena_extend_strategy: str = "kNextPowerOfTwo"  # OCR_ARENA_EXTEND_STRATEGY
    ocr_gpu_arena_shrinkage: bool = False               # OCR_GPUMEM_ARENA_SHRINKAGE=1
    parallel_devices: int = 0                           # PARALLEL_DEVICES

    # ── 公式识别 / 段落合并模型 ──
    formula_model_repo_id: str = "breezedeus/pix2text-mfr"   # DEEPDOC_FORMULA_MODEL_REPO_ID
    formula_model_dir: str = ""                              # DEEPDOC_FORMULA_MODEL_DIR
    formula_quantize: bool = True                            # DEEPDOC_FORMULA_QUANTIZE=0 关
    text_concat_model_repo_id: str = "InfiniFlow/text_concat_xgb_v1.0"  # DEEPDOC_TEXT_CONCAT_MODEL_REPO_ID
    text_concat_model_dir: str = ""                          # DEEPDOC_TEXT_CONCAT_MODEL_DIR

    # ── 解析行为（parsers/pdf / pdf_artifacts）──
    text_page_zoom: int = 0                             # DEEPDOC_TEXT_PAGE_ZOOM（0=自动，合法 2-4 由消费方校验）
    render_window_size: int = 0                         # DEEPDOC_RENDER_WINDOW_SIZE（0=默认窗）
    table_auto_rotate: bool = True                      # TABLE_AUTO_ROTATE=false 关
    crosspage_composite: bool = True                    # DEEPDOC_CROSSPAGE_COMPOSITE=false 关
    # PDF_PARSER_PAGE_BATCH_SIZE——注意：当前唯一消费者在 vendored
    # pdf_parser（vendor 豁免直读 env），本字段为接缝预留，注入暂无行为效果
    page_batch_size: int = 50


def load_settings(env: Mapping[str, str] | None = None) -> DeepDocSettings:
    """从 env 映射解析 DeepDocSettings（默认 ``os.environ``）。

    Args:
        env: 环境映射；None 时读进程环境。纯函数——测试可传 dict 注入。

    Returns:
        解析后的冻结配置。非法数值一律回退默认（与原散落实现的容错一致）。
    """
    e = env if env is not None else os.environ
    device_raw = (e.get("DEEPDOC_DEVICE") or "").strip().lower()
    flavor_raw = (e.get("DEVICE_FLAVOR") or "").strip().lower()
    return DeepDocSettings(
        model_repo_id=(e.get("DEEPDOC_MODEL_REPO_ID") or DeepDocSettings.model_repo_id),
        model_dir=(e.get("DEEPDOC_MODEL_DIR") or "").strip(),
        hf_endpoint=(e.get("HF_ENDPOINT") or DeepDocSettings.hf_endpoint).rstrip("/"),
        mirrors_json=(e.get("DEEPDOC_MIRRORS") or "").strip(),
        disable_mirrors=_env_flag(e, "DEEPDOC_DISABLE_MIRRORS", False),
        skip_checksum=_env_flag(e, "DEEPDOC_SKIP_MODEL_CHECKSUM", False),
        hf_etag_timeout=_env_int(e, "DEEPDOC_HF_ETAG_TIMEOUT", 60),
        hf_max_workers=_env_int(e, "DEEPDOC_HF_MAX_WORKERS", 4),
        device=(device_raw if device_raw in ("auto", "cuda", "cpu") else "auto"),
        # Dockerfile 以 ENV DEVICE_FLAVOR=${VISION_GPU} 传 true/false，归一为 gpu/cpu
        install_flavor={"true": "gpu", "gpu": "gpu", "false": "cpu", "cpu": "cpu"}.get(flavor_raw, flavor_raw),
        ocr_intra_op_threads=_env_int(e, "OCR_INTRA_OP_NUM_THREADS", 2),
        ocr_inter_op_threads=_env_int(e, "OCR_INTER_OP_NUM_THREADS", 2),
        ocr_gpu_mem_limit_mb=_env_int(e, "OCR_GPU_MEM_LIMIT_MB", 2048),
        ocr_arena_extend_strategy=(
            e.get("OCR_ARENA_EXTEND_STRATEGY") or DeepDocSettings.ocr_arena_extend_strategy
        ),
        ocr_gpu_arena_shrinkage=_env_flag(e, "OCR_GPUMEM_ARENA_SHRINKAGE", False),
        parallel_devices=_env_int(e, "PARALLEL_DEVICES", 0),
        formula_model_repo_id=(
            e.get("DEEPDOC_FORMULA_MODEL_REPO_ID") or DeepDocSettings.formula_model_repo_id
        ),
        formula_model_dir=(e.get("DEEPDOC_FORMULA_MODEL_DIR") or "").strip(),
        formula_quantize=_env_bool(e, "DEEPDOC_FORMULA_QUANTIZE", True, off="0"),
        text_concat_model_repo_id=(
            e.get("DEEPDOC_TEXT_CONCAT_MODEL_REPO_ID") or DeepDocSettings.text_concat_model_repo_id
        ),
        text_concat_model_dir=(e.get("DEEPDOC_TEXT_CONCAT_MODEL_DIR") or "").strip(),
        text_page_zoom=_env_int(e, "DEEPDOC_TEXT_PAGE_ZOOM", 0),
        render_window_size=_env_int(e, "DEEPDOC_RENDER_WINDOW_SIZE", 0),
        table_auto_rotate=_env_bool(e, "TABLE_AUTO_ROTATE", True, off="false"),
        crosspage_composite=_env_bool(e, "DEEPDOC_CROSSPAGE_COMPOSITE", True, off="false"),
        page_batch_size=_env_int(e, "PDF_PARSER_PAGE_BATCH_SIZE", 50),
    )


_override: DeepDocSettings | None = None


def get_settings() -> DeepDocSettings:
    """引擎内唯一消费口：宿主注入优先，否则按进程环境现读。

    不缓存——env 现读只是二十余次 dict 查询（无性能意义），不缓存则
    ``monkeypatch.setenv`` 等运行期环境变更即时生效（存量测试依赖此语义）；
    宿主经 ``set_settings`` 注入后 env 不再参与（透传语义）。
    """
    if _override is not None:
        return _override
    return load_settings()


def set_settings(settings: DeepDocSettings) -> None:
    """宿主注入口：启动期以部署配置覆盖（透传模式——宿主是配置事实来源）。

    注入后进程环境变量不再参与解析；``reset_settings()`` 恢复环境解析。
    """
    global _override
    _override = settings


def with_overrides(**overrides: Any) -> DeepDocSettings:
    """以当前配置为基准派生覆盖副本（宿主局部调参便捷方法）。"""
    return replace(get_settings(), **overrides)


def reset_settings() -> None:
    """清空宿主注入（测试隔离用：恢复按进程环境解析）。"""
    global _override
    _override = None


# ==================== 唯一设备探针 ====================
# 全系统标准：所有本地模型（DeepDoc OCR/layout/TSR/公式、本地 ASR）的
# GPU/CPU 判定只允许来自 resolve_device_policy()——一个函数、一次探测、
# 一个结论；任何组件不得自带第二套探针（判定不一致即是 bug）。
# 安装期（deploy 脚本）用同一判据决定镜像装 GPU/CPU 版依赖，构建结果经
# DEVICE_FLAVOR 环境变量回传，首次判定时与运行时结论对账——不一致仅告警，
# 行为一律以运行时判定为准（失败方向安全：无卡机器绝不尝试 GPU）。


def _compute_device_policy() -> str:
    """执行实际探测，返回 "cuda" 或 "cpu"（判定原因记入日志）。"""
    settings = get_settings()
    if settings.device == "cpu":
        _logger.info("设备探针：DEEPDOC_DEVICE=cpu 显式强制 → CPU", reason="forced_cpu")
        return "cpu"
    if settings.device == "cuda":
        # 显式指定：跳过 ORT/torch/容量检查；ORT 会话级 [CUDA, CPU] 列表兜底，
        # 无 CUDA 构建时 ORT 自行回落 CPU 并告警，不会抛错
        _logger.info("设备探针：DEEPDOC_DEVICE=cuda 显式指定（跳过探测）→ CUDA", reason="forced_cuda")
        return "cuda"
    # auto：按判定链逐项检查
    try:
        import onnxruntime as ort

        providers = ort.get_available_providers()
    except Exception as exc:  # noqa: BLE001 - 探测异常等价于无 GPU
        _logger.info("设备探针：onnxruntime 不可用 → CPU", reason="ort_import_failed", error=str(exc))
        return "cpu"
    if "CUDAExecutionProvider" not in providers:
        _logger.info(
            "设备探针：onnxruntime 为 CPU 构建（无 CUDAExecutionProvider）→ CPU",
            reason="ort_cpu_build",
            providers=providers,
        )
        return "cpu"
    try:
        import torch

        if not torch.cuda.is_available():
            _logger.info("设备探针：torch 无可见 CUDA 设备 → CPU", reason="torch_no_cuda")
            return "cpu"
        free_bytes, total_bytes = torch.cuda.mem_get_info(0)
    except Exception as exc:  # noqa: BLE001 - 探测异常等价于无 GPU
        _logger.info("设备探针：torch CUDA 探测失败 → CPU", reason="torch_probe_failed", error=str(exc))
        return "cpu"
    need_bytes = max(settings.ocr_gpu_mem_limit_mb, 0) * 1024 * 1024
    if free_bytes < need_bytes:
        _logger.warning(
            "设备探针：CUDA 空闲显存不足 → CPU",
            reason="insufficient_vram",
            free_mb=round(free_bytes / 1048576),
            need_mb=round(need_bytes / 1048576),
        )
        return "cpu"
    _logger.info(
        "设备探针：CUDA 可用 → GPU",
        reason="cuda_ok",
        free_mb=round(free_bytes / 1048576),
        total_mb=round(total_bytes / 1048576),
    )
    return "cuda"


def _compare_install_flavor(policy: str) -> None:
    """安装期构建标记（DEVICE_FLAVOR）与运行时判定对账：一致记 info，不一致告警。

    只对账不裁决——行为永远以运行时判定为准：GPU flavor 拿到无卡机器自动
    落 CPU（探针保证）；CPU flavor 拿到有卡机器维持 CPU 并提示重建。
    """
    flavor = get_settings().install_flavor
    if not flavor:
        return
    # 词汇归一：flavor 侧是 gpu/cpu（安装口径），判定侧是 cuda/cpu（运行时口径）
    flavor_as_policy = {"gpu": "cuda", "cuda": "cuda", "cpu": "cpu"}.get(flavor, flavor)
    if flavor_as_policy == policy:
        _logger.info("设备对账：安装 flavor ↔ 运行时判定一致", flavor=flavor, policy=policy)
    else:
        _logger.warning(
            "设备对账：安装 flavor 与运行时判定不一致，以运行时判定为准",
            flavor=flavor,
            policy=policy,
            hint="如在有 NVIDIA GPU 的目标机部署，请重新构建以启用 GPU 依赖",
        )


@functools.lru_cache(maxsize=1)
def resolve_device_policy() -> str:
    """全系统唯一设备探针：返回 "cuda" 或 "cpu"（进程级缓存，判定原因记日志一次）。

    所有本地模型组件的 GPU/CPU 决策必须经本函数；首次调用时与安装期
    DEVICE_FLAVOR 标记对账。测试用 ``reset_device_policy()`` 清缓存。
    """
    policy = _compute_device_policy()
    _compare_install_flavor(policy)
    return policy


def resolve_execution_providers() -> list[str]:
    """探针判定对应的 ORT providers 列表（cuda → [CUDA, CPU] 双列表兜底）。"""
    if resolve_device_policy() == "cuda":
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def reset_device_policy() -> None:
    """清空设备探针缓存（测试隔离用：环境变更后强制重探）。"""
    resolve_device_policy.cache_clear()
