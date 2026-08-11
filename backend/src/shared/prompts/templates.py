"""
提示词模板键枚举 PromptTemplate，作为提示词键的字符串常量引用。

键按模块归属：knowledge_space / deep_research / qa / evaluation / app / agent / skill / clawmate。
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

    # ==================== 深度研究相关 ====================
    RESEARCH_ANALYZE_QUERY = "research_analyze_query"
    RESEARCH_DECOMPOSE_TASKS = "research_decompose_tasks"
    RESEARCH_SYNTHESIZE_REPORT = "research_synthesize_report"
    RESEARCH_SYNTHESIZE_REPORT_STREAM = "research_synthesize_report_stream"

    # ==================== 问答系统相关 ====================
    # 对话压缩 + AI 对话系统提示
    QA_COMPRESSION_SUMMARY = "qa_compression_summary"
    QA_AI_CHAT_SYSTEM = "qa_ai_chat_system"

    # QueryRewriter 可插拔查询改写（4 种策略，与 search_service 的查询改写是两条独立路径）
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
    AGENT_SYSTEM_PROMPT = "agent_system_prompt"
    AGENT_LONG_TERM_MEMORY = "agent_long_term_memory"
    AGENT_STRUCTURED_SUMMARY = "agent_structured_summary"
    AGENT_SUMMARY_MERGE = "agent_summary_merge"

    # ==================== 技能安全审查 ====================
    SKILL_SECURITY_REVIEW = "skill_security_review"

    # ==================== 技能 AI 搜索 ====================
    SKILL_AI_SEARCH = "skill_ai_search"

    # ==================== ClawMate 终端助手 ====================
    CLAWMATE_SYSTEM = "clawmate_system"


# 向后兼容 re-export：PromptManager 注册表机制已迁至 prompt_manager.py。
# 保留此处 re-export，使现有 `from novamind.shared.prompts.templates import PromptManager`
# 调用方继续可用；新代码应直接 `from novamind.shared.prompts import PromptManager`。
from novamind.shared.prompts.prompt_manager import (  # noqa: E402,F401
    PromptManager,
    format_prompt,
    get_prompt,
)

__all__ = ["PromptTemplate", "PromptManager", "get_prompt", "format_prompt"]
