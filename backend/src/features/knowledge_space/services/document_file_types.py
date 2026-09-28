"""文档文件类型常量（中立模块）：上传校验、管道模态分流与路由白名单三方共用的唯一定义，避免常量漂移。"""

from novamind.shared.document.file_types import IMAGE_FILE_TYPES

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

# 图片文件类型（唯一定义 shared/document/file_types.py）

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