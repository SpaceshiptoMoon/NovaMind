from __future__ import annotations

from io import BytesIO

import logging
import pdfplumber

from src.shared.utils.deepdoc.constants import MAXIMUM_PAGE_NUMBER
from src.shared.utils.deepdoc.figure_support import picture_vision_llm_chunk
from src.shared.utils.deepdoc.ragflow_pdf_parser import RAGFlowPdfParser
from src.shared.utils.deepdoc.ragflow_pdf_plain_parser import RAGFlowPlainPdfParser
from src.shared.utils.deepdoc.ragflow_utils import extract_pdf_outlines


def vision_llm_describe_prompt(*, page: int) -> str:
    return f"Describe the content of PDF page {page}, preserving structure and key entities."


class PlainParser:
    def __init__(self):
        self._plain = RAGFlowPlainPdfParser()
        self.outlines = []
        self.pdf = None

    def __call__(self, filename, from_page=0, to_page=MAXIMUM_PAGE_NUMBER, **kwargs):
        docs, _, outlines = self._plain(filename, from_page=from_page, to_page=to_page)
        self.outlines = outlines
        return docs, []

    def crop(self, ck, need_position):
        raise NotImplementedError

    @staticmethod
    def remove_tag(txt):
        raise NotImplementedError


class VisionParser(RAGFlowPdfParser):
    def __init__(self, vision_model, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.vision_model = vision_model
        self.outlines = []
        self.total_page = 0

    def __images__(self, fnm, zoomin=3, page_from=0, page_to=MAXIMUM_PAGE_NUMBER, callback=None):
        try:
            with pdfplumber.open(fnm) if isinstance(fnm, str) else pdfplumber.open(BytesIO(fnm)) as pdf:
                self.pdf = pdf
                self.page_images = [
                    p.to_image(resolution=72 * zoomin).annotated
                    for p in self.pdf.pages[page_from:page_to]
                ]
                self.total_page = len(self.pdf.pages)
        except Exception:
            self.page_images = None
            self.total_page = 0
            logging.exception("VisionParser __images__")

    def __call__(self, filename, from_page=0, to_page=MAXIMUM_PAGE_NUMBER, **kwargs):
        callback = kwargs.get("callback", lambda prog, msg: None)
        zoomin = kwargs.get("zoomin", 3)
        self.__images__(fnm=filename, zoomin=zoomin, page_from=from_page, page_to=to_page, callback=callback)
        self.outlines = extract_pdf_outlines(filename)

        total_pdf_pages = self.total_page
        start_page = max(0, from_page)
        end_page = min(to_page, total_pdf_pages)
        all_docs = []

        for idx, img_binary in enumerate(self.page_images or []):
            pdf_page_num = from_page + idx
            if pdf_page_num < start_page or pdf_page_num >= end_page:
                continue

            text = picture_vision_llm_chunk(
                binary=img_binary,
                vision_model=self.vision_model,
                prompt=vision_llm_describe_prompt(page=pdf_page_num + 1),
                callback=callback,
            )

            if kwargs.get("callback"):
                kwargs["callback"](idx * 1.0 / max(len(self.page_images), 1), f"Processed: {idx + 1}/{len(self.page_images)}")

            if text:
                width, height = self.page_images[idx].size
                all_docs.append(
                    (
                        text,
                        f"@@{pdf_page_num + 1}\t{0.0:.1f}\t{width / zoomin:.1f}\t{0.0:.1f}\t{height / zoomin:.1f}##",
                    )
                )
        return all_docs, []


__all__ = ["RAGFlowPdfParser", "PlainParser", "VisionParser"]
