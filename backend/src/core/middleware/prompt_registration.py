"""提示词模板集中注册（组合根 wiring）

`shared/prompts/prompt_manager.PromptManager` 是纯机制、零 feature 依赖的注册表；
本模块是「组合根」wiring——合法地 import 各 feature 的纯数据 `*_prompts.TEMPLATES`
并注入注册表。把这份 wiring 单列成模块级函数，供：

- 宿主启动（`startup_manager._register_prompt_templates`）在 lifespan 调用；
- 单元测试（`tests/conftest.py` autouse fixture）在绕过 lifespan 直接调用内部
  服务函数时调用，确保 `PromptManager.get_template` 不抛 KeyError。

抽出本函数是为了消除「注册清单」在两处复制的漂移风险：新增 feature 提示词时，
只改本文件一处。本模块属 core 启动层，core→features 在组合根处允许（与
startup_manager 既有行为一致），不构成 shared→features 分层违规。
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