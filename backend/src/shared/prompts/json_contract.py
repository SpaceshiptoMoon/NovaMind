"""LLM JSON 输出的统一提示词约束片段，供各调用方在请求时追加。

「只输出 JSON」的约束写法在仓库内有 8 种变体（各自散落在 feature prompts
里），本模块提供唯一的规范文本。约束块设计为**请求时追加**而非模板内嵌：
PromptManager.format_prompt 走 str.format，模板内嵌 JSON 花括号示例必须
双写转义；请求时追加彻底避开该雷区，且对消息列表 prompt 同样适用。
"""

# 标准约束句。中文书写与全库 prompt 方言一致；「禁止 markdown 围栏」针对
# LLM 最常见的 ```json 包裹行为——该形态由提取层兜底，但约束前置可减少
# 提取层负担与解析失败率。
JSON_ONLY_RULE = "输出要求：只输出一个合法 JSON，禁止解释文字、前后缀或 markdown 围栏。"


def render_json_instruction(schema_hint: str | None = None) -> str:
    """渲染标准 JSON 输出约束块。

    Args:
        schema_hint: 期望的 JSON 形状描述（字符串，如 ``'{"claims": ["..."]}'``），
            非空时附加在标准约束句之后，帮助模型对齐字段名与嵌套结构。

    Returns:
        追加到用户 prompt 末尾的约束文本块（以换行分隔）。
    """
    if schema_hint:
        return f"{JSON_ONLY_RULE}\n期望的 JSON 形状：{schema_hint}"
    return JSON_ONLY_RULE
