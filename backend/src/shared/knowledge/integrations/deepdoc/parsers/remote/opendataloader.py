from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

import requests

from novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.opendataloader_parser import OpenDataLoaderParser


class RAGFlowOpenDataLoaderParser(OpenDataLoaderParser):
    """Adapted parser for RAGFlow's OpenDataLoader-backed PDF path."""

    TEXT_TYPES = {"heading", "title", "paragraph", "text", "list", "list_item", "caption"}
    TABLE_TYPES = {"table"}
    IMAGE_TYPES = {"image", "picture", "figure"}
    FORMULA_TYPES = {"formula", "equation"}

    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
    ):
        super().__init__()
        self.api_url = (api_url or os.getenv("OPENDATALOADER_APISERVER", "")).rstrip("/")
        self.api_key = (api_key if api_key is not None else os.getenv("OPENDATALOADER_API_KEY", "")).strip()
        env_timeout = os.getenv("OPENDATALOADER_TIMEOUT", "600")
        self.timeout = timeout if timeout is not None else int(env_timeout or "600")

    def is_configured(self) -> bool:
        return bool(self.api_url)

    def check_installation(self) -> bool:
        if not self.api_url:
            return False
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            response = requests.get(f"{self.api_url}/health", timeout=5, headers=headers)
            return response.status_code == 200
        except Exception:
            return False

    def parse(self, file_path: str | Path) -> tuple[str, list[str], dict[str, Any]]:
        path = Path(file_path)
        return self.parse_bytes(path.read_bytes(), file_name=path.name)

    def parse_bytes(self, file_bytes: bytes, *, file_name: str = "input.pdf") -> tuple[str, list[str], dict[str, Any]]:
        if not self.api_url:
            raise RuntimeError(
                "[OpenDataLoader] OPENDATALOADER_APISERVER is not configured. "
                "Please start the service and set the env var."
            )

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = requests.post(
            url=f"{self.api_url}/file_parse",
            files={"file": (file_name, file_bytes, "application/pdf")},
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self._transfer_payload(response.json())

    def _transfer_payload(self, payload: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        json_doc = payload.get("json_doc")
        md_text = payload.get("md_text")

        text_chunks: list[str] = []
        tables: list[dict[str, Any]] = []
        figures: list[dict[str, Any]] = []
        equations: list[str] = []

        if json_doc is not None:
            for element in self._iter_elements(json_doc):
                element_type = self._classify(element.get("type", ""))
                if element_type == "table":
                    html = self._element_html(element) or self._element_text(element)
                    if html:
                        tables.append({"html": html})
                        text_chunks.append(html)
                    continue
                if element_type == "image":
                    caption = self._element_text(element)
                    figures.append({"caption": caption})
                    if caption:
                        text_chunks.append(caption)
                    continue
                if element_type == "equation":
                    equation = self._element_text(element)
                    if equation:
                        equations.append(equation)
                        text_chunks.append(equation)
                    continue
                text = self._element_text(element).strip()
                if text:
                    text_chunks.append(text)

        if not text_chunks and md_text:
            stripped = str(md_text).strip()
            if stripped:
                text_chunks = [stripped]

        full_text = "\n\n".join(chunk for chunk in text_chunks if chunk.strip()).strip()
        metadata: dict[str, Any] = {
            "parser": "deepdoc",
            "parser_class": "RAGFlowOpenDataLoaderParser",
            "file_type": "pdf",
            "source": "ragflow-adapted",
            "service": {
                "api_url": self.api_url,
                "configured": bool(self.api_url),
            },
            "tables": tables,
            "figures": figures,
            "equations": equations,
        }
        return full_text, text_chunks or ([full_text] if full_text else []), metadata

    @classmethod
    def _classify(cls, element_type: str) -> str:
        lowered = (element_type or "").lower()
        if lowered in cls.TABLE_TYPES:
            return "table"
        if lowered in cls.IMAGE_TYPES:
            return "image"
        if lowered in cls.FORMULA_TYPES:
            return "equation"
        if lowered in cls.TEXT_TYPES:
            return "text"
        return lowered or "text"

    @classmethod
    def _iter_elements(cls, node: Any) -> Iterable[dict[str, Any]]:
        if isinstance(node, dict):
            if "type" in node and ("content" in node or "text" in node or "cells" in node or "html" in node):
                yield node
            for value in node.values():
                yield from cls._iter_elements(value)
            return
        if isinstance(node, list):
            for item in node:
                yield from cls._iter_elements(item)

    @staticmethod
    def _element_text(element: dict[str, Any]) -> str:
        content = element.get("content")
        if isinstance(content, str):
            return content
        text = element.get("text")
        if isinstance(text, str):
            return text
        cells = element.get("cells")
        if isinstance(cells, list):
            rows: list[str] = []
            for cell in cells:
                if isinstance(cell, dict):
                    rows.append(str(cell.get("content") or cell.get("text") or "").strip())
            return " | ".join(item for item in rows if item)
        return ""

    @staticmethod
    def _element_html(element: dict[str, Any]) -> str:
        for key in ("html", "html_content"):
            value = element.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""
