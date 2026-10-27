"""DeepDoc 兼容层：映射上游 RAGFlow 的模块路径 / 类名 / 函数签名到本实现。"""
from __future__ import annotations

import re
from dataclasses import dataclass


class SimpleTokenizer:
    """Compatibility shim for the subset of RAGFlow tokenizer APIs we need."""

    _token_pattern = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")

    def tokenize(self, text: str) -> str:
        """按中英文词边界粗分词，空格连接（上游 ragflow NltkTokenizer 的轻量替身）。

        Args:
            text: 待分词文本。

        Returns:
            空格连接的词串。
        """
        return " ".join(self._token_pattern.findall(text or ""))

    def tag(self, token: str) -> str:
        """词性粗标（n 名词/nr 人名/en 英文/m 数词/x 其他），供上游命名体识别路径兼容。

        Args:
            token: 单个词。

        Returns:
            词性标记字符串。
        """
        token = token or ""
        if self.is_chinese(token):
            return "n"
        if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*", token):
            return "nr"
        if re.fullmatch(r"[A-Za-z]+", token):
            return "en"
        if re.fullmatch(r"[0-9]+", token):
            return "m"
        return "x"

    def strQ2B(self, text: str) -> str:
        """全角字符转半角（含全角空格 U+3000），对齐上游 rag_tokenizer.strQ2B。

        Args:
            text: 待转换文本。

        Returns:
            半角文本。
        """
        chars: list[str] = []
        for ch in text or "":
            code = ord(ch)
            if code == 0x3000:
                chars.append(" ")
                continue
            if 0xFF01 <= code <= 0xFF5E:
                chars.append(chr(code - 0xFEE0))
                continue
            chars.append(ch)
        return "".join(chars)

    def tradi2simp(self, text: str) -> str:
        """繁转简的占位实现（无 OpenCC 依赖时原样返回）。

        Args:
            text: 待转换文本。

        Returns:
            原样返回输入。
        """
        # Lightweight fallback when OpenCC-style conversion is unavailable.
        return text or ""

    @staticmethod
    def is_chinese(text: str) -> bool:
        """字符串是否含任一 CJK 汉字。

        Args:
            text: 待检测文本。

        Returns:
            含 CJK 汉字为 True。
        """
        return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")


rag_tokenizer = SimpleTokenizer()


def num_tokens_from_string(text: str) -> int:
    """估算文本 token 数（分词后按空格计数），上游同名函数的兼容实现。

    Args:
        text: 待估算文本。

    Returns:
        token 数估计值。
    """
    tokenized = rag_tokenizer.tokenize(text or "")
    return len(tokenized.split()) if tokenized else 0


def _has_utf16_signature(binary: bytes) -> bool:
    """无 BOM 字节流是否具备 UTF-16 文本特征。

    UTF-16 的拉丁字符高字节是 \\x00，NUL 占比显著（纯英文 ~50%，中英混排
    ~10%+）；纯 CJK UTF-16 无 NUL，与 gb18030 存在真歧义——该场景让位
    gb18030（中文环境默认编码）。5% 分界下：合法多字节文本（gb18030/
    Shift-JIS/Big5 码位不含 0x00）占比恒为 0，两侧分离度充分。
    """
    if len(binary) < 4 or len(binary) % 2:
        return False
    return binary.count(0) / len(binary) >= 0.05


def find_codec(binary: bytes) -> str:
    """按 BOM → utf-8 → utf-16(特征) → gb18030 → 统计探测 → latin-1 探测。

    Args:
        binary: 待探测字节流。

    Returns:
        探测到的编码名。

    Notes:
        - BOM 是编码的最强信号，前置直判；utf-8-sig 解码仍会在文本首保留
          \\ufeff，消费方（decode_text_binary）负责剥除。
        - utf-16 探测必须有 NUL 特征门控：utf-16-le 几乎接受任何偶数长度
          字节流，「能解码」不代表「是 UTF-16」——无门控会把 gb18030 中文
          全部劫持成乱码（6d58ee1f 回归实测）；门控后仍覆盖原修复场景
          （Excel 导出的 ASCII 为主 UTF-16 文本，NUL 占比高）。
        - latin-1 接受一切字节，「解码成功」不等于「编码正确」——日文/
          繁中/韩文字节流会在 gb18030 或 latin-1 静默乱码，因此 latin-1
          之前先做一次统计探测（charset-normalizer，requests 依赖树自带，
          覆盖 Shift-JIS/Big5/EUC-KR 等）。
    """
    if binary.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if binary.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    # NUL 特征优先于 utf-8：纯 ASCII 的 UTF-16LE 字节流是合法 UTF-8（NUL
    # 是合法码点），但正常文本不含 NUL——显著 NUL 占比即判 UTF-16
    if _has_utf16_signature(binary):
        try:
            binary.decode("utf-16")
            return "utf-16"
        except Exception:
            pass
    try:
        binary.decode("utf-8")
        return "utf-8"
    except Exception:
        pass
    try:
        binary.decode("gb18030")
        return "gb18030"
    except Exception:
        pass
    try:
        from charset_normalizer import from_bytes

        match = from_bytes(binary).best()
        if match and match.encoding:
            return str(match.encoding)
    except Exception:
        pass
    return "latin-1"


def decode_text_binary(binary: bytes) -> str:
    """文本族字节流统一解码与消毒入口（BOM 剥除 + 行尾归一 + NUL 剔除）。

    处理三类实测污染（2026-10 文本族质量批次）：
    - BOM：utf-8-sig 解码仍会在文本首保留 \\ufeff 字符——显式剥除，防
      「ï»¿」双重编码形态进首块；
    - 行尾：\\r\\n 与孤立 \\r 归一为 \\n（Windows/老 Mac 导出文件）；
    - NUL：UTF-16 误判等来源的 \\x00 剔除。
    """
    encoding = find_codec(binary)
    text = binary.decode(encoding, errors="ignore")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x00", "")
    return text


def safe_fromstring(blob: bytes):
    """解析不可信 XML（禁 DTD/实体展开/网络取用），防实体炸弹与 XXE。

    OOXML part（脚注/页眉/图表/SmartArt 等）经 lxml 直解析时默认展开实体——
    恶意文档可在 part 里藏「billion laughs」放大器拖垮 worker。所有解析器
    对文档内嵌 XML 的解析必须经此入口。

    Args:
        blob: 待解析 XML 字节流。

    Returns:
        lxml 根元素。
    """
    from lxml import etree

    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
    )
    return etree.fromstring(blob, parser=parser)


# zip 解压比下限：单 entry 解压后体积超过该值且压缩比低于下限时判为炸弹。
# 与 Apache POI ZipSecureFile 默认 minInflateRatio（0.01）同款依据——已压缩
# 格式（png/jpg）在 zip 内 ratio 接近 1，全 NUL 炸弹 ratio 趋近 0，1% 分界
# 两侧分离度充分。
_ZIP_MIN_INFLATE_RATIO = 0.01
_ZIP_BOMB_MIN_UNCOMPRESSED = 1024 * 1024


def guard_office_zip(binary: bytes, format_name: str) -> None:
    """OOXML zip 包结构守卫：拒收损坏包/重复条目/解压炸弹。

    Args:
        binary: 文件字节流（调用方已确认以 PK 魔数开头）。
        format_name: 声明格式名，用于错误消息。

    Raises:
        MismatchedPayloadError: zip 目录损坏 / 同名条目重复（不同读取器会
            选中不同条目导致内容静默不一致，对齐 POI 5.4.0 拒收语义）/
            高膨胀低压缩比条目（解压炸弹）。
    """
    import zipfile
    from collections import Counter
    from io import BytesIO

    from novamind.engines.document.exceptions import MismatchedPayloadError

    try:
        zf = zipfile.ZipFile(BytesIO(binary))
    except zipfile.BadZipFile as exc:
        raise MismatchedPayloadError(
            f"{format_name} 内容不是有效的 OOXML zip 包（文件损坏或扩展名与实际格式不符）",
            format_name=format_name,
        ) from exc
    with zf:
        names = zf.namelist()
        duplicated = [name for name, count in Counter(names).items() if count > 1]
        if duplicated:
            raise MismatchedPayloadError(
                f"{format_name} 包内存在重复条目：{duplicated[:3]}（文件结构异常，可能被拼接篡改）",
                format_name=format_name,
            )
        for info in zf.infolist():
            if info.file_size <= _ZIP_BOMB_MIN_UNCOMPRESSED:
                continue
            if info.compress_size / info.file_size < _ZIP_MIN_INFLATE_RATIO:
                raise MismatchedPayloadError(
                    f"{format_name} 包内条目 {info.filename} 压缩比异常"
                    f"（解压后 {info.file_size} 字节），疑似解压炸弹，已拒收",
                    format_name=format_name,
                )


@dataclass(slots=True)
class LazyImage:
    """页图像字节序列的惰性容器（vendored 层按需取用，不做提前解码）。"""

    blobs: list[bytes]

    def first(self) -> bytes | None:
        """取首页图像字节；无页时 None。"""
        return self.blobs[0] if self.blobs else None

    def __bool__(self) -> bool:
        """是否持有任何页图像。"""
        return bool(self.blobs)
