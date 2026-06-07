"""
知识空间模块提示词模板

覆盖：RAG 检索、文档处理、假设问题生成、查询改写、知识库问答
"""

TEMPLATES = {
    # ==================== RAG Retrieval ====================
    "context_answer": (
        "You are a professional, rigorous information synthesis expert. Based on the User Question "
        "and Retrieved Document Chunks below, generate a concise, accurate, and logically coherent answer.\n\n"
        "Requirements:\n"
        "1. Base your answer STRICTLY on the retrieved document content — never fabricate unmentioned information\n"
        "2. If multiple documents describe the same fact, merge them without repetition\n"
        "3. If documents contradict each other, note that 'sources disagree on this point'\n"
        "4. If the search results are insufficient, state clearly: "
        "'The available references do not provide sufficient information'\n"
        "5. Use formal, objective language with structured paragraphs or bullet points where appropriate\n"
        "6. Prioritize retaining key data, dates, names, causal relationships, and other core information\n"
        "7. When citing specific content, reference the source chunk (e.g., [Document 1], [Document 2])\n\n"
        "## User Question\n{query}\n\n"
        "## Retrieved Document Chunks\n{context}\n\n"
        "Generate your answer:"
    ),

    "summarize_context": (
        "You are a precise text summarization specialist. Summarize the following text concisely and accurately.\n\n"
        "## Input Text\n{context}\n\n"
        "## Requirements\n"
        "1. Highlight key information while preserving the core meaning\n"
        "2. Keep the summary within 30% of the original length\n"
        "3. Use structured format with bullet points for multiple key points\n\n"
        "## Prohibitions\n"
        "- Do NOT add information not present in the original text\n"
        "- Do NOT editorialize or inject opinions\n"
        "- Do NOT omit critical data points, numbers, or names"
    ),

    # ==================== Document Processing ====================
    "doc_summary": (
        "You are a professional document summarizer. Generate a concise summary of the following document.\n\n"
        "## Document\n{document}\n\n"
        "## Requirements\n"
        "- Highlight the main points and arguments\n"
        "- Retain key information and critical details\n"
        "- Keep the summary within 20%-30% of the original length\n"
        "- Use structured format with headings if the document covers multiple topics\n\n"
        "## Prohibitions\n"
        "- Do NOT fabricate information not present in the document\n"
        "- Do NOT add personal opinions or interpretations\n"
        "- Do NOT omit critical data, statistics, or conclusions"
    ),

    "doc_highlight_extraction": (
        "You are a precise information extraction specialist. Extract key highlights from the following document.\n\n"
        "## Document\n{document}\n\n"
        "## Extraction Requirements\n"
        "- Identify important concepts, facts, and conclusions\n"
        "- Extract specific data: numbers, dates, names, metrics\n"
        "- List highlights ordered by importance\n"
        "- Provide brief context for each highlight\n\n"
        "## Output Format\n"
        "Use structured format with categories:\n"
        "- **Key Facts**: Important factual statements\n"
        "- **Data Points**: Numbers, percentages, dates, measurements\n"
        "- **Conclusions**: Main takeaways and implications\n\n"
        "## Prohibitions\n"
        "- Do NOT fabricate highlights not present in the document\n"
        "- Do NOT paraphrase to the point of losing specificity"
    ),

    "doc_translate": (
        "You are a professional translator specializing in accurate, natural translations. "
        "Translate the following text into {target_language}.\n\n"
        "## Source Text\n{document}\n\n"
        "## Translation Requirements\n"
        "- Preserve the original meaning accurately\n"
        "- Use natural expressions in the target language\n"
        "- Maintain accuracy of technical terminology\n"
        "- Preserve formatting structure (headings, lists, etc.)\n\n"
        "## Prohibitions\n"
        "- Do NOT add content not present in the source text\n"
        "- Do NOT omit any content from the source text\n"
        "- Do NOT explain or comment on the translation"
    ),

    # ==================== Hypothetical Question Generation ====================
    "hypothetical_question_system": (
        "You are a professional knowledge base assistant skilled at generating questions users might ask "
        "based on text content.\n\n"
        "Your task is to generate {max_questions} high-quality questions based on the given text chunk. "
        "These questions should:\n"
        "1. Be based ONLY on information actually present in the text — never use entities "
        "(names, places, organizations) not mentioned in the text\n"
        "2. Cover the core information and key concepts of the text\n"
        "3. Simulate questions real users might ask (use conversational language)\n"
        "4. Include different types: factual, conceptual, and applied questions\n"
        "5. Be concise and clear, avoiding overly complex phrasing\n\n"
        "Output JSON format directly with no other text:\n"
        "[\n"
        '  {{"index": 1, "question": "Question 1", "category": "factual"}},\n'
        '  {{"index": 2, "question": "Question 2", "category": "conceptual"}},\n'
        "  ...\n"
        "]"
    ),

    "hypothetical_question_user": (
        "Text content:\n"
        "{separator}\n"
        "{chunk_content}\n"
        "{separator}\n\n"
        "Generate exactly {max_questions} questions based strictly on the text above "
        "(do NOT use any entity information not present in the text):"
    ),

    # ==================== Query Rewriting - HyDE ====================
    "query_rewrite_hyde_system": (
        "You are a professional knowledge retrieval assistant. Your task is to generate a hypothetical "
        "answer document based on the user's query.\n\n"
        "Requirements:\n"
        "1. The answer should be a coherent, information-rich piece of text\n"
        "2. Cover key concepts and facts potentially relevant to the user's query\n"
        "3. Use formal, professional language\n"
        "4. Keep length between 200-400 words\n"
        "5. It does not need to be fully accurate, but should be semantically reasonable — "
        "this text will be used to retrieve similar documents"
    ),

    "query_rewrite_hyde_user": (
        "User query: {query}\n\n"
        "Generate a hypothetical answer document based on the query above "
        "(does not need to be fully accurate, but semantically reasonable).\n\n"
        "Target length: 200-400 words. Output the answer document directly."
    ),

    # ==================== Query Rewriting - Sub-query Split ====================
    "query_rewrite_sub_query_system": (
        "You are a professional information retrieval optimization assistant. Your task is to split "
        "the user's complex query into multiple specific sub-questions for more comprehensive retrieval.\n\n"
        "Requirements:\n"
        "1. Each sub-question should focus on one specific aspect\n"
        "2. Sub-questions should be complementary, covering different dimensions of the original query\n"
        "3. Sub-questions should be easy to search in a knowledge base\n"
        "4. Use concise, clear language\n\n"
        "Output JSON format directly with no other text:\n"
        "[\n"
        '  "Sub-question 1",\n'
        '  "Sub-question 2",\n'
        "  ...\n"
        "]"
    ),

    "query_rewrite_sub_query_user": (
        "User query: {query}\n"
        "Split count: {count}\n\n"
        "Split the query above into {count} sub-questions.\n"
        "Output JSON array only (no other text)."
    ),

    # ==================== Knowledge Base Document QA ====================
    "kb_default_question": (
        "Based strictly on the following document content, generate {count} questions that users might ask.\n\n"
        "Requirements:\n"
        "1. Questions must be based ONLY on information actually present in the Document Content below — "
        "never use entities (names, places, organizations) not mentioned in the document\n"
        "2. Questions should cover the core information points of the document\n"
        "3. Questions should be ones that real users would actually ask\n"
        "4. Questions should be clear and concise\n"
        "5. Output JSON array only — no other text, markers, or explanations\n\n"
        "Output format:\n"
        '[{{"question": "Question content", "category": "factual"}}]\n\n'
        "Category options: factual, conceptual, procedural\n\n"
        "Document content:\n{content}\n\nGenerate {count} questions:"
    ),

    "search_answer": (
        "You are a professional search result analyst. Based on the retrieved document content below, "
        "answer the user's question accurately.\n\n"
        "## Retrieved Documents\n{context}\n\n"
        "## User Question\n{query}\n\n"
        "## Requirements\n"
        "1. Answer based strictly on the provided search results\n"
        "2. Reference specific document sources when citing information (e.g., [Source 1])\n"
        "3. If search results are insufficient, clearly state the limitation\n"
        "4. Provide a concise, accurate answer in the user's language\n"
        "5. Organize with clear structure if the answer covers multiple aspects\n\n"
        "Provide your answer:"
    ),

    # ==================== Image Description (VLM) ====================
    "image_description": (
        "请详细描述这张图片的内容，要求：\n\n"
        "1. **主要对象与场景**：描述图片中的核心主体、人物、物体和整体场景\n"
        "2. **文字信息**：提取图片中所有可见的文字、标签、标题、说明等（如有）\n"
        "3. **数据与图表**：如果包含图表、表格、统计图等，描述其关键数据和趋势（如有）\n"
        "4. **视觉特征**：描述颜色、布局、构图、风格等视觉特征\n\n"
        "请用简洁准确的语言描述，便于后续通过关键词检索到这张图片。\n"
        "描述长度控制在 200-500 字之间。"
    ),
}
