"""KB 配置更新语义：深合并嵌套结构、None 字段保留不误删。"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.services.knowledge_base_service import KnowledgeBaseService

pytestmark = pytest.mark.unit


class FakeKnowledgeBase:
    def __init__(self, kb_id: int, config: dict):
        self.id = kb_id
        self.space_id = 1
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
    # 权限校验 mock（update_config 现需 user_id + service 层鉴权）
    fake_member = SimpleNamespace(is_active=lambda: True)
    service.member_repo = SimpleNamespace(get_by_space_and_user=AsyncMock(return_value=fake_member))
    service.permission_service = SimpleNamespace(can_manage_knowledge_base=lambda m: True)
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.knowledge_base_service.flag_modified",
        lambda obj, field: None,
    )

    updates = {
        "space_type": ["text", "image", "video", "audio"],
        "splitting": {
            "chunk_size": 1500,
        },
        "parsing": {
            "text": {
                "pdf": {
                    "strategy": "deepdoc",
                    "parser": "full",
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

    result = _run(service.update_config(1, 99, updates))

    assert result["message"]
    assert kb.config["space_type"] == ["text", "image", "video", "audio"]
    assert kb.config["splitting"]["strategy"] == "recursive"
    assert kb.config["splitting"]["chunk_size"] == 1500
    assert kb.config["parsing"]["text"]["pdf"]["strategy"] == "deepdoc"
    assert kb.config["parsing"]["text"]["pdf"]["parser"] == "full"
    assert kb.config["parsing"]["text"]["docx"]["strategy"] == "default"
    assert kb.config["parsing"]["text"]["excel"]["strategy"] == "deepdoc"
    assert kb.config["parsing"]["image"]["vlm_model"] == "glm-4v"
    assert kb.config["parsing"]["video"]["frame_interval"] == 8
    assert kb.config["parsing"]["audio"]["language"] == "zh"
    assert kb.config["question_generation"]["enabled"] is True
    assert kb.config["question_generation"]["max_questions_per_chunk"] == 4
    service.session.commit.assert_awaited_once()


def test_update_config_preserves_none_fields_via_deep_merge(monkeypatch):
    """_deep_merge now preserves None values instead of deleting keys, consistent with SpaceService."""
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
    fake_member = SimpleNamespace(is_active=lambda: True)
    service.member_repo = SimpleNamespace(get_by_space_and_user=AsyncMock(return_value=fake_member))
    service.permission_service = SimpleNamespace(can_manage_knowledge_base=lambda m: True)
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.knowledge_base_service.flag_modified",
        lambda obj, field: None,
    )

    _run(
        service.update_config(
            2,
            99,
            {
                "parsing": {
                    "image": None,
                }
            },
        )
    )

    # None values are preserved (not deleted), consistent with SpaceService._deep_merge
    assert kb.config["parsing"]["image"] is None


def test_update_config_denies_without_manage_permission():
    """H6-2: update_config 必须在 service 层校验权限，无 can_manage_knowledge_base 权限应拒绝。"""
    kb = FakeKnowledgeBase(3, {"space_type": ["text"]})
    service = object.__new__(KnowledgeBaseService)
    service.kb_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=kb))
    inactive_member = SimpleNamespace(is_active=lambda: False)
    service.member_repo = SimpleNamespace(get_by_space_and_user=AsyncMock(return_value=inactive_member))
    service.permission_service = SimpleNamespace(can_manage_knowledge_base=lambda m: True)

    from novamind.features.knowledge_space.exceptions import KnowledgeBaseAccessDeniedError

    with pytest.raises(KnowledgeBaseAccessDeniedError):
        _run(service.update_config(3, 99, {"splitting": {"chunk_size": 500}}))


def test_update_config_accepts_delimiter_strategy_with_separators(monkeypatch):
    """PATCH splitting.strategy=delimiter + separators 走通校验白名单并深合并保存。"""
    kb = FakeKnowledgeBase(
        4,
        {"space_type": ["text"], "splitting": {"strategy": "recursive", "chunk_size": 1000}},
    )
    service = object.__new__(KnowledgeBaseService)
    service.kb_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=kb))
    service.session = SimpleNamespace(commit=AsyncMock())
    member = SimpleNamespace(is_active=lambda: True)
    service.member_repo = SimpleNamespace(get_by_space_and_user=AsyncMock(return_value=member))
    service.permission_service = SimpleNamespace(can_manage_knowledge_base=lambda m: True)
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.knowledge_base_service.flag_modified",
        lambda obj, field: None,
    )

    _run(
        service.update_config(
            4,
            99,
            {
                "splitting": {
                    "strategy": "delimiter",
                    "separators": ["\n\n", "---"],
                }
            },
        )
    )

    assert kb.config["splitting"]["strategy"] == "delimiter"
    assert kb.config["splitting"]["separators"] == ["\n\n", "---"]
    # 深合并：未提及的 chunk_size 保留
    assert kb.config["splitting"]["chunk_size"] == 1000


def test_update_config_rejects_unknown_delimiter_separator_shape():
    """separators 形状校验：空串项/超长项被 Pydantic 拒绝（服务层转 InvalidParameterError）。"""
    from novamind.features.knowledge_space.exceptions import InvalidParameterError

    kb = FakeKnowledgeBase(5, {"space_type": ["text"], "splitting": {"strategy": "recursive"}})
    service = object.__new__(KnowledgeBaseService)
    service.kb_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=kb))
    member = SimpleNamespace(is_active=lambda: True)
    service.member_repo = SimpleNamespace(get_by_space_and_user=AsyncMock(return_value=member))
    service.permission_service = SimpleNamespace(can_manage_knowledge_base=lambda m: True)

    with pytest.raises(InvalidParameterError):
        _run(
            service.update_config(
                5,
                99,
                {"splitting": {"strategy": "delimiter", "separators": [""]}},
            )
        )


def test_config_update_schema_accepts_wiki_field():
    """KnowledgeBaseConfigUpdate 必须声明 wiki 字段（回归锁定）。

    漏声明时 Pydantic 静默丢弃 wiki，PATCH 返回成功但配置未更新——真实案例：
    wiki.llm.model 改 glm-5.3 假成功，wiki 生成继续用 qwen3.8 thinking 空响应。
    Update schema 的字段面必须与 KnowledgeBaseConfig 保持对齐。
    """
    from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
        KnowledgeBaseConfig,
        KnowledgeBaseConfigUpdate,
    )

    # 只传 wiki 片段（前端「仅改 wiki 模型」场景）
    update = KnowledgeBaseConfigUpdate.model_validate({
        "wiki": {"enabled": True, "llm": {"model": "glm-5.3"}},
    })
    dumped = update.model_dump(exclude_unset=True)
    assert "wiki" in dumped
    assert dumped["wiki"]["llm"]["model"] == "glm-5.3"
    assert dumped["wiki"]["enabled"] is True

    # Update schema 与完整 Config 的字段面必须对齐（防未来再漏字段）。
    # 例外：description 存于 config JSON 但更新走 KB 基础信息通道，不在 PATCH config 面。
    assert set(KnowledgeBaseConfigUpdate.model_fields.keys()) == (
        set(KnowledgeBaseConfig.model_fields.keys()) - {"description"}
    )


def _make_service(kb, monkeypatch):
    """构造 update_config 可用的 service（FakeKnowledgeBase + mock 鉴权链）。"""
    service = object.__new__(KnowledgeBaseService)
    service.kb_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=kb))
    service.session = SimpleNamespace(commit=AsyncMock())
    member = SimpleNamespace(is_active=lambda: True)
    service.member_repo = SimpleNamespace(get_by_space_and_user=AsyncMock(return_value=member))
    service.permission_service = SimpleNamespace(can_manage_knowledge_base=lambda m: True)
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.knowledge_base_service.flag_modified",
        lambda obj, field: None,
    )
    return service


def test_update_config_accepts_sentence_window_and_parent_child(monkeypatch):
    """新策略走通 PATCH 白名单：sentence_window 带 window_size、parent_child 带尺寸组。"""
    kb = FakeKnowledgeBase(
        6,
        {"space_type": ["text"], "splitting": {"strategy": "recursive", "chunk_size": 1000}},
    )
    service = _make_service(kb, monkeypatch)

    _run(
        service.update_config(
            6, 99,
            {"splitting": {"strategy": "sentence_window", "window_size": 3}},
        )
    )
    assert kb.config["splitting"]["strategy"] == "sentence_window"
    assert kb.config["splitting"]["window_size"] == 3

    kb2 = FakeKnowledgeBase(
        7,
        {"space_type": ["text"], "splitting": {"strategy": "recursive", "chunk_size": 1000}},
    )
    service2 = _make_service(kb2, monkeypatch)
    _run(
        service2.update_config(
            7, 99,
            {"splitting": {
                "strategy": "parent_child",
                "chunk_size": 500, "chunk_overlap": 50, "parent_chunk_size": 2000,
            }},
        )
    )
    assert kb2.config["splitting"]["strategy"] == "parent_child"
    assert kb2.config["splitting"]["parent_chunk_size"] == 2000


def test_patch_parent_child_with_stale_chunk_size_rejected(monkeypatch):
    """PATCH 只带 parent_chunk_size=500、kb 现值 chunk_size=1000 → 回填交叉校验拒绝。

    schema after 校验器在 PATCH 片段上看到的是缺省默认值（parent_chunk_size 默认
    2000 >= 默认 chunk_size 1000，通过），服务层带回填校验是唯一防线。
    """
    from novamind.features.knowledge_space.exceptions import InvalidParameterError

    kb = FakeKnowledgeBase(
        8,
        {"space_type": ["text"], "splitting": {"strategy": "recursive", "chunk_size": 1000}},
    )
    service = _make_service(kb, monkeypatch)

    with pytest.raises(InvalidParameterError, match="parent_chunk_size"):
        _run(
            service.update_config(
                8, 99,
                {"splitting": {"strategy": "parent_child", "parent_chunk_size": 500}},
            )
        )


def test_patch_parent_chunk_size_on_non_parent_child_strategy_allowed(monkeypatch):
    """相邻正常场景：非 parent_child 策略下 PATCH parent_chunk_size 不做交叉校验
    （先改尺寸后切策略是合法顺序，缺口由切策略时的 PATCH 再校验兜住）。"""
    kb = FakeKnowledgeBase(
        9,
        {"space_type": ["text"], "splitting": {"strategy": "recursive", "chunk_size": 1000}},
    )
    service = _make_service(kb, monkeypatch)
    _run(service.update_config(9, 99, {"splitting": {"parent_chunk_size": 800}}))
    assert kb.config["splitting"]["parent_chunk_size"] == 800


def test_patch_window_size_out_of_range_rejected():
    """window_size 越界（>10）被服务层拒绝。"""
    from novamind.features.knowledge_space.exceptions import InvalidParameterError

    kb = FakeKnowledgeBase(10, {"space_type": ["text"], "splitting": {"strategy": "sentence_window"}})
    service = object.__new__(KnowledgeBaseService)
    service.kb_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=kb))
    member = SimpleNamespace(is_active=lambda: True)
    service.member_repo = SimpleNamespace(get_by_space_and_user=AsyncMock(return_value=member))
    service.permission_service = SimpleNamespace(can_manage_knowledge_base=lambda m: True)

    with pytest.raises(InvalidParameterError, match="window_size"):
        _run(service.update_config(10, 99, {"splitting": {"window_size": 11}}))


def test_splitting_config_schema_accepts_new_strategies():
    """全量配置路径：新策略经 SplittingConfig 校验通过；交叉校验正向生效。"""
    from novamind.features.knowledge_space.schemas.knowledge_base_schema import SplittingConfig

    cfg = SplittingConfig.model_validate({
        "strategy": "parent_child", "chunk_size": 500, "parent_chunk_size": 2000,
    })
    assert cfg.strategy == "parent_child"
    assert cfg.window_size == 2  # 缺省默认值照常填充

    sw = SplittingConfig.model_validate({"strategy": "sentence_window", "window_size": 0})
    assert sw.window_size == 0  # 0 = 不扩窗，合法


def test_splitting_config_schema_rejects_parent_smaller_than_chunk():
    """全量配置路径交叉校验：parent_chunk_size < chunk_size 被 after 校验器拒绝。"""
    from pydantic import ValidationError

    from novamind.features.knowledge_space.schemas.knowledge_base_schema import SplittingConfig

    with pytest.raises(ValidationError, match="parent_chunk_size"):
        SplittingConfig.model_validate({
            "strategy": "parent_child", "chunk_size": 1000, "parent_chunk_size": 500,
        })
