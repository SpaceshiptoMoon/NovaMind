"""提示词注册表一致性门禁：PromptTemplate 枚举 ↔ 注册表键集双向对账。

防止两类漂移：
- 枚举有值、注册表无模板：调用 PromptManager.format_prompt 运行时才炸
  （ValueError），启动期发现不了。
- 注册表有模板、枚举无值：模板成为无枚举引用的孤儿，改键名时枚举方
  无感知（枚举是键名的类型安全引用层）。

测试依赖 conftest session 级 fixture 先行调用 register_all_prompt_templates。
"""
import pytest

pytestmark = pytest.mark.unit


def _registered_keys() -> set[str]:
    from novamind.core.middleware.prompt_registration import (
        register_all_prompt_templates,
    )
    from novamind.shared.prompts.prompt_manager import PromptManager

    register_all_prompt_templates()  # 幂等；显式调用防 fixture 顺序耦合
    return set(PromptManager._templates.keys())


def test_every_enum_value_has_template():
    """枚举每个值必须已注册——防运行时 KeyError/ValueError。"""
    from novamind.shared.prompts.templates import PromptTemplate

    keys = _registered_keys()
    missing = [m.value for m in PromptTemplate if m.value not in keys]
    assert not missing, f"枚举有值但注册表无模板（运行时会炸）: {missing}"


def test_every_template_has_enum_entry():
    """注册表每个模板键必须能在枚举里找到对应成员——防孤儿模板。"""
    from novamind.shared.prompts.templates import PromptTemplate

    enum_values = {m.value for m in PromptTemplate}
    orphans = sorted(_registered_keys() - enum_values)
    assert not orphans, f"注册表有模板但枚举无成员（孤儿模板）: {orphans}"


def test_engine_templates_registered():
    """agent_engine_* 10 键全部在册（引擎侧散落 prompt 收编的回归防线）。"""
    from novamind.shared.prompts.prompt_manager import PromptManager

    for key in (
        "agent_engine_structured_summary",
        "agent_engine_summary_merge",
        "agent_engine_compaction_aligned_instruction",
        "agent_engine_tag_convention",
        "agent_engine_tool_discipline_default",
        "agent_engine_model_adaptation_gpt",
        "agent_engine_model_adaptation_gemini",
        "agent_engine_plan_system",
        "agent_engine_plan_finalize_system",
        "agent_engine_subagent_system",
    ):
        assert PromptManager.is_registered(key), key


def test_removed_drifted_keys_gone():
    """已删除的漂移死键不得复活（qa 拆除 + agent_prompts 收编后的守卫）。"""
    from novamind.shared.prompts.prompt_manager import PromptManager

    for key in (
        "qa_compression_summary",
        "qa_ai_chat_system",
        "agent_system_prompt",
        "agent_structured_summary",
        "agent_summary_merge",
    ):
        assert not PromptManager.is_registered(key), key
