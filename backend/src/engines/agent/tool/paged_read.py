"""
分页读共享协议：read_tool_result / read_attachment / plan_output 三个分页读
工具共用的参数钳制与响应装配（构造端收口）。

历史教训：三份独立实现漂移出真实缺陷——read_tool_result/plan_output 无参数
钳制（负 limit 静默截尾且 has_more=True 诱导无限翻页）、read_tool_result
切片与否返回类型不一致（纯文本 vs JSON）、plan_output 两种 JSON 形态并存。
统一在此钳制与装配后，新增分页读工具不再复制第三份口径。
"""
import json
from typing import Any


def clamp_page(
    arguments: dict[str, Any], *, default_limit: int, max_limit: int
) -> tuple[int, int]:
    """从工具参数解析并钳制分页参数：offset>=0、limit∈[1, max_limit]。

    Args:
        arguments: LLM 传入的工具参数（offset/limit 均可选）。
        default_limit: limit 缺省值（参数缺失或畸形时回落）。
        max_limit: 单次返回字符数上限（畸形超大值钳到上限）。

    Returns:
        (offset, limit)：offset>=0，limit∈[1, max_limit]。
    """
    try:
        offset = int(arguments.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    try:
        limit = int(arguments.get("limit", default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    limit = min(max(1, limit), max_limit)
    return offset, limit


def paged_payload(
    content: str, offset: int, limit: int, total_length: int, **identity: Any
) -> dict[str, Any]:
    """统一分页响应 dict：工具自有标识键 + content/offset/limit/total_length/has_more。

    has_more 与切片口径统一在此计算（offset 越界时 content 为空、has_more=False，
    不再诱导翻页）。响应恒为同构 JSON——调用方直接 json.dumps，不再有无切片
    纯文本/切片 JSON 的双形态。
    """
    payload: dict[str, Any] = dict(identity)
    payload.update(
        {
            "content": content[offset : offset + limit],
            "offset": offset,
            "limit": limit,
            "total_length": total_length,
            "has_more": offset + limit < total_length,
        }
    )
    return payload


def paged_response(
    content: str,
    offset: int,
    limit: int,
    total_length: int,
    *,
    ensure_ascii: bool = False,
    **identity: Any,
) -> str:
    """paged_payload 的 JSON 序列化快捷入口（三工具统一走此出口）。"""
    return json.dumps(
        paged_payload(content, offset, limit, total_length, **identity),
        ensure_ascii=ensure_ascii,
    )


__all__ = ["clamp_page", "paged_payload", "paged_response"]
