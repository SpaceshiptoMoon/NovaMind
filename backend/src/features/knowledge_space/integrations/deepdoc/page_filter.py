from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, Sequence


TOC_HEADING_PATTERN = re.compile(
    r"(contents|鐩綍|鐩|table of contents|鑷磋阿|acknowledge(?:ment)?s?)$",
    re.IGNORECASE,
)
DIRTY_TEXT_PATTERN = re.compile(r"\(cid\s*:\s*\d+\s*\)|[\uE000-\uF8FF]|锟?")


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
        return {
            "boxes": filtered,
            "meta": {
                "toc_detected": False,
                **dirty_meta,
                "removed_boxes": original_count - len(filtered),
            },
        }["boxes"], {
            "toc_detected": False,
            **dirty_meta,
            "removed_boxes": original_count - len(filtered),
        }

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
        dirty_counts = [0] * page_count
        for box in boxes:
            if DIRTY_TEXT_PATTERN.search(box.text or ""):
                dirty_counts[int(box.page) - 1] += 1

        dirty_pages = [index + 1 for index, count in enumerate(dirty_counts) if count > 3]
        if not dirty_pages:
            return boxes, {"dirty_pages": [], "removed_pages": []}

        dirty_page_set = set(dirty_pages)
        filtered = [box for box in boxes if int(box.page) not in dirty_page_set]
        return filtered, {
            "dirty_pages": dirty_pages,
            "removed_pages": dirty_pages,
        }
