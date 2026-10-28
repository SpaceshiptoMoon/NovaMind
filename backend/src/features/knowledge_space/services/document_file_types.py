"""文档文件类型事实登记处（唯一定义）。

扩展名、模态归属的全部事实在本表登记，上传白名单与模态分流表一律自
spec 表派生——新增格式 = 加一行 FileFormatSpec，不再需要同步多处清单
（扩展性审计批次 3：此前同一事实分散在白名单/模态表/前端 accept 三处，
epub 曾因此成为「解析侧已支持、上传侧传不进来」的半接线格式）。

解析配置域类型（TEXT_DOC_TYPES / _DEEPDOC_ONLY_DOC_TYPES / parser 迁移表）
与其描述的 TextParsingConfig 字段同文件（knowledge_base_schema.py）维护，
不跨文件派生——它们与扩展名不是一一映射（json 的配置键是 json_file）。

半接线历史：excel/ppt 曾只有配置域与 deepdoc parser 而无上传路径（本表
刻意不登记）。xlsx/pptx 已于 2026-10-27 经配置矩阵端到端真测放开（上传→
deepdoc 解析→切分→索引→检索全链通过）。旧版二进制 xls/ppt 保持不登记：
runtime_parser 路由存在（xls 走 pandas+calamine 兜底），但缺真实夹具
端到端验证，放开前不冒「传得进、解析必失败」的新半接线风险。
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
    FileFormatSpec("xlsx", "text"),
    FileFormatSpec("pptx", "text"),
    # 容器/邮件族：zip 成员递归解析（成员数/解压总量上限防炸弹），eml/msg
    # 附件递归同链；ofd 为国内版式文档（zip 结构守卫覆盖）。解析器单测与
    # 容器正反用例覆盖。
    FileFormatSpec("zip", "text"),
    FileFormatSpec("eml", "text"),
    FileFormatSpec("msg", "text"),
    FileFormatSpec("ofd", "text"),
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
