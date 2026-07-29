from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Make `novamind` importable via the src-side namespace package
# (backend/src/novamind/) without relying on the legacy backend/novamind
# dev-bridge shim, which has been removed. The real code lives under
# backend/src/{core,features,setting,shared}; the inner novamind package
# re-export them as novamind.<name>.
SOURCE_ROOT = BACKEND_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _register_prompt_templates() -> None:
    """注册全部 feature 提示词模板，供绕过 lifespan 的单元测试使用。

    生产环境由 `startup_manager._register_prompt_templates` 在 lifespan 注册；
    但许多单元测试直接调用内部服务函数（如 `_generate_image_description`），
    这些函数内部 `PromptManager.get_template(...)` 需要模板已注册。本 fixture
    在 session 开始时调用与启动期相同的集中注册函数，保证单测路径不抛 KeyError。
    """
    from novamind.core.middleware.prompt_registration import (
        register_all_prompt_templates,
    )

    register_all_prompt_templates()
