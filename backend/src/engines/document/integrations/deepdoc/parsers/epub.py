"""DeepDoc EPUB 解析器。"""
from __future__ import annotations

# Adapted from RAGFlow deepdoc/parser/epub_parser.py
import logging
import posixpath
import re
import warnings
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from novamind.engines.document.integrations.deepdoc.core.document_model import (
    document_salt,
    figure_placeholder,
)
from novamind.engines.document.integrations.deepdoc.parsers.html import RAGFlowHtmlParser

# 章节 xhtml 里 <img src="..."> 的宽松提取（html 容错优先于严格 XML 解析——
# 真实 epub 的 xhtml 常有未闭合标签，ElementTree 会整章解析失败）
_IMG_SRC_RE = re.compile(r"""<img[^>]*?["']?src=["']([^"']+)["']""", re.IGNORECASE)

_OPF_NS = "http://www.idpf.org/2007/opf"
_CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
_XHTML_MEDIA_TYPES = {"application/xhtml+xml", "text/html", "text/xml"}

logger = logging.getLogger(__name__)


class RAGFlowEpubParser:
    """Parse EPUB files by extracting XHTML content in spine order."""

    def __call__(self, fnm, binary=None, chunk_token_num=512):
        """解析 EPUB 为（章节 section 列表, 图片 figure 契约列表）二元组。

        沿用 HTML 解析器的 section 结构；章节 xhtml 内 <img> 的 blob 经
        OPF manifest 映射提取，markdown 图片占位符附在所属章节文本尾部
        （章节是 epub 的自然锚定粒度）。

        Args:
            fnm: 文件路径（binary 为 None 时使用）。
            binary: EPUB 字节流；与 fnm 二选一，空字节流抛 ValueError。
            chunk_token_num: 传给 HTML 解析器的分块 token 上限。
        """
        if binary is not None:
            if not binary:
                logger.warning("RAGFlowEpubParser received an empty EPUB binary payload for %r", fnm)
                raise ValueError("Empty EPUB binary payload")
            zf = zipfile.ZipFile(BytesIO(binary))
            figure_salt = document_salt(binary)
        else:
            zf = zipfile.ZipFile(fnm)
            figure_salt = document_salt(Path(fnm).read_bytes())

        try:
            content_items, image_hrefs, manifest = self._get_spine_items(zf)
            all_sections = []
            figures = []
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

                # 章节 <img> 提取：src 相对章节目录归一化后必须在 manifest 的
                # image href 集合内（防 zip 路径穿越/外链）
                chapter_dir = posixpath.dirname(item_path)
                html_text = html_bytes.decode("utf-8", errors="replace")
                chapter_figures = []
                for src_attr in _IMG_SRC_RE.findall(html_text):
                    resolved = posixpath.normpath(
                        posixpath.join(chapter_dir, src_attr)
                    ).lstrip("/")
                    if resolved not in image_hrefs:
                        continue
                    try:
                        blob = zf.read(resolved)
                    except (KeyError, RuntimeError):
                        continue
                    if not blob:
                        continue
                    artifact_id = f"epub_fig_{len(figures)}"
                    placeholder = figure_placeholder(figure_salt, artifact_id)
                    figures.append({
                        "artifact_id": artifact_id,
                        "placeholder": placeholder,
                        "pages": [],
                        "page_start": 0,
                        "bbox": {},
                        "caption": f"EPUB 插图（{posixpath.basename(resolved)}）",
                        "text": "",
                        "member_texts": [],
                        "image_blobs": [blob],
                    })
                    chapter_figures.append(f"![{posixpath.basename(resolved)}]({placeholder})")
                if chapter_figures and all_sections:
                    all_sections.append("\n".join(chapter_figures))
            return all_sections, figures
        finally:
            zf.close()

    @staticmethod
    def _get_spine_items(zf):
        """按 spine 阅读顺序取（章节条目, image href 集合, manifest）三元组。

        链路任一环缺失时走兜底排序（image 集合与 manifest 为空——兜底场景
        图片不提取，能力缺失优于错误结果）。
        """
        try:
            container_xml = zf.read("META-INF/container.xml")
        except KeyError:
            return RAGFlowEpubParser._fallback_xhtml_order(zf), set(), {}, set(), {}

        try:
            container_root = ElementTree.fromstring(container_xml)
        except ElementTree.ParseError:
            logger.warning("Failed to parse META-INF/container.xml; falling back to XHTML order.")
            return RAGFlowEpubParser._fallback_xhtml_order(zf), set(), {}

        rootfile_el = container_root.find(f".//{{{_CONTAINER_NS}}}rootfile")
        if rootfile_el is None:
            return RAGFlowEpubParser._fallback_xhtml_order(zf), set(), {}

        opf_path = rootfile_el.get("full-path", "")
        if not opf_path:
            return RAGFlowEpubParser._fallback_xhtml_order(zf), set(), {}

        opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
        try:
            opf_xml = zf.read(opf_path)
        except KeyError:
            return RAGFlowEpubParser._fallback_xhtml_order(zf), set(), {}

        try:
            opf_root = ElementTree.fromstring(opf_xml)
        except ElementTree.ParseError:
            logger.warning("Failed to parse OPF file '%s'; falling back to XHTML order.", opf_path)
            return RAGFlowEpubParser._fallback_xhtml_order(zf), set(), {}

        manifest = {}
        for item in opf_root.findall(f".//{{{_OPF_NS}}}item"):
            item_id = item.get("id", "")
            href = item.get("href", "")
            media_type = item.get("media-type", "")
            if item_id and href:
                manifest[item_id] = (href, media_type)

        spine_items = []
        image_hrefs = {
            posixpath.normpath(posixpath.join(opf_dir, href)).lstrip("/")
            for href, media_type in manifest.values()
            if media_type.startswith("image/")
        }
        for itemref in opf_root.findall(f".//{{{_OPF_NS}}}itemref"):
            idref = itemref.get("idref", "")
            if idref not in manifest:
                continue
            href, media_type = manifest[idref]
            if media_type not in _XHTML_MEDIA_TYPES:
                continue
            spine_items.append(opf_dir + href)

        if not spine_items:
            return RAGFlowEpubParser._fallback_xhtml_order(zf), set(), {}
        return spine_items, image_hrefs, manifest

    @staticmethod
    def _fallback_xhtml_order(zf):
        """spine 元数据缺失时按文件名排序的兜底章节序。"""
        return sorted(
            name
            for name in zf.namelist()
            if name.lower().endswith((".xhtml", ".html", ".htm")) and not name.startswith("META-INF/")
        )
