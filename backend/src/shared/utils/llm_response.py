"""
LLM 响应 JSON 提取工具，从 markdown 代码块或混入文字中提取 JSON。

提供 extract_json_str（失败抛异常）、extract_json_obj（对象，失败返回 None）、
extract_json_value（对象或数组，失败返回 None）三种接口。
"""
import json
import re
from typing import Any


def extract_json_str(text: str) -> str:
    """从 LLM 输出提取 JSON 字符串，失败抛 ``ValueError``。

    策略顺序：
      1. 已以 ``{`` 或 ``[`` 开头 → 原样返回（已是合法 JSON 起始）。
      2. 匹配 ``` ```json ... ``` ``` 或 ``` ``` ... ``` ``` 代码块围栏 → 返回围栏内容。
      3. 兜底：定位首个 ``{`` 或 ``[``，返回从此处到末尾的子串。

    Raises:
        ValueError: 输入为空，或无法定位任何 JSON 起始符。
    """
    if not text or not text.strip():
        raise ValueError("LLM 返回空内容")
    text = text.strip()

    # 1) 已是合法 JSON 开头
    if text.startswith("{") or text.startswith("["):
        return text

    # 2) 剥 ```json ... ``` 或 ``` ... ``` 代码块围栏
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        if candidate:
            return candidate

    # 3) 兜底：找第一个 { 或 [ 到末尾
    start = -1
    for ch in ("{", "["):
        idx = text.find(ch)
        if idx >= 0 and (start < 0 or idx < start):
            start = idx
    if start >= 0:
        return text[start:]

    raise ValueError(f"无法从 LLM 输出中提取 JSON: {text[:200]}")


def extract_json_obj(text: str | None) -> dict | None:
    """从 LLM 输出提取并解析首个 JSON 对象，失败返回 ``None``。

    两级回退（精确保留原 ``grade_retrier`` 语义）：
      1. 先用 :func:`extract_json_str` 提取（覆盖纯 JSON 与 ``` ```json ``` 围栏两种形态），
         ``json.loads`` 解析成功即返回。
      2. 解析失败时，用贪婪正则 ``\\{[\\s\\S]*\\}``（首个 ``{`` 到末个 ``}``）兜底——
         可吃掉"前导文字 + JSON + 后缀"中的前导与后缀，再 ``json.loads``。

    任一阶段失败均返回 ``None``，不抛异常。供只需拿到 ``dict | None`` 的调用方使用。
    """
    parsed = extract_json_value(text)
    return parsed if isinstance(parsed, dict) else None


def extract_json_value(text: str | None) -> Any:
    """从 LLM 输出提取并解析首个 JSON 值（对象或数组），失败返回 ``None``。

    提取策略与 :func:`extract_json_obj` 同源（extract_json_str 两级 + 贪婪括号
    兜底），区别在于同时接受数组：``{...}`` 与 ``[...]`` 都能兜住，供消费
    JSON 数组输出（如 deep_research 计划、agent 记忆抽取）的调用方使用。

    Args:
        text: LLM 原始输出文本，可空。

    Returns:
        解析出的 dict/list/str/int 等原生 JSON 值；任何阶段失败返回 ``None``，
        不抛异常。
    """
    if not text:
        return None
    # 1) 纯 JSON / ```json 围栏
    try:
        return json.loads(extract_json_str(text))
    except (ValueError, json.JSONDecodeError):
        pass
    # 2) 贪婪括号兜底：先对象后数组（吃掉前导文字与后缀）
    for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group(0))
            except (ValueError, json.JSONDecodeError):
                continue
    return None