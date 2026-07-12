import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from novamind.core.middleware.structured_logging import get_logger


logger = get_logger(__name__)


class DocConversionError(RuntimeError):
    """Raised when a legacy .doc file cannot be converted to .docx."""


def _find_soffice() -> Optional[str]:
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


def _convert_with_soffice(source_path: Path, target_dir: Path) -> Optional[bytes]:
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


def _convert_with_win32com(source_path: Path, target_dir: Path) -> Optional[bytes]:
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
    return await asyncio.to_thread(_convert_doc_to_docx_sync, file_bytes, filename)
