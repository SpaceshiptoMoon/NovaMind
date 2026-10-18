"""agent 聊天附件共享链：上传/下载/文本提取/孤儿回收。

原 features/qa 附件基础设施（QA 对话清退后归位 agent——附件唯一消费方
是 agent 对话面）。物理存储 chat_attachments 表 + MinIO，前端
（stores/agent.ts）与后端（chat_service._prepare）按 user_id 维度引用
附件 id，不做会话级归属校验——同一用户可跨会话/跨 agent 复用附件，为
既有设计决策。孤儿回收由 cron 任务 cleanup_orphan_attachments 负责。
"""
from novamind.features.agent.attachments.models import ChatAttachment
from novamind.features.agent.attachments.service import AttachmentService

__all__ = ["ChatAttachment", "AttachmentService"]
