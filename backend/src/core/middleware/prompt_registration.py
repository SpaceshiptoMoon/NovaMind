"""
提示词注册入口，将各 feature 的 TEMPLATES 字典注册到 PromptManager。
"""
from __future__ import annotations

from novamind.shared.prompts.prompt_manager import PromptManager


def register_all_prompt_templates() -> int:
    """注册全部 feature 的提示词模板到 PromptManager，返回注册条数。

    注册幂等：合并到同一 dict，键不跨 feature 冲突；重复调用无副作用。
    注册顺序不影响结果。
    """
    # 各 feature 的提示词数据源（纯数据模块，零 novamind 导入）
    from novamind.features.agent.agent_prompts import TEMPLATES as _ag
    from novamind.features.app.app_prompts import TEMPLATES as _app
    from novamind.features.clawmate.clawmate_prompts import TEMPLATES as _cm
    from novamind.features.deep_research.deep_research_prompts import TEMPLATES as _dr
    from novamind.features.evaluation.evaluation_prompts import TEMPLATES as _ev
    from novamind.features.knowledge_space.prompts import TEMPLATES as _ks
    from novamind.features.qa.qa_prompts import TEMPLATES as _qa
    from novamind.features.skill.skill_prompts import TEMPLATES as _sk

    count = 0
    for templates in [_ks, _dr, _qa, _ev, _app, _ag, _sk, _cm]:
        PromptManager.register(templates)
        count += len(templates)
    return count


__all__ = ["register_all_prompt_templates"]