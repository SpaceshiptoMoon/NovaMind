"""
Deep Research module prompt templates

Covers: research topic analysis, task decomposition, report generation (stream/non-stream),
iterative retrieval reflection (query evolution + sufficiency, aligned with deer-flow) and
per-task finding summarization
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

    # ==================== 结构化规划（deer-flow planner 对齐） ====================

    "research_plan": (
        "You are a professional Deep Researcher. Study the research topic and produce a "
        "structured information-gathering plan.\n\n"
        "The final goal is a thorough, detailed report, so collect abundant information "
        "across multiple aspects. Insufficient information yields an inadequate report.\n\n"
        "Research topic: {research_topic}\n"
        "User query: {query}\n"
        "Max number of steps: {depth}\n"
        "Planning iteration: {iteration}\n\n"
        "Background investigation results of the user query:\n"
        "<background_results>\n{background_results}\n</background_results>\n\n"
        "User feedback on the previous plan (apply it when revising):\n"
        "<feedback>\n{feedback}\n</feedback>\n\n"
        "## Context Assessment (apply very strict criteria)\n"
        "Set \"has_enough_context\" to true ONLY IF the background investigation results "
        "already fully answer ALL aspects of the query with specific, reliable details. "
        "Even if you're 90% certain, choose to gather more. When in doubt, set false.\n\n"
        "## Step Types\n"
        "1. Research steps (\"step_type\": \"research\", \"need_search\": true): gather "
        "data — market info, historical facts, statistics, current events, comparisons.\n"
        "2. Processing steps (\"step_type\": \"processing\", \"need_search\": false): pure "
        "analysis — cross-validate findings, synthesize insights, compare perspectives, "
        "draw conclusions. Use SPARINGLY: at most one per plan, placed last.\n"
        "The plan MUST include at least one research step — without retrieval the report "
        "will contain fabricated data.\n\n"
        "## Output\n"
        "Return STRICT JSON only (no markdown fences, no extra text):\n"
        "{{\n"
        "  \"has_enough_context\": false,\n"
        "  \"thought\": \"one-sentence reasoning about the plan\",\n"
        "  \"title\": \"plan title\",\n"
        "  \"steps\": [\n"
        "    {{\"need_search\": true, \"title\": \"step title\", \"description\": "
        "\"exactly what data to collect\", \"step_type\": \"research\"}}\n"
        "  ]\n"
        "}}\n"
        "Steps must be independently researchable, logically ordered (foundational "
        "before advanced), and cover different dimensions. Max {depth} steps.\n\n"
        "Return the plan (JSON):"
    ),

    "research_processing_step": (
        "You are a research analyst executing a PURE ANALYSIS step (no retrieval "
        "available). Synthesize the findings from already-completed research steps "
        "into the conclusion this step asks for.\n\n"
        "Step title: {step_title}\n"
        "Step description: {task_description}\n\n"
        "Findings from completed steps:\n"
        "<findings>\n{prior_findings}\n</findings>\n\n"
        "Requirements:\n"
        "1. Base your analysis STRICTLY on the findings above — do not invent data\n"
        "2. Note explicitly if the findings are insufficient for a solid conclusion\n"
        "3. Use the same language as the step description\n"
        "4. Max 400 words, structured output\n\n"
        "Analysis conclusion:"
    ),

    # ==================== 迭代检索反思（deer-flow 对齐） ====================

    "research_generate_query": (
        "You are a research retrieval specialist. You are executing ONE research task "
        "through iterative retrieval rounds. Based on the observations gathered so far, "
        "decide whether the collected information is sufficient, and if not, produce "
        "the NEXT retrieval query.\n\n"
        "Task description: {task_description}\n\n"
        "Current iteration (1-based): {iteration}\n"
        "Previous query used: {current_query}\n\n"
        "Observations gathered so far (truncated):\n"
        "<observations>\n{observations}\n</observations>\n\n"
        "Findings from already-completed sibling tasks (do NOT repeat their angles):\n"
        "<prior_findings>\n{prior_findings}\n</prior_findings>\n\n"
        "Rules:\n"
        "1. Set \"sufficient\" to true ONLY IF the observations concretely answer the "
        "task description with specific facts, data, or citations. When in doubt, "
        "gather more.\n"
        "2. If not sufficient, \"next_query\" must fill the SPECIFIC gap: more precise "
        "keywords, a different angle, or a sub-aspect not yet covered. NEVER reuse the "
        "previous query verbatim. Write the query in the same language as the task "
        "description.\n"
        "3. Keep \"next_query\" concise (under 60 characters), suitable for a search "
        "engine or knowledge-base retrieval.\n"
        "4. Output STRICT JSON only, no markdown fences, no extra text:\n"
        '{{"sufficient": false, "next_query": "...", "reason": "one short sentence"}}'
    ),

    "research_task_finding": (
        "You are a research summarizer. Compress the observations of ONE completed "
        "research task into a concise finding note. Later sibling tasks will read this "
        "note to avoid redundant searching and to build on what is already known.\n\n"
        "Task description: {task_description}\n\n"
        "Observations (truncated):\n"
        "<observations>\n{observations}\n</observations>\n\n"
        "Requirements:\n"
        "1. 3-5 bullet points: key facts, data points, or conclusions with their sources\n"
        "2. Explicitly note what is still unknown or uncertain (if any)\n"
        "3. Use the same language as the task description\n"
        "4. Max 300 words. Output the finding note directly, no extra commentary\n\n"
        "Finding note:"
    ),
}
