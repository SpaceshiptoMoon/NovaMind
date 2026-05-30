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
}
