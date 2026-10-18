"""知识运营 feature 数据模型。

question_answer/message_feedback/session_config 为 QA 对话归档的历史表
（QA 对话链清退后只读，表名保留 qa_ 前缀），供归因/gap/governance 与
空间统计直查。qa_message_feedback.message_id 外键指向 question_answers，
两表必须同 feature 注册。
"""
from .kb_event import KbEvent
from .kb_review_suggestion import KbReviewSuggestion
from .message_feedback import MessageFeedback
from .question_answer import QuestionAnswer
from .session_config import SessionConfig

__all__ = [
    "KbEvent",
    "KbReviewSuggestion",
    "QuestionAnswer",
    "SessionConfig",
    "MessageFeedback",
]
