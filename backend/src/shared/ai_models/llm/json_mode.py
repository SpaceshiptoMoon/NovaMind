"""LLM JSON 请求-响应统一入口：prompt 约束追加 → response_format → 提取容错重试。

三层防护的组合函数。失败方向安全：transport 异常照常上抛（网络重试由
客户端 tenacity 管），空响应/解析失败不抛——重试轮次耗尽返回 ``None``，
由调用方决定降级语义。不替代调用方的业务校验（字段级验证仍归调用方）。
"""
import asyncio

from novamind.shared.ai_models.base_model import BaseLLM
from novamind.shared.logging import get_logger
from novamind.shared.prompts.json_contract import render_json_instruction
from novamind.shared.utils.llm_response import extract_json_value

logger = get_logger(__name__)

# 默认 SDK 约束：json_object 模式。全库大规模验证过；不用 json_schema——
# 第三方 OpenAI 兼容网关支持参差，不支持时 json_object 被静默忽略（退化为
# 现状），json_schema 则 400 直接炸任务，失败方向不安全。
DEFAULT_JSON_RESPONSE_FORMAT: dict = {"type": "json_object"}

# 空响应重试时压缩 max_tokens 的比例。thinking 模型思考 token 计入输出
# 预算，预算被思考耗尽后 content 为空；缩短预算对"接近上限才溢出"的
# 场景有效。与 wiki_ingest / question_generation 既有常量同语义。
EMPTY_RESPONSE_MAX_TOKENS_SCALE = 0.5
# 空响应重试的 max_tokens 下限（防比例压缩趋零）。
EMPTY_RESPONSE_MIN_MAX_TOKENS = 512


async def request_json(
    llm: BaseLLM,
    prompt: str | list,
    *,
    max_tokens: int = 2048,
    temperature: float = 0.1,
    top_p: float = 0.8,
    enable_thinking: bool = False,
    response_format: dict | None = DEFAULT_JSON_RESPONSE_FORMAT,
    schema_hint: str | None = None,
    append_json_rule: bool = True,
    max_parse_retries: int = 1,
    expect_list: bool = False,
    timeout: float | None = None,
) -> dict | list | None:
    """带三层加固的 JSON 请求：提示词约束 → response_format → 提取容错。

    Args:
        llm: LLM 客户端实例（具体类，不定义 Protocol）。
        prompt: 提示词文本或消息列表。str 时在末尾追加 JSON 约束块；list 时
            拷贝后向最后一条 user 消息的 content 追加（不改动方原列表）。
        max_tokens: 单次调用输出 token 上限；空响应重试时按比例缩短。
        temperature: 采样温度。JSON 任务默认低温。
        top_p: 核采样概率上限。
        enable_thinking: 是否请求 thinking 模式（服务商可能强制改写）。
        response_format: SDK 约束解码声明；None 表示不带该字段（服务端
            不支持 json_object 时可显式关掉）。
        schema_hint: 期望 JSON 形状的字符串描述（如 ``'{"claims": ["..."]}'``），
            追加进提示词帮助模型对齐结构；只进提示词，不进 response_format。
        append_json_rule: 是否追加标准 JSON 约束块；prompt 已自带等价约束时
            可关掉避免重复。
        max_parse_retries: 解析失败/空响应的重试轮数（不含首轮）。
        expect_list: True 时期望 JSON 数组（返回 list）；False 期望对象
            （返回 dict）。类型不符视为解析失败进入重试。
        timeout: 单次调用超时秒数；None 不限时（沿用客户端自身超时）。

    Returns:
        解析成功的 dict（expect_list=False）或 list（expect_list=True）；
        重试耗尽仍失败返回 ``None``。

    Raises:
        Exception: LLM 调用层的网络/认证等异常原样上抛，不在本函数吞掉。
    """
    effective_prompt = _append_json_instruction(prompt, schema_hint, append_json_rule)

    for attempt in range(max_parse_retries + 1):
        call = llm.generate_text(
            prompt=effective_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            response_format=response_format,
            enable_thinking=enable_thinking,
        )
        raw = await asyncio.wait_for(call, timeout) if timeout else await call

        if not raw or not raw.strip():
            logger.warning(
                "request_json 空响应",
                attempt=attempt + 1,
                max_retries=max_parse_retries + 1,
                max_tokens=max_tokens,
            )
            max_tokens = max(
                int(max_tokens * EMPTY_RESPONSE_MAX_TOKENS_SCALE),
                EMPTY_RESPONSE_MIN_MAX_TOKENS,
            )
            continue

        expected_type = list if expect_list else dict
        data = extract_json_value(raw)
        if isinstance(data, expected_type):
            return data

        logger.warning(
            "request_json 解析失败或类型不符",
            attempt=attempt + 1,
            max_retries=max_parse_retries + 1,
            expect="list" if expect_list else "dict",
            got=type(data).__name__,
            response_preview=raw[:120],
        )

    return None


def _append_json_instruction(
    prompt: str | list,
    schema_hint: str | None,
    append_json_rule: bool,
) -> str | list:
    """把 JSON 约束块追加到 prompt 末尾（str 直接拼；list 拷贝后改末条 user）。"""
    if not append_json_rule:
        return prompt
    instruction = render_json_instruction(schema_hint)

    if isinstance(prompt, str):
        return f"{prompt}\n\n{instruction}"

    # 消息列表：拷贝后向最后一条 user 消息追加，不改动方原列表
    messages = list(prompt)
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content", "")
            messages[i] = {**msg, "content": f"{content}\n\n{instruction}" if content else instruction}
            return messages
    # 无 user 消息（异常形态）：原样返回，约束缺失由调用方的模板负责
    return messages
