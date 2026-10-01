"""合成测试集生成（kb-ops C）：从知识库 chunks 采样，LLM 生成 QA 对落测试集。

设计要点：
- 深度耦合 evaluation 的 TestCase 契约与 create_test_set_from_cases 持久化路径，
  故归属 evaluation feature（kb-ops 只做 cron 编排与 gap 消费，R2 公共面调用）；
- 配额保守（YAML knowledge_ops.testset_max_cases 可配，默认 20 题）——LLM 成本
  硬闸，防止对大 KB 一次性生成数百题；
- 失败方向安全：LLM 生成失败/解析失败返回部分结果或空，绝不抛错阻断调用方
  （生成是旁路增强，不是主链路依赖）。

生成质量口径：question 只能基于 chunk 原文（防幻觉出题），expected_answer 是
chunk 内对应内容的摘录改写——检索命中验证型用例的 ground truth 是 chunk 本身。
"""
from __future__ import annotations

import json
import random
import re
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# 默认配额（YAML knowledge_ops.testset_max_cases 可覆盖）
DEFAULT_MAX_CASES = 20
# 每批送 LLM 的 chunk 数（question_generation_service 同量级：合并 prompt 控成本）
CHUNKS_PER_BATCH = 5
# 送 LLM 的单 chunk 截断长度（与 question_generation 的 1000 同依据：足够提取核心信息点）
CHUNK_TEXT_LIMIT = 1000
# 单 chunk 最短长度：太短的 chunk（标题/页码残片）出不了有效 QA
MIN_CHUNK_LENGTH = 80

# 生成 prompt：进 evaluation_prompts 注册表（模块级常量，注册见 evaluation_prompts.TEMPLATES）
GENERATED_TESTCASE_PROMPT_KEY = "eval_testset_generation"


def _load_max_cases() -> int:
    """读配额（YAML 可配，异常回退默认值）。公共面：cron 编排复用。"""
    try:
        from novamind.setting.yaml_config import get_config

        return int(get_config().knowledge_ops.testset_max_cases)
    except Exception:
        return DEFAULT_MAX_CASES


async def sample_chunks(
    session: AsyncSession,
    *,
    space_id: int,
    kb_id: int,
    limit: int,
) -> list[str]:
    """从 ES 检索该 KB 的 chunks 做均匀采样（跳短 chunk），返回文本列表。

    ES 无采样 API 的轻量替代：取回较大窗口（limit*4）后步长均匀抽样——
    保证覆盖不同文档而非集中在前几篇。
    """
    from novamind.features.knowledge_space.api.dependencies import (
        get_elasticsearch_client,
    )

    es_client = await get_elasticsearch_client()
    index_name = es_client.generate_index_name(space_id)
    window = min(limit * 4, 400)
    try:
        result = await es_client.es_client.search(
            index=index_name,
            query={"bool": {"filter": [{"term": {"kb_id": kb_id}}]}},
            size=window,
            _source=["content"],
        )
    except Exception as e:
        logger.warning("chunk 采样查询失败", kb_id=kb_id, error=str(e))
        return []

    texts = [
        h["_source"].get("content", "")
        for h in result.get("hits", {}).get("hits", [])
        if len(h["_source"].get("content", "")) >= MIN_CHUNK_LENGTH
    ]
    if len(texts) <= limit:
        return texts
    step = len(texts) / limit
    return [texts[int(i * step)] for i in range(limit)]


def build_generation_prompt(chunk_texts: list[str]) -> str:
    """构造 QA 生成 prompt（与 evaluation_prompts 注册表同文，此处拼变量）。"""
    sections = [f"### 片段 {i + 1}\n{t[:CHUNK_TEXT_LIMIT]}" for i, t in enumerate(chunk_texts)]
    chunks_text = "\n\n".join(sections)
    return (
        "请严格根据以下知识库片段，为每个片段生成 1 个「问题 + 期望答案」测试用例，"
        "用于评测知识库问答系统的检索与回答质量。\n\n"
        "要求：\n"
        "1. 问题必须且只能基于对应片段中实际出现的文字信息，禁止使用片段之外的知识\n"
        "2. 期望答案是片段中对应内容的提炼概括（50 字以内），不是原文照抄\n"
        "3. 问题应是用户真实可能提出的查询\n"
        "4. 只输出 JSON，不要输出任何其他文字\n\n"
        '输出格式：{"cases": [{"chunk_index": 1, "question": "问题", "expected_answer": "期望答案"}]}\n\n'
        f"{chunks_text}\n\n请生成："
    )


def parse_generation_response(response: str, expected_count: int) -> list[dict[str, str]]:
    """解析 LLM 响应为用例列表（容错：坏 JSON/缺字段跳过，不抛）。"""
    try:
        # 容忍 ```json 围栏
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.strip(), flags=re.MULTILINE)
        data = json.loads(cleaned)
        cases_raw = data.get("cases", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, AttributeError):
        return []

    cases: list[dict[str, str]] = []
    for item in cases_raw:
        if not isinstance(item, dict):
            continue
        q = (item.get("question") or "").strip()
        a = (item.get("expected_answer") or "").strip()
        if q and a:
            cases.append({"question": q, "expected_answer": a})
        if len(cases) >= expected_count:
            break
    return cases


async def generate_cases_from_chunks(
    session: AsyncSession,
    *,
    space_id: int,
    kb_id: int,
    user_id: int,
    max_cases: int | None = None,
) -> list[dict[str, str]]:
    """从 chunks 采样并 LLM 生成 QA 用例（旁路语义：失败返回部分/空结果）。

    Args:
        session: 数据库会话（解析用户模型配置用）。
        space_id/kb_id: 目标知识库。
        user_id: 发起用户（决定 LLM 模型解析）。
        max_cases: 配额上限；None 读 YAML 配置。

    Returns:
        [{question, expected_answer}]，可能少于配额（LLM 失败/解析跳过）。
    """
    quota = max_cases if max_cases is not None else _load_max_cases()
    if quota <= 0:
        return []

    chunk_texts = await sample_chunks(session, space_id=space_id, kb_id=kb_id, limit=quota)
    if not chunk_texts:
        logger.info("无可采样 chunks，跳过生成", kb_id=kb_id)
        return []

    cases: list[dict[str, str]] = []
    for batch_start in range(0, len(chunk_texts), CHUNKS_PER_BATCH):
        if len(cases) >= quota:
            break
        batch = chunk_texts[batch_start : batch_start + CHUNKS_PER_BATCH]
        try:
            llm_client = await _resolve_llm_client(session, user_id)
            prompt = build_generation_prompt(batch)
            response = await llm_client.generate_text(prompt=prompt, max_tokens=2000)
            cases.extend(parse_generation_response(response, quota - len(cases)))
        except Exception as e:
            # 单批失败跳过（部分结果优于全无；宁缺勿错不硬凑）
            logger.warning("测试集生成分批失败（跳过该批）", kb_id=kb_id, error=str(e))

    logger.info("合成测试用例生成完成", kb_id=kb_id, cases=len(cases), quota=quota)
    return cases


async def _resolve_llm_client(session: AsyncSession, user_id: int):
    """解析用户默认 LLM 客户端（ModelConfigService 公共面）。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    mcs = ModelConfigService(session)
    model_name = await mcs.get_user_default_model_name(user_id, "llm")
    if not model_name:
        raise RuntimeError(f"用户 {user_id} 未配置默认 LLM 模型")
    return await mcs.get_llm_client_by_model(user_id=user_id, model=model_name)
