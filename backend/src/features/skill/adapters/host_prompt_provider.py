"""
PromptProvider 宿主适配器（skill 引擎）

把宿主侧 ``shared.prompts.PromptManager`` 包成引擎端口 ``PromptProvider`` 实例，
供 ``SkillSecurityChecker`` 经构造器注入。skill_checker 不再直接 import
``shared.prompts.PromptManager``，切断 skill 引擎 -> 宿主 prompt 注册表的导入边
（批次 6 抽 ``novamind-skill-engine`` 前提）。
"""
from novamind.engines.ports import PromptProvider
from novamind.shared.prompts.templates import PromptManager


class HostPromptProvider:
    """PromptProvider 宿主实现：委托宿主侧 ``PromptManager``。"""

    def get(self, key: str) -> str:
        return PromptManager.get_template(key)

    def format(self, key: str, **kwargs: object) -> str:
        return PromptManager.format_prompt(key, **kwargs)


def as_prompt_provider() -> PromptProvider:
    """构造 PromptProvider 实例（供装配点注入 SkillSecurityChecker）。"""
    return HostPromptProvider()  # type: ignore[return-value]