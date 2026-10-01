"""质量基线配置指纹（kb-ops C）：切分/检索配置 + 模型名的稳定 hash。

指纹语义：同指纹两次跑批 = 同配置下的回归检测（分数下降告警）；
跨指纹 = 配置变更后的 A/B 对比。指纹只含影响检索/生成质量的字段，
不含 top_k 等跑批参数（改 top_k 不算「换了配置」——是同一配置的
不同取样方式，对比无意义）。

稳定性要求：hash 输入做键排序 + 类型归一，跨进程/跨时间同配置必须
产生同指纹（否则基线链断裂）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# 参与指纹的 EvaluationConfig 字段（影响检索/生成质量的子集；
# enable_mrr/enable_recall_at_k 等纯评估器开关不参与——它们改变的是
# 「测什么」而非「系统行为」）
FINGERPRINT_FIELDS = (
    "search_mode",
    "score_threshold",
    "enable_generation",
    "llm_model",
    "embedding_model",
    "retrieval_relevance_strategy",
    "correctness_strategy",
    "faithfulness_strategy",
    "relevance_strategy",
)


def compute_config_fingerprint(config: dict[str, Any] | None) -> str:
    """计算测评配置指纹（16 位 sha256 前缀）。

    Args:
        config: EvaluationConfig dict（任务 config 字段原样）；None=全默认配置。

    Returns:
        稳定指纹串（同配置恒同值）。
    """
    from novamind.features.evaluation.schemas.evaluation_schema import EvaluationConfig

    # 经 schema 归一（默认值补齐）再取参与字段——显式传默认值与不传同指纹
    normalized = EvaluationConfig(**(config or {})).model_dump()
    payload = {k: normalized.get(k) for k in FINGERPRINT_FIELDS}
    # sort_keys 保证键序稳定；ensure_ascii 保证中文模型名跨平台一致
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
