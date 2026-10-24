"""文档文件类型事实登记处（唯一定义）。

扩展名、模态归属的全部事实在本表登记，上传白名单与模态分流表一律自
spec 表派生——新增格式 = 加一行 FileFormatSpec，不再需要同步多处清单
（扩展性审计批次 3：此前同一事实分散在白名单/模态表/前端 accept 三处，
epub 曾因此成为「解析侧已支持、上传侧传不进来」的半接线格式）。

解析配置域类型（TEXT_DOC_TYPES / _DEEPDOC_ONLY_DOC_TYPES / parser 迁移表）
与其描述的 TextParsingConfig 字段同文件（knowledge_base_schema.py）维护，
不跨文件派生——它们与扩展名不是一一映射（excel/ppt 是合法配置域但无
上传路径；json 的配置键是 json_file）。

已知半接线（本表刻意不登记，放开前需端到端验证）：excel/ppt 有配置域与
deepdoc parser，但 xls/xlsx/ppt/pptx 扩展名未登记上传；放开需同步验证
runtime_parser 路由与 deepdoc excel/ppt 解析链。
"""

from dataclasses import dataclass

from novamind.shared.document.file_types import IMAGE_FILE_TYPES

# 文件大小限制（默认 100MB）
MAX_FILE_SIZE = 100 * 1024 * 1024


@dataclass(frozen=True)
class FileFormatSpec:
    """单格式上传事实。

    Attributes:
        ext: 上传扩展名（不含点，小写）。
        modality: 管道模态（text / image / video / audio），决定模态分流与
            上传大小上限。
    """

    ext: str
    modality: str


# 格式事实表（唯一定义处；新格式加一行）
_FILE_FORMAT_SPECS: tuple[FileFormatSpec, ...] = (
    FileFormatSpec("pdf", "text"),
    FileFormatSpec("doc", "text"),
    FileFormatSpec("docx", "text"),
    FileFormatSpec("epub", "text"),
    FileFormatSpec("txt", "text"),
    FileFormatSpec("md", "text"),
    FileFormatSpec("csv", "text"),
    FileFormatSpec("html", "text"),
    FileFormatSpec("json", "text"),
    FileFormatSpec("jpg", "image"),
    FileFormatSpec("jpeg", "image"),
    FileFormatSpec("png", "image"),
    FileFormatSpec("gif", "image"),
    FileFormatSpec("webp", "image"),
    FileFormatSpec("mp4", "video"),
    FileFormatSpec("mov", "video"),
    FileFormatSpec("avi", "video"),
    FileFormatSpec("mkv", "video"),
    FileFormatSpec("webm", "video"),
    FileFormatSpec("mp3", "audio"),
    FileFormatSpec("wav", "audio"),
    FileFormatSpec("flac", "audio"),
    FileFormatSpec("aac", "audio"),
    FileFormatSpec("ogg", "audio"),
    FileFormatSpec("m4a", "audio"),
)

_MODALITY_ORDER = ("text", "image", "video", "audio")

# ---- 派生常量（下游唯一允许的引用形态）----

# 支持的文件类型（上传白名单；document_routes ALLOWED_FILE_EXTENSIONS 自此派生）
SUPPORTED_FILE_TYPES: list[str] = [spec.ext for spec in _FILE_FORMAT_SPECS]

# 图片文件类型（唯一定义 shared/document/file_types.py）

# 视频文件类型
VIDEO_FILE_TYPES: frozenset[str] = frozenset(
    spec.ext for spec in _FILE_FORMAT_SPECS if spec.modality == "video"
)

# 音频文件类型
AUDIO_FILE_TYPES: frozenset[str] = frozenset(
    spec.ext for spec in _FILE_FORMAT_SPECS if spec.modality == "audio"
)

# 模态 → 文件类型映射（用于上传校验和管道分流）
MODALITY_TO_FILE_TYPES: dict[str, frozenset[str]] = {
    modality: frozenset(spec.ext for spec in _FILE_FORMAT_SPECS if spec.modality == modality)
    for modality in _MODALITY_ORDER
}
