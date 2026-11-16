"""
Evaluation module prompt templates

Covers: retrieval evaluation, generation evaluation, claim decomposition, answer generation
"""

TEMPLATES = {
    # ==================== Retrieval Evaluation ====================
    "eval_retrieval_relevance": (
        "You are an information retrieval evaluation expert.\n\n"
        "Given a question and a text chunk retrieved from a knowledge base, determine whether "
        "the chunk contains key information needed to answer the question.\n\n"
        "## Judgment Criteria\n"
        "- relevant: The chunk contains information that directly answers the question\n"
        "- not_relevant: The chunk is unrelated to the question or contains only marginal information\n"
        "- If the chunk is partially relevant but does not directly answer the question, lean toward 'not_relevant'\n\n"
        "## Prohibitions\n"
        "- Judge based ONLY on the provided chunk and question — do not introduce external knowledge\n"
        "- Do NOT fabricate relevance where none exists\n\n"
        "Question: {question}\n"
        "Retrieved chunk: {chunk_content}\n\n"
        "Output JSON only (no other text):\n"
        '{{"verdict": "relevant or not_relevant", "reason": "Brief explanation of the judgment"}}'
    ),

    "eval_context_recall": (
        "You are an information retrieval evaluation expert.\n\n"
        "Given a reference answer and a set of retrieved context chunks, determine whether "
        "each information point in the reference answer can be derived from the retrieved context.\n\n"
        "## Steps\n"
        "1. Decompose the reference answer into independent information points (claims)\n"
        "2. For each claim, determine if it can be derived from the retrieved context\n\n"
        "## Rules\n"
        "- If a claim can be reasonably inferred from the context, judge it as supported — even if not stated verbatim\n"
        "- If a claim is ambiguous or requires external knowledge, judge it as not supported\n"
        "- Base your judgment ONLY on the provided context — do not use external knowledge\n\n"
        "Reference answer: {expected_answer}\n"
        "Retrieved context:\n"
        "{context_chunks}\n\n"
        "Output JSON only (no other text):\n"
        '{{"claims": [{{"claim": "Information point content", "supported": true/false}}, ...]}}'
    ),

    # ==================== Generation Evaluation ====================
    "eval_correctness": (
        "You are a strict scoring expert. Compare the AI answer with the reference answer "
        "for semantic consistency and score 1-10.\n\n"
        "## Scoring Criteria\n"
        "- 9-10: Answer accurately covers ALL key information in the reference answer\n"
        "- 7-8: Answer covers most key information with minor omissions\n"
        "- 5-6: Answer covers some key information with notable omissions or deviations\n"
        "- 3-4: Answer differs significantly from the reference answer\n"
        "- 1-2: Answer is essentially unrelated to the reference answer\n\n"
        "## Requirements\n"
        "- In 'reasoning', quote specific phrases from both answers to justify the score\n"
        "- Do NOT give generic reasoning — reference concrete content\n"
        "- Respond in the same language as the input\n\n"
        "Question: {question}\n"
        "Reference answer: {expected_answer}\n"
        "AI answer: {generated_answer}\n\n"
        "Output JSON only (no other text):\n"
        '{{"score": N, "reasoning": "Brief explanation referencing specific content from both answers"}}'
    ),

    "eval_quality": (
        "You are a strict RAG system scoring expert. Evaluate the overall quality of the "
        "AI answer on a scale of 1-10.\n\n"
        "## Evaluation Dimensions\n"
        "- Completeness: Does the answer fully address the question?\n"
        "- Coherence: Does the answer have a clear logical structure?\n"
        "- Readability: Is the answer clearly expressed and easy to understand?\n\n"
        "## Scoring Rule\n"
        "Evaluate all three dimensions comprehensively. If any dimension is severely lacking, "
        "the score should not exceed 5.\n\n"
        "## Requirements\n"
        "- In 'reasoning', reference specific aspects of the answer\n"
        "- Respond in the same language as the input\n\n"
        "Question: {question}\n"
        "AI answer: {generated_answer}\n\n"
        "Output JSON only (no other text):\n"
        '{{"quality": N, "reasoning": "Brief explanation referencing specific aspects of the answer"}}'
    ),

    "eval_faithfulness": (
        "You are a strict RAG system scoring expert. Evaluate the faithfulness of the "
        "AI answer on a scale of 1-10.\n\n"
        "## Faithfulness Criteria\n"
        "- Does the answer rely ONLY on the provided context, without fabricating information?\n"
        "- 9-10: Answer is entirely based on context, no fabrication\n"
        "- 7-8: Minor uncertain information, but generally faithful\n"
        "- 5-6: Some information comes from knowledge outside the context\n"
        "- 3-4: Notable fabricated information\n"
        "- 1-2: Answer is almost entirely not based on the context\n\n"
        "## Edge Cases\n"
        "- If the provided context is empty or irrelevant, the score MUST be 1\n\n"
        "## Requirements\n"
        "- In 'reasoning', reference specific claims and their context support\n"
        "- Respond in the same language as the input\n\n"
        "Retrieved context:\n"
        "{context}\n\n"
        "Question: {question}\n"
        "AI answer: {generated_answer}\n\n"
        "Output JSON only (no other text):\n"
        '{{"score": N, "reasoning": "Brief explanation referencing specific claims and their context support"}}'
    ),

    "eval_relevance": (
        "You are a strict scoring expert. Evaluate the relevance of the AI answer "
        "to the original question on a scale of 1-10.\n\n"
        "## Scoring Criteria\n"
        "- 9-10: Answer is entirely on-topic, content is directly relevant\n"
        "- 7-8: Answer is mostly on-topic with minor tangents\n"
        "- 5-6: Answer partially addresses the question with notable off-topic content\n"
        "- 3-4: Answer has weak connection to the question\n"
        "- 1-2: Answer is essentially unrelated to the question\n\n"
        "## Distinction\n"
        "Distinguish between relevance and completeness. An answer may be relevant but incomplete — "
        "that should score 5-6, not 7-8.\n\n"
        "## Requirements\n"
        "- In 'reasoning', explain specifically how the answer relates to the question\n"
        "- Respond in the same language as the input\n\n"
        "Question: {question}\n"
        "AI answer: {generated_answer}\n\n"
        "Output JSON only (no other text):\n"
        '{{"score": N, "reasoning": "Brief explanation of how the answer relates to the question"}}'
    ),

    "eval_reverse_question": (
        "You are a question generation expert. Based on the following AI answer, generate "
        "3 distinct possible original questions that this answer would address.\n\n"
        "## Requirements\n"
        "- Each question should capture a DIFFERENT aspect of the answer\n"
        "- Questions must vary in scope and focus — do NOT generate variations of the same question\n"
        "- Questions should be natural and specific\n\n"
        "AI answer:\n"
        "{generated_answer}\n\n"
        "Output JSON only (no other text):\n"
        '{{"generated_questions": ["Question 1", "Question 2", "Question 3"]}}'
    ),

    # ==================== Claim Decomposition & Verification ====================
    "eval_claim_decompose": (
        "You are a claim extraction expert. Decompose the following AI answer into "
        "independent objective claims. Each claim should be a verifiable factual statement.\n\n"
        "## Rules\n"
        "- Extract only factual statements, excluding opinions and transitional phrases\n"
        "- Each claim should be as atomic as possible (containing only one fact)\n"
        "- Preserve the original semantics\n"
        "- If the answer contains no verifiable factual statements, return an empty array\n\n"
        "AI answer:\n"
        "{generated_answer}\n\n"
        "Output JSON only (no other text):\n"
        '{{"claims": ["claim 1", "claim 2", ...]}}'
    ),

    "eval_claim_verify": (
        "You are a claim verification expert. Verify whether the following claim can be "
        "derived from the provided retrieved context.\n\n"
        "Retrieved context:\n"
        "{context}\n\n"
        "Claim to verify: {claim}\n\n"
        "## Rules\n"
        "- If the context does not explicitly contain the information, or the claim cannot "
        "be reasonably derived from the context, then it is not supported\n"
        "- Base your judgment ONLY on the provided context — do not use external knowledge\n\n"
        "Output JSON only (no other text):\n"
        '{{"supported": true/false, "evidence": "Quote the relevant context content or explain why unsupported"}}'
    ),

    # ==================== Answer Generation ====================
    "eval_generate_answer": (
        "You are a Q&A expert. Answer the question based on the retrieved context below.\n\n"
        "## Rules\n"
        "- Use ONLY information contained in the context — do NOT fabricate\n"
        "- If the context is insufficient to fully answer the question, state what is available "
        "and explicitly identify what is missing\n"
        "- Do NOT guess or supplement with external knowledge\n"
        "- Respond in the same language as the question\n\n"
        "Retrieved context:\n"
        "{context_text}\n\n"
        "Question: {question}\n\n"
        "Provide your answer directly:"
    ),

    # ==================== Synthetic Test Set Generation（kb-ops C） ====================
    # 注册供检索/审计；运行时经 testset_generation.build_generation_prompt 拼变量
    # （批式模板带循环结构，注册表存结构说明即可——两处文本须保持同义）
    # kb-ops D 矛盾判定（运行时 contradiction_detector._llm_check_contradiction
    # 内联拼接，此处登记结构供检索/审计，两处文本保持同义）
    "kb_ops_contradiction_check": (
        "判断两段文档内容是否互相矛盾（同一事实不同数值/结论）。"
        "只判矛盾，不确定时输出 false；输出 JSON {{\"contradiction\": true/false, \"reason\": \"简短说明\"}}。"
        "内容 A：{text_a}\n内容 B：{text_b}"
    ),

    # ==================== Attribution Analysis（批次 E1：失败用例归因判定） ====================
    # 全部由 AttributionAnalyzer 消费；每步判定失败即降级，输出约定 JSON。
    "eval_attr_scope_check": (
        "你是知识库范围审查员。判断下面的问题是否属于该知识库应覆盖的范围。\n\n"
        "判定规则：\n"
        "- out_of_scope=true：问题明显超出知识库定位（如闲聊、无关业务），或问题本身歧义到无法判断在问什么\n"
        "- out_of_scope=false：问题属于知识库应覆盖的领域（哪怕知识库暂时没有答案）\n"
        "- 不确定时输出 false（宁可不拦，落后续判定）\n\n"
        "知识库名称：{kb_name}\n问题：{question}\n\n"
        "只输出 JSON：{{\"out_of_scope\": true/false, \"reason\": \"简短说明\"}}"
    ),
    "eval_attr_answer_compare": (
        "你是答案质量评审员。对同一问题的两个回答，判断第二个（替换上下文后重新生成）"
        "是否明显比第一个更符合期望答案。\n\n"
        "判定规则：\n"
        "- regenerated_better=true：第二个回答在事实与覆盖面上明显更接近期望答案\n"
        "- regenerated_better=false：两者相当，或第二个并不更好\n"
        "- 只依据期望答案判断，不引入外部知识\n\n"
        "问题：{question}\n期望答案：{expected}\n原始回答：{original}\n重生成回答：{regenerated}\n\n"
        "只输出 JSON：{{\"regenerated_better\": true/false, \"reason\": \"简短说明\"}}"
    ),
    "eval_attr_semantic_match": (
        "你是答案语义评审员。判断生成回答与期望答案是否语义一致。\n\n"
        "判定规则：\n"
        "- semantically_equivalent=true：两者表达的事实与结论一致（措辞/详略不同可接受）\n"
        "- semantically_equivalent=false：存在事实差异或结论不同\n"
        "- 部分一致但缺少关键事实时输出 false\n\n"
        "问题：{question}\n期望答案：{expected}\n生成回答：{generated}\n\n"
        "只输出 JSON：{{\"semantically_equivalent\": true/false, \"reason\": \"简短说明\"}}"
    ),
    "eval_attr_faithfulness_check": (
        "你是答案忠实度审查员。判断生成回答是否与提供的上下文矛盾（幻觉的快速判定）。\n\n"
        "判定规则：\n"
        "- contradicts=true：回答中的关键结论与上下文明确冲突（同一事实不同说法/数值）\n"
        "- contradicts=false：回答忠于上下文，或仅是信息不完整（不完整不是矛盾）\n"
        "- 只依据上下文判断，不用外部知识\n\n"
        "生成回答：{generated}\n上下文：\n{context_text}\n\n"
        "只输出 JSON：{{\"contradicts\": true/false, \"reason\": \"简短说明\"}}"
    ),
    "eval_attr_context_sufficiency": (
        "你是上下文充分性审查员。判断提供的上下文是否包含回答该问题所需的关键信息。\n\n"
        "判定规则：\n"
        "- sufficient=true：上下文包含期望答案的核心信息（足以答对）\n"
        "- sufficient=false：上下文缺少期望答案的关键信息（答不对情有可原）\n"
        "- 部分包含但缺关键事实时输出 false\n\n"
        "问题：{question}\n期望答案：{expected}\n上下文：\n{context_text}\n\n"
        "只输出 JSON：{{\"sufficient\": true/false, \"reason\": \"简短说明\"}}"
    ),
    "eval_attr_source_compare": (
        "你是解析质量审查员。问题所需信息未出现在命中的上下文中，判断这是"
        "「信息在源文档里但被解析/切分弄丢」还是「源文档本来就没有该信息」。\n\n"
        "判定规则：\n"
        "- info_cut_by_parsing=true：上下文与问题主题相关、行文有承接感，但关键信息在"
        "段落中间断裂（疑似表格被拆碎、句子被截断、跨页丢失）\n"
        "- info_cut_by_parsing=false：上下文与所需信息无关或明显不完整主题（源文档未覆盖）\n"
        "- 不确定时输出 false（宁归源文档缺陷，不冤枉解析）\n\n"
        "问题：{question}\n期望答案：{expected}\n命中上下文：\n{context_text}\n\n"
        "只输出 JSON：{{\"info_cut_by_parsing\": true/false, \"reason\": \"简短说明\"}}"
    ),
}
