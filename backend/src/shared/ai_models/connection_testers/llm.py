"""LLM 连通性探针（quirks 声明驱动梯子 + reactive 回退），shared 层公共设施。

原实现是 user ModelConfigService._test_llm（与 ModelTestRequest schema 耦合）；
2026-11-12 下沉为原始参数入口，供两个消费方共用：
- 用户「模型管理页测试连接」（mcs._test_llm 转薄调用，client_factory 传模块级
  引用以保持既有测试的 monkeypatch 兼容）；
- KB 配置保存预检（knowledge_space，按 creator_id 凭证在保存时提前暴露
  「模型名在所选 Base URL 下不存在」类配置错误）。

探针梯子：声明 stream_only → 直接流式探针（免付必败的第一次 400）；
声明 force_thinking → 直带 enable_thinking=True；未声明 → 非流式探针，
失败后按错误特征 reactive 回退（thinking 强制 / stream-only）。
"""
from __future__ import annotations

from typing import Any

from novamind.shared.ai_models.base_model import BaseLLM
from novamind.shared.ai_models.errors import translate_provider_error
from novamind.shared.ai_models.llm import create_llm_client
from novamind.shared.ai_models.llm.quirks import is_stream_only_error, resolve_quirks

# 探针预算放宽到 512：思考 token 计入 completion 预算（对齐 LiteLLM
# health_check_max_tokens_reasoning 的同类问题），10 会被思考吃满导致
# 正文恒空、连通性被误判为失败。
_PROBE_MAX_TOKENS = 512


async def probe_llm_stream(client: BaseLLM) -> str:
    """用流式调用探测 LLM 连通性，返回收到的内容（可为空串）。

    Args:
        client: 已构造的 LLM 客户端。

    Returns:
        流式响应拼接的内容；模型可达但 thinking 耗尽预算时为空串。

    Raises:
        Exception: 流式请求本身失败（鉴权/网络/参数错误）时原样抛出。
    """
    chunks: list[str] = []
    async for chunk in client.generate_text_stream(
        prompt="Hello", max_tokens=_PROBE_MAX_TOKENS, temperature=0.1
    ):
        chunks.append(chunk)
    return "".join(chunks)


async def probe_llm_connection(
    *,
    protocol: str,
    api_key: str,
    base_url: str,
    model: str,
    extra_config: dict[str, Any] | None = None,
    client_factory: Any = None,
) -> None:
    """对 (protocol, base_url, model, api_key) 组合做一次轻量连通性试调。

    Args:
        protocol: 服务商协议（openai/anthropic/...）。
        api_key: 已解密的 API Key。
        base_url: 服务商 Base URL。
        model: 模型名（原样进 provider 请求体——模型名拼写/归属错误在此暴露）。
        extra_config: 模型扩展配置（quirks 声明 stream_only/force_thinking 等）。
        client_factory: 客户端工厂；None 用 shared 默认 create_llm_client。
            传调用方模块级引用以保持测试 monkeypatch 兼容。

    Returns:
        None——可达且返回非空内容即通过。

    Raises:
        Exception: 不可达（已 translate_provider_error 翻译为中文人话）或
            返回空内容（thinking 吃满输出预算）。
    """
    factory = client_factory or create_llm_client
    quirks = resolve_quirks(base_url, model, extra_config)
    client = factory(
        protocol=protocol,
        api_key=api_key,
        base_url=base_url or "",
        model_name=model,
        quirks=quirks,
    )
    try:
        if quirks.stream_only:
            # 声明命中：直接流式探针，收到任意内容块即视为可达
            content = await probe_llm_stream(client)
        elif quirks.force_thinking:
            content = await client.generate_text(
                prompt="Hello", max_tokens=_PROBE_MAX_TOKENS, temperature=0.1,
                enable_thinking=True,
            )
        else:
            content = await client.generate_text(
                prompt="Hello", max_tokens=_PROBE_MAX_TOKENS, temperature=0.1
            )
    except Exception as e:
        error_msg = str(e)
        if "enable_thinking" in error_msg.lower():
            content = await client.generate_text(
                prompt="Hello", max_tokens=_PROBE_MAX_TOKENS, temperature=0.1,
                enable_thinking=True,
            )
        elif is_stream_only_error(error_msg):
            # reactive 兜底：声明漏了 stream-only 时的运行时回退
            content = await probe_llm_stream(client)
        else:
            # 统一错误翻译：403/404 等得到中文人话（未开通/模型不存在/额度耗尽）
            raise translate_provider_error(e, model=model) from e
    # 空 content 视为失败：thinking 强制模型可能把 max_tokens 全部耗在思考上
    # （generate_text 只打 warning 返回空串），报成功会让用户带着坏配置上线
    if not (content or "").strip():
        raise ValueError(
            "模型返回了空内容——可能启用了 thinking 且思考耗尽了输出预算，"
            "请在扩展配置中调整或更换非思考模型"
        )


__all__ = ["probe_llm_connection", "probe_llm_stream"]
