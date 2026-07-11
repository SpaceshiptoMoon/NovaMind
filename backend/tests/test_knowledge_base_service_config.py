import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.features.knowledge_space.services.knowledge_base_service import KnowledgeBaseService


class FakeKnowledgeBase:
    def __init__(self, kb_id: int, config: dict):
        self.id = kb_id
        self.config = config

    def get_config(self) -> dict:
        return self.config


def _run(coro):
    return asyncio.run(coro)


def test_update_config_merges_new_nested_parsing_structure(monkeypatch):
    kb = FakeKnowledgeBase(
        1,
        {
            "space_type": ["text"],
            "splitting": {
                "strategy": "recursive",
                "chunk_size": 1000,
                "chunk_overlap": 100,
            },
            "parsing": {
                "text": {
                    "pdf": {
                        "strategy": "default",
                        "ocr_enabled": False,
                    },
                    "docx": {"strategy": "default"},
                    "excel": {"strategy": "default"},
                    "ppt": {"strategy": "default"},
                    "epub": {"strategy": "default"},
                    "markdown": {"strategy": "default"},
                    "html": {"strategy": "default"},
                    "txt": {"strategy": "default"},
                    "json": {"strategy": "default"},
                }
            },
            "question_generation": {
                "enabled": False,
            },
        },
    )

    service = object.__new__(KnowledgeBaseService)
    service.kb_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=kb))
    service.session = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(
        "src.features.knowledge_space.services.knowledge_base_service.flag_modified",
        lambda obj, field: None,
    )

    updates = {
        "space_type": ["text", "image", "video", "audio"],
        "splitting": {
            "chunk_size": 1500,
            "audio": {
                "strategy": "fixed",
                "chunk_size": 900,
            },
        },
        "parsing": {
            "text": {
                "pdf": {
                    "strategy": "deepdoc",
                    "parser": "layout",
                    "ocr_enabled": True,
                },
                "excel": {"strategy": "deepdoc"},
            },
            "image": {
                "strategy": "vlm",
                "vlm_model": "glm-4v",
            },
            "video": {
                "frame_interval": 8,
                "max_frames": 40,
                "vlm_description_enabled": True,
                "vlm_model": "video-vlm",
            },
            "audio": {
                "asr_model": "whisper-1",
                "language": "zh",
            },
        },
        "question_generation": {
            "enabled": True,
            "max_questions_per_chunk": 4,
        },
    }

    result = _run(service.update_config(1, updates))

    assert result["message"]
    assert kb.config["space_type"] == ["text", "image", "video", "audio"]
    assert kb.config["splitting"]["strategy"] == "recursive"
    assert kb.config["splitting"]["chunk_size"] == 1500
    assert kb.config["splitting"]["audio"]["strategy"] == "fixed"
    assert kb.config["parsing"]["text"]["pdf"]["strategy"] == "deepdoc"
    assert kb.config["parsing"]["text"]["pdf"]["parser"] == "layout"
    assert kb.config["parsing"]["text"]["pdf"]["ocr_enabled"] is True
    assert kb.config["parsing"]["text"]["docx"]["strategy"] == "default"
    assert kb.config["parsing"]["text"]["excel"]["strategy"] == "deepdoc"
    assert kb.config["parsing"]["image"]["vlm_model"] == "glm-4v"
    assert kb.config["parsing"]["video"]["frame_interval"] == 8
    assert kb.config["parsing"]["audio"]["language"] == "zh"
    assert kb.config["question_generation"]["enabled"] is True
    assert kb.config["question_generation"]["max_questions_per_chunk"] == 4
    service.session.commit.assert_awaited_once()


def test_update_config_removes_none_fields_via_deep_merge(monkeypatch):
    kb = FakeKnowledgeBase(
        2,
        {
            "space_type": ["text", "image"],
            "parsing": {
                "image": {
                    "strategy": "vlm",
                    "vlm_model": "glm-4v",
                }
            },
        },
    )

    service = object.__new__(KnowledgeBaseService)
    service.kb_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=kb))
    service.session = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(
        "src.features.knowledge_space.services.knowledge_base_service.flag_modified",
        lambda obj, field: None,
    )

    _run(
        service.update_config(
            2,
            {
                "parsing": {
                    "image": None,
                }
            },
        )
    )

    assert "image" not in kb.config["parsing"]
