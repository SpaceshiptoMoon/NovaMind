"""回归测试：跨 feature 同名 Pydantic 响应类已消除，openapi 组件名确定性。

历史问题：5 个同名 Pydantic 响应类（MessageResponse / AvailableModelsResponse /
ActionResponse / SessionListResponse / LLMConfig）散落在多个 feature，FastAPI 自动
组件命名产生非确定性的 ``_1`` / ``_2`` 后缀（按路由注册顺序浮动）。

本次卫生项将每个同名类重命名为 feature 限定名（共 10 个），消除碰撞源头。
本测试锁定三条不变量，防止未来再次引入同名响应类。
"""
import pytest


def _build_openapi_components() -> set:
    from novamind.core.middleware.app_factory import create_app

    app = create_app()
    spec = app.openapi()
    return set(spec.get("components", {}).get("schemas", {}).keys())


# 5 个历史裸名（跨 feature 同名）——重命名后必须全部消失
_BARE_COLLIDING_NAMES = {
    "MessageResponse",
    "AvailableModelsResponse",
    "ActionResponse",
    "SessionListResponse",
}

# 10 个 feature 限定新名——必须全部出现在 openapi 组件中
_FEATURE_QUALIFIED_NAMES = {
    "UserMessageResponse",
    "AgentMessageResponse",
    "ModelConfigAvailableModelsResponse",
    "ChatAvailableModelsResponse",
    "MemberActionResponse",
    "AgentActionResponse",
    "SearchLLMConfig",
    "ResearchLLMConfig",
    "ChatSessionListResponse",
    "AgentSessionListResponse",
}


def test_no_bare_colliding_response_names_in_openapi():
    """5 个历史同名裸名不得重新出现在 openapi 组件中。"""
    comps = _build_openapi_components()
    leaked = _BARE_COLLIDING_NAMES & comps
    assert not leaked, f"跨 feature 同名裸名重新出现: {leaked}"


def test_feature_qualified_response_names_present():
    """10 个 feature 限定名必须出现在 openapi 组件中。"""
    comps = _build_openapi_components()
    missing = _FEATURE_QUALIFIED_NAMES - comps
    assert not missing, f"feature 限定名缺失: {missing}"


def test_no_nondeterministic_collision_suffixes():
    """openapi 组件名不得出现 FastAPI 自动生成的 ``_1`` / ``_2`` 碰撞后缀。"""
    comps = _build_openapi_components()
    suffixed = sorted(k for k in comps if k.endswith("_1") or k.endswith("_2"))
    assert not suffixed, f"检测到非确定性碰撞后缀组件: {suffixed}"