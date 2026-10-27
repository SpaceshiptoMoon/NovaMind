"""文档解析载荷异常族：引擎层统一显式失败语义。

坏文档（加密/伪格式/损坏包）不应以底层库异常链裸栈上抛——宿主（解析任务）
需要可区分、可直陈用户的失败原因。引擎只做检测与显式报错，不做解密/修复
（失败方向安全：能力缺失优于静默错误结果）。
"""
from __future__ import annotations


class ParsePayloadError(Exception):
    """文件载荷无法解析为声明格式的基类。

    Attributes:
        format_name: 声明格式名（docx/xlsx/pptx/pdf），用于错误消息语境。
    """

    def __init__(self, message: str, format_name: str = "") -> None:
        """初始化异常消息与格式语境。"""
        super().__init__(message)
        self.format_name = format_name


class EncryptedDocumentError(ParsePayloadError):
    """文档已加密（打开密码/IRM 敏感度标签/权限密码），引擎不提供解密。"""


class MismatchedPayloadError(ParsePayloadError):
    """文件内容与声明格式不符或包结构损坏（伪扩展名/损坏 zip/旧版二进制格式）。"""
