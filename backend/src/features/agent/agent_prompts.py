"""
Agent 模块提示词模板

覆盖：长期记忆提取。压缩摘要/融合/系统提示等引擎侧模板在
engines/agent/prompts.py（agent_engine_* 前缀）——此处旧版摘要/系统提示
模板已删除（与引擎内置版漂移，引擎版是权威实现）。
"""

TEMPLATES = {
    "agent_long_term_memory": (
        "You are an information extraction specialist. Extract key information worth remembering long-term from the conversation below.\n\n"
        "## When to Extract\n"
        "- User corrections or explicit preferences (\"remember this\", \"don't do that\")\n"
        "- User-shared facts: name, role, timezone, coding style, preferences\n"
        "- Environment discoveries: OS, tools, project structure, conventions\n"
        "- Stable facts that will be useful in future sessions\n\n"
        "## Priority\n"
        "User preferences and corrections > environment facts > procedural knowledge\n\n"
        "## Rules\n"
        "1. Only extract clear, valuable information — skip greetings and irrelevant content\n"
        "2. Each item must be self-contained and complete\n"
        "3. Categorize each item as one of:\n"
        "   - preference: Explicit user preferences (e.g., \"I prefer concise responses\")\n"
        "   - fact: Factual information (e.g., \"Project uses Python 3.12\")\n"
        "   - procedure: Operational steps or workflows (e.g., \"Deploy process is...\")\n"
        "   - insight: Valuable observations or conclusions\n"
        "4. Write as declarative facts, NOT instructions: 'User prefers concise responses' (correct) — 'Always respond concisely' (wrong)\n"
        "5. Do NOT save: task progress, session outcomes, completed-work logs, or temporary TODO state\n"
        "6. If nothing is worth remembering, return an empty array\n\n"
        "Conversation:\n{conversation_text}\n\n"
        "Return a JSON array with category and content fields:\n"
        '[{{"category": "fact", "content": "..."}}, ...]'
    ),
}

