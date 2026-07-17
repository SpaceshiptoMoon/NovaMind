"""
知识空间模块提示词模板

覆盖：查询改写（HyDE / 子查询拆分）、知识库问答、VLM 图片/视频描述
"""

TEMPLATES = {
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

    # ==================== Video Frame Description (VLM) ====================
    "video_frame_description": (
        "你是一个视频内容分析助手。请用中文描述这个视频截图中的内容，要求：\n\n"
        "1. **场景与对象**：描述画面中的核心主体、人物、物体和整体场景\n"
        "2. **动作与事件**：描述画面中正在发生的动作、事件或活动\n"
        "3. **文字信息**：提取画面中所有可见的文字、标题、标签等（如有）\n\n"
        "请用1-3句话简洁描述，便于后续通过关键词检索到这个视频片段。\n"
        "描述长度控制在 100-300 字之间。"
    ),
}
