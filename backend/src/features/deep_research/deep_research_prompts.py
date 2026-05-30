"""
Deep Research module prompt templates

Covers: research topic analysis, task decomposition, report generation (stream/non-stream)
"""

TEMPLATES = {
    "research_analyze_query": (
        "You are a professional research topic analyst. Analyze the following user query "
        "and extract a concise research topic.\n\n"
        "Requirements:\n"
        "1. Summarize the research topic in one sentence (max 50 characters in original language)\n"
        "2. The topic should accurately reflect the core intent of the query\n"
        "3. Use formal, professional expression\n\n"
        "User query: {query}\n\n"
        "Research topic:"
    ),

    "research_decompose_tasks": (
        "You are a professional research task planner. Decompose the following research topic "
        "into {depth} specific sub-tasks.\n\n"
        "Requirements:\n"
        "1. Each task should be independently researchable\n"
        "2. Tasks should follow a logical order (foundational before advanced)\n"
        "3. Tasks should be complementary, covering different dimensions of the topic\n"
        "4. Return JSON format directly with no other content\n\n"
        "JSON format:\n"
        "[\n"
        '  {{"task_id": "task_1", "description": "Task description", "priority": 1}},\n'
        '  {{"task_id": "task_2", "description": "Task description", "priority": 2}}\n'
        "]\n\n"
        "Research topic: {research_topic}\n"
        "User query: {query}\n"
        "Number of tasks: {depth}\n\n"
        "Return the task list (JSON):"
    ),

    "research_synthesize_report": (
        "You are an expert research report writer. Based on the information below, "
        "write a comprehensive research report.\n\n"
        "User query: {query}\n"
        "Research topic: {research_topic}\n\n"
        "Retrieved information sources:\n"
        "{context}\n\n"
        "Key sources:\n"
        "{key_sources}\n\n"
        "Report requirements:\n"
        "1. Clear structure with the following sections:\n"
        "   - Executive Summary (research purpose and key findings)\n"
        "   - Background (context and significance)\n"
        "   - Main Content (detailed analysis and findings with subsections)\n"
        "   - Conclusions & Recommendations (core insights with actionable recommendations)\n"
        "2. Strictly based on retrieved information — never fabricate content\n"
        "3. Cite sources when referencing (e.g., [Source 1], [Source 2])\n"
        "4. Use formal, objective academic language\n"
        "5. Target length: 2000-3000 words\n"
        "6. If information is insufficient, clearly state the limitations\n\n"
        "Write the research report:"
    ),

    "research_synthesize_report_stream": (
        "You are an expert research report writer. Based on the information below, "
        "write a comprehensive research report.\n\n"
        "User query: {query}\n"
        "Research topic: {research_topic}\n\n"
        "Retrieved information sources:\n"
        "{context}\n\n"
        "Report requirements:\n"
        "1. Clear structure with the following sections:\n"
        "   - Executive Summary (research purpose and key findings)\n"
        "   - Background (context and significance)\n"
        "   - Main Content (detailed analysis and findings with subsections)\n"
        "   - Conclusions & Recommendations (core insights with actionable recommendations)\n"
        "2. Strictly based on retrieved information — never fabricate content\n"
        "3. Use formal, objective academic language\n"
        "4. Target length: 2000-3000 words\n"
        "5. If information is insufficient, clearly state the limitations\n\n"
        "Write the research report:"
    ),
}
