"""嵌套载荷展开器：zip 压缩包的递归展开与容器成员限额。

企业上传常见「zip 里一堆 docx」——解析层把合法容器展开为成员流，逐成员
交既有解析器（成员天然过各自入口守卫：魔数/加密/zip 检查）。防御纪律：
展开总量与成员数上限（zip 炸弹第二道闸——guard_office_zip 拦单 entry 膨胀
比，此处拦解压总量）、嵌套深度限制、超限拒收整包而非静默截断（部分内容
入库比明确失败更难排查）。邮件附件展开归 eml/msg 解析器
（body_and_attachments），附件成员经 :func:`check_member_limits` 走同一限额。
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from io import BytesIO

from novamind.engines.document.exceptions import MismatchedPayloadError

# 展开防御上限：成员总数 / 解压后总量 / 嵌套 zip 再展开层数。
# 上传层限单文件 100MB，解压膨胀按 2 倍余量放行；超限拒绝整包。
ARCHIVE_MAX_MEMBERS = 100
ARCHIVE_MAX_TOTAL_BYTES = 200 * 1024 * 1024
ARCHIVE_MAX_DEPTH = 1

# 展开时跳过的噪音成员（macOS 打包元数据/目录项/隐藏文件）
_SKIP_NAME_PARTS = ("__MACOSX/", ".DS_Store")


@dataclass(slots=True)
class ArchiveMember:
    """容器展开出的单个成员。

    Attributes:
        name: 成员显示名（zip 内相对路径 / 附件文件名），正文标题与
            region 前缀共用。
        blob: 成员字节流（zip 套 zip 时为内层包全量字节）。
        depth: 嵌套深度（顶层容器成员为 0，内层 zip 的成员为 1）。
    """

    name: str
    blob: bytes
    depth: int = 0


def _is_noise_name(name: str) -> bool:
    """目录项/打包元数据/隐藏文件不算成员。"""
    if name.endswith("/"):
        return True
    return any(part in name for part in _SKIP_NAME_PARTS) or name.startswith(".")


def _members_within_limits(members: list[ArchiveMember], format_name: str) -> list[ArchiveMember]:
    """成员数/解压总量超限时拒收整包（部分内容入库比明确失败更难排查）。"""
    if len(members) > ARCHIVE_MAX_MEMBERS:
        raise MismatchedPayloadError(
            f"{format_name} 成员数超过上限（{len(members)} > {ARCHIVE_MAX_MEMBERS}），"
            "请解压后分批上传",
            format_name=format_name,
        )
    total = sum(len(member.blob) for member in members)
    if total > ARCHIVE_MAX_TOTAL_BYTES:
        raise MismatchedPayloadError(
            f"{format_name} 解压后总量超过上限"
            f"（{total // (1024 * 1024)}MB > {ARCHIVE_MAX_TOTAL_BYTES // (1024 * 1024)}MB），"
            "请解压后分批上传",
            format_name=format_name,
        )
    return members


# 邮件附件成员与 zip 成员走同一限额的公共入口
check_member_limits = _members_within_limits


def expand_zip_members(binary: bytes, format_name: str = "zip") -> list[ArchiveMember]:
    """展开 zip 为成员流（guard_office_zip 前置 + 嵌套 zip 递归一层）。

    成员过滤目录/__MACOSX/.DS_Store/隐藏文件；嵌套 zip 在深度上限内递归
    展开（内层包自身过结构守卫），超出深度按普通成员保留（不解析、正文
    列名——能力缺失优于错误结果）。成员数与解压总量按跨层合计检查。

    Raises:
        MismatchedPayloadError: 非 zip 内容 / 任意层结构损坏 / 成员数或
            解压总量超限。
    """
    members = _expand_zip_recursive(binary, format_name, depth=0)
    return _members_within_limits(members, format_name)


def _expand_zip_recursive(binary: bytes, format_name: str, depth: int) -> list[ArchiveMember]:
    """单层展开：嵌套 zip 在深度上限内递归，其余条目直接成成员。"""
    if not binary.startswith(b"PK\x03\x04"):
        raise MismatchedPayloadError(
            f"{format_name} 内容不是 zip 包（可能是其它格式改名或文件损坏）",
            format_name=format_name,
        )
    from novamind.engines.document.integrations.deepdoc.compat import guard_office_zip

    guard_office_zip(binary, format_name)
    members: list[ArchiveMember] = []
    with zipfile.ZipFile(BytesIO(binary)) as zf:
        for info in zf.infolist():
            if _is_noise_name(info.filename):
                continue
            blob = zf.read(info.filename)
            if info.filename.lower().endswith(".zip") and depth < ARCHIVE_MAX_DEPTH:
                members.extend(
                    _expand_zip_recursive(blob, info.filename, depth=depth + 1)
                )
                continue
            members.append(ArchiveMember(name=info.filename, blob=blob, depth=depth))
    return members
