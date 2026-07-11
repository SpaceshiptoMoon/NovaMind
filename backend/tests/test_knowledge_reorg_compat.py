from __future__ import annotations

from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_document_reader_compat_modules_reexport_new_implementations():
    from src.shared.document_processing.pipeline.document_loader import DocumentProcessor as NewDocumentProcessor
    from src.shared.document_processing.readers.base_reader import BaseReader as NewBaseReader
    from src.shared.document_processing.readers.docx_reader import DocxReader as NewDocxReader
    from src.shared.document_processing.readers.pdf_reader import PDFReader as NewPDFReader
    from src.shared.document_processing.readers.executor import run_in_executor as NewRunInExecutor
    from src.shared.document_processing.splitters.recursive_splitter import (
        RecursiveCharacterSplitter as NewRecursiveCharacterSplitter,
    )
    from src.shared.utils.document_readers import DocumentProcessor
    from src.shared.utils.document_readers.base_reader import BaseReader
    from src.shared.utils.document_readers.docx_reader import DocxReader
    from src.shared.utils.document_readers.pdf_reader import PDFReader
    from src.shared.utils.document_readers.executor import run_in_executor
    from src.shared.utils.document_readers.splitters.recursive_splitter import RecursiveCharacterSplitter

    assert DocumentProcessor is NewDocumentProcessor
    assert BaseReader is NewBaseReader
    assert DocxReader is NewDocxReader
    assert PDFReader is NewPDFReader
    assert run_in_executor is NewRunInExecutor
    assert RecursiveCharacterSplitter is NewRecursiveCharacterSplitter


def test_media_compat_modules_reexport_new_implementations():
    from src.shared.media_processing.audio import transcribe_audio_local as NewTranscribeAudioLocal
    from src.shared.media_processing.video import extract_video_frames as NewExtractVideoFrames
    from src.shared.media_processing.vlm import build_vlm_image_messages as NewBuildVlmImageMessages
    from src.shared.utils.media_utils import extract_video_frames, transcribe_audio_local
    from src.shared.utils.vlm_utils import build_vlm_image_messages

    assert extract_video_frames is NewExtractVideoFrames
    assert transcribe_audio_local is NewTranscribeAudioLocal
    assert build_vlm_image_messages is NewBuildVlmImageMessages


def test_source_root_compat_packages_bridge_to_real_modules():
    import src as compat_src
    import src.shared as compat_shared
    import src.shared.utils as compat_utils
    from src.shared.utils.deepdoc import DeepDocEngine
    from src.src.shared.utils.deepdoc import DeepDocEngine as NestedCompatDeepDocEngine

    assert (BACKEND_ROOT / "src").as_posix() in [Path(p).as_posix() for p in compat_src.__path__]
    assert (BACKEND_ROOT / "src" / "shared").as_posix() in [Path(p).as_posix() for p in compat_shared.__path__]
    assert (BACKEND_ROOT / "src" / "shared" / "utils").as_posix() in [Path(p).as_posix() for p in compat_utils.__path__]
    assert NestedCompatDeepDocEngine is DeepDocEngine
