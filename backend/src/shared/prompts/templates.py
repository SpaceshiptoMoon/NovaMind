"""
提示词模板键枚举 PromptTemplate，作为提示词键的字符串常量引用。

键按模块归属：knowledge_space / deep_research / qa / evaluation / app / agent / skill。
"""
from enum import Enum


class PromptTemplate(Enum):
    """提示词模板枚举"""

    # ==================== 知识空间相关 ====================
    # 查询改写
    QUERY_REWRITE_HYDE_SYSTEM = "query_rewrite_hyde_system"
    QUERY_REWRITE_HYDE_USER = "query_rewrite_hyde_user"
    QUERY_REWRITE_SUB_QUERY_SYSTEM = "query_rewrite_sub_query_system"
    QUERY_REWRITE_SUB_QUERY_USER = "query_rewrite_sub_query_user"

    # 知识库文档问答
    KB_DEFAULT_QUESTION = "kb_default_question"
    SEARCH_ANSWER = "search_answer"

    # 图片描述（VLM）
    IMAGE_DESCRIPTION = "image_description"

    # 视频帧描述（VLM）
    VIDEO_FRAME_DESCRIPTION = "video_frame_description"
    # 视频分组多帧描述（VLM 多图，grouped 策略）
    VIDEO_FRAME_GROUPED_DESCRIPTION = "video_frame_grouped_description"
    # 视频逐帧描述重写（LLM 润色，rewrite 策略，保留时间锚点）
    VIDEO_FRAME_REWRITE_PROMPT = "video_frame_rewrite_prompt"
    # 视频原生/序列/分步合成描述（knowledge_space prompts/templates.py 子模块）
    VIDEO_NATIVE_DESCRIPTION = "video_native_description"
    VIDEO_FRAME_SEQUENCE_DESCRIPTION = "video_frame_sequence_description"
    VIDEO_STEPS_SYNTHESIS = "video_steps_synthesis"
    # 音频转写清洗
    AUDIO_TRANSCRIPT_CLEAN = "audio_transcript_clean"

    # ==================== 深度研究相关 ====================
    RESEARCH_ANALYZE_QUERY = "research_analyze_query"
    RESEARCH_SYNTHESIZE_REPORT = "research_synthesize_report"
    RESEARCH_SYNTHESIZE_REPORT_STREAM = "research_synthesize_report_stream"
    # 引擎侧键（engines/deep_research/engine.py KEY_* 常量引用，模板在
    # features/deep_research/deep_research_prompts.py）
    RESEARCH_PLAN = "research_plan"
    RESEARCH_PROCESSING_STEP = "research_processing_step"
    RESEARCH_GENERATE_QUERY = "research_generate_query"
    RESEARCH_TASK_FINDING = "research_task_finding"

    # ==================== 问答系统相关 ====================
    # QueryRewriter（engines/rag）可插拔查询改写（4 种策略，与 search_service 的查询改写是两条独立路径）
    QA_RW_COMPLETION = "qa_rw_completion"
    QA_RW_SYNONYM = "qa_rw_synonym"
    QA_RW_DECOMPOSE = "qa_rw_decompose"
    QA_RW_HYDE = "qa_rw_hyde"

    # GradeRetrier 检索后自评估（运行时打分→重试，区别于 evaluation 的离线评估）
    QA_GRADE_RETRIEVAL = "qa_grade_retrieval"

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
    # 测评测试集生成 + kb-ops 矛盾检测（evaluation_prompts.py）
    EVAL_TESTSET_GENERATION = "eval_testset_generation"
    KB_OPS_CONTRADICTION_CHECK = "kb_ops_contradiction_check"

    # ==================== 简历解析（S1-S4） ====================
    RESUME_SECTION_SPLIT = "resume_section_split"
    RESUME_PARSE_PERSONAL_INFO = "resume_parse_personal_info"
    RESUME_PARSE_WORK_EXPERIENCE = "resume_parse_work_experience"
    RESUME_PARSE_PROJECT_EXPERIENCE = "resume_parse_project_experience"
    RESUME_PARSE_EDUCATION = "resume_parse_education"
    RESUME_PARSE_SKILLS = "resume_parse_skills"
    RESUME_PARSE_PUBLICATIONS = "resume_parse_publications"

    # ==================== 简历分析（S4.5-S9） ====================
    RESUME_SUMMARY = "resume_summary"
    RESUME_JD_ANALYSIS = "resume_jd_analysis"
    RESUME_PROBING_STRATEGY = "resume_probing_strategy"
    RESUME_PREFIX_KNOWLEDGE = "resume_prefix_knowledge"

    # ==================== 简历追问（S10-S11） ====================
    RESUME_PROBE_FIRST_ROUND = "resume_probe_first_round"
    RESUME_PROBE_FOLLOW_UP = "resume_probe_follow_up"
    RESUME_PROBE_EVALUATION = "resume_probe_evaluation"

    # ==================== 简历挖掘扩展（V2 新增） ====================
    RESUME_WORK_CONTEXT_ENRICHMENT = "resume_work_context_enrichment"
    RESUME_OPTIMIZATION_ADVICE = "resume_optimization_advice"
    RESUME_COMPLEXITY_ASSESSMENT = "resume_complexity_assessment"

    # ==================== Agent 相关 ====================
    # 长期记忆提取（features/agent/agent_prompts.py）。压缩摘要/融合/系统提示等
    # 引擎侧模板在 AGENT_ENGINE_*（engines/agent/prompts.py）。
    AGENT_LONG_TERM_MEMORY = "agent_long_term_memory"

    # ==================== Agent 引擎层（engines/agent/prompts.py） ====================
    AGENT_ENGINE_STRUCTURED_SUMMARY = "agent_engine_structured_summary"
    AGENT_ENGINE_SUMMARY_MERGE = "agent_engine_summary_merge"
    AGENT_ENGINE_COMPACTION_ALIGNED_INSTRUCTION = "agent_engine_compaction_aligned_instruction"
    AGENT_ENGINE_TAG_CONVENTION = "agent_engine_tag_convention"
    AGENT_ENGINE_TOOL_DISCIPLINE_DEFAULT = "agent_engine_tool_discipline_default"
    AGENT_ENGINE_MODEL_ADAPTATION_GPT = "agent_engine_model_adaptation_gpt"
    AGENT_ENGINE_MODEL_ADAPTATION_GEMINI = "agent_engine_model_adaptation_gemini"
    AGENT_ENGINE_PLAN_SYSTEM = "agent_engine_plan_system"
    AGENT_ENGINE_PLAN_FINALIZE_SYSTEM = "agent_engine_plan_finalize_system"
    AGENT_ENGINE_SUBAGENT_SYSTEM = "agent_engine_subagent_system"

    # ==================== Wiki 生成（knowledge_space prompts/templates.py 子模块） ====================
    WIKI_TAXONOMY_PLAN_USER = "wiki_taxonomy_plan_user"
    WIKI_INDEX_INTRO_USER = "wiki_index_intro_user"
    WIKI_INDEX_INTRO_UPDATE_USER = "wiki_index_intro_update_user"
    WIKI_SUMMARY_PAGE_USER = "wiki_summary_page_user"
    WIKI_PAGE_MODIFY_SYSTEM = "wiki_page_modify_system"
    WIKI_PAGE_MODIFY_USER = "wiki_page_modify_user"
    WIKI_DEDUP_USER = "wiki_dedup_user"
    WIKI_CHUNK_CITATION_USER = "wiki_chunk_citation_user"
    WIKI_CANDIDATE_SLUG_USER = "wiki_candidate_slug_user"

    # ==================== 技能安全审查 ====================
    SKILL_SECURITY_REVIEW = "skill_security_review"

    # ==================== 技能 AI 搜索 ====================
    SKILL_AI_SEARCH = "skill_ai_search"


# 向后兼容 re-export：PromptManager 注册表机制已迁至 prompt_manager.py。
# 保留此处 re-export，使现有 `from novamind.shared.prompts.templates import PromptManager`
# 调用方继续可用；新代码应直接 `from novamind.shared.prompts import PromptManager`。
from novamind.shared.prompts.prompt_manager import (  # noqa: E402,F401
    PromptManager,
    format_prompt,
    get_prompt,
)

__all__ = ["PromptTemplate", "PromptManager", "get_prompt", "format_prompt"]
