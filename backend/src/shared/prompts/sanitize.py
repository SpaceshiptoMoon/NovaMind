"""
提示词输入净化工具

在把用户/外部内容拼入 LLM 提示词模板前，剥离可能被用于 prompt 注入的结构性
分隔标记（markdown 标题、已知的 XML 分隔标签等），降低用户内容逃逸其所在
模板区段、伪造系统指令的风险。

仅用于「拼入提示词」前的轻量净化，不是完整的 prompt 注入防御——完整防御还需
结合模板分隔边界、模型侧约束等。本模块是其中可复用的一环。
"""
from typing import Any

# 已知的结构性分隔标签（与 ai_chat_service._sanitize 保持一致，便于共用）
_STRUCTURE_TAGS = (
    "<web-search-results>", "</web-search-results>",
    "<knowledge-base-context>", "</knowledge-base-context>",
)


def sanitize_prompt_input(text: Any) -> str:
    """
    净化将拼入提示词的文本。

    - 剥离已知的结构性 XML 分隔标签；
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