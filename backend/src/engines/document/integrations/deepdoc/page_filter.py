"""DeepDoc 页面筛选：按页码范围 / 内容密度过滤文档页。"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

TOC_HEADING_PATTERN = re.compile(
    r"(contents|目录|目次|table of contents|致谢|acknowledge(?:ment)?s?)$",
    re.IGNORECASE,
)
# 乱码文字层残留（cid/PUA/锟，doc 566 回归）+ 目录点线（上游 _filter_forpages
# 的脏页语义：TOC 引导行在文字层常渲染为连续中点，OCR 路径常见省略号/ASCII
# 点串；上游原版只认 U+00B7×2，这里补齐 OCR 变体——省略号与 4+ 连续 ASCII 点，
# 避开正文句末省略号 "..."）。一页内命中 >3 个框即判脏页整页剔除。
DIRTY_TEXT_PATTERN = re.compile(
    r"\(cid\s*:\s*\d+\s*\)|[\uE000-\uF8FF]|锟斤苟|锟"
    r"|··|…|\.{4,}"
)

# CID/PUA 与目录点线的脏页语义不同：点线框是「目录页」的确定性证据；而
# (cid:N)/PUA 在数学论文正文是行内符号的正常形态（LaTeX 排版把 −、≤、矩阵
# 构造线输出为未映射 CID，doc567 实测三页正文各 0.8%-4.2% 字符是 cid/PUA，
# 每页 >3 框即被整页删除）。因此 cid/PUA 命中必须叠加密度条件：占该页
# 有效字符 >= 30% 才判脏页；真乱码页（doc566）文字层整页是 cid 串，占比
# 接近 100%，不受影响。
CID_PUA_PATTERN = re.compile(r"\(cid\s*:\s*\d+\s*\)|[\uE000-\uF8FF]|锟斤苟|锟")
CID_PUA_DENSITY_THRESHOLD = 0.3


class PageNoiseFilter:
    """Adapted from RAGFlow PDF page-filter behavior."""

    def filter_boxes(self, boxes: Sequence[Any], total_pages: int | None = None) -> tuple[list[Any], dict[str, Any]]:
        if not boxes:
            return [], {"toc_detected": False, "dirty_pages": [], "removed_pages": [], "removed_boxes": 0}

        working = [box.__class__(**asdict(box)) for box in boxes]
        original_count = len(working)

        filtered, toc_meta = self._filter_toc_like_section(working)
        if toc_meta["toc_detected"]:
            return filtered, {
                **toc_meta,
                "dirty_pages": [],
                "removed_boxes": original_count - len(filtered),
            }

        filtered, dirty_meta = self._filter_dirty_pages(filtered, total_pages=total_pages)
        meta = {
            "toc_detected": False,
            **dirty_meta,
            "removed_boxes": original_count - len(filtered),
        }
        return filtered, meta

    def _filter_toc_like_section(self, boxes: list[Any]) -> tuple[list[Any], dict[str, Any]]:
        findit = False
        removed_pages: set[int] = set()
        i = 0
        while i < len(boxes):
            normalized = re.sub(r"( |\u3000)+", "", boxes[i].text.lower())
            if not TOC_HEADING_PATTERN.match(normalized):
                i += 1
                continue

            findit = True
            removed_pages.add(int(boxes[i].page))
            eng = re.match(r"[0-9a-zA-Z :'.-]{5,}", boxes[i].text.strip())
            boxes.pop(i)
            if i >= len(boxes):
                break

            prefix = boxes[i].text.strip()[:3] if not eng else " ".join(boxes[i].text.strip().split()[:2])
            while i < len(boxes) and not prefix:
                removed_pages.add(int(boxes[i].page))
                boxes.pop(i)
                if i >= len(boxes):
                    break
                prefix = boxes[i].text.strip()[:3] if not eng else " ".join(boxes[i].text.strip().split()[:2])

            if i >= len(boxes) or not prefix:
                break

            removed_pages.add(int(boxes[i].page))
            boxes.pop(i)
            if i >= len(boxes):
                break

            for j in range(i, min(i + 128, len(boxes))):
                if not re.match(re.escape(prefix), boxes[j].text):
                    continue
                for _ in range(i, j):
                    removed_pages.add(int(boxes[i].page))
                    boxes.pop(i)
                break

        return boxes, {
            "toc_detected": findit,
            "removed_pages": sorted(removed_pages),
        }

    def _filter_dirty_pages(self, boxes: list[Any], total_pages: int | None = None) -> tuple[list[Any], dict[str, Any]]:
        if not boxes:
            return boxes, {"dirty_pages": [], "removed_pages": []}

        max_page = max([int(box.page) for box in boxes], default=0)
        page_count = max(total_pages or 0, max_page)
        # 每页两条计数：目录点线命中框数（确定性证据，保持上游 >3 判据）；
        # cid/PUA 命中框数 + 命中字符数（需叠加密度，见 CID_PUA_PATTERN 注释）。
        dot_counts = [0] * page_count
        cid_counts = [0] * page_count
        cid_char_totals = [0] * page_count
        page_char_totals = [0] * page_count
        for box in boxes:
            page_index = int(box.page) - 1
            text = box.text or ""
            page_char_totals[page_index] += len(text)
            if CID_PUA_PATTERN.search(text):
                cid_counts[page_index] += 1
                cid_char_totals[page_index] += sum(
                    len(match.group(0)) for match in CID_PUA_PATTERN.finditer(text)
                )
            if DIRTY_TEXT_PATTERN.search(text) and not CID_PUA_PATTERN.search(text):
                dot_counts[page_index] += 1

        dirty_pages = [
            index + 1
            for index in range(page_count)
            if dot_counts[index] > 3
            or (
                cid_counts[index] > 3
                and page_char_totals[index] > 0
                and cid_char_totals[index] / page_char_totals[index] >= CID_PUA_DENSITY_THRESHOLD
            )
        ]
        if not dirty_pages:
            return boxes, {"dirty_pages": [], "removed_pages": []}

        dirty_page_set = set(dirty_pages)
        filtered = [box for box in boxes if int(box.page) not in dirty_page_set]
        return filtered, {
            "dirty_pages": dirty_pages,
            "removed_pages": dirty_pages,
        }
