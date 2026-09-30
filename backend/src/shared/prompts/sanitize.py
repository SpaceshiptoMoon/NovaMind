"""提示词输入净化工具。

仅用于拼入提示词前的轻量净化（剥结构性分隔标签、转义系统标签前缀与行首 markdown 标题），不是完整的 prompt 注入防御。
"""
from __future__ import annotations

import re
from typing import Any

# 已知的结构性分隔标签（唯一实现——qa 的本地 _sanitize 已于批次 5.3 删除收敛到本模块）。
# 与 _build_retrieval_context / _format_attachments_prompt 实际使用的块边界标签
# 保持同步：检索内容与附件正文可能含字面标签，缺一个就能伪造对应块边界。
_STRUCTURE_TAGS = (
    "<web-search-results>", "</web-search-results>",
    "<knowledge-base-context>", "</knowledge-base-context>",
    "<wiki-pages>", "</wiki-pages>",
    "<documents>", "</documents>",
    "</document>",
)

# 参数化开标签（带属性，如 <document filename="a.pdf">）：精确 replace 覆盖不了
# 任意属性组合，用正则剥除整个开标签。
_STRUCTURE_OPEN_TAG_PATTERN = re.compile(r"<document\b[^>]*>")

# 系统注入标签前缀：第三方内容（网页 snippet/KB chunk/工具输出）中出现的
# <system-*>/</system-*> 样式文本一律转义失活——与消息流的 <system-*> 系统注入
# 标签约定（prompt_builder._TAG_CONVENTION）对齐。只转义前缀而非全部 '<'：
# 保留工具输出/代码片段中的正常 HTML 可读性，同时结构性掐断伪造系统边界的可能。
# 注意 '<system-' 与 '</system-' 互不为子串（'<s' vs '</'），替换顺序无关。
_SYSTEM_TAG_ESCAPES = (
    ("</system-", "&lt;/system-"),
    ("<system-", "&lt;system-"),
)


def sanitize_prompt_input(text: Any) -> str:
    """
    净化将拼入提示词的文本。

    - 剥离已知的结构性 XML 分隔标签；
    - 转义 ``<system-`` / ``</system-`` 标签前缀为 ``&lt;system-`` / ``&lt;/system-``，
      防止第三方内容伪造系统注入边界（标签失活为字面文本，内容仍可读）；
    - 剥离行首 markdown 标题标记（`#`/`##`/`###` 等），防止用户内容伪造模板
      的 `## Retrieved Documents` / `## User Question` / `## Requirements`
      等区段结构。

    Args:
        text: 任意输入，非字符串会先 str() 转换。

    Returns:
        净化后的字符串。
    """
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)

    for tag in _STRUCTURE_TAGS:
        text = text.replace(tag, "")
    text = _STRUCTURE_OPEN_TAG_PATTERN.sub("", text)
    # 转义 <system- 前缀（覆盖任意 <system-xxx> 标签名，无需枚举）
    for marker, escaped in _SYSTEM_TAG_ESCAPES:
        text = text.replace(marker, escaped)

    # 剥离行首 markdown 标题标记（1-6 个 # 后接空白），
    # 防止用户内容伪造模板的 `## Retrieved Documents`/`## User Question`/`## Requirements` 等区段。
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if 1 < len(stripped) and stripped[0] == "#":
            hash_count = 0
            for ch in stripped:
                if ch == "#":
                    hash_count += 1
                else:
                    break
            if 1 <= hash_count <= 6 and hash_count < len(stripped) and stripped[hash_count] in (" ", "\t"):
                # 去掉 "## " 这类标记，保留标题正文
                body = stripped[hash_count:].lstrip(" \t")
                # 保留原行前导非 # 缩进已被 lstrip 掉，这里用 body 作为净化后内容
                cleaned_lines.append(body)
                continue
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()