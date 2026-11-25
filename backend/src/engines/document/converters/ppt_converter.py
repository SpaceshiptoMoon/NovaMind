"""PPT/PPTX 转 PDF 转换器，经 LibreOffice headless 供 VLM 文档转写线视觉化。

VLM 转写需要页图；PPT 没有纯 Python 渲染路径——先 soffice 转 PDF 再走
统一的页渲染（media/ocr/qwen.render_pdf_page_images）。soffice 未安装时
显式抛错（调用方转终态失败并给安装指引），不做静默降级。
"""
import asyncio
import subprocess
import tempfile
from pathlib import Path

from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class PptConversionError(RuntimeError):
    """PPT/PPTX 转 PDF 失败（soffice 缺失或转换出错）。"""


def _convert_ppt_to_pdf_sync(file_bytes: bytes, filename: str) -> bytes:
    """同步转换：临时目录落地 → soffice --convert-to pdf → 读回字节。

    Args:
        file_bytes: .ppt/.pptx 文件字节。
        filename: 原始文件名（决定临时落地名与输出 stem）。

    Returns:
        转换出的 PDF 字节。

    Raises:
        PptConversionError: soffice 未安装（含安装指引）或转换失败。
    """
    # 惰性 import 复用 doc_converter 的定位器（PATH + Windows 常见路径）
    from novamind.engines.document.converters.doc_converter import find_soffice

    soffice = find_soffice()
    if not soffice:
        raise PptConversionError(
            "服务器未安装 LibreOffice（soffice），PPT 的 VLM 转写需要先把幻灯片转成"
            "图片。请在部署环境安装：镜像构建参数 OFFICE_CONVERT=true，或手动"
            " apt install libreoffice-impress fonts-noto-cjk（中文字体必装，否则"
            "中文幻灯片转出乱码方块）"
        )

    with tempfile.TemporaryDirectory(prefix="novamind_ppt_convert_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        source_path = tmp_path / (filename or "input.pptx")
        source_path.write_bytes(file_bytes)

        command = [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_path),
            str(source_path),
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=180, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise PptConversionError("LibreOffice 转换 PPT 超时（180s）") from exc
        if result.returncode != 0:
            raise PptConversionError(
                f"LibreOffice 转换 PPT 失败: "
                f"{result.stderr.strip() or result.stdout.strip() or 'unknown error'}"
            )

        output_path = tmp_path / f"{source_path.stem}.pdf"
        if not output_path.exists():
            raise PptConversionError("LibreOffice 转换完成但未生成 PDF 文件")
        pdf_bytes = output_path.read_bytes()

    if not pdf_bytes:
        raise PptConversionError("LibreOffice 转换产物为空")
    return pdf_bytes


async def convert_ppt_to_pdf(file_bytes: bytes, filename: str) -> bytes:
    """异步入口：把同步转换放到线程池执行，避免阻塞事件循环。

    Args:
        file_bytes: .ppt/.pptx 文件字节流。
        filename: 原始文件名（带扩展名）。

    Returns:
        转换后的 PDF 字节流。

    Raises:
        PptConversionError: soffice 未安装或转换失败。
    """
    logger.info("PPT 转 PDF 开始", filename=filename, size=len(file_bytes))
    pdf_bytes = await asyncio.to_thread(_convert_ppt_to_pdf_sync, file_bytes, filename)
    logger.info("PPT 转 PDF 完成", filename=filename, pdf_size=len(pdf_bytes))
    return pdf_bytes
