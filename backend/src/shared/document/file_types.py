"""跨 feature 文件类型常量（批次 6.6 归位——原 minio_client 内嵌定义）。

供 qa（附件上传校验）与 knowledge_space（管道分流）共用。
"""

IMAGE_FILE_TYPES = frozenset({"jpg", "jpeg", "png", "gif", "webp"})

__all__ = ["IMAGE_FILE_TYPES"]
