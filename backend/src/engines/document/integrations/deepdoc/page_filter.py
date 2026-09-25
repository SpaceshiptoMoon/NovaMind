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
# 乱码文字层残留（cid/PUA/锟）+ 目录点线的脏页判据，三档置信度：
# 1) U+00B7×2 连续中点——上游 _filter_forpages 原版确定性证据（目录引导线专属，
#    正文几乎不出现），>3 框即删；
# 2) 省略号/ASCII 点串（…、\.{4,}、··）——OCR 路径 TOC 引导行变体，但 U+2026
#    同时是中文正文高频标点，降级为密度条件（ELLIPSIS_DENSITY_THRESHOLD）；
# 3) cid/PUA/锟——数学论文正文正常形态，密度条件（CID_PUA_DENSITY_THRESHOLD）。
DIRTY_TEXT_PATTERN = re.compile(
    r"\(cid\s*:\s*\d+\s*\)|[\uE000-\uF8FF]|锟斤苟|锟"
    r"|··|…|\.{4,}"
)
# 目录引导线专属字符：上游 _filter_forpages 原版的确定性证据（U+00B7×2 连续
# 中点，正文几乎不出现），保持 >3 框即删的上游判据。
TOC_DOT_LEADER_PATTERN = re.compile(r"·{2,}")

# cid/PUA 与省略号类弱证据的脏页语义：二者都不能只凭「>3 框」整页删——
# (cid:N)/PUA 在数学论文正文是行内符号的正常形态（LaTeX 排版把 −、≤、矩阵
# 构造线输出为未映射 CID，doc567 实测三页正文各 0.8%-4.2% 字符是 cid/PUA）；
# U+2026 同时是中文正文高频标点（规范省略号「……」即两个 U+2026），一页 4 行
# 含省略号的小说/对话体文档会被误删。因此命中必须叠加密度条件：占该页有效
# 字符 >= 30% 才判脏页；真乱码页（doc566）文字层整页是 cid 串，占比接近
# 100%，不受影响。省略号/ASCII 点串（OCR 路径 TOC 引导行变体）与 cid/PUA
# 共用同一密度阈值。
CID_PUA_PATTERN = re.compile(r"\(cid\s*:\s*\d+\s*\)|[\uE000-\uF8FF]|锟斤苟|锟")
CID_PUA_DENSITY_THRESHOLD = 0.3
ELLIPSIS_DENSITY_THRESHOLD = 0.3


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
        # 弱证据（cid/PUA + 省略号/点串）命中框数 + 命中字符数（需叠加密度，
        # 见 CID_PUA_PATTERN 注释）。
        dot_counts = [0] * page_count
        weak_counts = [0] * page_count
        weak_char_totals = [0] * page_count
        page_char_totals = [0] * page_count
        for box in boxes:
            page_index = int(box.page) - 1
            text = box.text or ""
            page_char_totals[page_index] += len(text)
            if TOC_DOT_LEADER_PATTERN.search(text):
                # 上游确定性证据：连续中点引导线，>3 框即删，不叠加密度。
                dot_counts[page_index] += 1
            if CID_PUA_PATTERN.search(text):
                weak_counts[page_index] += 1
                weak_char_totals[page_index] += sum(
                    len(match.group(0)) for match in CID_PUA_PATTERN.finditer(text)
                )
            elif DIRTY_TEXT_PATTERN.search(text):
                # 省略号/ASCII 点串框（不含 cid/PUA 时）：命中字符按框内全部
                # 点串匹配段累计，口径与 cid/PUA 一致。
                weak_counts[page_index] += 1
                weak_char_totals[page_index] += sum(
                    len(match.group(0))
                    for match in DIRTY_TEXT_PATTERN.finditer(text)
                )

        dirty_pages = [
            index + 1
            for index in range(page_count)
            if dot_counts[index] > 3
            or (
                weak_counts[index] > 3
                and page_char_totals[index] > 0
                and weak_char_totals[index] / page_char_totals[index] >= ELLIPSIS_DENSITY_THRESHOLD
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
