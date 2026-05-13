"""
提示词模板管理模块

统一管理项目中所有 LLM 提示词模板

模块分类：
1. 知识空间相关 - RAG 检索、文档处理
2. 深度研究相关 - 研究主题分析、任务分解、报告生成
3. 假设问题生成 - RAG 检索增强
4. 查询改写 - HyDE、子问题拆分
5. 问答系统相关 - 通用问答、文档问答、对话压缩
6. 知识库测评 - 检索评估、生成评估、Claim 验证
7. Agent 相关 - 系统提示词、上下文压缩
"""
from enum import Enum
from typing import Dict
import re


class PromptTemplate(Enum):
    """提示词模板枚举"""

    # ==================== 知识空间相关 ====================
    # RAG 检索
    CONTEXT_ANSWER = "context_answer"
    SUMMARIZE_CONTEXT = "summarize_context"

    # 文档处理
    DOC_SUMMARY = "doc_summary"
    DOC_HIGHLIGHT_EXTRACTION = "doc_highlight_extraction"
    DOC_TRANSLATE = "doc_translate"

    # ==================== 深度研究相关 ====================
    RESEARCH_ANALYZE_QUERY = "research_analyze_query"
    RESEARCH_DECOMPOSE_TASKS = "research_decompose_tasks"
    RESEARCH_SYNTHESIZE_REPORT = "research_synthesize_report"
    RESEARCH_SYNTHESIZE_REPORT_STREAM = "research_synthesize_report_stream"

    # ==================== 假设问题生成 ====================
    HYPOTHETICAL_QUESTION_SYSTEM = "hypothetical_question_system"
    HYPOTHETICAL_QUESTION_USER = "hypothetical_question_user"

    # ==================== 查询改写 ====================
    QUERY_REWRITE_HYDE_SYSTEM = "query_rewrite_hyde_system"
    QUERY_REWRITE_HYDE_USER = "query_rewrite_hyde_user"
    QUERY_REWRITE_SUB_QUERY_SYSTEM = "query_rewrite_sub_query_system"
    QUERY_REWRITE_SUB_QUERY_USER = "query_rewrite_sub_query_user"

    # ==================== 问答系统相关 ====================
    QA_GENERAL = "qa_general"
    QA_DOCUMENT_BASED = "qa_document_based"

    # ==================== 知识库测评相关 ====================
    # 检索评估
    EVAL_RETRIEVAL_RELEVANCE = "eval_retrieval_relevance"
    EVAL_CONTEXT_RECALL = "eval_context_recall"
    # 生成评估
    EVAL_CORRECTNESS = "eval_correctness"
    EVAL_QUALITY = "eval_quality"
    EVAL_FAITHFULNESS = "eval_faithfulness"
    EVAL_RELEVANCE = "eval_relevance"
    EVAL_REVERSE_QUESTION = "eval_reverse_question"
    # Claim 拆解验证
    EVAL_CLAIM_DECOMPOSE = "eval_claim_decompose"
    EVAL_CLAIM_VERIFY = "eval_claim_verify"
    # 测评回答生成
    EVAL_GENERATE_ANSWER = "eval_generate_answer"

    # ==================== Agent 相关 ====================
    AGENT_SYSTEM_PROMPT = "agent_system_prompt"
    AGENT_CONTEXT_COMPRESS = "agent_context_compress"

    # ==================== QA 对话补全 ====================
    QA_COMPRESSION_SUMMARY = "qa_compression_summary"
    QA_AI_CHAT_SYSTEM = "qa_ai_chat_system"


class PromptManager:
    """提示词管理器"""

    _templates: Dict[str, str] = {
        # ==================== 知识空间 - RAG 检索 ====================
        PromptTemplate.CONTEXT_ANSWER.value: (
            "你是一个专业、严谨的信息整合专家。请根据以下【用户问题】和【检索到的相关文档片段】，生成一段简洁、准确、逻辑连贯的总结性回答。\n"
            "要求：\n"
            "1. **严格基于检索到的文档内容**，不得编造未提及的信息；\n"
            "2. 若多个文档描述同一事实，请合并表述，避免重复；\n"
            "3. 若文档之间存在矛盾，请指出'不同来源说法不一致'；\n"
            "4. 若检索结果不足以回答问题，请明确说明'现有资料无法提供足够信息'；\n"
            "5. 使用正式、客观的书面语，分点或分段组织内容（如适用）；\n"
            "6. 优先保留关键数据、时间、名称、因果关系等核心信息。\n\n"
            "【用户问题】\n"
            "{query}\n\n"
            "【检索到的相关文档片段】\n"
            "{context}\n\n"
            "请生成回答："
        ),

        PromptTemplate.SUMMARIZE_CONTEXT.value: (
            "请对以下文本进行简洁准确的总结：\n\n{context}\n\n"
            "要求：突出重点信息，保持原文核心意思不变，长度不超过原文的30%。"
        ),

        # ==================== 知识空间 - 文档处理 ====================
        PromptTemplate.DOC_SUMMARY.value: (
            "请为以下文档生成一个简洁的摘要：\n\n{document}\n\n摘要要求：\n"
            "- 突出文档的主要观点\n- 保留关键信息\n- 长度控制在原文的20%-30%"
        ),

        PromptTemplate.DOC_HIGHLIGHT_EXTRACTION.value: (
            "请从以下文档中提取关键要点：\n\n{document}\n\n提取要求：\n"
            "- 识别重要概念和事实\n- 提取数字、日期、名称等具体信息\n"
            "- 按重要性排序列出要点"
        ),

        PromptTemplate.DOC_TRANSLATE.value: (
            "请将以下文本翻译成{target_language}：\n\n{document}\n\n"
            "翻译要求：\n- 保持原文意思不变\n- 符合目标语言的表达习惯\n"
            "- 专业术语请保持准确性"
        ),

        # ==================== 深度研究 - 主题分析 ====================
        PromptTemplate.RESEARCH_ANALYZE_QUERY.value: (
            "你是一个专业的研究主题分析师。请分析以下用户查询，提取一个简洁的研究主题。\n\n"
            "要求：\n"
            "1. 用一句话（不超过50字）概括研究主题\n"
            "2. 主题应准确反映查询的核心意图\n"
            "3. 使用正式、专业的表述\n\n"
            "用户查询：{query}\n\n"
            "研究主题："
        ),

        # ==================== 深度研究 - 任务分解 ====================
        PromptTemplate.RESEARCH_DECOMPOSE_TASKS.value: (
            "你是一个专业的研究任务规划师。请将以下研究主题分解为 {depth} 个具体的子任务。\n\n"
            "要求：\n"
            "1. 每个任务应可独立研究\n"
            "2. 任务之间应有逻辑顺序（先基础后深入）\n"
            "3. 返回 JSON 格式\n\n"
            "JSON 格式（直接输出 JSON，不要其他内容）：\n"
            "[\n"
            '  {{"task_id": "task_1", "description": "任务描述1", "priority": 1}},\n'
            '  {{"task_id": "task_2", "description": "任务描述2", "priority": 2}}\n'
            "]\n\n"
            "研究主题：{research_topic}\n"
            "用户查询：{query}\n"
            "任务数量：{depth}\n\n"
            "请返回任务列表（JSON）："
        ),

        # ==================== 深度研究 - 报告生成（非流式）====================
        PromptTemplate.RESEARCH_SYNTHESIZE_REPORT.value: (
            "你是一个专业的研究报告撰写专家。请基于以下信息，撰写一份深入、全面的研究报告。\n\n"
            "用户查询：{query}\n"
            "研究主题：{research_topic}\n\n"
            "检索到的信息来源：\n"
            "{context}\n\n"
            "关键来源：\n"
            "{key_sources}\n\n"
            "报告要求：\n"
            "1. 结构清晰，包含以下章节：\n"
            "   - 执行摘要（概述研究目的和主要发现）\n"
            "   - 背景介绍（研究背景和重要性）\n"
            "   - 主体内容（详细分析和发现，分点论述）\n"
            "   - 结论与建议（总结核心观点，提供实用建议）\n"
            "2. 严格基于检索到的信息，不编造内容\n"
            "3. 引用来源时标注（如 [来源1]、[来源2]）\n"
            "4. 使用正式、客观的学术语言\n"
            "5. 长度控制在 2000-3000 字\n"
            "6. 如信息不足，明确说明局限\n\n"
            "请撰写研究报告："
        ),

        # ==================== 深度研究 - 报告生成（流式）====================
        PromptTemplate.RESEARCH_SYNTHESIZE_REPORT_STREAM.value: (
            "你是一个专业的研究报告撰写专家。请基于以下信息，撰写一份深入、全面的研究报告。\n\n"
            "用户查询：{query}\n"
            "研究主题：{research_topic}\n\n"
            "检索到的信息来源：\n"
            "{context}\n\n"
            "报告要求：\n"
            "1. 结构清晰，包含以下章节：\n"
            "   - 执行摘要（概述研究目的和主要发现）\n"
            "   - 背景介绍（研究背景和重要性）\n"
            "   - 主体内容（详细分析和发现，分点论述）\n"
            "   - 结论与建议（总结核心观点，提供实用建议）\n"
            "2. 严格基于检索到的信息，不编造内容\n"
            "3. 使用正式、客观的学术语言\n"
            "4. 长度控制在 2000-3000 字\n\n"
            "请撰写研究报告："
        ),

        # ==================== 假设问题生成 - 系统提示词 ====================
        PromptTemplate.HYPOTHETICAL_QUESTION_SYSTEM.value: (
            "你是一个专业的知识库助手，擅长根据文本内容生成用户可能会问的问题。\n\n"
            "你的任务是根据给定的文本片段，生成 {max_questions} 个高质量的问题。这些问题应该：\n"
            "1. 必须且只能基于文本片段中实际出现的文字信息，禁止使用文本之外的任何人名、地名、机构名等实体\n"
            "2. 涵盖文本的核心信息和关键概念\n"
            "3. 模拟真实用户可能会问的问题（使用口语化表达）\n"
            "4. 包含不同类型：事实性问题、概念性问题、应用问题\n"
            "5. 问题应该简洁明了，避免过于复杂\n\n"
            "请直接输出 JSON 格式，不要有任何其他文字：\n"
            "[\n"
            '  {{"index": 1, "question": "问题1", "category": "factual"}},\n'
            '  {{"index": 2, "question": "问题2", "category": "conceptual"}},\n'
            "  ...\n"
            "]"
        ),

        # ==================== 假设问题生成 - 用户提示词 ====================
        PromptTemplate.HYPOTHETICAL_QUESTION_USER.value: (
            "文本内容：\n"
            "{separator}\n"
            "{chunk_content}\n"
            "{separator}\n\n"
            "请严格根据以上文本内容生成 {max_questions} 个问题（禁止使用文本内容之外的实体信息）："
        ),

        # ==================== 查询改写 - HyDE 系统提示词 ====================
        PromptTemplate.QUERY_REWRITE_HYDE_SYSTEM.value: (
            "你是一个专业的知识检索助手。你的任务是根据用户的查询，生成一段假设性的回答文档。\n\n"
            "要求：\n"
            "1. 回答应该是一段连贯的、包含丰富信息的文本\n"
            "2. 涵盖用户查询中可能涉及的关键概念和事实\n"
            "3. 使用正式、专业的表述\n"
            "4. 长度控制在 200-400 字\n"
            "5. 不需要完全准确，但要语义上合理，因为这段文本将用于检索相似文档"
        ),

        # ==================== 查询改写 - HyDE 用户提示词 ====================
        PromptTemplate.QUERY_REWRITE_HYDE_USER.value: (
            "用户查询：{query}\n\n"
            "请根据以上查询，生成一段假设性的回答文档（不需要完全准确，但要语义合理）："
        ),

        # ==================== 查询改写 - 子问题拆分系统提示词 ====================
        PromptTemplate.QUERY_REWRITE_SUB_QUERY_SYSTEM.value: (
            "你是一个专业的信息检索优化助手。你的任务是将用户的复杂查询拆分为多个具体的子问题，"
            "以便更全面地检索相关信息。\n\n"
            "要求：\n"
            "1. 每个子问题应该聚焦一个具体方面\n"
            "2. 子问题之间应互补，覆盖原查询的不同维度\n"
            "3. 子问题应便于在知识库中检索到相关内容\n"
            "4. 使用简洁、明确的表述\n\n"
            "请直接输出 JSON 格式，不要有任何其他文字：\n"
            "[\n"
            '  "子问题1",\n'
            '  "子问题2",\n'
            "  ...\n"
            "]"
        ),

        # ==================== 查询改写 - 子问题拆分用户提示词 ====================
        PromptTemplate.QUERY_REWRITE_SUB_QUERY_USER.value: (
            "用户查询：{query}\n"
            "拆分数量：{count}\n\n"
            "请将以上查询拆分为 {count} 个子问题："
        ),

        # ==================== 问答系统 - 通用问答 ====================
        PromptTemplate.QA_GENERAL.value: (
            "你是一个专业的问答助手，请回答用户的问题：\n\n问题：{query}\n\n请提供准确、有用的信息。"
        ),

        # ==================== 问答系统 - 基于文档问答 ====================
        PromptTemplate.QA_DOCUMENT_BASED.value: (
            "请仔细阅读以下文档内容，并据此回答用户的问题：\n\n文档内容：\n{document}\n\n"
            "用户问题：{query}\n\n注意事项：\n1. 答案必须基于提供的文档内容\n"
            "2. 如果文档中没有相关信息，请明确说明\n3. 请尽量引用文档中的具体信息支持答案"
        ),

        # ==================== 知识库测评 - 检索评估 ====================
        PromptTemplate.EVAL_RETRIEVAL_RELEVANCE.value: (
            "你是一个信息检索评估专家。\n\n"
            "给定一个问题和一段从知识库中检索到的文本，请判断该文本是否包含回答该问题所需的关键信息。\n\n"
            "判断标准：\n"
            "- relevant：文本包含直接回答问题所需的信息\n"
            "- not_relevant：文本与问题无关，或仅包含边缘信息\n\n"
            "问题：{question}\n"
            "检索文本：{chunk_content}\n\n"
            "请严格按以下 JSON 格式输出：\n"
            '{{"verdict": "relevant 或 not_relevant", "reason": "简要说明判断理由"}}'
        ),

        PromptTemplate.EVAL_CONTEXT_RECALL.value: (
            "你是一个信息检索评估专家。\n\n"
            "给定一个标准答案和一组检索到的上下文，请判断标准答案中的每个信息点是否可以从检索上下文中推导出来。\n\n"
            "步骤：\n"
            "1. 将标准答案拆解为独立的信息点（claims）\n"
            "2. 对每个信息点，判断它是否可以从检索上下文中推导\n\n"
            "标准答案：{expected_answer}\n"
            "检索上下文：\n"
            "{context_chunks}\n\n"
            "请按以下 JSON 格式输出：\n"
            '{{"claims": [{{"claim": "信息点内容", "supported": true或false}}, ...]}}'
        ),

        # ==================== 知识库测评 - 生成评估 ====================
        PromptTemplate.EVAL_CORRECTNESS.value: (
            "你是一个严格的评分专家。请对比 AI 回答与标准答案的语义一致性，给出 1-10 分。\n\n"
            "评分标准：\n"
            "- 9-10分：回答准确覆盖标准答案的所有关键信息\n"
            "- 7-8分：回答包含大部分关键信息，有小遗漏\n"
            "- 5-6分：回答包含部分关键信息，有明显遗漏或偏差\n"
            "- 3-4分：回答与标准答案差异较大\n"
            "- 1-2分：回答与标准答案几乎无关\n\n"
            "问题：{question}\n"
            "标准答案：{expected_answer}\n"
            "AI 回答：{generated_answer}\n\n"
            "请按以下 JSON 格式输出：\n"
            '{{"score": N, "reasoning": "简要说明评分理由"}}'
        ),

        PromptTemplate.EVAL_QUALITY.value: (
            "你是一个严格的 RAG 系统评分专家。请综合评价以下 AI 回答的质量（1-10分）。\n\n"
            "评价维度：\n"
            "- 完整性：回答是否完整地解答了问题\n"
            "- 条理性：回答是否有清晰的逻辑结构\n"
            "- 可读性：回答是否表达清晰、易于理解\n\n"
            "问题：{question}\n"
            "AI 回答：{generated_answer}\n\n"
            "请按以下 JSON 格式输出：\n"
            '{{"quality": N, "reasoning": "简要说明评分理由"}}'
        ),

        PromptTemplate.EVAL_FAITHFULNESS.value: (
            "你是一个严格的 RAG 系统评分专家。请评估 AI 回答的忠实度（1-10分）。\n\n"
            "忠实度评估标准：\n"
            "- 回答是否仅基于给定的检索上下文，没有编造上下文中不存在的信息\n"
            "- 9-10分：回答完全基于上下文，无任何编造\n"
            "- 7-8分：有轻微的不确定信息，但总体忠实\n"
            "- 5-6分：部分信息来自上下文外的知识\n"
            "- 3-4分：有明显的编造信息\n"
            "- 1-2分：回答几乎不基于上下文\n\n"
            "检索上下文：\n"
            "{context}\n\n"
            "问题：{question}\n"
            "AI 回答：{generated_answer}\n\n"
            "请按以下 JSON 格式输出：\n"
            '{{"score": N, "reasoning": "简要说明评分理由"}}'
        ),

        PromptTemplate.EVAL_RELEVANCE.value: (
            "你是一个严格的评分专家。请评估 AI 回答与原始问题的相关性（1-10分）。\n\n"
            "评估标准：\n"
            "- 9-10分：回答完全针对问题，内容直接相关\n"
            "- 7-8分：回答基本针对问题，有少量偏题\n"
            "- 5-6分：回答部分针对问题，有明显无关内容\n"
            "- 3-4分：回答与问题关联较弱\n"
            "- 1-2分：回答与问题几乎无关\n\n"
            "问题：{question}\n"
            "AI 回答：{generated_answer}\n\n"
            "请按以下 JSON 格式输出：\n"
            '{{"score": N, "reasoning": "简要说明评分理由"}}'
        ),

        PromptTemplate.EVAL_REVERSE_QUESTION.value: (
            "请根据以下 AI 回答，生成 3 个可能的原始问题。这些问题应该能够被该回答所解答。\n\n"
            "AI 回答：\n"
            "{generated_answer}\n\n"
            "请按以下 JSON 格式输出：\n"
            '{{"generated_questions": ["问题1", "问题2", "问题3"]}}'
        ),

        # ==================== 知识库测评 - Claim 拆解验证 ====================
        PromptTemplate.EVAL_CLAIM_DECOMPOSE.value: (
            "请将以下 AI 回答拆解为独立的客观陈述（claims）。每个 claim 应该是一个可以独立验证的事实性陈述。\n\n"
            "规则：\n"
            "- 只提取事实性陈述，排除观点和过渡语句\n"
            "- 每个 claim 应尽可能原子化（只包含一个事实）\n"
            "- 保持原始语义不变\n\n"
            "AI 回答：\n"
            "{generated_answer}\n\n"
            "请按以下 JSON 格式输出：\n"
            '{{"claims": ["claim 1", "claim 2", ...]}}'
        ),

        PromptTemplate.EVAL_CLAIM_VERIFY.value: (
            "请验证以下 claim 是否可以从给定的检索上下文中推导出来。\n\n"
            "检索上下文：\n"
            "{context}\n\n"
            "待验证的 Claim：{claim}\n\n"
            "请判断该 claim 是否被上下文所支持。如果上下文中没有明确包含该信息，"
            "或者无法从上下文中合理推导，则判定为不支持。\n\n"
            "请按以下 JSON 格式输出：\n"
            '{{"supported": true或false, "evidence": "引用上下文中的相关内容或说明不支持的原因"}}'
        ),

        # ==================== 知识库测评 - 回答生成 ====================
        PromptTemplate.EVAL_GENERATE_ANSWER.value: (
            "请根据以下检索到的上下文回答问题。只使用上下文中包含的信息来回答，不要编造信息。\n\n"
            "检索上下文：\n"
            "{context_text}\n\n"
            "问题：{question}\n\n"
            "请直接给出回答："
        ),

        # ==================== Agent - 系统提示词 ====================
        PromptTemplate.AGENT_SYSTEM_PROMPT.value: (
            "你是一个智能助手，可以使用工具来帮助用户完成任务。\n\n"
            "工作方式：\n"
            "1. 仔细理解用户的需求\n"
            "2. 如果需要查找信息或执行操作，使用可用的工具\n"
            "3. 根据工具返回的结果，综合分析后给出准确、有用的回答\n"
            "4. 如果现有工具无法满足需求，坦诚告知用户\n\n"
            "注意事项：\n"
            "- 优先使用工具获取真实数据，不要编造信息\n"
            "- 每次工具调用后，基于结果进行分析再决定下一步\n"
            "- 回答时用清晰、准确的语言，必要时引用数据来源\n\n"
            "当前可用技能：{skills}\n"
            "当前日期：{current_date}"
        ),

        # ==================== Agent - 上下文压缩 ====================
        PromptTemplate.AGENT_CONTEXT_COMPRESS.value: (
            "请将以下对话历史压缩为简洁的摘要，保留关键信息和上下文：\n\n"
            "{conversation}\n\n"
            "摘要要求：\n"
            "1. 保留所有关键事实、数据、决策\n"
            "2. 保留用户的核心需求和意图\n"
            "3. 保留已执行的工具调用及其关键结果\n"
            "4. 去除重复和冗余信息\n"
            "5. 长度控制在 500 字以内"
        ),

        # ==================== QA - 对话压缩摘要 ====================
        PromptTemplate.QA_COMPRESSION_SUMMARY.value: (
            "你是一个专业的对话压缩助手。你的任务是将旧消息压缩为简洁的摘要，保留关键信息和上下文。\n\n"
            "压缩要求:\n"
            "1. 保留对话的主要话题和意图\n"
            "2. 保留关键实体（人名、地点、时间、数字等）\n"
            "3. 保留重要决策和结论\n"
            "4. 保留用户的核心需求\n"
            "5. 使用简洁的自然语言\n"
            "6. 控制摘要长度在 150-200 字\n\n"
            "输出格式:\n"
            "直接输出摘要内容，不要添加任何前缀或说明。"
        ),

        # ==================== QA - AI 对话系统提示 ====================
        PromptTemplate.QA_AI_CHAT_SYSTEM.value: (
            "You are a helpful assistant."
        ),
    }

    @classmethod
    def get_template(cls, template_name: str) -> str:
        """
        获取提示词模板

        Args:
            template_name: 模板名称（PromptTemplate 枚举值）

        Returns:
            模板字符串

        Raises:
            ValueError: 模板不存在
        """
        if template_name not in cls._templates:
            raise ValueError(f"模板 '{template_name}' 不存在")
        return cls._templates[template_name]

    @classmethod
    def format_prompt(cls, template_name: str, **kwargs) -> str:
        """
        格式化提示词

        Args:
            template_name: 模板名称（PromptTemplate 枚举值）
            **kwargs: 模板参数

        Returns:
            格式化后的提示词

        Raises:
            ValueError: 模板不存在或缺少参数
        """
        template = cls.get_template(template_name)

        # 检查是否缺少必要的参数
        missing_params = cls._find_missing_params(template, **kwargs)
        if missing_params:
            raise ValueError(f"模板 '{template_name}' 缺少必要的参数: {', '.join(missing_params)}")

        return template.format(**kwargs)

    @classmethod
    def add_template(cls, template_name: str, template_content: str):
        """
        添加新的提示词模板

        Args:
            template_name: 模板名称
            template_content: 模板内容
        """
        cls._templates[template_name] = template_content

    @classmethod
    def update_template(cls, template_name: str, template_content: str):
        """
        更新现有的提示词模板

        Args:
            template_name: 模板名称
            template_content: 新的模板内容

        Raises:
            ValueError: 模板不存在
        """
        if template_name not in cls._templates:
            raise ValueError(f"模板 '{template_name}' 不存在")
        cls._templates[template_name] = template_content

    @classmethod
    def list_templates(cls) -> Dict[str, str]:
        """
        列出所有可用模板

        Returns:
            模板名称到描述的映射
        """
        descriptions = {
            # 知识空间
            PromptTemplate.CONTEXT_ANSWER.value: "基于检索上下文生成回答",
            PromptTemplate.SUMMARIZE_CONTEXT.value: "总结上下文内容",
            PromptTemplate.DOC_SUMMARY.value: "生成文档摘要",
            PromptTemplate.DOC_HIGHLIGHT_EXTRACTION.value: "提取文档关键要点",
            PromptTemplate.DOC_TRANSLATE.value: "文档翻译",
            # 深度研究
            PromptTemplate.RESEARCH_ANALYZE_QUERY.value: "分析研究查询，提取主题",
            PromptTemplate.RESEARCH_DECOMPOSE_TASKS.value: "分解研究任务为子任务",
            PromptTemplate.RESEARCH_SYNTHESIZE_REPORT.value: "综合信息生成研究报告（非流式）",
            PromptTemplate.RESEARCH_SYNTHESIZE_REPORT_STREAM.value: "综合信息生成研究报告（流式）",
            # 假设问题生成
            PromptTemplate.HYPOTHETICAL_QUESTION_SYSTEM.value: "假设问题生成 - 系统提示词",
            PromptTemplate.HYPOTHETICAL_QUESTION_USER.value: "假设问题生成 - 用户提示词",
            # 查询改写
            PromptTemplate.QUERY_REWRITE_HYDE_SYSTEM.value: "查询改写 HyDE - 系统提示词",
            PromptTemplate.QUERY_REWRITE_HYDE_USER.value: "查询改写 HyDE - 用户提示词",
            PromptTemplate.QUERY_REWRITE_SUB_QUERY_SYSTEM.value: "查询改写子问题拆分 - 系统提示词",
            PromptTemplate.QUERY_REWRITE_SUB_QUERY_USER.value: "查询改写子问题拆分 - 用户提示词",
            # 问答系统
            PromptTemplate.QA_GENERAL.value: "通用问答",
            PromptTemplate.QA_DOCUMENT_BASED.value: "基于文档的问答",
            # 知识库测评
            PromptTemplate.EVAL_RETRIEVAL_RELEVANCE.value: "检索相关性判断",
            PromptTemplate.EVAL_CONTEXT_RECALL.value: "上下文召回评估",
            PromptTemplate.EVAL_CORRECTNESS.value: "正确性评分",
            PromptTemplate.EVAL_QUALITY.value: "质量评分",
            PromptTemplate.EVAL_FAITHFULNESS.value: "忠实度评分",
            PromptTemplate.EVAL_RELEVANCE.value: "相关性评分",
            PromptTemplate.EVAL_REVERSE_QUESTION.value: "反向问题生成",
            PromptTemplate.EVAL_CLAIM_DECOMPOSE.value: "Claim 拆解",
            PromptTemplate.EVAL_CLAIM_VERIFY.value: "Claim 验证",
            PromptTemplate.EVAL_GENERATE_ANSWER.value: "测评回答生成",
            # Agent
            PromptTemplate.AGENT_SYSTEM_PROMPT.value: "Agent 系统提示词",
            PromptTemplate.AGENT_CONTEXT_COMPRESS.value: "Agent 上下文压缩",
            # QA 对话补全
            PromptTemplate.QA_COMPRESSION_SUMMARY.value: "对话压缩摘要",
            PromptTemplate.QA_AI_CHAT_SYSTEM.value: "AI 对话默认系统提示",
        }
        return descriptions

    @classmethod
    def _find_missing_params(cls, template: str, **kwargs) -> list:
        """
        查找模板中缺失的参数

        Args:
            template: 模板字符串
            **kwargs: 提供的参数

        Returns:
            缺失参数列表
        """
        # 提取模板中所有的参数名（花括号内的名称）
        param_pattern = r'\{(\w+)\}'
        required_params = set(re.findall(param_pattern, template))

        # 提供的参数
        provided_params = set(kwargs.keys())

        return list(required_params - provided_params)


# 便捷函数
def get_prompt(template_name: str) -> str:
    """获取提示词模板"""
    return PromptManager.get_template(template_name)


def format_prompt(template_name: str, **kwargs) -> str:
    """格式化提示词"""
    return PromptManager.format_prompt(template_name, **kwargs)


__all__ = [
    "PromptTemplate",
    "PromptManager",
    "get_prompt",
    "format_prompt",
]
