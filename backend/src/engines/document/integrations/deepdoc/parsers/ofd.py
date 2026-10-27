"""DeepDoc OFD 版式文档文本层提取器（GB/T 33190，zip + XML，零第三方依赖）。"""
from __future__ import annotations

import re
import zipfile
from io import BytesIO

from novamind.engines.document.exceptions import MismatchedPayloadError
from novamind.engines.document.integrations.deepdoc.compat import safe_fromstring

# OFD 命名空间（GB/T 33190-2016 固定值）
_OFD_NS = "http://www.ofdspec.org/2016"
_PAGE_NUM_RE = re.compile(r"Pages/Page_(\d+)/")


class RAGFlowOfdParser:
    """OFD 文本层粗提取：按页聚合 TextObject/TextCode 文本。

    边界（能力缺失而非错误，显式声明）：只提取文字层；版式坐标还原、
    印章/图片/签名、附件包不在提取范围。OFD 是国内政务/国企版式文档
    主流格式，文字层入检索已覆盖主需求。
    """

    def __call__(self, binary: bytes) -> list[str]:
        """解析 OFD 字节流为逐页文本块列表。

        Args:
            binary: OFD 文件字节流。

        Returns:
            逐页文本块列表（页序按 Page_N 数字序）；无文字层的纯印章/扫描
            OFD 返回空列表。

        Raises:
            MismatchedPayloadError: 非 zip 载荷或包结构损坏。
        """
        if not binary.startswith(b"PK\x03\x04"):
            raise MismatchedPayloadError(
                "ofd 内容不是 OFD 包（应为 zip 结构，扩展名与实际格式不符或文件损坏）",
                format_name="ofd",
            )
        try:
            zf = zipfile.ZipFile(BytesIO(binary))
        except zipfile.BadZipFile as exc:
            raise MismatchedPayloadError(
                "ofd 包结构损坏（zip 目录无法解析）",
                format_name="ofd",
            ) from exc

        page_texts: list[tuple[int, str]] = []
        with zf:
            for name in zf.namelist():
                if not name.endswith("Content.xml"):
                    continue
                match = _PAGE_NUM_RE.search(name)
                page_order = int(match.group(1)) if match else 0
                try:
                    root = safe_fromstring(zf.read(name))
                except Exception:
                    continue
                # TextCode 承载文字；doc:dgm 之外按文档序收集（同页内版面
                # 坐标排序不做——文本层粗提取，坐标在 meta 需求出现前不伪造）
                pieces = [
                    (node.text or "").strip()
                    for node in root.iter(f"{{{_OFD_NS}}}TextCode")
                    if (node.text or "").strip()
                ]
                if pieces:
                    page_texts.append((page_order, "\n".join(pieces)))

        page_texts.sort(key=lambda item: item[0])
        return [text for _order, text in page_texts]
