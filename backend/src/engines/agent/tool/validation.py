"""工具参数 JSON Schema 校验器：执行前验证参数符合工具定义，失败安全回喂。

对齐 pi 的失败安全方向——模型产出的畸形参数不进入工具执行（防"错误结果
优于失败"），而是生成带修正指引的错误 ToolResult 回喂模型，由模型下轮自纠。
校验基于 OpenAI function calling 的 parameters schema（即 JSON Schema），
内置与 MCP 工具统一覆盖（MCP schema 由外部服务器提供，同样不可信）。
"""
import json
from typing import Any

import jsonschema
from novamind.engines.agent.tool.definition import ToolDefinition
from novamind.engines.agent.tool.result import ToolResult, ToolResultStatus
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 修正指引后缀：错误信息里带 schema 摘要，模型可据此自纠
_RECTIFY_SUFFIX = (
    "\n\n工具未执行。请根据上方错误修正参数后重新调用该工具。"
)


def validate_tool_arguments(
    tool_def: ToolDefinition,
    arguments: dict[str, Any],
) -> ToolResult | None:
    """校验工具参数是否符合定义 schema。

    Args:
        tool_def: 工具定义（parameters/required 即 JSON Schema 投影）。
        arguments: 待校验参数（应为 dict；类型不符由调用方先行处理）。

    Returns:
        None 表示校验通过（或无 schema 可校验，放行）；
        否则返回 status=ERROR 的 ToolResult，content 为模型可读错误说明。
    """
    if not tool_def.parameters:
        return None

    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            name: {"type": p.type, "description": p.description,
                   **({"enum": p.enum} if p.enum else {})}
            for name, p in tool_def.parameters.items()
        },
        "required": list(tool_def.required),
    }

    try:
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.absolute_path))
    except jsonschema.SchemaError as e:
        logger.warning("工具参数 schema 无效，放行执行", tool_name=tool_def.name, error=str(e))
        return None
    except TypeError:
        # arguments 非 dict（如模型把数组当参数），统一按校验失败处理
        error = f"工具 '{tool_def.name}' 参数必须是 JSON 对象，实际为 {type(arguments).__name__}{_RECTIFY_SUFFIX}"
        return ToolResult(
            status=ToolResultStatus.ERROR,
            content=error,
            error_message=error,
        )

    if not errors:
        return None

    first = errors[0]
    path = "/".join(str(p) for p in first.absolute_path) or "(根)"
    message = (
        f"工具 '{tool_def.name}' 参数校验失败：{first.message}（位于参数路径 {path}）"
        f"{_RECTIFY_SUFFIX}"
    )
    if len(errors) > 1:
        message = f"共 {len(errors)} 处校验错误，首条：" + message
    logger.info(
        "工具参数校验失败",
        tool_name=tool_def.name,
        error_count=len(errors),
        first_error=first.message,
    )
    return ToolResult(
        status=ToolResultStatus.ERROR,
        content=message,
        error_message=message,
    )


def parse_tool_arguments(tool_name: str, raw_arguments: Any) -> tuple[dict[str, Any] | None, str | None]:
    """解析模型产出的原始工具参数（JSON 字符串或已反序列化对象）。

    Args:
        tool_name: 工具名（用于错误信息）。
        raw_arguments: 原始参数——JSON 字符串、dict 或其他畸形值。

    Returns:
        (args, error) 二元组：解析成功返回 (dict, None)；
        失败返回 (None, 模型可读错误说明，含修正指引)。
    """
    if isinstance(raw_arguments, str):
        if not raw_arguments.strip():
            # 空 JSON 串按空参数处理（部分 provider 对无参工具返回 ""）
            return {}, None
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError as e:
            error = (
                f"工具 '{tool_name}' 的参数不是合法 JSON：{e.msg}（第 {e.lineno} 行第 {e.colno} 列）"
                f"{_RECTIFY_SUFFIX}"
            )
            logger.warning("工具参数 JSON 解析失败", tool_name=tool_name, raw=repr(raw_arguments)[:200])
            return None, error
        if not isinstance(parsed, dict):
            error = (
                f"工具 '{tool_name}' 的参数 JSON 必须是对象（{{...}}），实际为 "
                f"{type(parsed).__name__}{_RECTIFY_SUFFIX}"
            )
            return None, error
        return parsed, None
    if isinstance(raw_arguments, dict):
        return raw_arguments, None
    error = (
        f"工具 '{tool_name}' 的参数必须是 JSON 对象，实际为 {type(raw_arguments).__name__}"
        f"{_RECTIFY_SUFFIX}"
    )
    return None, error
