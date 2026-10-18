"""消息反馈与引用点击 schema（kb-ops O2 契约）。

历史：原 features/qa/schemas/qa.py（早期 QA 对话与 agent 对话共用反馈端点
的产物），组件名 MessageFeedback*/CitationClickRequest 已进 OpenAPI 快照，
随 QA 清退归位 agent 原文迁移——迁移保持类名不变以维持契约确定性。
"""

from typing import Literal

from pydantic import BaseModel, Field


class MessageFeedbackResponse(BaseModel):
    """消息反馈响应（回显当前状态）"""
    message_id: int
    rating: str | None = Field(default=None, description="当前反馈状态：up/down/null")
    comment: str | None = None


class MessageFeedbackRequest(BaseModel):
    """消息反馈请求（批次 2a：点赞/点踩）

    rating=null 表示撤销反馈（幂等：无论是否曾投过，撤销后均无反馈记录）。
    """
    rating: Literal["up", "down"] | None = Field(
        default=None, description="反馈类型：up=赞 / down=踩 / null=撤销",
    )
    comment: str | None = Field(
        default=None, max_length=2000, description="反馈补充说明（可选）",
    )


class CitationClickRequest(BaseModel):
    """引用点击上报请求（kb-ops O2：用户核验行为的被动信号）。

    点击正文 [N] 角标或展开来源卡时上报被点击的来源；全字段可选——
    上报是行为信号而非数据写入，前端拿不到的字段（如联网来源无 doc_id）不强求。
    """
    source_index: int | None = Field(
        default=None, ge=1, description="被点击来源的序号（与正文角标对齐，1-based）",
    )
    chunk_id: str | None = Field(
        default=None, max_length=128, description="命中的分块 ID（KB 来源）",
    )
    document_id: int | None = Field(
        default=None, gt=0, description="命中的文档 ID（KB 来源）",
    )
    kb_id: int | None = Field(
        default=None, gt=0, description="命中的知识库 ID（KB 来源）",
    )
