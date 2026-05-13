"""
SKILL.md 解析器 — 解析 Anthropic 技能标准格式

解析 ZIP 包中的 SKILL.md 文件，提取 YAML frontmatter 和 Markdown body
"""
import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

import yaml

from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# frontmatter 分隔符
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# 合法技能名：kebab-case
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

# 资源目录类型映射
_RESOURCE_DIRS = {
    "scripts": "script",
    "references": "reference",
    "assets": "asset",
}

# 允许的资源文件最大大小 (10MB)
_MAX_RESOURCE_SIZE = 10 * 1024 * 1024


@dataclass
class ParsedSkill:
    """解析后的技能数据"""
    name: str
    description: str
    display_name: str
    body_markdown: str
    frontmatter_raw: str
    license: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ResourceFile:
    """资源文件"""
    path: str
    type: str  # script / reference / asset
    content: bytes
    size: int


@dataclass
class ExtractedSkill:
    """解压后的完整技能"""
    skill_md_content: str
    parsed: ParsedSkill
    resources: List[ResourceFile] = field(default_factory=list)


@dataclass
class ValidationResult:
    """验证结果"""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    parsed: Optional[ParsedSkill] = None


def parse_skill_md(content: str) -> ParsedSkill:
    """
    解析 SKILL.md 文件内容，提取 frontmatter 和 body

    Args:
        content: SKILL.md 文件的完整文本内容

    Returns:
        ParsedSkill 解析后的技能数据

    Raises:
        ValueError: 格式无效时
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError("未找到有效的 YAML frontmatter（需要以 --- 开头和结尾）")

    frontmatter_str = match.group(1)
    body = content[match.end():]

    try:
        frontmatter = yaml.safe_load(frontmatter_str)
    except yaml.YAMLError as e:
        raise ValueError(f"YAML 解析失败: {e}")

    if not isinstance(frontmatter, dict):
        raise ValueError("frontmatter 必须是 YAML 键值对格式")

    name = frontmatter.get("name")
    if not name:
        raise ValueError("缺少必填字段: name")

    description = frontmatter.get("description")
    if not description:
        raise ValueError("缺少必填字段: description")

    # 解析 allowed-tools（空格分隔字符串）
    allowed_tools_raw = frontmatter.get("allowed-tools")
    allowed_tools = None
    if allowed_tools_raw:
        if isinstance(allowed_tools_raw, str):
            allowed_tools = allowed_tools_raw.split()
        elif isinstance(allowed_tools_raw, list):
            allowed_tools = allowed_tools_raw

    # 解析 metadata
    metadata = frontmatter.get("metadata") or {}
    category = metadata.get("category") if isinstance(metadata, dict) else None
    tags = metadata.get("tags") if isinstance(metadata, dict) else None

    # display_name 优先用 metadata 中的，否则用 name
    display_name = name
    if isinstance(metadata, dict) and metadata.get("display_name"):
        display_name = metadata["display_name"]

    return ParsedSkill(
        name=name,
        description=str(description)[:1024],
        display_name=display_name,
        body_markdown=body.strip(),
        frontmatter_raw=frontmatter_str,
        license=frontmatter.get("license"),
        allowed_tools=allowed_tools,
        category=category,
        tags=tags if isinstance(tags, list) else None,
        metadata=metadata if isinstance(metadata, dict) else None,
    )


def validate_skill_md(content: str) -> ValidationResult:
    """
    验证 SKILL.md 格式

    Returns:
        ValidationResult 含 valid 标志和错误列表
    """
    errors: List[str] = []
    warnings: List[str] = []

    match = _FRONTMATTER_RE.match(content)
    if not match:
        return ValidationResult(valid=False, errors=["未找到有效的 YAML frontmatter"])

    frontmatter_str = match.group(1)
    try:
        frontmatter = yaml.safe_load(frontmatter_str)
    except yaml.YAMLError as e:
        return ValidationResult(valid=False, errors=[f"YAML 解析失败: {e}"])

    if not isinstance(frontmatter, dict):
        return ValidationResult(valid=False, errors=["frontmatter 必须是键值对格式"])

    # 必填字段检查
    name = frontmatter.get("name")
    if not name:
        errors.append("缺少必填字段: name")
    elif not _NAME_RE.match(str(name)):
        errors.append(f"name 格式无效 '{name}'，需要 kebab-case（小写字母、数字、连字符，以字母开头）")

    description = frontmatter.get("description")
    if not description:
        errors.append("缺少必填字段: description")
    elif len(str(description)) > 1024:
        errors.append("description 超过 1024 字符限制")

    body = content[match.end():].strip()
    if not body:
        warnings.append("Markdown body 为空")

    parsed = None
    if not errors:
        try:
            parsed = parse_skill_md(content)
        except ValueError as e:
            errors.append(str(e))

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        parsed=parsed,
    )


def extract_skill_zip(zip_bytes: bytes) -> ExtractedSkill:
    """
    解压技能 ZIP 包，提取 SKILL.md 和资源文件

    ZIP 包结构要求：
      根目录或一级子目录下必须包含 SKILL.md
      可选: scripts/, references/, assets/ 目录

    Args:
        zip_bytes: ZIP 文件的字节数据

    Returns:
        ExtractedSkill 含解析结果和资源文件列表

    Raises:
        ValueError: ZIP 格式无效或缺少 SKILL.md
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise ValueError("无效的 ZIP 文件")

    names = zf.namelist()

    # 过滤 __MACOSX 和隐藏文件
    names = [
        n for n in names
        if not n.startswith("__MACOSX") and not n.split("/")[-1].startswith(".")
    ]

    if not names:
        raise ValueError("ZIP 包为空")

    # 定位 SKILL.md（根目录或一级子目录）
    skill_md_path = None
    prefix = ""

    for name in names:
        basename = name.rsplit("/", 1)[-1]
        if basename == "SKILL.md":
            skill_md_path = name
            # 如果在子目录中，记录前缀
            if "/" in name:
                prefix = name.rsplit("/", 1)[0] + "/"
            break

    if not skill_md_path:
        raise ValueError("ZIP 包中未找到 SKILL.md 文件")

    # 读取 SKILL.md
    skill_md_content = zf.read(skill_md_path).decode("utf-8")
    parsed = parse_skill_md(skill_md_content)

    # 收集资源文件
    resources: List[ResourceFile] = []
    for name in names:
        if name == skill_md_path:
            continue
        if name.endswith("/"):
            continue  # 跳过目录

        # 去掉前缀得到相对路径
        rel_path = name
        if prefix and name.startswith(prefix):
            rel_path = name[len(prefix):]

        # 防止路径遍历攻击
        if ".." in rel_path:
            raise ValueError(f"ZIP 文件包含非法路径: {name}")

        # 判断资源类型
        top_dir = rel_path.split("/")[0] if "/" in rel_path else ""
        res_type = _RESOURCE_DIRS.get(top_dir)
        if not res_type:
            continue

        data = zf.read(name)
        if len(data) > _MAX_RESOURCE_SIZE:
            logger.warning("资源文件过大，跳过", path=rel_path, size=len(data))
            continue

        resources.append(ResourceFile(
            path=rel_path,
            type=res_type,
            content=data,
            size=len(data),
        ))

    zf.close()

    return ExtractedSkill(
        skill_md_content=skill_md_content,
        parsed=parsed,
        resources=resources,
    )
