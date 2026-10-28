"""DeepDoc Outlook MSG 邮件解析器（extract-msg，OLE 复合文档）。"""
from __future__ import annotations

from io import BytesIO

from novamind.engines.document.exceptions import MismatchedPayloadError
from novamind.engines.document.integrations.deepdoc.parsers.html import RAGFlowHtmlParser

# OLE 复合文档魔数（MSG 与旧版 Office 二进制格式共用）
_OLE_HEADER_MAGIC = b"\xd0\xcf\x11\xe0"


class RAGFlowMsgParser:
    """Outlook MSG 解析器：头部元信息 + 正文（纯文本优先，HTML 复用 html 解析器）。

    独立解析场景附件只列文件名清单；容器递归场景（msg 作为邮件容器上传）
    经 :meth:`body_and_attachments` 取附件字节流交宿主逐成员解析。
    """

    def __init__(self) -> None:
        """初始化 HTML 正文解析器（bodyHtml 复用）。"""
        self._html_parser = RAGFlowHtmlParser()

    def __call__(self, binary: bytes) -> list[str]:
        """解析 MSG 字节流为文本块列表。

        Args:
            binary: MSG 文件字节流。

        Returns:
            文本块列表：首块为邮件头，后续为正文块。

        Raises:
            MismatchedPayloadError: 非 OLE 载荷或 compound 文档损坏。
        """
        sections, _attachments = self.body_and_attachments(binary)
        return sections

    def body_and_attachments(
        self, binary: bytes
    ) -> tuple[list[str], list[tuple[str, bytes]]]:
        """解析 MSG 为（正文文本块列表, 附件 (文件名, 字节流) 列表）二元组。

        容器递归路径的统一入口：正文含头部元信息块，附件带原始字节流交
        调用方逐成员解析（嵌套 .msg 附件同样作为成员交给 msg 解析器递归）。

        Raises:
            MismatchedPayloadError: 非 OLE 载荷或 compound 文档损坏。
        """
        if not binary.startswith(_OLE_HEADER_MAGIC):
            raise MismatchedPayloadError(
                "msg 内容不是 Outlook 复合文档（扩展名与实际格式不符或文件损坏）",
                format_name="msg",
            )
        import extract_msg

        try:
            msg = extract_msg.openMsg(BytesIO(binary))
        except Exception as exc:
            raise MismatchedPayloadError(
                f"msg 复合文档解析失败（文件可能损坏）：{exc}",
                format_name="msg",
            ) from exc
        try:
            lines: list[str] = []
            for label, value in (
                ("发件人", getattr(msg, "sender", None)),
                ("收件人", getattr(msg, "to", None)),
                ("抄送", getattr(msg, "cc", None)),
                ("主题", getattr(msg, "subject", None)),
                ("日期", getattr(msg, "date", None)),
            ):
                if value:
                    lines.append(f"{label}：{value}")
            attachments: list[tuple[str, bytes]] = []
            attachment_names: list[str] = []
            for att in (getattr(msg, "attachments", None) or []):
                name = str(att.longFilename or att.shortFilename or "")
                if not name:
                    continue
                try:
                    data = att.data
                except Exception:
                    data = b""
                attachment_names.append(name)
                attachments.append((name, data or b""))
            if attachment_names:
                lines.append("附件：" + "、".join(attachment_names))
            sections: list[str] = ["\n".join(lines)] if lines else []

            body = (getattr(msg, "body", None) or "").strip()
            if body:
                sections.append(body)
                return sections, attachments
            html_body = (getattr(msg, "htmlBody", None) or b"").decode(
                "utf-8", errors="ignore"
            ).strip()
            if html_body:
                body_sections = self._html_parser(
                    "", binary=html_body.encode("utf-8")
                )
                sections.extend(s for s in body_sections if s.strip())
            return sections, attachments
        finally:
            msg.close()
