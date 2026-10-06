"""模型调用统一异常族：provider 原始错误 → 带状态码的类型化异常（参照 browser-use llm/exceptions.py）。

约束：shared 层异常不继承 BaseAPIError（HTTP 语义归 feature 层）；translate_provider_error
是非 HTTP 网络错误的翻译边界——非模型调用异常原样透传，不做兜底包装。
"""
import re

# 从异常对象提取 HTTP 状态码的兜底正则：OpenAI SDK 的错误串形如 "Error code: 403 - {...}"
_STATUS_CODE_IN_TEXT = re.compile(r"Error code:\s*(\d{3})")

# 厂商原文在用户消息中的截断长度（保留定位证据，避免整段 dict 刷屏）
_RAW_DETAIL_MAX_LEN = 300


class ModelProviderError(Exception):
    """模型服务商返回错误的统一异常。

    Attributes:
        message: 面向用户的中文说明（含厂商原文摘要）。
        status_code: 服务商 HTTP 状态码；无法判定时为 None。
        model: 关联的模型名，可为 None。
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        model: str | None = None,
    ):
        """初始化统一异常。

        Args:
            message: 面向用户的中文说明。
            status_code: 服务商 HTTP 状态码。
            model: 关联的模型名。
        """
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.model = model


class ModelRateLimitError(ModelProviderError):
    """服务商限流（默认状态码 429），调用方可安全重试。"""

    def __init__(
        self,
        message: str,
        status_code: int = 429,
        model: str | None = None,
    ):
        """初始化限流异常（状态码缺省 429）。"""
        super().__init__(message, status_code, model)


class ModelOutputTruncatedError(ModelProviderError):
    """输出被 max_tokens 截断（finish_reason=length/max_tokens）。

    状态码固定 400：对同一模型不可重试，但对 fallback 模型可恢复。
    """

    def __init__(
        self,
        message: str,
        model: str | None = None,
    ):
        """初始化截断异常（status_code=400 避开同模型重试环）。"""
        super().__init__(message, status_code=400, model=model)


class ModelQuotaError(ModelProviderError):
    """模型额度不可用（欠费/免费额度耗尽/余额不足）。

    状态码固定 400 档语义（同模型不可重试），但对换卡充值后可恢复。
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = 400,
        model: str | None = None,
    ):
        """初始化额度异常（默认状态码 400，同模型重试无意义）。"""
        super().__init__(message, status_code, model)


def _extract_status_code(exc: BaseException) -> int | None:
    """按优先级从异常对象提取 HTTP 状态码。

    提取顺序：属性 status_code（OpenAI SDK 异常）→ response.status_code
    （httpx.HTTPStatusError）→ 错误文本 "Error code: NNN" 正则兜底。

    Args:
        exc: 待提取的异常。

    Returns:
        状态码；无法判定时 None。
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    resp_status = getattr(response, "status_code", None)
    if isinstance(resp_status, int):
        return resp_status
    match = _STATUS_CODE_IN_TEXT.search(str(exc))
    return int(match.group(1)) if match else None


# 状态码 → 中文说明。403 覆盖百炼官方文档列出的三类根因（未开通/额度耗尽/已下线）。
_STATUS_MESSAGES: dict[int, str] = {
    400: "请求参数不被该模型接受（参数组合或输入格式不匹配）",
    401: "API Key 无效或已过期",
    403: "无权访问该模型（未开通、额度不可用或已下线）",
    404: "模型或接口路径不存在（请检查模型名拼写与 Base URL）",
    429: "触发服务商限流，请稍后重试或降低调用频率",
}

# 额度类错误的通用词面（小写）：覆盖 quota/arrearage/insufficient/balance/credit
# 等主流服务商计费错误的英文措辞与中文欠费类措辞。判据从第一性原理出发
# （计费语义词 + 4xx），具体厂商样例（DashScope Arrearage/AllocationQuota.
# FreeTierOnly）仅作测试验证，不作判据来源。
_QUOTA_TEXT_PATTERNS = (
    "quota",
    "arrearage",
    "insufficient",
    "balance",
    "credit",
    "欠费",
    "余额不足",
    "免费额度",
)


def _is_quota_error(status_code: int | None, raw_detail: str) -> bool:
    """判定是否为额度类错误：4xx（除 404）+ 错误文本命中计费语义词面。

    404 排除：「不存在」语义下 balance/credit 等词面（如 "check balance of
    model name"）无计费含义，不应归类额度错误。

    Args:
        status_code: 服务商 HTTP 状态码。
        raw_detail: 服务商错误原文（小写化由本函数内部处理）。

    Returns:
        True 表示应归类为 ModelQuotaError。
    """
    if status_code is None or not (400 <= status_code < 500) or status_code == 404:
        return False
    lowered = raw_detail.lower()
    return any(p in lowered for p in _QUOTA_TEXT_PATTERNS)


def translate_provider_error(exc: BaseException, model: str | None = None) -> ModelProviderError:
    """把模型调用异常翻译为统一异常族（保留原始异常为 __cause__ 由调用方处理）。

    Args:
        exc: 模型调用抛出的原始异常（OpenAI SDK / httpx / 其他）。
        model: 关联的模型名，写入异常属性便于上层日志归因。

    Returns:
        ModelProviderError（或其子类）：HTTP 类异常翻译为中文人话消息；
        与模型调用无关的异常原样返回（不包装、不吞类型）。
    """
    if isinstance(exc, ModelProviderError):
        if model and not exc.model:
            exc.model = model
        return exc

    status_code = _extract_status_code(exc)
    if status_code is None and not isinstance(exc, (ConnectionError, TimeoutError)):
        # 无状态码且非网络异常：大概率不是模型调用的错，原样透传
        return exc  # type: ignore[return-value]

    raw_detail = str(exc).strip()[:_RAW_DETAIL_MAX_LEN]
    if status_code is None:
        human = "无法连接到模型服务（网络错误或超时）"
    else:
        if status_code >= 500:
            human = "模型服务商暂不可用（服务端错误）"
        else:
            human = _STATUS_MESSAGES.get(status_code, f"模型调用失败（HTTP {status_code}）")
    message = f"{human}。服务商返回：{raw_detail}" if raw_detail else human

    if status_code == 429:
        return ModelRateLimitError(message, status_code=429, model=model)
    if _is_quota_error(status_code, raw_detail):
        # 额度类错误给短文案 + 行动指引，不再拼「请求参数」类误导前缀
        quota_message = "模型额度不可用（欠费或免费额度耗尽），请充值或在服务商控制台调整"
        if raw_detail:
            quota_message += f"。服务商返回：{raw_detail}"
        return ModelQuotaError(quota_message, status_code=status_code, model=model)
    return ModelProviderError(message, status_code=status_code, model=model)
