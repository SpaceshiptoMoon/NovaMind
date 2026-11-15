"""
提示词模板键枚举 PromptTemplate，作为提示词键的字符串常量引用。

键按模块归属：knowledge_space / qa / evaluation。
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
    # kb-ops 矛盾检测（evaluation_prompts.py）
    KB_OPS_CONTRADICTION_CHECK = "kb_ops_contradiction_check"

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


# 向后兼容 re-export：PromptManager 注册表机制已迁至 prompt_manager.py。
# 保留此处 re-export，使现有 `from novamind.shared.prompts.templates import PromptManager`
# 调用方继续可用；新代码应直接 `from novamind.shared.prompts import PromptManager`。
from novamind.shared.prompts.prompt_manager import (  # noqa: E402,F401
    PromptManager,
    format_prompt,
    get_prompt,
)

__all__ = ["PromptTemplate", "PromptManager", "get_prompt", "format_prompt"]
