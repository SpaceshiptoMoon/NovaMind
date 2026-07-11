from __future__ import annotations

# Adapted from RAGFlow deepdoc/parser/epub_parser.py

import logging
import warnings
import zipfile
from io import BytesIO
from xml.etree import ElementTree

from src.shared.utils.deepdoc.ragflow_html_parser import RAGFlowHtmlParser

_OPF_NS = "http://www.idpf.org/2007/opf"
_CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
_XHTML_MEDIA_TYPES = {"application/xhtml+xml", "text/html", "text/xml"}

logger = logging.getLogger(__name__)


class RAGFlowEpubParser:
    """Parse EPUB files by extracting XHTML content in spine order."""

    def __call__(self, fnm, binary=None, chunk_token_num=512):
        if binary is not None:
            if not binary:
                logger.warning("RAGFlowEpubParser received an empty EPUB binary payload for %r", fnm)
                raise ValueError("Empty EPUB binary payload")
            zf = zipfile.ZipFile(BytesIO(binary))
        else:
            zf = zipfile.ZipFile(fnm)

        try:
            content_items = self._get_spine_items(zf)
            all_sections = []
            html_parser = RAGFlowHtmlParser()

            for item_path in content_items:
                try:
                    html_bytes = zf.read(item_path)
                except KeyError:
                    continue
                if not html_bytes:
                    logger.debug("Skipping empty EPUB content item: %s", item_path)
                    continue
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=UserWarning)
                    sections = html_parser(item_path, binary=html_bytes, chunk_token_num=chunk_token_num)
                all_sections.extend(sections)
            return all_sections
        finally:
            zf.close()

    @staticmethod
    def _get_spine_items(zf):
        try:
            container_xml = zf.read("META-INF/container.xml")
        except KeyError:
            return RAGFlowEpubParser._fallback_xhtml_order(zf)

        try:
            container_root = ElementTree.fromstring(container_xml)
        except ElementTree.ParseError:
            logger.warning("Failed to parse META-INF/container.xml; falling back to XHTML order.")
            return RAGFlowEpubParser._fallback_xhtml_order(zf)

        rootfile_el = container_root.find(f".//{{{_CONTAINER_NS}}}rootfile")
        if rootfile_el is None:
            return RAGFlowEpubParser._fallback_xhtml_order(zf)

        opf_path = rootfile_el.get("full-path", "")
        if not opf_path:
            return RAGFlowEpubParser._fallback_xhtml_order(zf)

        opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
        try:
            opf_xml = zf.read(opf_path)
        except KeyError:
            return RAGFlowEpubParser._fallback_xhtml_order(zf)

        try:
            opf_root = ElementTree.fromstring(opf_xml)
        except ElementTree.ParseError:
            logger.warning("Failed to parse OPF file '%s'; falling back to XHTML order.", opf_path)
            return RAGFlowEpubParser._fallback_xhtml_order(zf)

        manifest = {}
        for item in opf_root.findall(f".//{{{_OPF_NS}}}item"):
            item_id = item.get("id", "")
            href = item.get("href", "")
            media_type = item.get("media-type", "")
            if item_id and href:
                manifest[item_id] = (href, media_type)

        spine_items = []
        for itemref in opf_root.findall(f".//{{{_OPF_NS}}}itemref"):
            idref = itemref.get("idref", "")
            if idref not in manifest:
                continue
            href, media_type = manifest[idref]
            if media_type not in _XHTML_MEDIA_TYPES:
                continue
            spine_items.append(opf_dir + href)

        return spine_items if spine_items else RAGFlowEpubParser._fallback_xhtml_order(zf)

    @staticmethod
    def _fallback_xhtml_order(zf):
        return sorted(
            name
            for name in zf.namelist()
            if name.lower().endswith((".xhtml", ".html", ".htm")) and not name.startswith("META-INF/")
        )
