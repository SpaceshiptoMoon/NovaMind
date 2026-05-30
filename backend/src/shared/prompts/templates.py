"""
提示词模板管理模块

统一管理项目中所有 LLM 提示词模板。

架构：
  templates.py              → PromptTemplate 枚举 + PromptManager 注册表（薄壳）
  features/{module}/{module}_prompts.py → 各模块的模板内容 + 描述（数据源）

模块分类：
  1. knowledge_space — RAG 检索、文档处理、假设问题生成、查询改写、知识库问答
  2. deep_research   — 研究主题分析、任务分解、报告生成
  3. qa              — 通用问答、文档问答、对话压缩、AI 对话系统提示
  4. evaluation      — 检索评估、生成评估、Claim 拆解验证
  5. app             — 简历解析（S1-S4）、简历分析（S4.5-S9）、追问模拟（S10-S11）
  6. agent           — 系统提示词、长期记忆提取、结构化摘要、迭代融合
  7. skill           — 技能安全审查
"""
from enum import Enum
from typing import Dict


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

    # 假设问题生成
    HYPOTHETICAL_QUESTION_SYSTEM = "hypothetical_question_system"
    HYPOTHETICAL_QUESTION_USER = "hypothetical_question_user"

    # 查询改写
    QUERY_REWRITE_HYDE_SYSTEM = "query_rewrite_hyde_system"
    QUERY_REWRITE_HYDE_USER = "query_rewrite_hyde_user"
    QUERY_REWRITE_SUB_QUERY_SYSTEM = "query_rewrite_sub_query_system"
    QUERY_REWRITE_SUB_QUERY_USER = "query_rewrite_sub_query_user"

    # 知识库文档问答
    KB_DEFAULT_QUESTION = "kb_default_question"
    SEARCH_ANSWER = "search_answer"

    # ==================== 深度研究相关 ====================
    RESEARCH_ANALYZE_QUERY = "research_analyze_query"
    RESEARCH_DECOMPOSE_TASKS = "research_decompose_tasks"
    RESEARCH_SYNTHESIZE_REPORT = "research_synthesize_report"
    RESEARCH_SYNTHESIZE_REPORT_STREAM = "research_synthesize_report_stream"

    # ==================== 问答系统相关 ====================
    QA_GENERAL = "qa_general"
    QA_DOCUMENT_BASED = "qa_document_based"
    QA_COMPRESSION_SUMMARY = "qa_compression_summary"
    QA_AI_CHAT_SYSTEM = "qa_ai_chat_system"

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

    # ==================== Agent 相关 ====================
    AGENT_SYSTEM_PROMPT = "agent_system_prompt"
    AGENT_LONG_TERM_MEMORY = "agent_long_term_memory"
    AGENT_STRUCTURED_SUMMARY = "agent_structured_summary"
    AGENT_SUMMARY_MERGE = "agent_summary_merge"

    # ==================== 技能安全审查 ====================
    SKILL_SECURITY_REVIEW = "skill_security_review"


class PromptManager:
    """提示词管理器"""

    _templates: Dict[str, str] = {}

    @classmethod
    def _ensure_loaded(cls):
        """延迟加载各模块模板（仅首次调用时执行）"""
        if cls._templates:
            return

        from src.features.knowledge_space.knowledge_space_prompts import TEMPLATES as _ks
        from src.features.deep_research.deep_research_prompts import TEMPLATES as _dr
        from src.features.qa.qa_prompts import TEMPLATES as _qa
        from src.features.evaluation.evaluation_prompts import TEMPLATES as _ev
        from src.features.app.app_prompts import TEMPLATES as _app
        from src.features.agent.agent_prompts import TEMPLATES as _ag
        from src.features.skill.skill_prompts import TEMPLATES as _sk

        for t in [_ks, _dr, _qa, _ev, _app, _ag, _sk]:
            cls._templates.update(t)

    @classmethod
    def get_template(cls, template_name: str) -> str:
        """获取提示词模板"""
        cls._ensure_loaded()
        if template_name not in cls._templates:
            raise ValueError(f"模板 '{template_name}' 不存在")
        return cls._templates[template_name]

    @classmethod
    def format_prompt(cls, template_name: str, **kwargs) -> str:
        """格式化提示词"""
        template = cls.get_template(template_name)
        try:
            return template.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"模板 '{template_name}' 缺少参数: {e}") from None


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
