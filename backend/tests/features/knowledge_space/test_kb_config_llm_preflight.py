"""KB 配置保存 LLM 模型连通性预检回归测试。

背景：wiki 生成 404 Model not exist——模型名在所选 Base URL 下不存在要等
任务失败才暴露。预检在 update_config 保存前对「本次变更且启用中」的 LLM 类
模型字段做轻量试调（按 kb.creator_id 解析凭证，与 wiki_tasks 运行时同口径），
失败拒绝保存（422）。

验证核心不变量：
1. 变更字段触发预检且凭证缺失/探针失败 → InvalidParameterError + 不落库；
2. 探针收到的 model 是凭证解析后的真实名（与运行时构造同口径）；
3. 未变更字段零触发（不阻塞无关保存）；
4. wiki/假设问题生成受 enabled 门控：功能关闭时改模型不触发预检。
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.exceptions import InvalidParameterError
from novamind.features.knowledge_space.services.knowledge_base_service import (
    KnowledgeBaseService,
)

pytestmark = pytest.mark.unit


def _make_service(monkeypatch, kb) -> KnowledgeBaseService:
    """__new__ 绕过 init；repo/权限/commit 全桩 + 探针/凭证打桩钩子返回。"""
    service = object.__new__(KnowledgeBaseService)
    service.kb_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=kb))
    service.session = SimpleNamespace(commit=AsyncMock())
    fake_member = SimpleNamespace(is_active=lambda: True)
    service.member_repo = SimpleNamespace(
        get_by_space_and_user=AsyncMock(return_value=fake_member)
    )
    service.permission_service = SimpleNamespace(can_manage_knowledge_base=lambda m: True)
    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.knowledge_base_service.flag_modified",
        lambda obj, field: None,
    )
    return service


def _make_kb(config: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=1, space_id=1, creator_id=7, config=config, get_config=lambda: config
    )


def _patch_credentials(monkeypatch, found: dict[str, SimpleNamespace | None]) -> list:
    """凭证解析桩：found[model] → 凭证（缺失 → None），返回调用记录。"""
    calls: list[tuple[int, str, str]] = []

    class _FakeMCS:
        def __init__(self, session):
            pass

        async def get_credentials_by_model(self, user_id, model_type, model):
            calls.append((user_id, model_type, model))
            return found.get(model)

    monkeypatch.setattr(
        "novamind.features.knowledge_space.services.knowledge_base_service.ModelConfigService",
        _FakeMCS,
    )
    return calls


def _patch_probe(monkeypatch, fail_for: str | None = None) -> list:
    """探针桩：记录调用；fail_for 指定的真实模型名抛 404 类错误。"""
    calls: list[dict] = []

    async def _fake_probe(**kwargs):
        calls.append(kwargs)
        if fail_for is not None and kwargs.get("model") == fail_for:
            raise Exception(
                "Error code: 404 - {'error': {'message': 'Model not exist.'}}"
            )

    monkeypatch.setattr(
        "novamind.shared.ai_models.connection_testers.llm.probe_llm_connection",
        _fake_probe,
    )
    return calls


_CRED = SimpleNamespace(
    protocol="openai",
    api_key="sk-x",
    base_url="https://provider.example.com/v1",
    model="real-model-name",
    extra_config={},
)


@pytest.mark.asyncio
async def test_changed_wiki_model_probes_and_saves(monkeypatch):
    """正例：变更 wiki 模型（enabled）→ 预检按凭证真实名调用 → 保存成功。"""
    kb = _make_kb({"wiki": {"enabled": True, "llm": {"model": "old-model"}}})
    service = _make_service(monkeypatch, kb)
    cred_calls = _patch_credentials(monkeypatch, {"new-model": _CRED})
    probe_calls = _patch_probe(monkeypatch)

    result = await service.update_config(
        kb_id=1,
        user_id=2,
        config_updates={"wiki": {"enabled": True, "llm": {"model": "new-model"}}},
    )

    assert "成功" in result["message"]
    # 凭证按创建者 7 解析；探针收到凭证解析后的真实模型名（与运行时同口径）
    assert cred_calls == [(7, "llm", "new-model")]
    assert len(probe_calls) == 1
    assert probe_calls[0]["model"] == "real-model-name"
    service.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_credentials_rejects_save(monkeypatch):
    """凭证缺失（编辑者选的模型创建者没配）→ 422 拒绝且不落库。"""
    kb = _make_kb({"wiki": {"enabled": True, "llm": {"model": "old"}}})
    service = _make_service(monkeypatch, kb)
    _patch_credentials(monkeypatch, {})  # 任何模型都查不到凭证
    _patch_probe(monkeypatch)

    with pytest.raises(InvalidParameterError) as exc_info:
        await service.update_config(
            kb_id=1,
            user_id=2,
            config_updates={"wiki": {"llm": {"model": "ghost-model"}}},
        )

    assert "创建者" in str(exc_info.value)
    assert "ghost-model" in str(exc_info.value)
    service.session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_probe_failure_rejects_save_with_model_name(monkeypatch):
    """探针失败（404 Model not exist）→ 422 拒绝，错误含模型名与 Base URL。"""
    kb = _make_kb({"wiki": {"enabled": True, "llm": {"model": "old"}}})
    service = _make_service(monkeypatch, kb)
    _patch_credentials(monkeypatch, {"bad-model": _CRED})
    _patch_probe(monkeypatch, fail_for="real-model-name")

    with pytest.raises(InvalidParameterError) as exc_info:
        await service.update_config(
            kb_id=1,
            user_id=2,
            config_updates={"wiki": {"llm": {"model": "bad-model"}}},
        )

    msg = str(exc_info.value)
    assert "连通性预检失败" in msg
    assert "bad-model" in msg and "provider.example.com" in msg
    service.session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_unchanged_fields_do_not_probe(monkeypatch):
    """相邻场景不误伤：未触碰的模型字段零预检（不阻塞无关保存）。"""
    kb = _make_kb(
        {"wiki": {"enabled": True, "llm": {"model": "kept"}}, "splitting": {"chunk_size": 500}}
    )
    service = _make_service(monkeypatch, kb)
    cred_calls = _patch_credentials(monkeypatch, {})
    probe_calls = _patch_probe(monkeypatch)

    await service.update_config(
        kb_id=1, user_id=2, config_updates={"splitting": {"chunk_size": 800}}
    )

    assert cred_calls == [] and probe_calls == []
    service.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_disabled_wiki_model_change_skips_probe(monkeypatch):
    """门控：wiki 功能关闭时改模型不触发预检（模型当前不被消费）。"""
    kb = _make_kb({"wiki": {"enabled": False, "llm": {"model": "old"}}})
    service = _make_service(monkeypatch, kb)
    cred_calls = _patch_credentials(monkeypatch, {})
    probe_calls = _patch_probe(monkeypatch)

    await service.update_config(
        kb_id=1,
        user_id=2,
        config_updates={"wiki": {"enabled": False, "llm": {"model": "new-model"}}},
    )

    assert cred_calls == [] and probe_calls == []
    service.session.commit.assert_awaited_once()
