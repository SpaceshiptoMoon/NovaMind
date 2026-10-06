"""LLM provider 怪癖声明层：有序注册表把「模型是什么样」变成数据，未知模型落全默认。

参照 WeKnora providerAdapter/baseProvider 语义：每条规则特异在前、通配在后，
谁都不匹配返回默认 LLMQuirks（零怪癖照常工作），resolve 永不抛错。
用户可经 extra_config 覆盖（stream_only/force_thinking 键），覆盖优先级最高。
"""
import re
from dataclasses import dataclass, field, fields


@dataclass(frozen=True)
class LLMQuirks:
    """provider/model 专属怪癖——全字段带默认值，缺省即无怪癖（baseProvider 语义）。

    Attributes:
        stream_only: 模型仅支持流式调用（如 DashScope glm-4.5）。客户端在
            generate_text 内部改走流式聚合（LiteLLM should_fake_stream 先例）。
        force_thinking: 连接探针直接带 enable_thinking=True（如 DashScope qwen3 系）。
            仅影响探针，不改变运行时请求行为。
        thinking_budget_ratio: thinking 模式下思考预算占 max_tokens 的比例封顶。
            收编自 openai_compatible._THINKING_BUDGET_RATIO。
        auth_type: Anthropic 协议凭据的鉴权头语义。"api_key"（默认）发
            x-api-key 头（官方 Anthropic）；"bearer" 发 Authorization: Bearer
            头（兼容网关的 coding-plan token）。凭据签发方声明的属性，
            仅经用户 extra_config 声明，注册表不做 URL 猜测。
    """

    stream_only: bool = False
    force_thinking: bool = False
    thinking_budget_ratio: float = 0.5
    auth_type: str = "api_key"


@dataclass(frozen=True)
class _QuirkRule:
    """单条怪癖规则：provider 端点匹配 + 模型名匹配 → 该组怪癖值。

    Attributes:
        base_url_pattern: base_url 子串匹配（小写化后 contains）。
        model_pattern: 模型名正则（re.search，小写化后匹配）。
        quirks: 命中后合并的怪癖值（仅显式非默认字段生效）。
    """

    base_url_pattern: str
    model_pattern: str
    quirks: LLMQuirks = field(default_factory=LLMQuirks)


# 有序注册表：特异在前，通配在后。每条规则附实测证据（日期 + 报错原文），
# 新增怪癖 = 追加一条规则，不改任何分支代码。
_QUIRK_RULES: tuple[_QuirkRule, ...] = (
    # DashScope glm-4.5：仅支持流式（2026-10-05 实测 400
    # "This model only support stream mode, please enable the stream parameter
    #  to access the model."）
    _QuirkRule(
        base_url_pattern="dashscope.aliyuncs.com",
        model_pattern=r"glm-4\.5",
        quirks=LLMQuirks(stream_only=True),
    ),
    # DashScope qwen3 系：服务商强制 enable_thinking=True（openai_compatible
    # _restricted_thinking_value 的 reactive 重试即为此而设；声明后探针直带，
    # 省掉一次必败 400）
    _QuirkRule(
        base_url_pattern="dashscope.aliyuncs.com",
        model_pattern=r"^qwen3",
        quirks=LLMQuirks(force_thinking=True),
    ),
)

# extra_config → LLMQuirks 字段的白名单（布尔字段），防任意键注入
_OVERRIDE_KEYS = {"stream_only", "force_thinking"}
# 字符串枚举类覆盖键：值必须落在合法集合内才生效。
# auth_type 是凭据签发方声明的语义（API Key vs Bearer token），代码无从推断，
# 只能由用户经 extra_config.auth_type 声明——不做 URL 猜测，不内置特定厂商规则。
_OVERRIDE_ENUM_KEYS: dict[str, frozenset[str]] = {"auth_type": frozenset({"api_key", "bearer"})}


def _coerce_bool(value: object) -> bool | None:
    """宽容解析布尔声明：True/False 原样，其他一律 None（视为未声明）。"""
    if isinstance(value, bool):
        return value
    return None


def resolve_quirks(
    base_url: str | None,
    model: str,
    overrides: dict | None = None,
) -> LLMQuirks:
    """解析 provider+model 的怪癖：注册表匹配 → 用户声明覆盖 → 全默认兜底。

    Args:
        base_url: 模型服务端点；空/None 不参与匹配。
        model: 模型名称。
        overrides: 用户显式声明（extra_config 中的 stream_only/force_thinking/
            auth_type 键），优先级最高；非法值静默忽略，不抛错。

    Returns:
        合并后的 LLMQuirks；无注册表命中且无覆盖时为全默认实例。
    """
    quirks_kwargs: dict = {}

    url_lower = (base_url or "").lower()
    model_lower = (model or "").lower()
    for rule in _QUIRK_RULES:
        if rule.base_url_pattern not in url_lower:
            continue
        if not re.search(rule.model_pattern, model_lower):
            continue
        # dataclasses.fields 顺序遍历，只取显式声明的字段合并进结果
        for f in fields(rule.quirks):
            value = getattr(rule.quirks, f.name)
            declared_default = getattr(LLMQuirks(), f.name)
            if value != declared_default:
                quirks_kwargs[f.name] = value

    if overrides:
        for key in _OVERRIDE_KEYS:
            coerced = _coerce_bool(overrides.get(key))
            if coerced is not None:
                quirks_kwargs[key] = coerced
        for key, allowed in _OVERRIDE_ENUM_KEYS.items():
            value = overrides.get(key)
            if isinstance(value, str) and value in allowed:
                quirks_kwargs[key] = value

    if not quirks_kwargs:
        return LLMQuirks()
    return LLMQuirks(**quirks_kwargs)


# stream-only 类错误的通用判据：错误文本含 stream 且命中服务商典型措辞
_STREAM_ONLY_PATTERNS = ("only support", "only_support", "stream mode")


def is_stream_only_error(error_msg: str) -> bool:
    """识别「模型仅支持流式调用」类服务端错误（stream-only 探针回退的判据）。

    Args:
        error_msg: LLM 服务端返回的错误文本。

    Returns:
        True 表示该错误源于非流式调用被拒（如 DashScope glm-4.5 的
        "only support stream mode"），应改用流式探针重试。
    """
    lowered = error_msg.lower()
    return "stream" in lowered and any(p in lowered for p in _STREAM_ONLY_PATTERNS)
