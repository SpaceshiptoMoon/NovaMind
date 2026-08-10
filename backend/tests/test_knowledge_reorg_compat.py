from __future__ import annotations

from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_document_reader_compat_modules_reexport_new_implementations():
    from novamind.features.knowledge_space.pipeline import DocumentProcessor
    from novamind.shared.document.readers.base_reader import BaseReader
    from novamind.shared.document.readers.docx_reader import DocxReader
    from novamind.shared.document.readers.pdf_reader import PDFReader
    from novamind.shared.document.readers.executor import run_in_executor
    from novamind.engines.document.splitters.recursive_splitter import RecursiveCharacterSplitter

    assert DocumentProcessor is not None
    assert BaseReader is not None
    assert DocxReader is not None
    assert PDFReader is not None
    assert run_in_executor is not None
    assert RecursiveCharacterSplitter is not None


def test_media_compat_modules_reexport_new_implementations():
    from novamind.engines.document.media.audio import transcribe_audio_local
    from novamind.engines.document.media.video import extract_video_frames
    from novamind.engines.document.media.vlm import build_vlm_image_messages

    assert extract_video_frames is not None
    assert transcribe_audio_local is not None
    assert build_vlm_image_messages is not None


def test_novamind_root_package_bridges_to_real_modules():
    import novamind as compat_novamind
    import novamind.shared as compat_shared
    import novamind.shared.utils as compat_utils
    from novamind.engines.document.integrations.deepdoc import DeepDocEngine
    from novamind.engines.document.integrations.deepdoc import DeepDocEngine as ReImportedDeepDocEngine

    assert (BACKEND_ROOT / "src").as_posix() in [Path(p).as_posix() for p in compat_novamind.__path__]
    assert (BACKEND_ROOT / "src" / "shared").as_posix() in [Path(p).as_posix() for p in compat_shared.__path__]
    assert (BACKEND_ROOT / "src" / "shared" / "utils").as_posix() in [Path(p).as_posix() for p in compat_utils.__path__]
    assert ReImportedDeepDocEngine is DeepDocEngine
