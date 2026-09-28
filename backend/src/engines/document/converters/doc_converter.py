"""旧版 .doc 转 .docx 转换器，经 soffice 或 win32com 执行在线格式迁移。"""
import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class DocConversionError(RuntimeError):
    """Raised when a legacy .doc file cannot be converted to .docx."""


def _find_soffice() -> str | None:
    """定位 soffice 可执行文件：先查 PATH，再探测 Windows 常见安装路径；找不到返回 None。"""
    candidates = [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def _convert_with_soffice(source_path: Path, target_dir: Path) -> bytes | None:
    """用 LibreOffice headless 转 .doc 为 .docx；未安装返回 None，转换失败抛 DocConversionError。"""
    soffice = _find_soffice()
    if not soffice:
        return None

    command = [
        soffice,
        "--headless",
        "--convert-to",
        "docx",
        "--outdir",
        str(target_dir),
        str(source_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode != 0:
        raise DocConversionError(
            f"LibreOffice 转换 .doc 失败: {result.stderr.strip() or result.stdout.strip() or 'unknown error'}"
        )

    output_path = target_dir / f"{source_path.stem}.docx"
    if not output_path.exists():
        raise DocConversionError("LibreOffice 转换完成但未生成 .docx 文件")

    return output_path.read_bytes()


def _convert_with_win32com(source_path: Path, target_dir: Path) -> bytes | None:
    """Windows-only 路径：经 Word COM 组件（pywin32）转 .doc 为 .docx；未装 pywin32 返回 None 交下一转换器，COM 失败抛错。"""
    try:
        import pythoncom
        import win32com.client  # type: ignore[import-not-found]
    except ImportError:
        return None

    output_path = target_dir / f"{source_path.stem}.docx"
    pythoncom.CoInitialize()
    word = None
    document = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        document = word.Documents.Open(str(source_path), ReadOnly=True)
        document.SaveAs(str(output_path), FileFormat=16)
    except Exception as exc:  # pragma: no cover - depends on host environment
        raise DocConversionError(f"Word COM 转换 .doc 失败: {exc}") from exc
    finally:
        if document is not None:
            document.Close(False)
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()

    if not output_path.exists():
        raise DocConversionError("Word COM 转换完成但未生成 .docx 文件")

    return output_path.read_bytes()


def _convert_doc_to_docx_sync(file_bytes: bytes, filename: str) -> bytes:
    """同步转换主流程：临时目录落地后依次尝试 soffice 与 Word COM，全部不可用抛 DocConversionError。"""
    with tempfile.TemporaryDirectory(prefix="novamind_doc_convert_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        source_path = tmp_path / filename
        source_path.write_bytes(file_bytes)

        for converter in (_convert_with_soffice, _convert_with_win32com):
            try:
                result = converter(source_path, tmp_path)
                if result:
                    logger.info("Legacy .doc converted to .docx", filename=filename, converter=converter.__name__)
                    return result
            except DocConversionError:
                raise
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.warning("DOC converter failed unexpectedly", filename=filename, converter=converter.__name__, error=str(exc))

    raise DocConversionError("服务器未配置 .doc 转换能力，请安装 LibreOffice 或 Word COM 组件")


async def convert_doc_to_docx(file_bytes: bytes, filename: str) -> bytes:
    """异步入口：把同步转换放到线程池执行，避免阻塞事件循环。

    Args:
        file_bytes: 旧版 .doc 文件字节流。
        filename: 原始文件名（带扩展名，决定临时落地名）。

    Returns:
        转换后的 .docx 文件字节流；输出写入临时目录、不落业务存储。

    Raises:
        DocConversionError: LibreOffice 与 Word COM 两条路径均不可用或转换失败。
    """
    return await asyncio.to_thread(_convert_doc_to_docx_sync, file_bytes, filename)
