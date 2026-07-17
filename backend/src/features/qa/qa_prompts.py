"""
问答模块提示词模板

覆盖：对话压缩、AI 对话系统提示、QueryRewriter 查询改写（4 策略）、GradeRetrier 检索自评估
"""

TEMPLATES = {
    "qa_compression_summary": (
        "Your task is to create a detailed, structured summary of the conversation so far, "
        "ensuring no key context is lost for subsequent dialogue. "
        "Pay close attention to the user's intent, key facts, and any knowledge-base sources referenced.\n\n"
        "## Summary Structure\n"
        "Include the following sections:\n"
        "1. User Intent: The core problems and needs the user is trying to address in this conversation\n"
        "2. Key Information: Retain key entities (names, products, dates, numbers, file names, etc.), "
        "important facts, decisions, and conclusions — prefer recording too much over losing a key fact\n"
        "3. Knowledge-Base Sources: Core points of any documents/materials referenced from the knowledge base (if any)\n"
        "4. Current Topic: The specific question and progress being discussed most recently\n"
        "5. Pending & Next Steps: Unresolved issues or explicitly requested follow-up tasks (omit if none)\n\n"
        "## Requirements\n"
        "- Write in the same language the user was using in the conversation\n"
        "- Preserve business/technical details thoroughly; avoid vague generalities\n"
        "- NEVER include API keys, passwords, tokens, or credentials — replace with [REDACTED]\n"
        "- Output the summary directly with no prefix, greeting, or explanation"
    ),

    "qa_ai_chat_system": (
        "You are an intelligent AI assistant. You are helpful, knowledgeable, and direct.\n\n"
        "Behavioral guidelines:\n"
        "1. Honesty first — admit uncertainty when appropriate, never fabricate information\n"
        "2. Be precise — give direct, useful answers without unnecessary verbosity\n"
        "3. Structure clearly — use headings, lists, and paragraphs for complex answers\n"
        "4. Respect the user — respond in the language the user is using, stay professional\n\n"
        "If the user has uploaded files or provided context, prioritize those sources.\n"
        "If information is insufficient to answer, say so clearly and suggest alternatives."
    ),

    # ==================== QueryRewriter 查询改写（4 策略） ====================
    # 注意：这是 QA 聊天路径（ai_chat_service → QueryRewriter）的查询改写，
    # 与 search_service 的 query_rewrite_hyde/sub_query 是两条独立实现路径，勿混用。
    "qa_rw_completion": (
        "你是一个对话助手。用户的问题是针对一段对话历史提出的，其中可能使用了代词或省略表达。\n"
        "请根据对话历史，将用户的问题补全为一个完整的、无需上下文就能理解的独立问题。\n"
        "只输出补全后的问题，不要任何解释。\n\n"
        "对话历史：\n{history}\n\n"
        "用户问题：{query}\n\n"
        "补全后的问题："
    ),

    "qa_rw_synonym": (
        "你是一个检索优化专家。请将用户的问题改写为更适合知识库检索的形式。\n"
        "要求：\n"
        "- 保留核心意图\n"
        "- 使用更精确的关键词\n"
        "- 去除口语化表达\n"
        "- 直接输出改写结果，不要解释\n\n"
        "用户问题：{query}\n\n"
        "改写后的检索查询："
    ),

    "qa_rw_decompose": (
        "你是一个问题分析专家。用户的问题是复合型的，包含多个子问题。\n"
        "请将问题拆解为多个独立的原子子问题，每个子问题只问一件事。\n"
        "每个子问题应能独立检索知识库。\n"
        "按从基础到进阶的顺序排列。\n\n"
        "输出格式：每行一个子问题，不要编号，不要解释。\n\n"
        "用户问题：{query}\n\n"
        "子问题："
    ),

    "qa_rw_hyde": (
        "你是一个知识库专家。用户提出了一个问题。\n"
        "请根据你的知识，生成一段假设性的文档片段，该文档应该包含回答该问题所需的关键信息。\n"
        "这段文档将用于检索相似的知识库文档，因此应该使用事实性、陈述性语言。\n\n"
        "用户问题：{query}\n\n"
        "假设文档："
    ),

    # ==================== GradeRetrier 检索后自评估 ====================
    # 运行时对多条检索结果整体打分（1-10）以决定是否重试；区别于 evaluation 的离线单 chunk 评估。
    "qa_grade_retrieval": (
        "你是一个检索质量评估专家。请根据用户问题，评估以下检索结果是否充分回答了问题。\n\n"
        "评估标准（1-10 分）：\n"
        "- 1-3 分：结果完全无关或严重不足\n"
        "- 4-5 分：部分相关但信息明显不全\n"
        "- 6-7 分：基本相关，能提供有用信息\n"
        "- 8-10 分：高度相关，信息充分\n\n"
        "输出格式（JSON）：\n"
        '{{"score": <分数>, "reason": "<简要理由（中文）>"}}\n\n'
        "用户问题：{query}\n\n"
        "检索结果：\n"
        "{results}\n"
    ),
}
