"""视频叙事文档 ORM 模型：长视频解析后合成的章节化连贯叙事文档（与碎片块并存）。"""
from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from novamind.core.database.base import BaseModel


class VideoNarrative(BaseModel):
    """视频叙事文档（每文档一份，重复生成覆盖）。

    章节化连贯叙事：碎片块负责命中召回，本表负责整体呈现与生成上下文。
    """

    __tablename__ = "video_narratives"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_video_narratives_document"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    space_id = Column(BigInteger, nullable=False, index=True, comment="空间 ID")
    kb_id = Column(
        BigInteger, nullable=False, index=True,
        comment="知识库 ID",
    )
    document_id = Column(
        BigInteger, nullable=False, unique=True, comment="源视频文档 ID（每文档一份）"
    )
    status = Column(
        Integer, nullable=False, default=0,
        comment="状态: 0-生成中 1-完成 2-失败",
    )
    llm_model = Column(String(100), nullable=True, comment="合成用 LLM 模型名")
    overview = Column(Text, nullable=True, comment="全片梗概（连贯叙事）")
    chapters = Column(JSON, nullable=True, comment="章节列表[title/start_time/end_time/summary/chunk_indices]")
    content_md = Column(Text, nullable=True, comment="完整 markdown 文档（梗概+时间轴+章节详情）")
    error_message = Column(Text, nullable=True, comment="失败原因")


class VideoNarrativeStatus:
    """叙事文档状态机。"""

    RUNNING = 0
    COMPLETED = 1
    FAILED = 2
