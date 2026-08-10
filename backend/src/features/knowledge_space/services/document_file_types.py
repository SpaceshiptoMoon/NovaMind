"""文档文件类型常量（中立模块）。

被三方共用，避免 service 之间互相依赖：
- 上传校验（DocumentUploadService 按模态校验文件类型 + 大小上限）
- 管道分流（execute_document_pipeline 按模态路由到文本/图片/视频/音频分支）
- 路由白名单（document_routes 派生 ALLOWED_FILE_EXTENSIONS）

收敛到唯一定义，避免常量在 service / route / pipeline 各写一份而漂移。
"""

from novamind.shared.storage.minio_client import IMAGE_FILE_TYPES

# 文件大小限制（默认 100MB）
MAX_FILE_SIZE = 100 * 1024 * 1024

# 支持的文件类型
SUPPORTED_FILE_TYPES = [
    "pdf",
    "doc",
    "docx",
    "txt",
    "md",
    "csv",
    "html",
    "json",
    "jpg",
    "jpeg",
    "png",
    "gif",
    "webp",
    "mp4",
    "mov",
    "avi",
    "mkv",
    "webm",
    "mp3",
    "wav",
    "flac",
    "aac",
    "ogg",
    "m4a",
]

# 图片文件类型（从 MinIO 工具收敛到唯一定义）
IMAGE_FILE_TYPES = IMAGE_FILE_TYPES

# 视频文件类型
VIDEO_FILE_TYPES = frozenset({"mp4", "mov", "avi", "mkv", "webm"})

# 音频文件类型
AUDIO_FILE_TYPES = frozenset({"mp3", "wav", "flac", "aac", "ogg", "m4a"})

# 模态 → 文件类型映射（用于上传校验和管道分流）
MODALITY_TO_FILE_TYPES = {
    "text": frozenset({"pdf", "doc", "docx", "txt", "md", "csv", "html", "json"}),
    "image": IMAGE_FILE_TYPES,
    "video": VIDEO_FILE_TYPES,
    "audio": AUDIO_FILE_TYPES,
}