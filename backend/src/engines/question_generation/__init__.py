"""假设问题生成引擎：LLM 为文本分块生成假设性问题（通用模块）。"""
from novamind.engines.question_generation.service import (
    BatchGenerationStats,
    GeneratedQuestion,
    QuestionGenConfig,
    QuestionGenerationError,
    QuestionGenerationService,
    generate_hypothetical_questions,
)

__all__ = [
    "BatchGenerationStats",
    "GeneratedQuestion",
    "QuestionGenConfig",
    "QuestionGenerationError",
    "QuestionGenerationService",
    "generate_hypothetical_questions",
]
