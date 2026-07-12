"""
聊天附件模型

用户在 AI 对话中上传的文档附件，仅记录文件存储信息。
上传后取消发送的附件会成为孤儿记录。
"""
from sqlalchemy import Column, BigInteger, String, Text, ForeignKey

from novamind.core.database.base import BaseModel


class ChatAttachment(BaseModel):
    """
    聊天附件模型

    存储用户上传的文档，提取的文本缓存用于 LLM 上下文注入。
    不再关联 session_id / message_id，附件信息通过消息的 extra 字段传递。
    """
    __tablename__ = "chat_attachments"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True, comment="用户ID")

    # 文件信息
    filename = Column(String(500), nullable=False, comment="原始文件名")
    file_type = Column(String(20), nullable=False, comment="文件类型（pdf/docx/txt/md/jpg/png/gif/webp）")
    file_size = Column(BigInteger, nullable=False, comment="文件大小（字节）")

    # 存储
    storage_path = Column(String(500), nullable=False, comment="MinIO 对象路径")

    # 提取的文本缓存
    extracted_text = Column(Text, nullable=True, comment="提取的文档文本（截断至 50000 字符）")

    __table_args__ = (
        {"comment": "聊天附件表，存储对话中上传的文档及其提取文本"},
    )

    def __repr__(self) -> str:
        return f"<ChatAttachment(id={self.id}, filename='{self.filename}')>"
