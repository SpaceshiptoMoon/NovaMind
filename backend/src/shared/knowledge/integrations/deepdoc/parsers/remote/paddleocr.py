from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.paddleocr_parser import PaddleOCRParser

SUPPORTED_PADDLEOCR_ALGORITHMS: tuple[str, ...] = (
    "PaddleOCR-VL",
    "PaddleOCR-VL-1.6",
    "PP-OCRv5",
    "PP-OCRv6",
    "PP-StructureV3",
    "PaddleOCR-VL-1.5",
)

_MARKDOWN_IMAGE_PATTERN = re.compile(
    r"""
        <div[^>]*>\s*
        <img[^>]*/>\s*
        </div>
        |
        <img[^>]*/>
        """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


class RAGFlowPaddleOCRParser(PaddleOCRParser):
    """Adapted parser for RAGFlow's PaddleOCR-backed remote PDF path."""

    _ZOOMIN = 2

    def __init__(
        self,
        *,
        base_url: str | None = None,
        access_token: str | None = None,
        algorithm: str | None = None,
        timeout: int | None = None,
    ):
        effective_base_url = (base_url or os.getenv("PADDLEOCR_BASE_URL", "")).rstrip("/")
        effective_access_token = (
            access_token if access_token is not None else os.getenv("PADDLEOCR_ACCESS_TOKEN", "")
        ).strip()
        effective_algorithm = (algorithm or os.getenv("PADDLEOCR_ALGORITHM", "PaddleOCR-VL")).strip()
        env_timeout = os.getenv("PADDLEOCR_REQUEST_TIMEOUT", "600")
        effective_timeout = timeout if timeout is not None else int(env_timeout or "600")
        super().__init__(
            base_url=effective_base_url or None,
            access_token=effective_access_token or None,
            algorithm=effective_algorithm,
            request_timeout=effective_timeout,
        )
        self.base_url = effective_base_url
        self.access_token = effective_access_token
        self.algorithm = effective_algorithm
        self.timeout = effective_timeout

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def check_installation(self) -> bool:
        if not self.base_url:
            return False
        try:
            response = requests.get(
                f"{self.base_url}/api/v2/health",
                headers=self._build_headers(),
                timeout=5,
            )
            return response.status_code < 400
        except Exception:
            return False

    def parse(self, file_path: str | Path) -> tuple[str, list[str], dict[str, Any]]:
        path = Path(file_path)
        return self.parse_bytes(path.read_bytes(), file_name=path.name)

    def parse_bytes(
        self,
        file_bytes: bytes,
        *,
        file_name: str = "input.pdf",
    ) -> tuple[str, list[str], dict[str, Any]]:
        if not self.base_url:
            raise RuntimeError("[PaddleOCR] PADDLEOCR_BASE_URL is not configured.")
        if self.algorithm not in SUPPORTED_PADDLEOCR_ALGORITHMS:
            raise RuntimeError(f"[PaddleOCR] Unsupported algorithm: {self.algorithm}")

        submit_response = requests.post(
            f"{self.base_url}/api/v2/ocr/jobs",
            data={
                "model": self.algorithm,
                "optionalPayload": json.dumps(
                    {
                        "prettifyMarkdown": True,
                        "showFormulaNumber": True,
                        "visualize": False,
                    }
                ),
            },
            files={"file": (file_name, file_bytes, "application/pdf")},
            headers=self._build_headers(),
            timeout=self.timeout,
        )
        submit_response.raise_for_status()
        submit_payload = submit_response.json()
        job_id = (
            self._nested_get(submit_payload, "data", "jobId")
            or submit_payload.get("jobId")
            or submit_payload.get("id")
        )
        if not job_id:
            raise RuntimeError(f"[PaddleOCR] job ID not found in response: {submit_payload}")

        poll_payload = self._poll_job(job_id)
        result_url = (
            self._nested_get(poll_payload, "data", "resultJsonUrl")
            or self._nested_get(poll_payload, "data", "resultUrl", "jsonUrl")
            or poll_payload.get("resultJsonUrl")
        )
        if not result_url:
            raise RuntimeError(f"[PaddleOCR] result URL not found in response: {poll_payload}")

        result_response = requests.get(result_url, headers=self._build_headers(), timeout=self.timeout)
        result_response.raise_for_status()
        return self._transfer_payload(self._parse_result_payload(result_response))

    def _poll_job(self, job_id: str) -> dict[str, Any]:
        poll_url = f"{self.base_url}/api/v2/ocr/jobs/{job_id}"
        deadline = time.monotonic() + self.timeout
        interval = 1.0

        while True:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"[PaddleOCR] job {job_id} timed out after {self.timeout}s")

            response = requests.get(poll_url, headers=self._build_headers(), timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            state = self._nested_get(payload, "data", "state") or payload.get("state")

            if state == "done":
                return payload
            if state == "failed":
                error_message = (
                    self._nested_get(payload, "data", "errorMsg")
                    or payload.get("errorMsg")
                    or "Unknown error"
                )
                raise RuntimeError(f"[PaddleOCR] job failed: {error_message}")

            time.sleep(interval)
            interval = min(interval * 1.5, 5.0)

    def _transfer_payload(self, payload: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        sections: list[str] = []
        page_count = 0

        layout_results = payload.get("layoutParsingResults", [])
        for page_index, page_result in enumerate(layout_results, start=1):
            page_count = max(page_count, page_index)
            for block in self._iter_layout_blocks(page_result):
                content = self._clean_block_content(block.get("block_content", ""))
                if not content:
                    continue
                tag = self._bbox_tag(page_index, block.get("block_bbox"))
                sections.append(f"{tag}{content}" if tag else content)

        if not sections:
            ocr_results = payload.get("ocrResults", [])
            for page_index, ocr_result in enumerate(ocr_results, start=1):
                page_count = max(page_count, page_index)
                pruned = ocr_result.get("prunedResult", {}) if isinstance(ocr_result, dict) else {}
                texts = pruned.get("rec_texts", [])
                boxes = pruned.get("rec_boxes", [])
                for index, text in enumerate(texts):
                    stripped = str(text).strip()
                    if not stripped:
                        continue
                    bbox = boxes[index] if index < len(boxes) else None
                    tag = self._bbox_tag(page_index, bbox)
                    sections.append(f"{tag}{stripped}" if tag else stripped)

        full_text = "\n\n".join(section.strip() for section in sections if section.strip()).strip()
        metadata: dict[str, Any] = {
            "parser": "deepdoc",
            "parser_class": "RAGFlowPaddleOCRParser",
            "file_type": "pdf",
            "source": "ragflow-adapted",
            "service": {
                "base_url": self.base_url,
                "configured": bool(self.base_url),
            },
            "algorithm": self.algorithm,
            "page_count": page_count,
        }
        return full_text, sections or ([full_text] if full_text else []), metadata

    def _build_headers(self) -> dict[str, str]:
        headers = {"Client-Platform": "ragflow"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    @staticmethod
    def _nested_get(payload: dict[str, Any], *keys: str) -> Any:
        current: Any = payload
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @classmethod
    def _parse_result_payload(cls, response: requests.Response) -> dict[str, Any]:
        content_type = str(response.headers.get("content-type", "")).lower()
        if "jsonl" not in content_type and "ndjson" not in content_type and "application/json" in content_type:
            parsed = response.json()
            if isinstance(parsed, dict):
                return parsed
            raise RuntimeError(f"[PaddleOCR] unexpected JSON result payload: {type(parsed)!r}")

        text = response.text.strip()
        if not text:
            return {}
        if text.startswith("{"):
            first_line = text.splitlines()[0]
            parsed = json.loads(first_line)
            if len(text.splitlines()) == 1 and isinstance(parsed, dict) and (
                "layoutParsingResults" in parsed or "ocrResults" in parsed
            ):
                return parsed

        combined: dict[str, Any] = {"layoutParsingResults": [], "ocrResults": []}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            line_payload = json.loads(stripped)
            if not isinstance(line_payload, dict):
                continue
            result = line_payload.get("result", line_payload)
            if isinstance(result.get("layoutParsingResults"), list):
                combined["layoutParsingResults"].extend(result["layoutParsingResults"])
            if isinstance(result.get("ocrResults"), list):
                combined["ocrResults"].extend(result["ocrResults"])
        return combined

    @staticmethod
    def _iter_layout_blocks(page_result: Any) -> list[dict[str, Any]]:
        if not isinstance(page_result, dict):
            return []
        pruned = page_result.get("prunedResult", {})
        blocks = pruned.get("parsing_res_list", [])
        return [block for block in blocks if isinstance(block, dict)]

    @staticmethod
    def _clean_block_content(text: Any) -> str:
        if not isinstance(text, str):
            return ""
        return _MARKDOWN_IMAGE_PATTERN.sub("", text).strip()

    @classmethod
    def _bbox_tag(cls, page_index: int, bbox: Any) -> str:
        normalized = cls._normalize_bbox(bbox)
        if normalized is None:
            return ""
        left, top, right, bottom = normalized
        return (
            f"@@{page_index}\t"
            f"{int(left // cls._ZOOMIN)}\t{int(right // cls._ZOOMIN)}\t"
            f"{int(top // cls._ZOOMIN)}\t{int(bottom // cls._ZOOMIN)}##"
        )

    @staticmethod
    def _normalize_bbox(bbox: Any) -> tuple[float, float, float, float] | None:
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            return None
        left, top, right, bottom = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        if left > right:
            left, right = right, left
        if top > bottom:
            top, bottom = bottom, top
        return left, top, right, bottom
