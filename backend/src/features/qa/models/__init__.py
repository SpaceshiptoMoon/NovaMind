"""
QA 模块数据模型

包含:
- QuestionAnswer: 问答记录模型
- SessionConfig: 会话配置模型（压缩配置）
- SessionSummary: 会话摘要模型
- ChatAttachment: 聊天附件模型
- MessageFeedback: 消息反馈模型（点赞/点踩）
"""
from .chat_attachment import ChatAttachment
from .qa_feedback import MessageFeedback
from .question_answer import QuestionAnswer
from .session_config import SessionConfig
from .session_summary import SessionSummary

__all__ = [
    "QuestionAnswer",
    "SessionConfig",
    "SessionSummary",
    "ChatAttachment",
    "MessageFeedback",
]
