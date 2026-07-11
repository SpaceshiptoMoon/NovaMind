from __future__ import annotations

import re
from dataclasses import asdict
from statistics import median
from typing import Any, Sequence

from src.shared.integrations.deepdoc.compat import rag_tokenizer
from src.shared.integrations.deepdoc.text_concat_model import (
    _import_xgboost,
    get_text_concat_model_status,
    load_text_concat_model,
)


class UpDownConcatMerger:
    """Adapted from RAGFlow deepdoc/parser/pdf_parser.py paragraph concat logic."""

    def __init__(self):
        self._model = None

    def model_status(self) -> dict[str, Any]:
        return get_text_concat_model_status()

    def model_available(self) -> bool:
        return bool(self.model_status()["available"])

    def load_model(self):
        if self._model is None:
            self._model = load_text_concat_model()
        return self._model

    def merge(self, boxes: Sequence[Any]) -> tuple[list[Any], str]:
        if not boxes:
            return [], "empty"
        if not self.model_available():
            return self._heuristic_merge(boxes), "heuristic"
        try:
            model = self.load_model()
        except Exception:
            return self._heuristic_merge(boxes), "heuristic"
        return self._xgb_merge(boxes, model), "xgboost"

    @staticmethod
    def _char_width(box: dict[str, Any]) -> float:
        return max((box["x1"] - box["x0"]) / max(len(box["text"]), 1), 1.0)

    @staticmethod
    def _height(box: dict[str, Any]) -> float:
        return max(box["bottom"] - box["top"], 1.0)

    @staticmethod
    def _x_dis(a: dict[str, Any], b: dict[str, Any]) -> float:
        return min(
            abs(a["x1"] - b["x0"]),
            abs(a["x0"] - b["x1"]),
            abs(a["x0"] + a["x1"] - b["x0"] - b["x1"]) / 2,
        )

    @staticmethod
    def _y_dis(a: dict[str, Any], b: dict[str, Any]) -> float:
        return (b["top"] + b["bottom"] - a["top"] - a["bottom"]) / 2

    @staticmethod
    def _match_proj(text: str) -> bool:
        proj_patt = [
            r"绗琜闆朵竴浜屼笁鍥涗簲鍏竷鍏節鍗佺櫨]+绔?",
            r"绗琜闆朵竴浜屼笁鍥涗簲鍏竷鍏節鍗佺櫨]+[鏉¤妭]",
            r"[闆朵竴浜屼笁鍥涗簲鍏竷鍏節鍗佺櫨]+[銆佹槸 銆€]",
            r"[\(锛圿[闆朵竴浜屼笁鍥涗簲鍏竷鍏節鍗佺櫨]+[锛塡)]",
            r"[\(锛圿[0-9]+[锛塡)]",
            r"[0-9]+(銆亅\.[銆€ ]|锛墊\.[^0-9./a-zA-Z_%><-]{4,})",
            r"[0-9]+\.[0-9.]+(銆亅\.[ 銆€])",
            r"[鈿€⑩灑飦垛憼鈶?]",
        ]
        return any(re.match(pattern, text or "") for pattern in proj_patt)

    def _updown_concat_features(self, up: dict[str, Any], down: dict[str, Any]) -> list[Any]:
        w = max(self._char_width(up), self._char_width(down))
        h = max(self._height(up), self._height(down))
        y_dis = self._y_dis(up, down)
        length = 6
        up_text = up.get("text", "") or ""
        down_text = down.get("text", "") or ""
        tks_down = rag_tokenizer.tokenize(down_text[:length]).split()
        tks_up = rag_tokenizer.tokenize(up_text[-length:]).split()
        up_tail = up_text[-length:].strip()
        down_head = down_text[:length].strip()
        joiner = " " if up_tail and down_head and re.match(r"[a-zA-Z0-9]+", up_tail[-1] + down_head[0]) else ""
        tks_all = rag_tokenizer.tokenize(up_tail + joiner + down_head).split()
        up_layout = up.get("layout_type", "") or ""
        down_layout = down.get("layout_type", "") or ""
        return [
            up.get("R", -1) == down.get("R", -1),
            y_dis / h,
            down["page_number"] - up["page_number"],
            up_layout == down_layout,
            up_layout == "text",
            down_layout == "text",
            up_layout == "table",
            down_layout == "table",
            bool(re.search(r"([銆傦紵锛侊紱!?;+)锛塢|[a-z]\.)$", up_text)),
            bool(re.search(r"[锛岋細鈥樷€溿€?-9锛?\-]$", up_text)),
            bool(re.search(r"(^.?[/,?;:\]锛屻€傦紱锛氣€欌€濓紵锛併€嬨€戯級-])", down_text)),
            bool(re.match(r"[\(锛圿[^\(\)锛堬級]+[锛塡)]$", up_text)),
            bool(re.search(r"[锛?][^銆?]+$", up_text)),
            bool(re.search(r"[锛?][^銆?]+$", up_text)),
            bool(re.search(r"[\(锛圿[^\)锛塢+$", up_text) and re.search(r"[\)锛塢", down_text)),
            self._match_proj(down_text),
            bool(re.match(r"[A-Z]", down_text)),
            bool(up_text and re.match(r"[A-Z]", up_text[-1])),
            bool(up_text and re.match(r"[a-z0-9]", up_text[-1])),
            bool(re.match(r"[0-9.%,-]+$", down_text)),
            up_text.strip()[-2:] == down_text.strip()[-2:] if len(up_text.strip()) > 1 and len(down_text.strip()) > 1 else False,
            up["x0"] > down["x1"],
            abs(self._height(up) - self._height(down)) / min(self._height(up), self._height(down)),
            self._x_dis(up, down) / max(w, 0.000001),
            (len(up_text) - len(down_text)) / max(len(up_text), len(down_text), 1),
            len(tks_all) - len(tks_up) - len(tks_down),
            len(tks_down) - len(tks_up),
            tks_down[-1] == tks_up[-1] if tks_down and tks_up else False,
            max(int(down.get("in_row", 0)), int(up.get("in_row", 0))),
            abs(int(down.get("in_row", 0)) - int(up.get("in_row", 0))),
            len(tks_down) == 1 and rag_tokenizer.tag(tks_down[0]).find("n") >= 0,
            len(tks_up) == 1 and rag_tokenizer.tag(tks_up[0]).find("n") >= 0,
        ]

    def _xgb_merge(self, boxes: Sequence[Any], model) -> list[Any]:
        xgb = _import_xgboost()
        states = [self._state_from_box(box) for box in boxes]
        mean_height = self._mean_height_by_page(states)
        mean_width = self._mean_width_by_page(states)
        ordered = sorted(states, key=lambda item: (item["page_number"], item["top"], item["x0"]))
        self._annotate_in_row_counts(ordered, mean_height)
        merged_states = self._merge_states_with_model(ordered, mean_height, mean_width, model)
        return [self._box_from_state(state, boxes[0].__class__) for state in merged_states]

    def _annotate_in_row_counts(self, states: list[dict[str, Any]], mean_height: dict[int, float]) -> None:
        for index, state in enumerate(states):
            mh = mean_height.get(state["page_number"], 10.0)
            state["in_row"] = 0
            cursor = max(0, index - 12)
            while cursor < min(index + 12, len(states)):
                if cursor == index:
                    cursor += 1
                    continue
                ydis = self._y_dis(state, states[cursor]) / max(mh, 1.0)
                if abs(ydis) < 1:
                    state["in_row"] += 1
                elif ydis > 0:
                    break
                cursor += 1

    def _merge_states_with_model(
        self,
        states: list[dict[str, Any]],
        mean_height: dict[int, float],
        mean_width: dict[int, float],
        model,
    ) -> list[dict[str, Any]]:
        remaining = [dict(state) for state in states]
        blocks: list[list[dict[str, Any]]] = []

        while remaining:
            chunks: list[dict[str, Any]] = []

            def dfs(up: dict[str, Any], dp: int):
                chunks.append(up)
                cursor = dp
                while cursor < min(dp + 12, len(remaining)):
                    down = remaining[cursor]
                    ydis = self._y_dis(up, down)
                    same_page = up["page_number"] == down["page_number"]
                    mh = mean_height.get(up["page_number"], 10.0)
                    mw = mean_width.get(up["page_number"], 10.0)
                    if same_page and ydis > mh * 4:
                        break
                    if not same_page and ydis > mh * 16:
                        break
                    if re.match(r"[0-9]{2,3}/[0-9]{3}$", up["text"]) or re.match(r"[0-9]{2,3}/[0-9]{3}$", down["text"]):
                        cursor += 1
                        continue
                    if not up["text"].strip() or not down["text"].strip():
                        cursor += 1
                        continue
                    if up["x1"] < down["x0"] - 10 * mw or up["x0"] > down["x1"] + 10 * mw:
                        cursor += 1
                        continue

                    features = self._updown_concat_features(up, down)
                    score = float(model.predict(xgb.DMatrix([features]))[0])
                    if score <= 0.5:
                        cursor += 1
                        continue
                    dfs(down, cursor + 1)
                    remaining.pop(cursor)
                    return

            dfs(remaining[0], 1)
            remaining.pop(0)
            if chunks:
                blocks.append(chunks)

        merged = [self._merge_block_states(block) for block in blocks]
        return sorted(merged, key=lambda item: (item["page_number"], item["top"], item["x0"]))

    def _heuristic_merge(self, boxes: Sequence[Any]) -> list[Any]:
        if not boxes:
            return []
        mean_height = median(max(1.0, float(box.bottom - box.top)) for box in boxes)
        ordered = sorted(boxes, key=lambda item: (item.page, item.x0, item.top))
        for index in range(len(ordered) - 1):
            for cursor in range(index, -1, -1):
                if (
                    abs(ordered[cursor + 1].x0 - ordered[cursor].x0) < max(8.0, mean_height * 0.8)
                    and ordered[cursor + 1].top < ordered[cursor].top
                    and ordered[cursor + 1].page == ordered[cursor].page
                ):
                    ordered[cursor], ordered[cursor + 1] = ordered[cursor + 1], ordered[cursor]
        merged = []
        current = None
        for box in ordered:
            if current is None:
                current = box.__class__(**asdict(box))
                continue
            if not self._should_merge_heuristic(current, box, mean_height):
                merged.append(current)
                current = box.__class__(**asdict(box))
                continue
            merged_text = (current.text.rstrip() + " " + box.text.lstrip()).strip()
            merged_positions = list(current.positions or [])
            if box.positions:
                merged_positions.extend(box.positions)
            current = box.__class__(
                page=current.page,
                x0=min(current.x0, box.x0),
                x1=max(current.x1, box.x1),
                top=current.top,
                bottom=box.bottom,
                text=merged_text,
                col_id=current.col_id,
                position_tag=current.position_tag,
                positions=merged_positions,
                layout_type=current.layout_type or box.layout_type,
            )
        if current is not None:
            merged.append(current)
        return merged

    def _should_merge_heuristic(self, upper: Any, lower: Any, mean_height: float) -> bool:
        if upper.page != lower.page or upper.col_id != lower.col_id:
            return False
        if (upper.layout_type or "") != (lower.layout_type or ""):
            return False
        if not upper.text.strip() or not lower.text.strip():
            return False
        vertical_gap = lower.top - upper.bottom
        if vertical_gap > mean_height * 1.5:
            return False
        overlap = max(0.0, min(upper.x1, lower.x1) - max(upper.x0, lower.x0))
        min_width = max(1.0, min(upper.x1 - upper.x0, lower.x1 - lower.x0))
        if overlap / min_width < 0.3:
            return False
        if self._match_proj(upper.text) or self._match_proj(lower.text):
            return False
        concatting_features = [
            upper.text.strip()[-1] in ",;:'\"锛屻€佲€滐紱(",
            len(upper.text.strip()) > 1 and upper.text.strip()[-2] in ",;:'\"锛屸€欌€濄€侊紱(",
            bool(lower.text.strip()) and lower.text.strip()[0] in "銆傦紱锛氾紵锛屻€嬨€戯級),锛屻€?",
        ]
        break_features = [
            upper.text.strip()[-1] in "銆傦紵锛?",
            vertical_gap > mean_height * 1.2,
        ]
        detach_features = [upper.x1 < lower.x0, upper.x0 > lower.x1]
        return not ((any(break_features) and not any(concatting_features)) or any(detach_features))

    @staticmethod
    def _state_from_box(box: Any) -> dict[str, Any]:
        state = asdict(box)
        state["page_number"] = state.pop("page")
        return state

    @staticmethod
    def _box_from_state(state: dict[str, Any], box_cls) -> Any:
        positions = state.get("positions") or []
        return box_cls(
            page=int(state["page_number"]),
            x0=float(state["x0"]),
            x1=float(state["x1"]),
            top=float(state["top"]),
            bottom=float(state["bottom"]),
            text=str(state.get("text", "")),
            col_id=int(state.get("col_id", 0)),
            position_tag=str(state.get("position_tag", "")),
            positions=[list(pos) for pos in positions] if positions else None,
            layout_type=str(state.get("layout_type", "")),
        )

    @staticmethod
    def _mean_height_by_page(states: Sequence[dict[str, Any]]) -> dict[int, float]:
        result: dict[int, list[float]] = {}
        for state in states:
            result.setdefault(int(state["page_number"]), []).append(max(float(state["bottom"] - state["top"]), 1.0))
        return {page: median(values) for page, values in result.items()}

    @staticmethod
    def _mean_width_by_page(states: Sequence[dict[str, Any]]) -> dict[int, float]:
        result: dict[int, list[float]] = {}
        for state in states:
            width = max(float(state["x1"] - state["x0"]) / max(len(state.get("text", "")), 1), 1.0)
            result.setdefault(int(state["page_number"]), []).append(width)
        return {page: median(values) for page, values in result.items()}

    @staticmethod
    def _merge_block_states(block: Sequence[dict[str, Any]]) -> dict[str, Any]:
        merged = dict(block[0])
        merged_positions = [list(pos) for pos in (merged.get("positions") or [])]
        for state in block[1:]:
            current_text = (merged.get("text", "") or "").strip()
            next_text = (state.get("text", "") or "").strip()
            if not next_text:
                continue
            if current_text and current_text[-1].isalnum() and next_text[0].isalnum():
                merged["text"] = current_text + " " + next_text
            else:
                merged["text"] = current_text + next_text
            merged["x0"] = min(float(merged["x0"]), float(state["x0"]))
            merged["x1"] = max(float(merged["x1"]), float(state["x1"]))
            merged["bottom"] = float(state["bottom"])
            merged["page_number"] = min(int(merged["page_number"]), int(state["page_number"]))
            if not merged.get("layout_type") and state.get("layout_type"):
                merged["layout_type"] = state["layout_type"]
            if state.get("positions"):
                merged_positions.extend([list(pos) for pos in state["positions"]])
        merged["positions"] = merged_positions
        return merged
