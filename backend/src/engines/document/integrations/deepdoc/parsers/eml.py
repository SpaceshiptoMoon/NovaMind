"""DeepDoc EML 邮件解析器（RFC 822，标准库 email，零第三方依赖）。"""
from __future__ import annotations

import email
from io import BytesIO
from email import policy

from novamind.engines.document.integrations.deepdoc.parsers.html import RAGFlowHtmlParser


class RAGFlowEmlParser:
    """EML 邮件解析器：头部元信息 + 正文（纯文本优先，HTML 复用 html 解析器）。

    附件只列文件名清单不提取内容（能力边界显式声明）——附件作为独立文档
    入库由上层决定，解析器不静默吞掉也不递归解析。
    """

    def __init__(self) -> None:
        """初始化 HTML 正文解析器（text/html 部件复用）。"""
        self._html_parser = RAGFlowHtmlParser()

    def __call__(self, binary: bytes) -> list[str]:
        """解析 EML 字节流为文本块列表。

        Args:
            binary: EML 文件字节流。

        Returns:
            文本块列表：首块为邮件头（发件人/收件人/主题/日期/附件），
            后续为正文块。无正文的纯附件邮件只有头块。

        Raises:
            ValueError: 非法邮件格式（email 库解析出无头节点的裸内容）。
        """
        msg = email.message_from_bytes(binary, policy=policy.default)
        if msg["From"] is None and msg["Subject"] is None:
            raise ValueError("EML 内容无法识别为 RFC 822 邮件（缺少头节点）")

        lines: list[str] = []
        for label, key in (
            ("发件人", "From"),
            ("收件人", "To"),
            ("主题", "Subject"),
            ("日期", "Date"),
        ):
            value = msg[key]
            if value:
                lines.append(f"{label}：{value}")

        attachments = [
            str(part.get_filename())
            for part in msg.walk()
            if part.get_content_disposition() == "attachment" and part.get_filename()
        ]
        if attachments:
            lines.append("附件：" + "、".join(attachments))
        sections: list[str] = ["\n".join(lines)] if lines else []

        html_body = None
        text_body = None
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain" and text_body is None:
                try:
                    text_body = part.get_content()
                except Exception:
                    text_body = None
            elif content_type == "text/html" and html_body is None:
                try:
                    html_body = part.get_content()
                except Exception:
                    html_body = None

        body_text = ""
        if text_body and str(text_body).strip():
            body_text = str(text_body)
        elif html_body and str(html_body).strip():
            # HTML 正文复用 html 解析器（噪音剔除/实体解码/表格转块同链）
            body_sections = self._html_parser(
                "", binary=str(html_body).encode("utf-8")
            )
            sections.extend(s for s in body_sections if s.strip())
            return sections
        if body_text.strip():
            sections.append(body_text.strip())
        return sections
