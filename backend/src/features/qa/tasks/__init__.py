"""QA feature 后台任务（arq）。"""
from novamind.features.qa.tasks.attachment_cleanup import cleanup_orphan_attachments

__all__ = ["cleanup_orphan_attachments"]