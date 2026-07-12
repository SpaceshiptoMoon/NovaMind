from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import requests

from novamind.shared.knowledge.integrations.deepdoc.parsers.upstream.docling_parser import DoclingParser


class RAGFlowDoclingParser(DoclingParser):
    """Adapted parser for RAGFlow's Docling-backed remote PDF path."""

    def __init__(
        self,
        *,
        server_url: str | None = None,
        timeout: int | None = None,
    ):
        effective_server_url = (server_url or os.getenv("DOCLING_SERVER_URL", "")).rstrip("/")
        env_timeout = os.getenv("DOCLING_REQUEST_TIMEOUT", "600")
        effective_timeout = timeout if timeout is not None else int(env_timeout or "600")
        super().__init__(
            docling_server_url=effective_server_url,
            request_timeout=effective_timeout,
        )
        self.server_url = effective_server_url
        self.timeout = effective_timeout

    def is_configured(self) -> bool:
        return bool(self.server_url)

    def check_installation(self) -> bool:
        if not self.server_url:
            return False
        for suffix in ("/openapi.json", "/docs", "/v1/convert/source"):
            try:
                response = requests.get(f"{self.server_url}{suffix}", timeout=5)
                if response.status_code < 400:
                    return True
            except Exception:
                continue
        return False

    def parse(self, file_path: str | Path) -> tuple[str, list[str], dict[str, Any]]:
        path = Path(file_path)
        return self.parse_bytes(path.read_bytes(), file_name=path.name)

    def parse_bytes(self, file_bytes: bytes, *, file_name: str = "input.pdf") -> tuple[str, list[str], dict[str, Any]]:
        if not self.server_url:
            raise RuntimeError("[Docling] DOCLING_SERVER_URL is not configured.")

        payloads = self._build_payloads(file_bytes=file_bytes, file_name=file_name)
        errors: list[str] = []
        response_json = None
        chunked = False

        for endpoint, payload, is_chunked in (
            ("/v1/convert/source", payloads["v1_chunked"], True),
            ("/v1alpha/convert/source", payloads["v1alpha_chunked"], True),
            ("/v1/convert/source", payloads["v1_standard"], False),
            ("/v1alpha/convert/source", payloads["v1alpha_standard"], False),
        ):
            try:
                response = requests.post(f"{self.server_url}{endpoint}", json=payload, timeout=self.timeout)
                if response.status_code < 300:
                    response_json = response.json()
                    chunked = is_chunked
                    break
                errors.append(f"{endpoint}: HTTP {response.status_code}")
            except Exception as exc:
                errors.append(f"{endpoint}: {exc}")

        if response_json is None:
            raise RuntimeError("[Docling] remote convert failed: " + " | ".join(errors))

        return self._transfer_payload(response_json, chunked=chunked)

    def _build_payloads(self, *, file_bytes: bytes, file_name: str) -> dict[str, dict[str, Any]]:
        b64 = base64.b64encode(file_bytes).decode("ascii")
        chunking_options = {
            "from_formats": ["pdf"],
            "to_formats": ["json", "md", "text"],
            "do_chunking": True,
            "chunking_options": {
                "max_tokens": 512,
                "overlap": 50,
                "tokenizer": "sentencepiece",
            },
        }
        return {
            "v1_chunked": {
                "options": chunking_options,
                "sources": [{"kind": "file", "filename": file_name, "base64_string": b64}],
            },
            "v1alpha_chunked": {
                "options": chunking_options,
                "file_sources": [{"filename": file_name, "base64_string": b64}],
            },
            "v1_standard": {
                "options": {"from_formats": ["pdf"], "to_formats": ["json", "md", "text"]},
                "sources": [{"kind": "file", "filename": file_name, "base64_string": b64}],
            },
            "v1alpha_standard": {
                "options": {"from_formats": ["pdf"], "to_formats": ["json", "md", "text"]},
                "file_sources": [{"filename": file_name, "base64_string": b64}],
            },
        }

    def _transfer_payload(self, payload: Any, *, chunked: bool) -> tuple[str, list[str], dict[str, Any]]:
        sections: list[str] = []
        if chunked:
            results = payload if isinstance(payload, list) else payload.get("results", [])
            for item in results:
                if not isinstance(item, dict):
                    continue
                text = item.get("text", "")
                if not text and isinstance(item.get("chunk"), dict):
                    text = item["chunk"].get("text", "")
                if isinstance(text, str) and text.strip():
                    sections.append(text.strip())
        else:
            for document in self._extract_documents(payload):
                md_content = document.get("md_content")
                text_content = document.get("text_content")
                if isinstance(md_content, str) and md_content.strip():
                    sections.append(md_content.strip())
                elif isinstance(text_content, str) and text_content.strip():
                    sections.append(text_content.strip())

        full_text = "\n\n".join(sections).strip()
        metadata: dict[str, Any] = {
            "parser": "deepdoc",
            "parser_class": "RAGFlowDoclingParser",
            "file_type": "pdf",
            "source": "ragflow-adapted",
            "service": {
                "server_url": self.server_url,
                "configured": bool(self.server_url),
            },
            "docling_chunked": chunked,
        }
        return full_text, sections or ([full_text] if full_text else []), metadata

    @staticmethod
    def _extract_documents(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        if isinstance(payload.get("document"), dict):
            return [payload["document"]]
        if isinstance(payload.get("documents"), list):
            return [doc for doc in payload["documents"] if isinstance(doc, dict)]
        if isinstance(payload.get("results"), list):
            docs = []
            for item in payload["results"]:
                if isinstance(item, dict):
                    if isinstance(item.get("document"), dict):
                        docs.append(item["document"])
                    elif isinstance(item.get("result"), dict):
                        docs.append(item["result"])
                    else:
                        docs.append(item)
            return docs
        return []
